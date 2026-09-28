#!/usr/bin/env python3
"""
native_cua_engine.py — Native Linux CUA Master Engine v1.0
Combines:
1. Chromium Accessibility Tree via Playwright / CDP (page.accessibility.snapshot pruned)
2. Native Linux Desktop Accessibility Tree via AT-SPI2 / PyGObject
3. Functional Semantic Selectors (get_by_role, click, fill) + Native Fallback
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
        """Extracts and clean-filters Chromium Accessibility layout nodes."""
        # Try Playwright first if installed
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=3000)
                contexts = browser.contexts
                if not contexts or not contexts[0].pages:
                    return {"status": "No active browser tabs opened"}
                
                page = contexts[0].pages[0]
                raw_tree = page.accessibility.snapshot()
                browser.close()
                return self._prune_node(raw_tree)
        except Exception as pw_err:
            # Fallback to direct CDP WebSocket / HTTP evaluation
            try:
                import urllib.request
                import websocket
                tabs = json.loads(urllib.request.urlopen(f"{self.cdp_url}/json", timeout=1.5).read().decode('utf-8'))
                page_tabs = [t for t in tabs if t.get('type') == 'page']
                if not page_tabs:
                    return {"status": "No active browser tabs opened"}
                
                ws_url = page_tabs[0]["webSocketDebuggerUrl"]
                ws = websocket.create_connection(ws_url, timeout=2)
                # Request Accessibility.getFullAXTree or evaluate compact DOM representation
                js_code = """
                (function() {
                    var items = [];
                    var title = document.title;
                    if (title) items.push({role: "heading", name: title, value: title});
                    var elements = document.querySelectorAll('h1, h2, h3, h4, p, button, a, input, select, textarea, [role="button"], [role="link"], [role="heading"], [role="textbox"]');
                    var seen = new Set();
                    for (var el of elements) {
                        var txt = (el.innerText || el.textContent || el.value || el.placeholder || "").trim();
                        if (txt && txt.length >= 2 && !seen.has(txt)) {
                            seen.add(txt);
                            var role = el.getAttribute('role') || el.tagName.toLowerCase();
                            if (role === 'a') role = 'link';
                            if (role === 'input') role = el.type === 'button' || el.type === 'submit' ? 'button' : 'textbox';
                            items.push({
                                role: role,
                                name: txt.slice(0, 100),
                                value: el.value || undefined,
                                focused: document.activeElement === el ? true : undefined
                            });
                            if (items.length >= 35) break;
                        }
                    }
                    return items;
                })()
                """
                ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js_code, "returnByValue": True}}))
                res = json.loads(ws.recv())
                ws.close()
                items = res.get("result", {}).get("result", {}).get("value", [])
                if isinstance(items, list):
                    return {"role": "WebArea", "name": page_tabs[0].get("title", "Web Page"), "children": items}
            except Exception as cdp_err:
                pass
            return {"status": f"Browser CDP offline ({str(pw_err)})"}

    def _prune_node(self, node: dict) -> dict:
        """Recursively removes layout bloat to keep tokens incredibly small."""
        if not node:
            return {}
        
        pruned = {
            "role": node.get("role"),
            "name": (node.get("name") or "").strip()
        }
        
        if "value" in node and node["value"]:
            pruned["value"] = node["value"]
        if node.get("focused"):
            pruned["focused"] = True
            
        if "children" in node:
            valid_children = []
            for child in node["children"]:
                clean_child = self._prune_node(child)
                if clean_child and (clean_child.get("name") or clean_child.get("children") or clean_child.get("value")):
                    valid_children.append(clean_child)
            if valid_children:
                pruned["children"] = valid_children
                
        return pruned

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

    def execute_browser_action(self, action: str, role: str, name: str, value: str = None):
        """Executes a browser interaction strictly via functional selectors."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url)
                page = browser.contexts[0].pages[0]
                locator = page.get_by_role(role, name=name)
                
                if action == "click":
                    locator.click()
                elif action == "type" or action == "fill":
                    locator.fill(value or "")
                browser.close()
                return {"success": True}
        except Exception as e:
            # Fallback to coordinate or xdotool
            return {"success": False, "error": str(e)}

    def execute_desktop_click(self, x: int, y: int):
        """Fallback system coordination click engine (runs natively inside Linux environment)."""
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=False)
        return {"success": True}


if __name__ == "__main__":
    engine = NativeCUAEngine()
    if len(sys.argv) > 1 and sys.argv[1] == "state":
        print(engine.get_integrated_ui_state())
    else:
        print(engine.get_integrated_ui_state())
