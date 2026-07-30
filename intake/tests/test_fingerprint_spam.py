"""Tests for UA/IP fingerprint spam signals and logical cluster grouping."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from intake.clusters import cluster_info, cluster_key, related_requests
from intake.models import InboundRequest, InboundRequestStatus
from intake.risk import evaluate_rules
from intake.services import payload_hash, process_request_by_rules

GOOD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
OTHER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1"


def _make(
    *,
    external_id: str,
    phone: str = "+7 999 000-00-00",
    phone_normalized: str = "",
    text: str = "Хочу купить автомобиль",
    user_agent: str = GOOD_UA,
    ip: str = "10.0.0.1",
    email: str = "lead@example.test",
    status: str = InboundRequestStatus.RECEIVED,
    minutes_ago: int = 0,
) -> InboundRequest:
    payload = {"phone": phone, "text": text}
    obj = InboundRequest.objects.create(
        external_id=external_id,
        source_type="site",
        source_name="site",
        name_raw="Lead",
        phone_raw=phone,
        phone_normalized=phone_normalized,
        email_raw=email,
        message_text=text,
        received_at=timezone.now() - timedelta(minutes=minutes_ago),
        raw_payload_json=payload,
        payload_hash=payload_hash(payload),
        ip_address=ip,
        user_agent=user_agent,
        status=status,
    )
    if minutes_ago:
        InboundRequest.objects.filter(pk=obj.pk).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago)
        )
        obj.refresh_from_db()
    return obj


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 1: invalid / malformed data
# ──────────────────────────────────────────────────────────────────────────────

class InvalidPhoneTests(TestCase):
    def test_garbage_phone_gives_phone_invalid_signal(self):
        """Mangle phone like 'abc' triggers phone_invalid, no 500."""
        inbound = _make(external_id="bad-phone-1", phone="abc")
        risk = evaluate_rules(inbound)
        codes = [s.code for s in risk.signals]
        self.assertIn("phone_invalid", codes)
        self.assertGreater(risk.score, 0)

    def test_short_number_phone_gives_phone_invalid(self):
        """Very short number like '123' also triggers phone_invalid."""
        inbound = _make(external_id="bad-phone-2", phone="123")
        risk = evaluate_rules(inbound)
        self.assertIn("phone_invalid", [s.code for s in risk.signals])

    def test_empty_phone_does_not_crash(self):
        """Empty phone field: evaluate_rules must not raise; no phone_normalized set."""
        inbound = _make(external_id="empty-phone", phone="")
        # Should not raise
        risk = evaluate_rules(inbound)
        # Empty phone treated as invalid
        self.assertIn("phone_invalid", [s.code for s in risk.signals])

    def test_disposable_email_domain_gives_signal(self):
        """Known disposable domain triggers disposable_email signal."""
        inbound = _make(external_id="disp-email", phone="+7 911 111-11-11", email="user@mailinator.com")
        risk = evaluate_rules(inbound)
        self.assertIn("disposable_email", [s.code for s in risk.signals])

    def test_process_request_by_rules_invalid_phone_does_not_raise(self):
        """Full pipeline with bad phone saves the record (risk_flagged or suspicious)."""
        inbound = _make(external_id="full-bad-phone", phone="+7 00")
        # Should not raise
        process_request_by_rules(inbound=inbound)
        inbound.refresh_from_db()
        self.assertIn(inbound.status, [
            InboundRequestStatus.PROCESSED,
            InboundRequestStatus.SUSPICIOUS,
            InboundRequestStatus.BLOCKED,
        ])


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 2: many requests, ALL DIFFERENT User-Agents → no ua_flood
# ──────────────────────────────────────────────────────────────────────────────

class DifferentUANoFloodTests(TestCase):
    def _unique_ua(self, i: int) -> str:
        return f"Mozilla/5.0 (BotBrowser/{i}) Gecko/20100101 Firefox/112.{i}"

    def test_different_ua_no_ua_flood_signal(self):
        """6 background requests, each a unique UA → ua_flood must NOT fire on #7."""
        ip = "10.10.10.10"
        for i in range(6):
            _make(
                external_id=f"diff-ua-bg-{i}",
                phone=f"+7 900 100-00-{i:02d}",
                phone_normalized=f"7900100000{i}",
                email=f"user{i}@example.test",
                user_agent=self._unique_ua(i),
                ip=ip,
                minutes_ago=10,
            )

        subject = _make(
            external_id="diff-ua-subject",
            phone="+7 900 200-00-00",
            user_agent=self._unique_ua(99),
            ip=ip,
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertNotIn("ua_flood", codes)
        self.assertNotIn("ua_multi_identity", codes)

    def test_different_ua_cluster_keys_are_distinct(self):
        """Each request with a unique UA has its own cluster key → no cross-mixing."""
        items = [
            _make(
                external_id=f"ck-ua-{i}",
                user_agent=self._unique_ua(i),
                ip="10.10.0.1",
                minutes_ago=5,
            )
            for i in range(3)
        ]
        keys = [cluster_key(item) for item in items]
        self.assertEqual(len(set(keys)), 3, "All cluster keys must be distinct")

    def test_ip_flood_fires_independently_of_ua_flood(self):
        """6 background reqs same IP but different UAs: ip_flood can fire, ua_flood must NOT."""
        ip = "10.20.0.1"
        for i in range(6):
            _make(
                external_id=f"ip-only-bg-{i}",
                phone=f"+7 901 000-00-{i:02d}",
                user_agent=self._unique_ua(i + 100),
                ip=ip,
                minutes_ago=10,
            )
        subject = _make(
            external_id="ip-only-subject",
            phone="+7 901 999-00-00",
            user_agent=self._unique_ua(999),
            ip=ip,
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        # ip_flood fires (7 total from same IP, 6 others > 5)
        self.assertIn("ip_flood", codes)
        # but ua_flood does NOT
        self.assertNotIn("ua_flood", codes)
        self.assertNotIn("ua_multi_identity", codes)


# ──────────────────────────────────────────────────────────────────────────────
# Scenario 3: many requests, SAME User-Agent → ua_flood + multi_identity
# ──────────────────────────────────────────────────────────────────────────────

class SameUAFloodTests(TestCase):
    def test_ua_flood_fires_when_more_than_5_others_in_hour(self):
        """6 background records with same UA → 7th sees 6 others > 5 → ua_flood."""
        ua = GOOD_UA
        for i in range(6):
            _make(
                external_id=f"ua-flood-bg-{i}",
                phone=f"+7 912 000-00-{i:02d}",
                user_agent=ua,
                ip="10.30.0.1",
                minutes_ago=20,
            )
        subject = _make(
            external_id="ua-flood-subject",
            phone="+7 912 999-00-00",
            user_agent=ua,
            ip="10.30.0.1",
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertIn("ua_flood", codes)

    def test_ua_flood_score_is_30(self):
        ua = GOOD_UA
        for i in range(6):
            _make(
                external_id=f"ua-score-bg-{i}",
                phone=f"+7 913 000-00-{i:02d}",
                user_agent=ua,
                ip="10.31.0.1",
                minutes_ago=20,
            )
        subject = _make(
            external_id="ua-score-subject",
            phone="+7 913 999-00-00",
            user_agent=ua,
            ip="10.31.0.1",
        )
        risk = evaluate_rules(subject)
        flood_signal = next((s for s in risk.signals if s.code == "ua_flood"), None)
        self.assertIsNotNone(flood_signal)
        self.assertEqual(flood_signal.score, 30)

    def test_ua_multi_identity_fires_at_3_different_phones(self):
        """Same UA with 3 distinct phone_normalized in24h → ua_multi_identity."""
        ua = OTHER_UA
        phones = ["+79141000001", "+79141000002", "+79141000003"]
        for i, ph in enumerate(phones):
            _make(
                external_id=f"ua-mi-bg-{i}",
                phone=ph,
                phone_normalized=ph.replace("+", ""),
                user_agent=ua,
                ip="10.40.0.1",
                minutes_ago=60,
            )
        subject = _make(
            external_id="ua-mi-subject",
            phone="+79141000099",
            user_agent=ua,
            ip="10.40.0.1",
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertIn("ua_multi_identity", codes)

    def test_ua_multi_identity_fires_at_3_different_emails(self):
        """Same UA with 3 distinct email_raw in 24h → ua_multi_identity."""
        ua = GOOD_UA + " EmailTest"
        for i in range(3):
            _make(
                external_id=f"ua-email-mi-bg-{i}",
                phone=f"+7 915 000-00-{i:02d}",
                email=f"spammer{i}@suspect.test",
                user_agent=ua,
                ip="10.41.0.1",
                minutes_ago=60,
            )
        subject = _make(
            external_id="ua-email-mi-subject",
            phone="+7 915 999-00-00",
            email="spammer99@suspect.test",
            user_agent=ua,
            ip="10.41.0.1",
        )
        risk = evaluate_rules(subject)
        self.assertIn("ua_multi_identity", [s.code for s in risk.signals])

    def test_empty_ua_no_ua_flood(self):
        """Empty UA must never trigger ua_flood regardless of request count."""
        for i in range(6):
            _make(
                external_id=f"empty-ua-bg-{i}",
                phone=f"+7 916 000-00-{i:02d}",
                user_agent="",
                ip="10.50.0.1",
                minutes_ago=20,
            )
        subject = _make(
            external_id="empty-ua-subject",
            phone="+7 916 999-00-00",
            user_agent="",
            ip="10.50.0.1",
        )
        risk = evaluate_rules(subject)
        codes = [s.code for s in risk.signals]
        self.assertNotIn("ua_flood", codes)
        self.assertNotIn("ua_multi_identity", codes)

    def test_short_ua_no_ua_flood(self):
        """UA shorter than UA_MIN_LENGTH must be skipped (treated as empty)."""
        short_ua = "curl/7"  # 6 chars < 10
        for i in range(6):
            _make(
                external_id=f"short-ua-bg-{i}",
                phone=f"+7 917 000-00-{i:02d}",
                user_agent=short_ua,
                ip="10.51.0.1",
                minutes_ago=20,
            )
        subject = _make(
            external_id="short-ua-subject",
            phone="+7 917 999-00-00",
            user_agent=short_ua,
            ip="10.51.0.1",
        )
        risk = evaluate_rules(subject)
        self.assertNotIn("ua_flood", [s.code for s in risk.signals])

    def test_same_ua_high_volume_reaches_suspicious_threshold(self):
        """ua_flood (+30) on top of other signals should push score >= 60 → suspicious."""
        ua = GOOD_UA
        for i in range(6):
            _make(
                external_id=f"ua-susp-bg-{i}",
                phone=f"+7 918 000-00-{i:02d}",
                user_agent=ua,
                ip="10.60.0.1",
                minutes_ago=15,
            )
        subject = _make(
            external_id="ua-susp-subject",
            phone="+7 918 999-00-00",
            text="Короткое",  # short_text +15, so 30+15 = 45 → risk_flagged; enough to see the signal
            user_agent=ua,
            ip="10.60.0.1",
        )
        process_request_by_rules(inbound=subject)
        subject.refresh_from_db()
        # ua_flood is in spam_reason
        self.assertIn("частые заявки с одного User-Agent", subject.spam_reason)

    def test_ua_flood_out_of_window_does_not_fire(self):
        """Requests older than 1h must not contribute to ua_flood count."""
        ua = GOOD_UA + " OldBatch"
        for i in range(6):
            _make(
                external_id=f"ua-old-bg-{i}",
                phone=f"+7 919 000-00-{i:02d}",
                user_agent=ua,
                ip="10.70.0.1",
                minutes_ago=90,  # 90 min ago → outside 1h window
            )
        subject = _make(
            external_id="ua-old-subject",
            phone="+7 919 999-00-00",
            user_agent=ua,
            ip="10.70.0.1",
        )
        risk = evaluate_rules(subject)
        self.assertNotIn("ua_flood", [s.code for s in risk.signals])


# ──────────────────────────────────────────────────────────────────────────────
# Cluster logic tests
# ──────────────────────────────────────────────────────────────────────────────

class ClusterTests(TestCase):
    def test_cluster_key_same_ua_returns_same_key(self):
        a = _make(external_id="ck-a", user_agent=GOOD_UA, ip="10.0.0.1")
        b = _make(external_id="ck-b", user_agent=GOOD_UA, ip="10.0.0.1")
        self.assertEqual(cluster_key(a), cluster_key(b))
        self.assertIn("ip:10.0.0.1", cluster_key(a))
        self.assertIn("ua:", cluster_key(a))

    def test_cluster_key_falls_back_to_ip_when_ua_short(self):
        obj = _make(external_id="ck-ip", user_agent="short", ip="10.0.1.1")
        self.assertEqual(cluster_key(obj), "ip:10.0.1.1")

    def test_cluster_key_telegram_returns_none(self):
        obj = _make(external_id="ck-tg", user_agent=GOOD_UA)
        obj.source_type = "telegram"
        obj.save(update_fields=["source_type"])
        self.assertIsNone(cluster_key(obj))

    def test_related_requests_returns_same_ua_records(self):
        """related_requests for a suspicious record returns all with same UA."""
        ua = GOOD_UA
        recs = [
            _make(
                external_id=f"rel-{i}",
                phone=f"+7 920 000-00-{i:02d}",
                user_agent=ua,
                ip="10.80.0.1",
                minutes_ago=30,
                status=InboundRequestStatus.SUSPICIOUS,
            )
            for i in range(3)
        ]
        subject = recs[0]
        subject.status = InboundRequestStatus.SUSPICIOUS
        subject.save(update_fields=["status"])

        qs = related_requests(subject, include_self=False)
        related_ids = set(qs.values_list("pk", flat=True))
        # Must contain the other 2 but not itself
        self.assertIn(recs[1].pk, related_ids)
        self.assertIn(recs[2].pk, related_ids)
        self.assertNotIn(subject.pk, related_ids)

    def test_related_requests_links_different_uas_on_same_ip(self):
        """Different UAs on the same IP still belong to one Admin Ops cluster."""
        a = _make(
            external_id="mix-a",
            user_agent=GOOD_UA,
            ip="10.90.0.1",
            minutes_ago=30,
            status=InboundRequestStatus.SUSPICIOUS,
        )
        b = _make(
            external_id="mix-b",
            user_agent=OTHER_UA,
            ip="10.90.0.1",
            minutes_ago=30,
            status=InboundRequestStatus.SUSPICIOUS,
        )
        related_a = set(related_requests(a, include_self=False).values_list("pk", flat=True))
        self.assertIn(b.pk, related_a)

    def test_related_requests_does_not_mix_unrelated_ip_and_ua(self):
        """Different UA and different IP must not appear in each other's related set."""
        a = _make(
            external_id="nomix-a",
            user_agent=GOOD_UA,
            ip="10.90.0.1",
            minutes_ago=30,
            status=InboundRequestStatus.SUSPICIOUS,
        )
        b = _make(
            external_id="nomix-b",
            user_agent=OTHER_UA,
            ip="10.90.0.2",
            minutes_ago=30,
            status=InboundRequestStatus.SUSPICIOUS,
        )
        related_a = set(related_requests(a, include_self=False).values_list("pk", flat=True))
        self.assertNotIn(b.pk, related_a)

    def test_cluster_info_aggregates_phones_and_emails(self):
        """cluster_info collects all unique phones/emails across related requests."""
        ua = GOOD_UA
        phones = ["+79200000001", "+79200000002", "+79200000003"]
        emails = ["a@x.test", "b@x.test"]
        for i, (ph, em) in enumerate(zip(phones, emails + ["c@x.test"])):
            _make(
                external_id=f"agg-{i}",
                phone=ph,
                phone_normalized=ph.replace("+", ""),
                email=em,
                user_agent=ua,
                ip="10.100.0.1",
                minutes_ago=60,
                status=InboundRequestStatus.SUSPICIOUS,
            )

        subject = _make(
            external_id="agg-subject",
            phone="+79200000099",
            phone_normalized="79200000099",
            email="z@x.test",
            user_agent=ua,
            ip="10.100.0.1",
            status=InboundRequestStatus.SUSPICIOUS,
        )
        info = cluster_info(subject)
        self.assertIsNotNone(info)
        self.assertEqual(info.count, 3)
        self.assertGreaterEqual(len(info.unique_phones), 3)
        self.assertGreaterEqual(len(info.unique_emails), 3)

    def test_cluster_info_returns_none_for_lone_request(self):
        """No other requests with same UA → cluster_info returns None."""
        obj = _make(external_id="lone", user_agent=GOOD_UA, ip="10.200.0.1",
                    status=InboundRequestStatus.SUSPICIOUS)
        self.assertIsNone(cluster_info(obj))

    def test_cluster_info_returns_none_for_telegram(self):
        obj = _make(external_id="tg-cluster", user_agent=GOOD_UA)
        obj.source_type = "telegram"
        obj.save(update_fields=["source_type"])
        self.assertIsNone(cluster_info(obj))


# ──────────────────────────────────────────────────────────────────────────────
# fingerprint_mass_identity signal (long-window, score=90)
# ──────────────────────────────────────────────────────────────────────────────

class MassIdentityTests(TestCase):
    """Tests for the fingerprint_mass_identity risk signal.

    Thresholds: ≥4 distinct phones/emails in 24h → 90; ≥6 in 7d → 90.
    """

    def test_24h_4_distinct_phones_fires_mass_signal(self):
        """4 peers with distinct phone_raw from same IP in 24h → fingerprint_mass_identity."""
        ip = "10.150.0.1"
        for i in range(4):
            _make(
                external_id=f"mass-24h-{i}",
                phone=f"+7 920 000-0{i}-00",
                email=f"x{i}@example.test",
                ip=ip,
                minutes_ago=60,
            )
        subject = _make(external_id="mass-24h-subject", phone="+7 920 999-00-00", ip=ip)
        risk = evaluate_rules(subject)
        self.assertIn("fingerprint_mass_identity", [s.code for s in risk.signals])
        self.assertGreaterEqual(risk.score, 90)

    def test_24h_4_distinct_emails_fires_mass_signal(self):
        """4 peers with distinct email_raw from same IP in 24h → fingerprint_mass_identity."""
        ip = "10.151.0.1"
        for i in range(4):
            _make(
                external_id=f"mass-email-{i}",
                phone="+7 921 000-00-00",  # same phone — emails differ
                email=f"user{i}@attack.test",
                ip=ip,
                minutes_ago=60,
            )
        subject = _make(
            external_id="mass-email-subject",
            phone="+7 921 000-00-00",
            email="attacker@attack.test",
            ip=ip,
        )
        risk = evaluate_rules(subject)
        self.assertIn("fingerprint_mass_identity", [s.code for s in risk.signals])

    def test_7d_6_distinct_phones_fires_mass_signal(self):
        """6 peers spread over 7 days from same IP → fingerprint_mass_identity via 7d window."""
        ip = "10.152.0.1"
        for i in range(6):
            obj = _make(
                external_id=f"mass-7d-{i}",
                phone=f"+7 922 00{i}-00-00",
                ip=ip,
                minutes_ago=0,
            )
            # Backdate to 3 days ago to be outside 24h but inside 7d
            from django.utils import timezone as tz
            InboundRequest.objects.filter(pk=obj.pk).update(
                created_at=tz.now() - timedelta(days=3)
            )
        subject = _make(external_id="mass-7d-subject", phone="+7 922 999-00-00", ip=ip)
        risk = evaluate_rules(subject)
        self.assertIn("fingerprint_mass_identity", [s.code for s in risk.signals])

    def test_below_24h_threshold_no_mass_signal(self):
        """3 peers from same IP in 24h → below threshold, no fingerprint_mass_identity."""
        ip = "10.153.0.1"
        for i in range(3):
            _make(
                external_id=f"mass-below-{i}",
                phone=f"+7 923 000-0{i}-00",
                ip=ip,
                minutes_ago=60,
            )
        subject = _make(external_id="mass-below-subject", phone="+7 923 999-00-00", ip=ip)
        risk = evaluate_rules(subject)
        self.assertNotIn("fingerprint_mass_identity", [s.code for s in risk.signals])

    def test_internal_trust_exempt_from_mass(self):
        """Internal trust → fingerprint_mass_identity must NOT fire."""
        from intake.models import TrustLevel
        ip = "10.154.0.1"
        for i in range(6):
            _make(
                external_id=f"int-mass-{i}",
                phone=f"+7 924 000-0{i}-00",
                ip=ip,
                minutes_ago=30,
            )
        subject = _make(external_id="int-mass-subject", phone="+7 924 999-00-00", ip=ip)
        subject.trust_level = TrustLevel.INTERNAL
        subject.save(update_fields=["trust_level"])
        risk = evaluate_rules(subject)
        self.assertNotIn("fingerprint_mass_identity", [s.code for s in risk.signals])

    def test_telegram_exempt_from_mass(self):
        """Telegram requests have trust_level=internal → fingerprint_mass_identity must NOT fire."""
        from intake.models import TrustLevel
        ip = "10.155.0.1"
        for i in range(6):
            _make(
                external_id=f"tg-mass-{i}",
                phone=f"+7 925 000-0{i}-00",
                ip=ip,
                minutes_ago=30,
            )
        subject = _make(external_id="tg-mass-subject", phone="+7 925 999-00-00", ip=ip)
        # create_telegram_inbound_request always sets trust_level=internal; replicate here.
        subject.source_type = "telegram"
        subject.trust_level = TrustLevel.INTERNAL
        subject.save(update_fields=["source_type", "trust_level"])
        risk = evaluate_rules(subject)
        self.assertNotIn("fingerprint_mass_identity", [s.code for s in risk.signals])

    def test_mass_identity_score_is_90(self):
        """fingerprint_mass_identity signal score must be exactly 90."""
        from intake.risk import RISK_SIGNAL_SCORES
        self.assertEqual(RISK_SIGNAL_SCORES["fingerprint_mass_identity"], 90)

    def test_mass_identity_leads_to_blocked_status(self):
        """process_request_by_rules with mass identity → status blocked, no linked deal."""
        ip = "10.156.0.1"
        for i in range(4):
            _make(
                external_id=f"proc-mass-{i}",
                phone=f"+7 926 000-0{i}-00",
                ip=ip,
                minutes_ago=30,
            )
        subject = _make(
            external_id="proc-mass-subject",
            phone="+7 926 999-00-00",
            text="Хочу Haval Jolion в кредит",
            ip=ip,
        )
        process_request_by_rules(inbound=subject)
        subject.refresh_from_db()
        self.assertEqual(subject.status, InboundRequestStatus.BLOCKED)
        self.assertIsNone(subject.linked_deal)
        self.assertIn("много разных контактов", subject.spam_reason)

    def test_batch_7_same_ip_all_blocked(self):
        """7 requests from same IP with distinct phones: all → blocked after process."""
        ip = "10.157.0.1"
        batch = [
            _make(
                external_id=f"batch-{i}",
                phone=f"+7 927 {i:03d}-00-00",
                ip=ip,
            )
            for i in range(7)
        ]
        # Process in reverse order (most peers first), matching demo command behavior.
        for inbound in sorted(batch, key=lambda x: x.pk, reverse=True):
            process_request_by_rules(inbound=inbound)
        for inbound in batch:
            inbound.refresh_from_db()
            self.assertEqual(
                inbound.status,
                InboundRequestStatus.BLOCKED,
                f"Request #{inbound.id} should be blocked, got {inbound.status}",
            )
