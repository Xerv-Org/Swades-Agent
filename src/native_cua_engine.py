#!/usr/bin/env python3
"""
native_cua_engine.py — High-Performance Native Linux CUA Engine v2.0
Combines:
1. Playwright CDP Browser Extraction (ARIA Snapshots + Main Content Text Extraction)
2. Direct Playwright Functional Actions (click, fill, goto, scroll)
3. Native Linux Desktop AT-SPI2 / PyGObject Integration
"""

import sys
import os
import json
import subprocess
import warnings

warnings.filterwarnings("ignore")

if "/usr/lib/python3/dist-packages" not in sys.path:
    sys.path.append("/usr/lib/python3/dist-packages")

def ensure_display_and_env():
    if not os.environ.get("DISPLAY"):
        if os.path.exists("/tmp/.X11-unix/X99"):
            os.environ["DISPLAY"] = ":99"
        else:
            os.environ["DISPLAY"] = ":0"
    os.environ["GTK_MODULES"] = "gail:atk-bridge"
    os.environ["NO_AT_BRIDGE"] = "0"
    os.environ["QT_ACCESSIBILITY"] = "1"
    os.environ["AX_ENABLED"] = "1"

ensure_display_and_env()

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    HAS_ATSPI = True
except Exception:
    HAS_ATSPI = False


class NativeCUAEngine:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self.cdp_url = cdp_url

    def get_integrated_ui_state(self) -> str:
        """
        Gathers structural elements from both the Web DOM and Native Apps,
        merging them into a single token-optimized JSON payload.
        """
        state = {
            "browser_context": self._get_browser_tree(),
            "desktop_context": self._get_desktop_tree()
        }
        return json.dumps(state, indent=2)

    def _get_browser_tree(self) -> dict:
        """Extracts and clean-filters Chromium Accessibility layout nodes using Playwright."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=3000)
                contexts = browser.contexts
                if not contexts or not contexts[0].pages:
                    browser.close()
                    return {"status": "No active browser tabs opened"}
                
                page = contexts[0].pages[0]
                title = page.title()
                url = page.url
                
                # Extract main content text
                main_text = ""
                for selector in ['#main', '#rso', '[role="main"]', 'article', 'main', 'body']:
                    loc = page.locator(selector).first
                    try:
                        if loc.count() > 0:
                            txt = loc.inner_text(timeout=1000).strip()
                            if len(txt) > 50:
                                main_text = txt
                                break
                    except Exception:
                        pass
                
                # Extract key interactive elements (links, headings, buttons)
                interactive_items = []
                try:
                    js_code = """
                    (function() {
                        var items = [];
                        var els = document.querySelectorAll('h1, h2, h3, h4, [role="heading"], a[href], button, input, [role="button"]');
                        var seen = new Set();
                        for (var el of els) {
                            var txt = (el.innerText || el.textContent || el.value || "").trim();
                            if (txt && txt.length > 2 && !seen.has(txt)) {
                                seen.add(txt);
                                var tag = el.tagName.toLowerCase();
                                var role = el.getAttribute('role') || (tag.startsWith('h') ? 'heading' : (tag === 'a' ? 'link' : tag));
                                items.push({
                                    role: role,
                                    name: txt.slice(0, 100),
                                    value: el.value || undefined
                                });
                                if (items.length >= 35) break;
                            }
                        }
                        return items;
                    })()
                    """
                    interactive_items = page.evaluate(js_code)
                except Exception:
                    pass

                browser.close()
                return {
                    "role": "WebArea",
                    "title": title,
                    "url": url,
                    "content_summary": main_text[:1200] if main_text else "",
                    "elements": interactive_items[:30]
                }
        except Exception as e:
            return {"status": f"Browser CDP offline: {str(e)}"}

    def _get_desktop_tree(self) -> list:
        """Queries Linux D-Bus registry for system windows outside of Chromium."""
        inventory = []
        if not HAS_ATSPI:
            return inventory
            
        SYSTEM_NAMES = {"xfwm4", "xfce4-panel", "xfdesktop", "desktop", "mutter", "wrapper-2.0"}
        try:
            desktop = Atspi.get_desktop(0)
            for i in range(desktop.get_child_count()):
                app = desktop.get_child_at_index(i)
                if not app:
                    continue
                app_name = app.get_name() or ""
                app_name_lower = app_name.lower()
                
                # Skip browser (handled via CDP) and system desktop components
                if any(k in app_name_lower for k in ["chromium", "chrome", "google-chrome"]):
                    continue
                if any(s == app_name_lower for s in SYSTEM_NAMES):
                    continue
                
                app_elements = []
                self._traverse_atspi(app, app_elements)
                if app_elements:
                    inventory.append({
                        "app": app_name,
                        "elements": app_elements[:25]
                    })
        except Exception:
            pass
        return inventory

    def _traverse_atspi(self, node, element_list, depth=0, max_depth=6):
        if not node or depth > max_depth or len(element_list) >= 30:
            return
        try:
            role = (node.get_role_name() or "").lower()
            name = (node.get_name() or "").strip()
            
            # Interactive roles
            if any(r in role for r in ["push button", "button", "entry", "text", "link", "check box", "radio", "menu item", "terminal", "page tab", "combo box"]):
                geom = None
                try:
                    cif = node.get_component_iface()
                    if cif:
                        r = cif.get_extents(Atspi.CoordType.SCREEN)
                        if r.width > 0 and r.height > 0 and (r.x >= 0 or r.y >= 0):
                            geom = {
                                "x": r.x + (r.width // 2),
                                "y": r.y + (r.height // 2)
                            }
                except Exception:
                    pass
                
                if name or geom:
                    entry = {"role": role}
                    if name:
                        entry["name"] = name
                    if geom:
                        entry["coords"] = geom
                    element_list.append(entry)
        except Exception:
            pass
            
        cc = node.get_child_count()
        for i in range(min(cc, 20)):
            self._traverse_atspi(node.get_child_at_index(i), element_list, depth + 1, max_depth)

    def execute_browser_action(self, action: str, role: str = None, name: str = None, value: str = None, url: str = None):
        """Executes a browser interaction strictly via Playwright functional selectors."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url)
                page = browser.contexts[0].pages[0]
                
                if action == "goto" and url:
                    page.goto(url, timeout=10000)
                elif action == "click" and role and name:
                    page.get_by_role(role, name=name).click(timeout=5000)
                elif action in ["type", "fill"] and role and name:
                    page.get_by_role(role, name=name).fill(value or "", timeout=5000)
                elif action == "scroll":
                    page.evaluate(f"window.scrollBy(0, {value or 500})")
                
                browser.close()
                return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_desktop_click(self, x: int, y: int):
        """Fallback system coordination click engine."""
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=False)
        return {"success": True}


if __name__ == "__main__":
    engine = NativeCUAEngine()
    print(engine.get_integrated_ui_state())
