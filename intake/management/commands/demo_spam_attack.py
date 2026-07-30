"""Live spam demo for defense video: fingerprint flood visible in /requests/."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

from intake.clusters import cluster_info
from intake.models import InboundRequest, InboundRequestStatus
from intake.services import process_request_by_rules
from intake.worker import process_next_request

# Разные реальные UA для атак/контрольных прогонов.
REAL_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.3 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1"
    ),
    (
        "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.6261.64 Mobile Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
    ),
    (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0"
    ),
    (
        "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
    ),
]

CAR_TEXTS = [
    "Здравствуйте, интересует Haval Jolion в кредит, какая ставка?",
    "Подскажите наличие Chery Tiggo 7 Pro, можно ли trade-in?",
    "Хочу Geely Coolray, есть ли комплектация Comfort?",
    "Нужен авто до 2 млн, рассрочка на 36 месяцев возможна?",
    "Запишите на тест-драйв Jolion, удобно в субботу.",
    "Сколько стоит страховка и первый взнос по кредиту?",
    "Смотрю Tiggo 4, есть ли машина в цвете белый?",
    "Интересует трейд-ин моей Lada, оценка и доплата.",
]

# Реалистичные домены (gmail.com — настоящий Gmail; gmail.ru в природе почти не встречается).
EMAIL_DOMAINS = (
    "mail.ru",
    "yandex.ru",
    "gmail.com",
    "bk.ru",
    "inbox.ru",
    "list.ru",
    "ya.ru",
)

EMAIL_LOCAL_PARTS = (
    "ivan.petrov",
    "maria.sokolova",
    "alexey.ivanov",
    "olga.kuznetsova",
    "dmitry.smirnov",
    "elena.volkova",
    "sergey.novikov",
    "anna.morozova",
    "pavel.lebedev",
    "natalia.kozlova",
    "andrey.pavlov",
    "victoria.semenova",
    "kirill.egorov",
    "tatiana.makarova",
    "roman.nikolaev",
)

# Кривые «похожие на РФ» телефоны: короткий номер, пробелы, символы, лишний текст.
MESSY_PHONES = (
    "8985451833",
    "8 985 451 833",
    "8-985-451-83-3",
    "8(985)451-83-3",
    "8!!!985!!!451!!!83!!!3",
    "8985451833x",
    "8 985 451 833 лишний",
    "тел:8985451833",
    "8985451833#",
    "8_985_451_833",
    "8 985 451 833!",
    "+7(985)451-83-3extra",
)

# Общий IP для сценария invalid-phone (кластер в /requests/).
INVALID_PHONE_IP = "203.0.113.77"


def realistic_email(index: int, *, tag: str = "") -> str:
    """Build a human-looking email with rotating RU/global domains."""

    local = EMAIL_LOCAL_PARTS[index % len(EMAIL_LOCAL_PARTS)]
    domain = EMAIL_DOMAINS[index % len(EMAIL_DOMAINS)]
    # Лёгкий суффикс, чтобы повторные прогоны не клеили один и тот же адрес.
    suffix = "".join(ch for ch in tag[-4:] if ch.isalnum()) or str(index + 1)
    return f"{local}.{suffix}@{domain}"


@dataclass(frozen=True)
class DemoHit:
    index: int
    external_id: str
    phone: str
    email: str
    text: str
    user_agent: str
    ip: str
    status_code: int
    request_id: int | None


class Command(BaseCommand):
    help = (
        "Автоспам для демо на защите: same-ua / diff-ua / invalid-phone. "
        "Смотри результат на http://127.0.0.1:8000/requests/ (нужен head)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario",
            choices=("same-ua", "diff-ua", "invalid-phone", "all"),
            default="same-ua",
            help=(
                "same-ua = разные UA, один IP, валидные телефоны (кластер). "
                "diff-ua = разные UA и IP (контроль). "
                "invalid-phone = разные UA, один IP, кривые телефоны "
                "(8985451833 / пробелы / символы / лишний текст → blocked)."
            ),
        )
        parser.add_argument("--count", type=int, default=7, help="Сколько заявок в сценарии (для same-ua нужно ≥7).")
        parser.add_argument("--delay", type=float, default=0.8, help="Пауза между заявками (сек), удобно для видео.")
        parser.add_argument(
            "--process",
            action="store_true",
            help="После отправки прогнать rules/worker, чтобы сразу увидеть suspicious/blocked.",
        )
        parser.add_argument(
            "--rules-only",
            action="store_true",
            help="С --process считать только rules (без AI) — быстрее и стабильнее для видео.",
        )
        parser.add_argument("--max-steps", type=int, default=40, help="Лимит шагов worker при --process без --rules-only.")
        parser.add_argument(
            "--tag",
            default="",
            help="Суффикс external_id, чтобы не пересечься с прошлым прогоном (по умолчанию timestamp).",
        )

    def handle(self, *args, **options):
        if not settings.WEBHOOK_SECRET:
            raise CommandError("Нужен WEBHOOK_SECRET в .env (подпись webhook).")

        tag = options["tag"] or timezone.now().strftime("%H%M%S")
        scenario = options["scenario"]
        count = max(1, options["count"])
        delay = max(0.0, options["delay"])

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("=== DEMO SPAM ATTACK (для видео на защите) ==="))
        self.stdout.write(f"Сценарий: {scenario} | count={count} | delay={delay}s | tag={tag}")
        self.stdout.write("Держи открытым: /requests/  (логин head)")
        self.stdout.write("")

        client = Client()
        hits: list[DemoHit] = []

        if scenario in {"same-ua", "all"}:
            hits.extend(self._run_same_ua(client, count=count, delay=delay, tag=tag))
        if scenario in {"diff-ua", "all"}:
            hits.extend(self._run_diff_ua(client, count=count, delay=delay, tag=f"{tag}-diff"))
        if scenario in {"invalid-phone", "all"}:
            hits.extend(self._run_invalid_phone(client, count=count, delay=delay, tag=f"{tag}-bad"))

        if options["process"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("--- обработка ---"))
            if options["rules_only"]:
                self._process_rules_only(hits)
            else:
                self._process_worker(options["max_steps"])

        self._print_summary(hits)
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Готово. Обнови /requests/ — ищи блок «Fingerprint / кластер»."))
        self.stdout.write(
            f"Фильтр: suspicious / blocked; IP 203.0.113.50 (same-ua) или {INVALID_PHONE_IP} (invalid-phone)."
        )

    def _run_same_ua(self, client: Client, *, count: int, delay: float, tag: str) -> list[DemoHit]:
        # Один IP + разные реальные UA + разные контакты → кластер по IP (не один «Demo» UA).
        shared_ip = "203.0.113.50"
        self.stdout.write(
            self.style.HTTP_INFO(
                f"[same-ua] {count} заявок: РАЗНЫЕ User-Agent, один IP {shared_ip}, разные телефоны/email"
            )
        )
        hits: list[DemoHit] = []
        for index in range(count):
            ua = REAL_USER_AGENTS[index % len(REAL_USER_AGENTS)]
            phone = f"+7 999 88{index:01d}-{10 + index:02d}-{20 + index:02d}"
            email = realistic_email(index, tag=tag)
            text = CAR_TEXTS[index % len(CAR_TEXTS)]
            hit = self._post_lead(
                client,
                index=index,
                tag=tag,
                phone=phone,
                email=email,
                text=text,
                user_agent=ua,
                ip=shared_ip,
                name=["Алексей", "Мария", "Игорь", "Ольга", "Павел", "Елена", "Дмитрий", "Анна"][index % 8],
            )
            hits.append(hit)
            short_ua = ua.split(")")[0][:48] + "…)" if ")" in ua else ua[:50]
            self._narrate(hit, note=f"UA: {short_ua}")
            if delay and index + 1 < count:
                time.sleep(delay)
        return hits

    def _run_diff_ua(self, client: Client, *, count: int, delay: float, tag: str) -> list[DemoHit]:
        self.stdout.write(self.style.HTTP_INFO(f"[diff-ua] {count} заявок, РАЗНЫЕ User-Agent (контрольный прогон)"))
        hits: list[DemoHit] = []
        for index in range(count):
            ip = f"198.51.100.{(20 + index) % 250}"
            ua = REAL_USER_AGENTS[index % len(REAL_USER_AGENTS)]
            phone = f"+7 999 77{index:01d}-{30 + index:02d}-{40 + index:02d}"
            email = realistic_email(index + 17, tag=tag)
            text = CAR_TEXTS[index % len(CAR_TEXTS)]
            hit = self._post_lead(
                client,
                index=index,
                tag=tag,
                phone=phone,
                email=email,
                text=text,
                user_agent=ua,
                ip=ip,
                name=["Сергей", "Наталья", "Андрей", "Виктория", "Кирилл", "Татьяна", "Роман", "Юлия"][index % 8],
            )
            hits.append(hit)
            self._narrate(hit, note="разный UA")
            if delay and index + 1 < count:
                time.sleep(delay)
        return hits

    def _run_invalid_phone(self, client: Client, *, count: int, delay: float, tag: str) -> list[DemoHit]:
        shared_ip = INVALID_PHONE_IP
        self.stdout.write(
            self.style.HTTP_INFO(
                f"[invalid-phone] {count} заявок: РАЗНЫЕ User-Agent, один IP {shared_ip}, "
                "кривые телефоны (короткий номер / пробелы / символы / лишний текст)"
            )
        )
        hits: list[DemoHit] = []
        names = ["Иван", "Пётр", "Светлана", "Олег", "Дарья", "Никита", "Юлия", "Максим"]
        for index in range(count):
            phone = MESSY_PHONES[index % len(MESSY_PHONES)]
            ua = REAL_USER_AGENTS[index % len(REAL_USER_AGENTS)]
            hit = self._post_lead(
                client,
                index=index,
                tag=tag,
                phone=phone,
                email=realistic_email(index + 31, tag=tag),
                text=CAR_TEXTS[index % len(CAR_TEXTS)],
                user_agent=ua,
                ip=shared_ip,
                name=names[index % len(names)],
            )
            hits.append(hit)
            short_ua = ua.split(")")[0][:40] + "…)" if ")" in ua else ua[:42]
            self._narrate(hit, note=f"битый телефон | UA: {short_ua}")
            if delay and index + 1 < count:
                time.sleep(delay)
        return hits

    def _post_lead(
        self,
        client: Client,
        *,
        index: int,
        tag: str,
        phone: str,
        email: str,
        text: str,
        user_agent: str,
        ip: str,
        name: str,
    ) -> DemoHit:
        external_id = f"defense-spam-{tag}-{index}"
        payload = {
            "external_id": external_id,
            "source": "site_form",
            "name": name,
            "phone": phone,
            "email": email,
            "text": text,
            "received_at": timezone.now().isoformat(),
            "metadata": {"demo": "defense_spam_attack", "tag": tag, "index": index},
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        response = client.post(
            "/api/v1/intake/lead",
            data=body,
            content_type="application/json",
            **self._signed_headers(body, user_agent=user_agent, ip=ip),
        )
        request_id = None
        if response.status_code in {200, 202}:
            try:
                request_id = int(response.json().get("request_id"))
            except (TypeError, ValueError, AttributeError):
                inbound = InboundRequest.objects.filter(external_id=external_id).order_by("-id").first()
                request_id = inbound.id if inbound else None
        elif response.status_code not in {200, 202}:
            self.stdout.write(self.style.ERROR(f"  FAIL HTTP {response.status_code} for {external_id}"))
        return DemoHit(
            index=index,
            external_id=external_id,
            phone=phone,
            email=email,
            text=text,
            user_agent=user_agent,
            ip=ip,
            status_code=response.status_code,
            request_id=request_id,
        )

    def _signed_headers(self, body: bytes, *, user_agent: str, ip: str) -> dict[str, str]:
        timestamp = str(int(time.time()))
        signature = hmac.new(settings.WEBHOOK_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return {
            "HTTP_X_TIMESTAMP": timestamp,
            "HTTP_X_SIGNATURE": signature,
            "HTTP_USER_AGENT": user_agent,
            "HTTP_X_FORWARDED_FOR": ip,
            "HTTP_HOST": "127.0.0.1",
        }

    def _narrate(self, hit: DemoHit, *, note: str) -> None:
        rid = f"#{hit.request_id}" if hit.request_id else "—"
        self.stdout.write(
            f"  → [{hit.index + 1}] HTTP {hit.status_code} {rid}  {hit.phone}  {hit.email}  ({note})"
        )

    def _process_rules_only(self, hits: list[DemoHit]) -> None:
        ids = [hit.request_id for hit in hits if hit.request_id]
        # Reverse order: last-created requests have the most peers already in DB
        # when the loop starts, ensuring fingerprint_mass_identity fires immediately.
        qs = InboundRequest.objects.filter(pk__in=ids, status=InboundRequestStatus.RECEIVED)
        for inbound in qs.order_by("-id"):
            process_request_by_rules(inbound=inbound)
            inbound.refresh_from_db()
            self.stdout.write(
                f"  rules #{inbound.id}: {inbound.status}  "
                f"risk={inbound.risk_score_final}  reason={inbound.spam_reason[:80]}"
            )

    def _process_worker(self, max_steps: int) -> None:
        for step in range(max_steps):
            result = process_next_request()
            InboundRequest.objects.filter(status=InboundRequestStatus.RETRY_WAIT).update(next_retry_at=timezone.now())
            if not result.processed:
                self.stdout.write(f"  worker idle after {step} steps")
                break
            self.stdout.write(f"  worker step {step + 1}: ok")

    def _print_summary(self, hits: list[DemoHit]) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("--- итог ---"))
        ids = [hit.request_id for hit in hits if hit.request_id]
        rows = list(InboundRequest.objects.filter(pk__in=ids).order_by("id"))
        if not rows:
            self.stdout.write(self.style.ERROR("Заявки не создались — проверь WEBHOOK_SECRET и логи."))
            return

        for inbound in rows:
            ua = (inbound.user_agent or "")[:40]
            self.stdout.write(
                f"  #{inbound.id}  {inbound.status:12}  risk={inbound.risk_score_final or 0:3}  "
                f"IP={inbound.ip_address}  UA={ua}…  "
                f"{inbound.phone_raw}  | {(inbound.spam_reason or '-')[:50]}"
            )

        # Кластер для атак с общим IP: same-ua (.50) или invalid-phone (.77)
        sample = next(
            (
                row
                for row in rows
                if str(row.ip_address) in {"203.0.113.50", INVALID_PHONE_IP}
            ),
            rows[0],
        )
        info = cluster_info(sample)
        if info:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(f"Кластер: {info.count} заявок ({info.key})"))
            self.stdout.write(f"  phones: {', '.join(info.unique_phones) or '—'}")
            self.stdout.write(f"  emails: {', '.join(info.unique_emails) or '—'}")
            self.stdout.write(f"  ids: {', '.join(f'#{pk}' for pk in info.request_ids)}")
        else:
            self.stdout.write("Кластер не собран (для diff-ua/одиночных это нормально).")
        self.stdout.write(
            f"Поиск в /requests/: IP 203.0.113.50 / {INVALID_PHONE_IP} или сырой телефон 8985451833."
        )
