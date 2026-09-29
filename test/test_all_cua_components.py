import unittest
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.richup_automator import RichupScreenState, TurnstileStatus
from src.browser_cdp import ensure_display_and_auth
from src.native_cua_engine import browser_snapshot, browser_navigate

class TestCUAComponents(unittest.TestCase):
    def test_richup_enums(self):
        self.assertEqual(RichupScreenState.LANDING.value, "LANDING")
        self.assertEqual(RichupScreenState.IN_GAME.value, "IN_GAME")
        self.assertEqual(TurnstileStatus.SOLVED.value, "SOLVED")
        self.assertEqual(TurnstileStatus.MANUAL_INTERVENTION_REQUIRED.value, "MANUAL_INTERVENTION_REQUIRED")

    def test_display_detection(self):
        ensure_display_and_auth()
        self.assertIn("DISPLAY", os.environ)
        self.assertTrue(os.environ["DISPLAY"].startswith(":"))

    def test_compact_dom_path_exists(self):
        compact_dom_path = os.path.join(PROJECT_ROOT, "src", "compact_dom.js")
        self.assertTrue(os.path.exists(compact_dom_path))
        with open(compact_dom_path, "r") as f:
            content = f.read()
            self.assertIn("createTreeWalker", content)
            self.assertIn("data-swades-id", content)

    def test_engine_callable(self):
        self.assertTrue(callable(browser_snapshot))
        self.assertTrue(callable(browser_navigate))

if __name__ == "__main__":
    unittest.main()
