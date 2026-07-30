"""Rule-based risk scoring for inbound requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from phonenumbers import NumberParseException

from crm.phones import normalize_phone

from .models import Blocklist, BlocklistKind, InboundRequest


LINK_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
DISPOSABLE_DOMAINS = {"mailinator.com", "10minutemail.com", "tempmail.com"}
# User-Agent shorter than this is treated as empty/generic and skipped for UA signals.
UA_MIN_LENGTH = 10
RISK_SIGNAL_SCORES = {
    "honeypot": 100,
    "rate_limit": 100,
    "threat": 70,
    "profanity": 60,
    "troll": 60,
    "off_topic": 60,
    "abuse_staff": 60,
    "scam_keywords": 60,
    "pii_harvest": 60,
    "job_spam": 55,
    "prompt_injection": 50,
    "gibberish": 45,
    "aggression": 40,
    "test_message": 40,
    "wrong_company": 40,
    "payload_repeat": 40,
    "phone_flood": 35,
    "links_2plus": 30,
    "promo_keywords": 30,
    "ip_flood": 30,
    "ua_flood": 30,
    "ua_multi_identity": 40,
    "ip_multi_identity": 40,
    "fingerprint_mass_identity": 90,
    "form_too_fast": 25,
    "phone_invalid": 25,
    "no_business_intent": 25,
    "disposable_email": 20,
    "short_text": 15,
    "tg_not_ru": 15,
    "repeat_insult": 20,
}
RISK_REASON_LABELS = {
    "honeypot": "honeypot заполнен",
    "rate_limit": "rate limit",
    "threat": "угрозы",
    "profanity": "мат/оскорбления",
    "troll": "троллинг/провокация без покупки",
    "off_topic": "явно не про авто/кредит/сервис салона",
    "abuse_staff": "оскорбление салона/сотрудника",
    "scam_keywords": "мошеннические маркеры",
    "pii_harvest": "запрос базы/контактов менеджеров",
    "job_spam": "вакансии/HR-спам",
    "prompt_injection": "prompt injection маркеры",
    "gibberish": "бессмыслица/кракозябры",
    "aggression": "агрессия без явного мата",
    "test_message": "тестовое/мусорное сообщение",
    "wrong_company": "обращение не в ту компанию",
    "payload_repeat": "повтор payload",
    "phone_flood": "частые заявки с телефона",
    "links_2plus": "две и более ссылки",
    "promo_keywords": "подозрительные промо-слова",
    "ip_flood": "частые заявки с IP",
    "ua_flood": "частые заявки с одного User-Agent",
    "ua_multi_identity": "несколько идентичностей с одного User-Agent",
    "ip_multi_identity": "несколько идентичностей с одного IP",
    "fingerprint_mass_identity": "много разных контактов с одного IP/User-Agent",
    "form_too_fast": "форма отправлена быстрее 2 секунд",
    "phone_invalid": "телефон не разбирается",
    "no_business_intent": "нет делового запроса и мусорный тон",
    "disposable_email": "одноразовый email-домен",
    "short_text": "текст короче 10 символов",
    "tg_not_ru": "telegram аккаунт не похож на российский",
    "repeat_insult": "повтор грубости в треде",
}
PROMO_KEYWORDS = ("казино", "viagra", "ставки", "crypto", "крипта", "заработок", "накрутка", "быстрый доход")
PROFANITY_WORDS = (
    "бля",
    "блять",
    "сука",
    "хуй",
    "хуе",
    "пизд",
    "еба",
    "ёба",
    "ебан",
    "мудак",
    "дебил",
    "идиот",
    "урод",
    "тварь",
    "гандон",
)
THREAT_WORDS = ("убью", "зарежу", "сожгу", "взорву", "сломаю", "приеду разбираться", "угрожаю", "расправ")
TROLL_PHRASES = ("лохотрон", "разводилы", "клоуны", "поржать", "троллю", "куплю танк", "дайте бесплатно", "вы все мошенники")
OFF_TOPIC_PHRASES = ("купить слона", "продам гараж", "пицца", "доставка еды", "криптокошелек", "ставки на спорт", "казино")
AUTO_BUSINESS_WORDS = (
    "авто",
    "автомобиль",
    "машин",
    "кредит",
    "рассроч",
    "trade",
    "трейд",
    "сервис",
    "ремонт",
    "то ",
    "тест-драйв",
    "haval",
    "chery",
    "geely",
    "jolion",
    "tiggo",
    "купить",
    "налич",
    "комплектац",
    "салон",
)
STAFF_WORDS = ("менеджер", "сотрудник", "салон", "дилер", "продавец", "оператор")
SCAM_KEYWORDS = ("обнал", "скам", "кардинг", "дроп", "переведите деньги", "гарантированный доход", "взлом")
PII_HARVEST_PHRASES = ("базу клиентов", "контакты менеджеров", "телефоны менеджеров", "список клиентов", "выгрузку клиентов")
JOB_SPAM_WORDS = ("ваканси", "резюме", "ищу работу", "hr", "работа менеджером", "трудоустрой")
PROMPT_INJECTION_PHRASES = ("ignore previous", "забудь инструкции", "system prompt", "developer message", "раскрой промпт", "jailbreak")
AGGRESSION_WORDS = ("ненавижу", "достали", "бесите", "отвратительно", "ужасный сервис", "никогда к вам")
TEST_MESSAGES = {"test", "тест", "asdf", "qwerty", "123", "проверка", "ping"}
WRONG_COMPANY_PHRASES = ("это банк", "доставка заказа", "интернет провайдер", "медицинская клиника", "ресторан")
CYRILLIC_OR_LATIN_RE = re.compile(r"[a-zа-яё]", re.IGNORECASE)
REPEATED_CHAR_RE = re.compile(r"(.)\1{5,}")

# A restored thread remains usable, but starts close to the moderation boundary.
RESTORED_RISK_FLOOR = 59

# Fingerprint mass identity: many distinct contacts from same IP/UA → direct blocked.
# Windows and thresholds are fixed here and documented in .ai/docs/intake.md.
MASS_IDENTITY_24H_THRESHOLD = 4   # ≥4 distinct phones or emails in 24 h → score 90
MASS_IDENTITY_7D_THRESHOLD = 6    # ≥6 distinct phones or emails in 7 d  → score 90


@dataclass(frozen=True)
class RiskSignal:
    code: str
    score: int
    reason: str


@dataclass(frozen=True)
class RiskResult:
    score: int
    reasons: list[str]
    signals: list[RiskSignal]
    phone_normalized: str
    phone_valid: bool
    blocklisted: bool


def email_domain(email: str) -> str:
    if "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].casefold()


def _fingerprint_peers(inbound: InboundRequest, *, window: timedelta):
    """Peers sharing the same IP or UA (OR) within the given window, excluding self/Telegram."""
    filters = Q()
    if inbound.ip_address:
        filters |= Q(ip_address=inbound.ip_address)
    ua = (inbound.user_agent or "").strip()
    if len(ua.casefold()) >= UA_MIN_LENGTH:
        filters |= Q(user_agent__iexact=ua)
    if not filters:
        return InboundRequest.objects.none()
    return (
        InboundRequest.objects.filter(filters)
        .exclude(pk=inbound.pk)
        .exclude(source_type__iexact="telegram")
        .filter(created_at__gte=timezone.now() - window)
    )


def evaluate_rules(inbound: InboundRequest) -> RiskResult:
    """Evaluate deterministic risk rules and return score with reasons."""

    score = 0
    reasons: list[str] = []
    signals: list[RiskSignal] = []
    text = risk_text_for_inbound(inbound)
    current_text = inbound.message_text or ""
    phone_normalized = ""
    phone_valid = True

    def add_signal(code: str) -> None:
        nonlocal score
        signal_score = RISK_SIGNAL_SCORES[code]
        score += signal_score
        reason = RISK_REASON_LABELS[code]
        reasons.append(reason)
        signals.append(RiskSignal(code=code, score=signal_score, reason=reason))

    existing_reason = (inbound.spam_reason or "").casefold()
    if "honeypot" in existing_reason:
        add_signal("honeypot")
    if "rate limit" in existing_reason:
        add_signal("rate_limit")

    if len(current_text.strip()) < 10:
        add_signal("short_text")

    if len(LINK_RE.findall(text)) >= 2:
        add_signal("links_2plus")

    try:
        phone_normalized = normalize_phone(inbound.phone_raw)
    except (ValueError, NumberParseException):
        phone_valid = False
        add_signal("phone_invalid")

    lowered = text.casefold()
    lowered_current = current_text.casefold()
    if any(word in lowered for word in PROMO_KEYWORDS):
        add_signal("promo_keywords")
    if contains_any(lowered, THREAT_WORDS):
        add_signal("threat")
    if contains_any(lowered, PROFANITY_WORDS):
        add_signal("profanity")
    if contains_any(lowered, TROLL_PHRASES):
        add_signal("troll")
    if contains_any(lowered, OFF_TOPIC_PHRASES) or is_off_topic(lowered_current):
        add_signal("off_topic")
    if contains_any(lowered, PROFANITY_WORDS) and contains_any(lowered, STAFF_WORDS):
        add_signal("abuse_staff")
    if contains_any(lowered, SCAM_KEYWORDS):
        add_signal("scam_keywords")
    if contains_any(lowered, PII_HARVEST_PHRASES):
        add_signal("pii_harvest")
    if contains_any(lowered, JOB_SPAM_WORDS):
        add_signal("job_spam")
    if contains_any(lowered, PROMPT_INJECTION_PHRASES):
        add_signal("prompt_injection")
    if is_gibberish(current_text):
        add_signal("gibberish")
    if contains_any(lowered, AGGRESSION_WORDS):
        add_signal("aggression")
    if lowered_current.strip(" !?.") in TEST_MESSAGES:
        add_signal("test_message")
    if contains_any(lowered, WRONG_COMPANY_PHRASES):
        add_signal("wrong_company")
    if "profanity" in [signal.code for signal in signals] and text.count("клиент:") > 1:
        add_signal("repeat_insult")
    if has_no_business_intent(lowered_current) and ("gibberish" in [signal.code for signal in signals] or "test_message" in [signal.code for signal in signals]):
        add_signal("no_business_intent")

    if InboundRequest.objects.filter(payload_hash=inbound.payload_hash).exclude(pk=inbound.pk).exists():
        add_signal("payload_repeat")

    if phone_normalized:
        recent_phone_count = InboundRequest.objects.filter(
            phone_normalized=phone_normalized,
            created_at__gte=timezone.now() - timedelta(minutes=10),
        ).exclude(pk=inbound.pk).count()
        if recent_phone_count > 3:
            add_signal("phone_flood")

    # Velocity/fingerprint signals are skipped for trusted internal sources.
    # Internal = server-to-server calls verified by HMAC + X-Intake-Trust header,
    # or Telegram (trust_level set by create_telegram_inbound_request).
    is_velocity_exempt = getattr(inbound, "trust_level", "external") == "internal"

    if not is_velocity_exempt and inbound.ip_address:
        recent_ip_count = InboundRequest.objects.filter(
            ip_address=inbound.ip_address,
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).exclude(pk=inbound.pk).count()
        if recent_ip_count > 5:
            add_signal("ip_flood")
        window_24h_ip = timezone.now() - timedelta(hours=24)
        ip_phone_count = (
            InboundRequest.objects.filter(
                ip_address=inbound.ip_address,
                created_at__gte=window_24h_ip,
            )
            .exclude(pk=inbound.pk)
            .exclude(phone_normalized="")
            .values("phone_normalized")
            .distinct()
            .count()
        )
        ip_email_count = (
            InboundRequest.objects.filter(
                ip_address=inbound.ip_address,
                created_at__gte=window_24h_ip,
            )
            .exclude(pk=inbound.pk)
            .exclude(email_raw="")
            .values("email_raw")
            .distinct()
            .count()
        )
        if ip_phone_count >= 3 or ip_email_count >= 3:
            add_signal("ip_multi_identity")

    ua = (inbound.user_agent or "").strip()
    if not is_velocity_exempt and len(ua) >= UA_MIN_LENGTH:
        recent_ua_count = (
            InboundRequest.objects.filter(
                user_agent__iexact=ua,
                created_at__gte=timezone.now() - timedelta(hours=1),
            )
            .exclude(pk=inbound.pk)
            .count()
        )
        if recent_ua_count > 5:
            add_signal("ua_flood")
        window_24h_ua = timezone.now() - timedelta(hours=24)
        ua_phone_count = (
            InboundRequest.objects.filter(
                user_agent__iexact=ua,
                created_at__gte=window_24h_ua,
            )
            .exclude(pk=inbound.pk)
            .exclude(phone_normalized="")
            .values("phone_normalized")
            .distinct()
            .count()
        )
        ua_email_count = (
            InboundRequest.objects.filter(
                user_agent__iexact=ua,
                created_at__gte=window_24h_ua,
            )
            .exclude(pk=inbound.pk)
            .exclude(email_raw="")
            .values("email_raw")
            .distinct()
            .count()
        )
        if ua_phone_count >= 3 or ua_email_count >= 3:
            add_signal("ua_multi_identity")

    # Mass identity: many distinct contacts over a longer fingerprint window → score 90 (blocked).
    # Exempt: internal trust, Telegram (is_velocity_exempt set above).
    if not is_velocity_exempt:
        for _window, _threshold in (
            (timedelta(hours=24), MASS_IDENTITY_24H_THRESHOLD),
            (timedelta(days=7), MASS_IDENTITY_7D_THRESHOLD),
        ):
            _peers = _fingerprint_peers(inbound, window=_window)
            _n_phones = _peers.exclude(phone_raw="").values("phone_raw").distinct().count()
            _n_emails = _peers.exclude(email_raw="").values("email_raw").distinct().count()
            if _n_phones >= _threshold or _n_emails >= _threshold:
                add_signal("fingerprint_mass_identity")
                break

    domain = email_domain(inbound.email_raw)
    if domain in DISPOSABLE_DOMAINS:
        add_signal("disposable_email")

    elapsed = inbound.raw_payload_json.get("form_elapsed_seconds")
    if elapsed is not None and float(elapsed) < 2:
        add_signal("form_too_fast")

    if telegram_account_risk(inbound):
        add_signal("tg_not_ru")

    blocklisted = False
    if phone_normalized and Blocklist.objects.filter(kind=BlocklistKind.PHONE, value=phone_normalized).exists():
        blocklisted = True
        reasons.append("телефон в blocklist")
    if inbound.ip_address and Blocklist.objects.filter(kind=BlocklistKind.IP, value=inbound.ip_address).exists():
        blocklisted = True
        reasons.append("IP в blocklist")
    if domain and Blocklist.objects.filter(kind=BlocklistKind.EMAIL_DOMAIN, value=domain).exists():
        blocklisted = True
        reasons.append("email-домен в blocklist")

    return RiskResult(score=min(score, 100), reasons=reasons, signals=signals, phone_normalized=phone_normalized, phone_valid=phone_valid, blocklisted=blocklisted)


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return whether any literal casefolded pattern is present."""

    return any(pattern in text for pattern in patterns)


