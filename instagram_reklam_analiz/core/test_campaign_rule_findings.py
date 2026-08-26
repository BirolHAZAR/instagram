from datetime import date

from django.test import SimpleTestCase

from core.views.campaign_center import _structured_rule_findings


class CampaignRuleFindingTests(SimpleTestCase):
    def test_findings_are_dated_and_exact_duplicates_are_removed(self):
        event = {
            "event": "Gelir Verimi Düştü",
            "detected_at": "22.07.2026 09:43",
            "severity": "critical",
            "severity_label": "Kritik",
            "description": "Gelir Verimi Düştü: ROAS önceki güne göre azaldı.",
            "solution": "Bütçeyi kontrol et.",
        }

        findings = _structured_rule_findings(
            [event, dict(event)],
            date(2026, 6, 23),
            date(2026, 7, 22),
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["event"], "Gelir Verimi Düştü")
        self.assertEqual(findings[0]["detected_at"], "22.07.2026 09:43")
        self.assertEqual(findings[0]["description"], "ROAS önceki güne göre azaldı.")

    def test_same_rule_on_different_dates_remains_separate(self):
        first = {"event": "CTR Düştü", "detected_at": "21.07.2026", "description": "CTR %1,20"}
        second = {"event": "CTR Düştü", "detected_at": "22.07.2026", "description": "CTR %0,90"}

        findings = _structured_rule_findings([first, second], date(2026, 7, 1), date(2026, 7, 22))

        self.assertEqual([row["detected_at"] for row in findings], ["21.07.2026", "22.07.2026"])
