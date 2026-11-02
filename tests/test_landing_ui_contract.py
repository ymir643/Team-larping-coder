"""Source-level guardrails for the landing page and responsive dome nav.

These checks protect the structure and responsive rules; they do not replace
real-browser viewport testing.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "style.css").read_text(encoding="utf-8")


class LandingUiContractTests(unittest.TestCase):
    def test_role_selector_remains_before_new_landing_sections(self):
        landing_start = HTML.index('<section id="landing-page"')
        selector = HTML.index('<section class="portal-card glass-panel"')
        brand = HTML.index('<section id="loopin-branding"')
        events = HTML.index('<section id="official-campus-events"')
        dashboard = HTML.index('<div id="student-view"')
        self.assertLess(landing_start, selector)
        self.assertLess(selector, brand)
        self.assertLess(brand, events)
        self.assertLess(events, dashboard)
        for role in ("STUDENT", "VISITOR", "ADMIN"):
            self.assertIn(f"selectPortal('{role}', this)", HTML)

    def test_branding_copy_and_topographic_asset_are_present(self):
        self.assertIn("loopIn", HTML)
        self.assertIn("Where Ideas Become Reality.", HTML)
        self.assertIn("/assets/topography.svg", CSS)
        self.assertIn('href="#official-campus-events"', HTML)

    def test_official_event_cards_use_past_labels_and_official_sources(self):
        cards = re.findall(r'<article class="official-event-card">(.*?)</article>', HTML, re.S)
        self.assertEqual(len(cards), 3)
        for card in cards:
            self.assertRegex(card, r'class="official-event-status past">Past · [0-9]{4} edition')
            self.assertRegex(card, r'href="https://www\.bits-pilani\.ac\.in/hyderabad/events-festivals/')
        self.assertIn("does not publish future dates", HTML)

    def test_original_wheel_actions_remain_available(self):
        for tab in ("campus", "map", "events", "contact", "announcements", "progress"):
            self.assertIn(f"switchStudentSubTab('{tab}', this)", HTML)
        self.assertIn("student-campus-subview", HTML)
        self.assertIn("student-events-subview", HTML)

    def test_mobile_wheel_is_a_top_mounted_fan_not_a_button_grid(self):
        mobile_rules = CSS[CSS.rfind("/* Mobile radial wheel:"):]
        self.assertIn("position:relative", mobile_rules)
        self.assertIn("border-radius:0 0 50% 50% / 0 0 100% 100%", mobile_rules)
        self.assertIn("aspect-ratio:2/1", mobile_rules)
        for angle in ("125deg", "111deg", "97deg", "83deg", "69deg", "55deg"):
            self.assertIn(f"--tab-angle:{angle}", mobile_rules)
        self.assertIn("mobile-campus-tab", HTML)
        self.assertIn("width:104px; height:36px", mobile_rules)
        self.assertNotIn("grid-template-columns:repeat(3", mobile_rules)
        self.assertIn("@media (max-width:520px)", mobile_rules)
        self.assertIn("campus-hero { min-height:clamp(460px", mobile_rules)
        self.assertIn("margin-top:.5rem", mobile_rules)

    def test_student_id_dialog_precedes_dashboard_and_is_not_persisted(self):
        dialog = HTML.index('id="student-id-dialog"')
        dashboard = HTML.index('id="student-view"')
        self.assertLess(dialog, dashboard)
        for text in ("Student ID", "Enter your organization-provided ID number.", "ID Number", "Enter your ID number", "Continue", "Cancel"):
            self.assertIn(text, HTML)
        source = (ROOT / "script.js").read_text(encoding="utf-8")
        handler = source[source.index("function continueStudentId"):source.index("function cancelStudentId")]
        self.assertIn(".trim()", handler)
        self.assertIn("input.value = ''", handler)
        self.assertNotIn("localStorage", handler)
        self.assertNotIn("fetch(", handler)

    def test_topography_isolated_to_opening_role_screen(self):
        self.assertIn('id="role-topography" class="role-topography"', HTML)
        self.assertIn('id="role-screen"', HTML)
        self.assertIn('src="/assets/topography-background.js?v=2"', HTML)
        self.assertIn('href="/assets/topography-background.css?v=2"', HTML)
        source = (ROOT / "topography" / "Topography.jsx").read_text(encoding="utf-8")
        mount = (ROOT / "topography" / "mount.jsx").read_text(encoding="utf-8")
        self.assertIn("getContext('webgl2'", source)
        self.assertIn("webgl2-ready", mount)
        self.assertIn("TopographyBoundary", mount)
        self.assertIn('color="#4f7cff"', mount)
        self.assertIn("lineCount={22}", mount)
        self.assertIn("lineWidth={1.2}", mount)
        self.assertIn('hoverEffect="lift"', mount)
        self.assertIn('clickEffect="pulse"', mount)
        self.assertIn("speed={reducedMotion ? 0 : 0.25}", mount)
        self.assertIn("requestAnimationFrame", source)
        self.assertIn("IntersectionObserver", source)
        self.assertIn("aria-hidden=\"true\"", HTML)

    def test_desktop_left_wheel_and_reduced_motion_rules_remain(self):
        self.assertIn("@media (min-width:901px) {\n  .student-stage-content { margin-left:250px; }", CSS)
        self.assertIn("@media (prefers-reduced-motion:reduce)", CSS)
        self.assertIn(".semi-circle-dock { position:fixed", CSS)
        self.assertIn(".semi-circle-dock { position:relative; inset:auto", CSS)


if __name__ == "__main__":
    unittest.main()
