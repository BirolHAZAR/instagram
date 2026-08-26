from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.template.loader import render_to_string

from core.utils.html_translations import repair_mojibake


CONTROL_TOWER_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "templates" / "dashboard" / "control_tower"
)
MOJIBAKE_MARKERS = ("Ã", "Â", "Ä", "Å", "â€", "ðŸ", "�", "þ", "ý", "ð", "Ý", "Þ", "Ð")


class ControlTowerEncodingTests(SimpleTestCase):
    def test_repair_mojibake_supports_utf8_and_windows_1254_artifacts(self):
        broken = "DÃ–NÃœÅ\x9eÃœM, saÄ\x9flÄ±k, paylaÅ\x9fÄ±m ve dönüþüm deðeri"

        self.assertEqual(
            repair_mojibake(broken),
            "DÖNÜŞÜM, sağlık, paylaşım ve dönüşüm değeri",
        )

    def test_control_tower_templates_are_saved_as_clean_utf8(self):
        offenders = []
        for template_path in CONTROL_TOWER_TEMPLATE_DIR.glob("*.html"):
            content = template_path.read_text(encoding="utf-8-sig")
            found = [marker for marker in MOJIBAKE_MARKERS if marker in content]
            if found:
                offenders.append(f"{template_path.name}: {', '.join(found)}")

        self.assertEqual(offenders, [], "Bozuk kodlanmış Control Tower şablonları bulundu")

    def test_prominent_agency_filter_is_only_rendered_for_agencies(self):
        organization = SimpleNamespace(name="Demo Ajans")
        client = SimpleNamespace(id=4, name="Demo Marka", organization=organization)
        filters = SimpleNamespace(
            active_period="monthly",
            date_from="2026-06-13",
            date_to="2026-07-13",
        )
        request = SimpleNamespace(path="/control-tower/")

        agency_html = render_to_string(
            "dashboard/control_tower/agency_filter.html",
            {
                "agency_scope": SimpleNamespace(
                    is_agency=True,
                    selected_client=client,
                    clients=(client,),
                ),
                "filters": filters,
                "request": request,
            },
        )
        personal_html = render_to_string(
            "dashboard/control_tower/agency_filter.html",
            {
                "agency_scope": SimpleNamespace(
                    is_agency=False,
                    selected_client=None,
                    clients=(),
                ),
                "filters": filters,
                "request": request,
            },
        )

        self.assertIn('class="ct-agency-filter-feature"', agency_html)
        self.assertIn("Demo Ajans · Demo Marka", agency_html)
        self.assertIn("Firma filtresi aktif", agency_html)
        self.assertNotIn('class="ct-agency-filter-feature"', personal_html)

    def test_executive_agency_filter_renders_selected_client(self):
        organization = SimpleNamespace(name="Demo Ajans")
        client = SimpleNamespace(id=4, name="Demo Marka", organization=organization)
        html = render_to_string(
            "dashboard/executive_agency_filter.html",
            {
                "agency_scope": SimpleNamespace(
                    is_agency=True,
                    selected_client=client,
                    clients=(client,),
                ),
                "request": SimpleNamespace(path="/executive-dashboard/"),
            },
        )

        self.assertIn('class="exec-agency-filter"', html)
        self.assertIn("Demo Ajans · Demo Marka", html)
        self.assertIn("Firma filtresi aktif", html)