def has_no_business_intent(text: str) -> bool:
    """Detect absence of obvious dealership intent in a short current message."""

    clean_text = " ".join(text.split())
    if not clean_text:
        return True
    return not contains_any(clean_text, AUTO_BUSINESS_WORDS)


def is_off_topic(text: str) -> bool:
    """Heuristic off-topic detector for obvious non-dealership messages."""

    clean_text = " ".join(text.split())
    if len(clean_text) < 12:
        return False
    return has_no_business_intent(clean_text) and contains_any(clean_text, ("купить", "продам", "заказать", "доставка", "ставки", "казино"))


def is_gibberish(text: str) -> bool:
    """Detect obvious keyboard mash / meaningless text."""

    clean_text = "".join(text.split())
    if len(clean_text) < 8:
        return False
    if REPEATED_CHAR_RE.search(clean_text):
        return True
    letters = CYRILLIC_OR_LATIN_RE.findall(clean_text)
    if not letters:
        return True
    unique_ratio = len(set(clean_text.casefold())) / max(len(clean_text), 1)
    return unique_ratio < 0.25


def risk_text_for_inbound(inbound: InboundRequest) -> str:
    """Use the current risk context, excluding pre-restore history when needed."""

    try:
        from channels.services import conversation_context_for_inbound
    except ImportError:
        return inbound.message_text or ""

    context = conversation_context_for_inbound(
        inbound=inbound,
        limit=None,
        since=getattr(inbound, "risk_restored_at", None),
    )
    if context:
        return context
    return "" if getattr(inbound, "risk_restored_at", None) is not None else (inbound.message_text or "")


def effective_risk_score(*, inbound: InboundRequest, score: int) -> int:
    """Keep restored threads near the threshold while allowing new risk to rise."""

    if getattr(inbound, "risk_restored_at", None) is None:
        return min(score, 100)
    return min(max(score, RESTORED_RISK_FLOOR), 100)


def telegram_account_risk(inbound: InboundRequest) -> bool:
    """Flag Telegram users that do not look Russian by available metadata."""

    if (inbound.source_type or "").casefold() != "telegram":
        return False
    payload = inbound.raw_payload_json or {}
    language_code = str(payload.get("language_code") or "").casefold()
    if language_code and not language_code.startswith("ru"):
        return True
    phone = str(payload.get("phone") or inbound.phone_raw or "")
    if phone and not phone.strip().startswith(("+7", "7", "8")):
        return True
    return False


def decision_for_score(score: int, *, blocklisted: bool = False) -> str:
    """Map risk score to processing decision."""

    if blocklisted or score >= 90:
        return "blocked"
    if score >= 60:
        return "suspicious"
    if score >= 30:
        return "risk_flagged"
    return "process"
