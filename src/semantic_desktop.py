#!/usr/bin/env python3
import sys
import json
import os
import glob
import subprocess
import re
import warnings

warnings.filterwarnings("ignore")

# Ensure dist-packages is available for system PyGObject / Atspi
if "/usr/lib/python3/dist-packages" not in sys.path:
    sys.path.append("/usr/lib/python3/dist-packages")

# Dynamic Display & Auth Auto-Discovery
def ensure_display_and_auth():
    if not os.environ.get("DISPLAY"):
        if os.path.exists("/tmp/.X11-unix/X99"):
            os.environ["DISPLAY"] = ":99"
        else:
            os.environ["DISPLAY"] = ":0"

ensure_display_and_auth()

import gi
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# Ensure accessibility bridge is active
os.environ["GTK_MODULES"] = "gail:atk-bridge"
os.environ["NO_AT_BRIDGE"] = "0"

def get_node_states(node):
    states = []
    try:
        state_set = node.get_state_set()
        if state_set:
            if state_set.contains(Atspi.StateType.VISIBLE): states.append("visible")
            if state_set.contains(Atspi.StateType.SHOWING): states.append("showing")
            if state_set.contains(Atspi.StateType.FOCUSABLE): states.append("focusable")
            if state_set.contains(Atspi.StateType.FOCUSED): states.append("focused")
            if state_set.contains(Atspi.StateType.EDITABLE): states.append("editable")
            if state_set.contains(Atspi.StateType.ENABLED): states.append("enabled")
            if state_set.contains(Atspi.StateType.ACTIVE): states.append("active")
            if state_set.contains(Atspi.StateType.CHECKED): states.append("checked")
    except Exception:
        pass
    return states

def get_node_extents(node):
    try:
        comp = node.get_component_iface()
        if comp:
            rect = comp.get_extents(Atspi.CoordType.SCREEN)
            if rect.width <= 0 or rect.height <= 0 or rect.x < -1000 or rect.y < -1000:
                return None
            return {
                "x": rect.x,
                "y": rect.y,
                "width": rect.width,
                "height": rect.height,
                "center_x": rect.x + (rect.width // 2) if rect.width > 0 else rect.x,
                "center_y": rect.y + (rect.height // 2) if rect.height > 0 else rect.y
            }
    except Exception:
        pass
    return None

def get_compact_accessible_tree(node, max_elements=60, current_depth=0, max_depth=10, elements=None):
    if elements is None:
        elements = []
    if not node or current_depth > max_depth or len(elements) >= max_elements:
        return elements

    try:
        role = (node.get_role_name() or "unknown").lower()
        name = (node.get_name() or "").strip()
        states = get_node_states(node)

        # Extract text for text-like nodes
        text = ""
        if any(r in role for r in ["text", "entry", "label", "paragraph", "heading", "value"]):
            try:
                tif = node.get_text_iface()
                if tif:
                    c = tif.get_character_count()
                    if c > 0:
                        text = Atspi.Text.get_text(tif, 0, min(c, 300)).strip()
            except Exception:
                pass

        # Extract actions for interactive nodes
        actions = []
        if any(r in role for r in ["button", "menu", "entry", "link", "tab", "item", "check", "radio", "page", "frame", "window"]):
            try:
                aif = node.get_action_iface()
                if aif:
                    for i in range(aif.get_n_actions()):
                        aname = Atspi.Action.get_action_name(aif, i)
                        if aname:
                            actions.append(aname)
            except Exception:
                pass

        # Extract geometry
        geom = None
        if name or text or actions or role in ["entry", "text", "button", "tab", "page", "frame", "window"]:
            try:
                cif = node.get_component_iface()
                if cif:
                    r = cif.get_extents(Atspi.CoordType.SCREEN)
                    if r.width > 0 and r.height > 0:
                        geom = {"x": r.x, "y": r.y, "w": r.width, "h": r.height, "cx": r.x + r.width // 2, "cy": r.y + r.height // 2}
            except Exception:
                pass

        # Add semantic node if it has meaningful name/text/actions or is an interactive role
        if name or text or actions or role in ["entry", "text", "button", "tab", "page", "frame", "window", "dialog"]:
            item = {"role": role}
            if name:
                item["name"] = name
            if text and text != name:
                item["text"] = text
            if actions:
                item["actions"] = actions
            if geom:
                item["bounds"] = geom
            elements.append(item)

        # Recurse children
        cc = node.get_child_count()
        for i in range(min(cc, 25)):
            get_compact_accessible_tree(node.get_child_at_index(i), max_elements, current_depth + 1, max_depth, elements)
    except Exception:
        pass
    return elements

def get_accessible_tree(node, max_depth=7, current_depth=0):
    elements = get_compact_accessible_tree(node, max_elements=50, max_depth=max_depth)
    return elements

def find_node_by_name_or_role(node, target_name, target_role=None, depth=0, max_depth=8):
    if not node or depth > max_depth:
        return None
    try:
        name = node.get_name() or ""
        role = node.get_role_name() or ""

        if target_role and role.lower() == target_role.lower():
            if not target_name or target_name.lower() in name.lower():
                return node
        elif not target_role and target_name and target_name.lower() in name.lower():
            return node

        child_count = node.get_child_count()
        for i in range(min(child_count, 20)):
            found = find_node_by_name_or_role(node.get_child_at_index(i), target_name, target_role, depth + 1, max_depth)
            if found:
                return found
    except Exception:
        pass
    return None

def find_focused_node(node, depth=0, max_depth=8):
    if not node or depth > max_depth:
        return None
    try:
        name = (node.get_name() or "").lower()
        role = (node.get_role_name() or "").lower()
        if any(s in name or s in role for s in ["xfwm4", "xfce4-panel", "xfdesktop"]):
            return None
        states = get_node_states(node)
        if "focused" in states:
            ext = get_node_extents(node)
            if ext and ext.get("x", 0) < 0 and ext.get("y", 0) < 0:
                pass
            else:
                return node

        child_count = node.get_child_count()
        for i in range(min(child_count, 20)):
            res = find_focused_node(node.get_child_at_index(i), depth + 1, max_depth)
            if res:
                return res
    except Exception:
        pass
    return None


def get_browser_cdp_elements():
    try:
        import urllib.request, websocket
        tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=1.5).read().decode("utf-8"))
        page_tabs = [t for t in tabs if t.get("type") == "page"]
        if not page_tabs:
            return []
        
        ws_url = page_tabs[0]["webSocketDebuggerUrl"]
        ws = websocket.create_connection(ws_url, timeout=2)
        js_code = """(function() {
            var items = [];
            var title = document.title;
            if (title) items.push({role: 'heading', name: title, text: title});
            var elements = document.querySelectorAll('h1, h2, h3, h4, p, [data-async-context], div[data-content-feature], .g, [role="heading"], [role="link"], [role="article"]');
            var seen = new Set();
            for (var el of elements) {
                var txt = (el.innerText || el.textContent || '').trim();
                if (txt && txt.length > 5 && !seen.has(txt)) {
                    seen.add(txt);
                    var tag = el.tagName.toLowerCase();
                    var role = (tag.startsWith('h') ? 'heading' : (tag === 'p' ? 'paragraph' : 'section'));
                    var rect = el.getBoundingClientRect();
                    items.push({
                        role: role,
                        name: txt.slice(0, 120),
                        text: txt.slice(0, 600),
                        bounds: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height),
                            cx: Math.round(rect.x + rect.width / 2),
                            cy: Math.round(rect.y + rect.height / 2)
                        }
                    });
                    if (items.length >= 35) break;
                }
            }
            return items;
        })()"""
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js_code, "returnByValue": True}}))
        res = json.loads(ws.recv())
        ws.close()
        items = res.get("result", {}).get("result", {}).get("value", [])
        return items if isinstance(items, list) else []
    except Exception:
        return []

def cmd_dump(target=""):
    desktop = Atspi.get_desktop(0)
    node = None
    if target:
        node = find_node_by_name_or_role(desktop, target, max_depth=30)
    if not node:
        node = find_focused_node(desktop)
        curr = node
        while curr:
            role = (curr.get_role_name() or "").lower()
            if role in ["window", "frame", "application", "dialog"]:
                node = curr
                break
            try:
                curr = curr.get_parent()
            except Exception:
                break
    if not node:
        node = desktop

    tree = get_accessible_tree(node, max_depth=7)
    cdp_items = get_browser_cdp_elements()
    if cdp_items:
        if len(tree) <= 3 or any("chrom" in (e.get("name") or "").lower() for e in tree):
            tree = tree + cdp_items
    print(json.dumps(tree, indent=2))

def get_x11_ewmh_windows():
    windows = []
    try:
        out = subprocess.check_output(["xprop", "-root", "_NET_CLIENT_LIST"], text=True, stderr=subprocess.DEVNULL)
        win_ids = re.findall(r"0x[0-9a-fA-F]+", out)
        for wid in win_ids:
            try:
                p_out = subprocess.check_output(["xprop", "-id", wid], text=True, stderr=subprocess.DEVNULL)
                title_match = re.search(r'_NET_WM_NAME\(UTF8_STRING\) = "(.*)"', p_out) or re.search(r'WM_NAME\(.*?\) = "(.*)"', p_out)
                class_match = re.search(r'WM_CLASS\(STRING\) = (.*)', p_out)
                pid_match = re.search(r'_NET_WM_PID\(CARDINAL\) = (\d+)', p_out)
                state_match = re.search(r'_NET_WM_STATE\(ATOM\) = (.*)', p_out)

                title = title_match.group(1) if title_match else ""
                wm_class = class_match.group(1).replace('"', '') if class_match else ""
                pid = int(pid_match.group(1)) if pid_match else None
                states = [s.strip() for s in state_match.group(1).split(",") if s.strip()] if state_match else []

                # Geometry via xwininfo
                geo = None
                is_viewable = True
                try:
                    w_out = subprocess.check_output(["xwininfo", "-id", wid], text=True, stderr=subprocess.DEVNULL)
                    x_m = re.search(r"Absolute upper-left X:\s+(-?\d+)", w_out)
                    y_m = re.search(r"Absolute upper-left Y:\s+(-?\d+)", w_out)
                    w_m = re.search(r"Width:\s+(\d+)", w_out)
                    h_m = re.search(r"Height:\s+(\d+)", w_out)
                    if x_m and y_m and w_m and h_m:
                        x = int(x_m.group(1))
                        y = int(y_m.group(1))
                        w = int(w_m.group(1))
                        h = int(h_m.group(1))
                        is_viewable = "Map State: IsViewable" in w_out
                        geo = {
                            "x": x,
                            "y": y,
                            "width": w,
                            "height": h,
                            "center_x": x + (w // 2) if w > 0 else x,
                            "center_y": y + (h // 2) if h > 0 else y,
                            "viewable": is_viewable
                        }
                except Exception:
                    pass

                # Process name and memory RSS from /proc/<pid>
                rss_kb = None
                proc_name = None
                cmdline = None
                if pid and os.path.exists(f"/proc/{pid}"):
                    try:
                        if os.path.exists(f"/proc/{pid}/status"):
                            with open(f"/proc/{pid}/status") as f:
                                for line in f:
                                    if line.startswith("VmRSS:"):
                                        rss_kb = int(line.split()[1])
                                    elif line.startswith("Name:"):
                                        proc_name = line.split()[1]
                        if os.path.exists(f"/proc/{pid}/cmdline"):
                            with open(f"/proc/{pid}/cmdline", "rb") as f:
                                raw = f.read()
                                cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
                    except Exception:
                        pass

                windows.append({
                    "window_id": wid,
                    "title": title,
                    "class": wm_class,
                    "pid": pid,
                    "process_name": proc_name,
                    "command": cmdline,
                    "rss_kb": rss_kb,
                    "geometry": geo,
                    "viewable": is_viewable,
                    "states": states,
                    "source": "x11_ewmh"
                })
            except Exception:
                continue
    except Exception:
        pass
    return windows

def get_proc_info_by_name(name):
    if not name:
        return None, None
    try:
        # Check running processes
        out = subprocess.check_output(["pgrep", "-f", name], text=True, stderr=subprocess.DEVNULL)
        pids = [int(p) for p in out.strip().split() if p.isdigit()]
        if pids:
            target_pid = pids[0]
            rss_kb = None
            if os.path.exists(f"/proc/{target_pid}/status"):
                with open(f"/proc/{target_pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            rss_kb = int(line.split()[1])
                            break
            return target_pid, rss_kb
    except Exception:
        pass
    return None, None

def cmd_list_windows():
    atspi_windows = []
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            child = desktop.get_child_at_index(i)
            if not child:
                continue
            try:
                name = child.get_name() or ""
                role = child.get_role_name() or ""
                child_count = child.get_child_count()
                if child_count == 0:
                    continue
                sub_titles = []
                for c_idx in range(child_count):
                    try:
                        c_node = child.get_child_at_index(c_idx)
                        if c_node:
                            c_title = c_node.get_name() or ""
                            if c_title:
                                sub_titles.append(c_title)
                    except Exception:
                        pass
                
                # Fast tab extraction (only for tabbed editors/browsers, max_d=6)
                all_tabs = sub_titles
                name_lower = name.lower()
                role_lower = role.lower()
                if any(k in name_lower or k in role_lower for k in ["editor", "firefox", "chrome", "brave", "terminal", "gedit", "code"]):
                    def _find_tabs(n, depth=0, max_d=6):
                        res = []
                        if not n or depth > max_d:
                            return res
                        try:
                            r = (n.get_role_name() or "").lower()
                            nm = n.get_name() or ""
                            if (r in ["page tab", "tab", "page"] or "tab" in r) and nm:
                                res.append(nm)
                            cc = n.get_child_count()
                            for k in range(min(cc, 15)):
                                res.extend(_find_tabs(n.get_child_at_index(k), depth + 1, max_d))
                        except Exception:
                            pass
                        return res

                    deep_tabs = _find_tabs(child)
                    all_tabs = list(dict.fromkeys(sub_titles + deep_tabs))
                window_title = ", ".join(all_tabs) if all_tabs else name
                pid, rss_kb = get_proc_info_by_name(name)
                extents = get_node_extents(child)
                atspi_windows.append({
                    "index": i,
                    "name": name,
                    "title": window_title,
                    "open_tabs_or_windows": all_tabs,
                    "role": role,
                    "pid": pid,
                    "process_name": name,
                    "rss_kb": rss_kb,
                    "children": child_count,
                    "geometry": extents,
                    "source": "atspi"
                })
            except Exception:
                continue
    except Exception:
        pass

    x11_windows = get_x11_ewmh_windows()

    # Merge and deduplicate AT-SPI2 + X11/EWMH windows
    unified = []
    matched_x11 = set()

    for aw in atspi_windows:
        aname = (aw.get("name") or "").lower()
        match = None
        for idx, xw in enumerate(x11_windows):
            if idx in matched_x11:
                continue
            xtitle = (xw.get("title") or "").lower()
            xclass = (xw.get("class") or "").lower()
            xproc = (xw.get("process_name") or "").lower()
            if aname and (aname in xtitle or xtitle in aname or aname in xclass or aname in xproc):
                match = xw
                matched_x11.add(idx)
                break

        entry = dict(aw)
        if match:
            entry["window_id"] = match.get("window_id")
            entry["pid"] = match.get("pid")
            entry["process_name"] = match.get("process_name")
            entry["rss_kb"] = match.get("rss_kb")
            entry["title"] = match.get("title")
            entry["class"] = match.get("class")
            if not entry.get("geometry") and match.get("geometry"):
                entry["geometry"] = match.get("geometry")
            entry["viewable"] = match.get("viewable", True)
            entry["source"] = "hybrid (atspi + x11)"
        unified.append(entry)

    # Add remaining X11 windows (such as sandboxed Snap, Flatpak, Spotify, CEF, games)
    for idx, xw in enumerate(x11_windows):
        if idx not in matched_x11:
            unified.append({
                "index": len(unified),
                "name": xw.get("title") or xw.get("class") or xw.get("process_name") or "Window",
                "title": xw.get("title"),
                "class": xw.get("class"),
                "role": "application",
                "pid": xw.get("pid"),
                "process_name": xw.get("process_name"),
                "rss_kb": xw.get("rss_kb"),
                "window_id": xw.get("window_id"),
                "children": 0,
                "geometry": xw.get("geometry"),
                "viewable": xw.get("viewable", True),
                "source": "x11_ewmh"
            })

    # Filter out internal desktop infrastructure
    SYSTEM_CLASSES = {"xfwm4", "xfce4-panel", "xfdesktop", "desktop", "mutter", "gnome-shell", "polybar", "kwin", "swades_desktop_hud", "swades ai copilot", "wrapper-2.0"}
    filtered_unified = []
    for w in unified:
        w_name = (w.get("name") or "").lower()
        w_title = (w.get("title") or "").lower()
        w_class = (w.get("class") or "").lower()
        is_sys = any(s in w_name or s in w_title or s in w_class for s in SYSTEM_CLASSES)
        w["is_system"] = is_sys
        if not is_sys:
            filtered_unified.append(w)

    print(json.dumps(filtered_unified if filtered_unified else [w for w in unified if w.get("viewable")], indent=2))

def cmd_focused():
    desktop = Atspi.get_desktop(0)
    node = find_focused_node(desktop)
    if not node:
        print(json.dumps({"focused": False, "message": "No accessibility element currently has focus"}))
        return

    name = node.get_name() or ""
    role = node.get_role_name() or ""
    states = get_node_states(node)
    extents = get_node_extents(node)
    text = None
    try:
        text_iface = node.get_text_iface()
        if text_iface:
            cc = text_iface.get_character_count()
            text = text_iface.get_text(0, min(cc, 500))
    except Exception:
        pass

    print(json.dumps({
        "focused": True,
        "name": name,
        "role": role,
        "states": states,
        "geometry": extents,
        "text": text
    }, indent=2))

def cmd_extents(target):
    desktop = Atspi.get_desktop(0)
    node = None
    focused = find_focused_node(desktop, max_depth=15)
    if focused:
        node = find_node_by_name_or_role(focused, target, max_depth=15)
    if not node:
        node = find_node_by_name_or_role(desktop, target, max_depth=15)

    if node:
        extents = get_node_extents(node)
        if extents:
            print(json.dumps({
                "success": True,
                "target": target,
                "name": node.get_name() or "",
                "role": node.get_role_name() or "",
                "geometry": extents,
                "source": "atspi"
            }, indent=2))
            return

    # Fallback to X11 windows (for Spotify, Steam, Snap/Flatpak apps without AT-SPI)
    tgt_lower = (target or "").lower()
    x11_windows = get_x11_ewmh_windows()
    for xw in x11_windows:
        xtitle = (xw.get("title") or "").lower()
        xclass = (xw.get("class") or "").lower()
        xproc = (xw.get("process_name") or "").lower()
        if tgt_lower in xtitle or tgt_lower in xclass or tgt_lower in xproc:
            if xw.get("geometry"):
                print(json.dumps({
                    "success": True,
                    "target": target,
                    "name": xw.get("title") or xw.get("class"),
                    "role": "application",
                    "window_id": xw.get("window_id"),
                    "pid": xw.get("pid"),
                    "geometry": xw.get("geometry"),
                    "source": "x11_ewmh"
                }, indent=2))
                return

    print(json.dumps({"success": False, "error": f"Element '{target}' not found in AT-SPI2 or X11 windows"}))

def cmd_interact(target, action_name="click"):
    desktop = Atspi.get_desktop(0)
    node = find_node_by_name_or_role(desktop, target)
    if node:
        action_iface = node.get_action_iface()
        if action_iface:
            n = action_iface.get_n_actions()
            for i in range(n):
                act = action_iface.get_action_name(i)
                if action_name.lower() in act.lower() or act.lower() in action_name.lower():
                    ok = action_iface.do_action(i)
                    print(json.dumps({"success": ok, "action": act, "element": node.get_name() or node.get_role_name()}))
                    return
            if n > 0:
                ok = action_iface.do_action(0)
                print(json.dumps({"success": ok, "action": action_iface.get_action_name(0), "element": node.get_name() or node.get_role_name()}))
                return

    # Fallback to X11 windows (click window center)
    tgt_lower = (target or "").lower()
    x11_windows = get_x11_ewmh_windows()
    for xw in x11_windows:
        xtitle = (xw.get("title") or "").lower()
        xclass = (xw.get("class") or "").lower()
        xproc = (xw.get("process_name") or "").lower()
        if tgt_lower in xtitle or tgt_lower in xclass or tgt_lower in xproc:
            geo = xw.get("geometry")
            if geo and geo.get("center_x") and geo.get("center_y"):
                cmd_click_coords(geo["center_x"], geo["center_y"], "left", 1)
                return

    print(json.dumps({"success": False, "error": f"Element '{target}' not found in AT-SPI2 or X11 windows"}))

def find_editable_node(node, depth=0, max_depth=30):
    if not node or depth > max_depth:
        return None
    try:
        if node.get_editable_text_iface():
            return node
        for i in range(node.get_child_count()):
            res = find_editable_node(node.get_child_at_index(i), depth + 1, max_depth)
            if res:
                return res
    except Exception:
        pass
    return None

def _do_save():
    """Triple-redundancy save: AT-SPI page.save action → synthetic keysym → pyautogui."""
    import time
    saved = False
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app:
                for j in range(app.get_child_count()):
                    win = app.get_child_at_index(j)
                    act = win.get_action_iface() if win else None
                    if act:
                        for a_idx in range(act.get_n_actions()):
                            a_name = Atspi.Action.get_action_name(act, a_idx)
                            if a_name in ["page.save", "win.save", "save"]:
                                act.do_action(a_idx)
                                saved = True
                                break
                    if saved:
                        break
            if saved:
                break
    except Exception:
        pass
    try:
        Atspi.generate_keyboard_event(65507, None, Atspi.KeySynthType.PRESS)
        time.sleep(0.02)
        Atspi.generate_keyboard_event(115, "s", Atspi.KeySynthType.PRESSRELEASE)
        time.sleep(0.02)
        Atspi.generate_keyboard_event(65507, None, Atspi.KeySynthType.RELEASE)
    except Exception:
        pass
    try:
        import pyautogui
        pyautogui.hotkey("ctrl", "s")
    except Exception:
        pass
    return saved

def cmd_set_text(target, text, auto_save=False):
    desktop = Atspi.get_desktop(0)
    node = None

    # 1. If target specified, try finding target window/app or element
    if target:
        for i in range(desktop.get_child_count()):
            child = desktop.get_child_at_index(i)
            if child:
                found = None
                if target.lower() in (child.get_name() or "").lower():
                    found = child
                else:
                    for j in range(child.get_child_count()):
                        w_sub = child.get_child_at_index(j)
                        if w_sub and target.lower() in (w_sub.get_name() or "").lower():
                            found = w_sub
                            break
                if found:
                    node = find_editable_node(found, max_depth=30)
                    if node:
                        break

        if not node:
            node = find_node_by_name_or_role(desktop, target, "text", max_depth=30)
        if not node:
            node = find_node_by_name_or_role(desktop, target, "entry", max_depth=30)
        if not node:
            node = find_node_by_name_or_role(desktop, target, max_depth=30)

    # 2. Try finding editable inside focused window or desktop
    if not node:
        focused = find_focused_node(desktop)
        if focused:
            node = find_editable_node(focused, max_depth=30)

    # 3. Try finding any editable on desktop (e.g. active text editor buffer)
    if not node:
        for i in range(desktop.get_child_count()):
            child = desktop.get_child_at_index(i)
            if child:
                cname = (child.get_name() or "").lower()
                if any(ed_name in cname for ed_name in ["editor", "text", "notepad", "writer"]):
                    node = find_editable_node(child, max_depth=30)
                    if node:
                        break

    if not node:
        node = find_editable_node(desktop, max_depth=30)

    if node:
        try:
            editable = node.get_editable_text_iface()
            if editable:
                ok = editable.set_text_contents(text)
                saved = _do_save() if auto_save else None
                print(json.dumps({"success": ok, "text": text, "element": node.get_name() or node.get_role_name(), "source": "atspi", "saved": saved}))
                return
        except Exception:
            pass

    # Fallback to typing into active window
    cmd_type_keys(text, False)
    if auto_save:
        _do_save()


def cmd_mouse_pos():
    try:
        import pyautogui
        pos = pyautogui.position()
        size = pyautogui.size()
        print(json.dumps({"x": pos.x, "y": pos.y, "screen_width": size.width, "screen_height": size.height}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

def cmd_click_coords(x, y, button="left", clicks=1):
    try:
        import pyautogui
        pyautogui.click(x=int(x), y=int(y), clicks=int(clicks), button=button)
        print(json.dumps({"success": True, "x": int(x), "y": int(y), "button": button, "clicks": int(clicks)}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_type_keys(keys, is_shortcut=False):
    import time
    try:
        lower = keys.strip().lower()

        # Shortcut detection
        is_sc = is_shortcut or "+" in keys or lower in ["return", "enter", "tab", "escape", "space", "backspace", "up", "down", "left", "right"]
        if is_sc:
            parts = [p.strip().lower() for p in keys.split("+")]
            key_map = {"enter": "Return", "return": "Return", "ctrl": "ctrl", "alt": "alt", "shift": "shift", "esc": "Escape", "tab": "Tab", "space": "space"}
            xdo_parts = "+".join([key_map.get(p, p) for p in parts])
            
            try:
                subprocess.run(["xdotool", "key", "--clearmodifiers", xdo_parts], check=True, stderr=subprocess.DEVNULL)
                print(json.dumps({"success": True, "hotkey": parts, "source": "xdotool"}))
                return
            except Exception:
                pass
            
            import pyautogui
            mapped = [p if p != "return" else "enter" for p in parts]
            pyautogui.hotkey(*mapped)
            print(json.dumps({"success": True, "hotkey": mapped, "source": "pyautogui"}))
            return

        if any(ord(c) > 127 for c in keys):
            try:
                import tkinter as tk
                r = tk.Tk()
                r.withdraw()
                r.clipboard_clear()
                r.clipboard_append(keys)
                r.update()
                r.destroy()
                time.sleep(0.05)
                subprocess.run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], stderr=subprocess.DEVNULL)
                print(json.dumps({"success": True, "typed": keys, "method": "clipboard_paste"}))
                return
            except Exception:
                pass

        try:
            subprocess.run(["xdotool", "type", "--delay", "15", "--", keys], check=True, stderr=subprocess.DEVNULL)
            print(json.dumps({"success": True, "typed": keys, "method": "xdotool"}))
            return
        except Exception:
            pass

        import pyautogui
        pyautogui.write(keys, interval=0.01)
        print(json.dumps({"success": True, "typed": keys, "method": "pyautogui"}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))


def cmd_browser_type(text, send=False, click_offset_y=-80):
    """
    For web apps in Firefox/Chrome: focus the browser, click near the bottom of the window
    (where chat inputs typically live), type text, optionally press Enter to send.
    Falls back to AT-SPI set_text if a focusable input is found.
    """
    import time
    try:
        import pyautogui
        # Get screen dimensions
        sw, sh = pyautogui.size()
        # Click bottom-center of screen (chat input zone for most web chat apps)
        cx = sw // 2
        cy = sh + int(click_offset_y)  # e.g. 80px from bottom
        pyautogui.click(cx, cy)
        time.sleep(0.3)
        # Clear existing text and type message
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.write(text, interval=0.02)
        if send:
            time.sleep(0.1)
            pyautogui.press("enter")
        print(json.dumps({"success": True, "text": text, "sent": send, "clicked": [cx, cy]}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_mouse_scroll(clicks=5, direction="down"):
    import subprocess
    import time
    try:
        # Move cursor to center of active window or screen (960, 540)
        subprocess.run(["xdotool", "mousemove", "960", "540"], stderr=subprocess.DEVNULL)
        time.sleep(0.05)
        
        btn = "5" if direction == "down" else "4"
        num = int(clicks) if clicks else 5
        for _ in range(num):
            subprocess.run(["xdotool", "click", btn], stderr=subprocess.DEVNULL)
            time.sleep(0.03)

        print(json.dumps({"success": True, "direction": direction, "clicks": num, "source": "xdotool"}))
        return
    except Exception:
        pass

    try:
        import pyautogui
        amount = -int(clicks) if direction == "down" else int(clicks)
        pyautogui.scroll(amount)
        print(json.dumps({"success": True, "direction": direction, "clicks": int(clicks), "source": "pyautogui"}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_update_scratchpad(status, notes):
    state = {
        "status": status,
        "notes": notes
    }
    with open('/tmp/swades_scratchpad.json', 'w') as f:
        json.dump(state, f, indent=2)
    print(json.dumps({"success": True, "scratchpad": state}))

def cmd_focus_window(title):
    if not title:
        print(json.dumps({"success": False, "error": "Title required"}))
        return
    title_lower = title.lower()
    
    # 1. Try xdotool (fastest & robust X11 input focus)
    try:
        out = subprocess.check_output(["xdotool", "search", "--onlyvisible", "--name", title], text=True, stderr=subprocess.DEVNULL)
        wids = [w.strip() for w in out.splitlines() if w.strip()]
        if not wids:
            out = subprocess.check_output(["xdotool", "search", "--name", title], text=True, stderr=subprocess.DEVNULL)
            wids = [w.strip() for w in out.splitlines() if w.strip()]
        if not wids:
            out = subprocess.check_output(["xdotool", "search", "--class", title], text=True, stderr=subprocess.DEVNULL)
            wids = [w.strip() for w in out.splitlines() if w.strip()]
        if wids:
            wid = wids[0]
            subprocess.run(["xdotool", "windowactivate", "--sync", wid], stderr=subprocess.DEVNULL)
            subprocess.run(["xdotool", "windowfocus", "--sync", wid], stderr=subprocess.DEVNULL)
            subprocess.run(["xdotool", "windowraise", wid], stderr=subprocess.DEVNULL)
            w_name = subprocess.check_output(["xdotool", "getwindowname", wid], text=True, stderr=subprocess.DEVNULL).strip()
            print(json.dumps({"success": True, "focused": w_name or title, "window_id": wid, "source": "xdotool"}))
            return
    except Exception:
        pass

    # 2. Try X11 / EWMH
    try:
        from Xlib import X, display, protocol
        d = display.Display()
        root = d.screen().root
        windows = get_x11_ewmh_windows()
        for w in windows:
            if title_lower in (w.get("title") or "").lower() or title_lower in (w.get("class") or "").lower():
                wid = int(w["window_id"], 16)
                win = d.create_resource_object("window", wid)
                win.map()
                win.raise_window()
                net_active = d.intern_atom("_NET_ACTIVE_WINDOW")
                data = [1, X.CurrentTime, 0, 0, 0]
                ev = protocol.event.ClientMessage(window=win, client_type=net_active, data=(32, data))
                root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                d.set_input_focus(win, X.RevertToParent, X.CurrentTime)
                d.sync()
                subprocess.run(["xdotool", "windowactivate", "--sync", str(wid)], stderr=subprocess.DEVNULL)
                print(json.dumps({"success": True, "focused": w.get("title"), "source": "x11"}))
                return
    except Exception:
        pass

    print(json.dumps({"success": False, "error": f"Window '{title}' not found"}))


def cmd_window_control(title, action):
    title_lower = (title or "").lower()
    if action == "close" and title_lower in ["all", "all windows", "all apps", "everything"]:
        try:
            # Gracefully close all user applications
            subprocess.run(["pkill", "-f", "chromium|chrome|firefox|gedit|kate|code|mousepad|leafpad|terminal|xterm"], check=False)
            print(json.dumps({"success": True, "action": "close_all_user_apps"}))
            return
        except Exception as e:
            print(json.dumps({"success": False, "error": str(e)}))
            return
    try:
        from Xlib import X, display, protocol
        d = display.Display()
        root = d.screen().root
        windows = get_x11_ewmh_windows()
        for w in windows:
            if title_lower in (w.get("title") or "").lower() or title_lower in (w.get("class") or "").lower():
                wid = int(w["window_id"], 16)
                win = d.create_resource_object('window', wid)
                if action == "close":
                    net_close = d.intern_atom('_NET_CLOSE_WINDOW')
                    ev = protocol.event.ClientMessage(window=win, client_type=net_close, data=(32, [X.CurrentTime, 2, 0, 0, 0]))
                    root.send_event(ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
                    d.sync()
                    print(json.dumps({"success": True, "action": "close", "target": w.get("title")}))
                    return
                elif action == "minimize":
                    win.unmap()
                    d.sync()
                    print(json.dumps({"success": True, "action": "minimize", "target": w.get("title")}))
                    return
                elif action == "maximize":
                    win.map()
                    win.raise_window()
                    d.sync()
                    print(json.dumps({"success": True, "action": "maximize", "target": w.get("title")}))
                    return
    except Exception:
        pass

    if action == "close" and title:
        try:
            subprocess.run(["pkill", "-f", title], check=False)
            print(json.dumps({"success": True, "action": "close", "target": title, "source": "pkill"}))
            return
        except Exception:
            pass

    print(json.dumps({"success": False, "error": f"Could not perform '{action}' on '{title}'"}))

def cmd_system_info():
    try:
        import psutil
        vmem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        load = os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0]
        
        top_procs = []
        for p in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']), 
                         key=lambda x: (x.info.get('memory_percent') or 0), reverse=True)[:8]:
            try:
                top_procs.append({
                    "pid": p.info['pid'],
                    "name": p.info['name'],
                    "cpu_percent": p.info['cpu_percent'],
                    "mem_percent": round(p.info['memory_percent'] or 0, 1),
                })
            except Exception:
                continue

        info = {
            "cpu": {
                "percent": psutil.cpu_percent(interval=0.1),
                "cores": psutil.cpu_count(logical=True),
                "load_avg": [round(x, 2) for x in load]
            },
            "memory": {
                "total_gb": round(vmem.total / (1024**3), 2),
                "used_gb": round(vmem.used / (1024**3), 2),
                "available_gb": round(vmem.available / (1024**3), 2),
                "percent": vmem.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            },
            "top_processes": top_procs
        }
        print(json.dumps(info, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))

def cmd_manage_process(action="list", target=""):
    try:
        import psutil
        if action == "list" or not target:
            procs = []
            for p in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']), 
                             key=lambda x: (x.info.get('cpu_percent') or 0), reverse=True)[:15]:
                try:
                    procs.append(p.info)
                except Exception:
                    continue
            print(json.dumps({"processes": procs}, indent=2))
            return

        if action == "search":
            results = []
            target_lower = target.lower()
            for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_percent']):
                try:
                    name = p.info['name'] or ''
                    cmd = ' '.join(p.info.get('cmdline') or [])
                    if target_lower in name.lower() or target_lower in cmd.lower():
                        results.append(p.info)
                except Exception:
                    continue
            print(json.dumps({"matches": results}, indent=2))
            return

        if action == "kill":
            protected = ['systemd', 'gnome-shell', 'Xorg', 'Xwayland', 'dbus', 'pipewire', 'init']
            target_pid = int(target) if target.isdigit() else None
            killed = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if (target_pid and p.info['pid'] == target_pid) or (not target_pid and target.lower() in (p.info['name'] or '').lower()):
                        if p.info['name'] in protected:
                            continue
                        p.terminate()
                        killed.append(p.info)
                except Exception:
                    continue
            print(json.dumps({"success": True, "terminated": killed}))
            return
    except Exception as e:
        print(json.dumps({"error": str(e)}))

def cmd_get_clipboard():
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        content = r.clipboard_get()
        r.destroy()
        print(json.dumps({"success": True, "content": content}))
    except Exception as e:
        print(json.dumps({"success": False, "content": "", "error": str(e)}))

def cmd_set_clipboard(text):
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        print(json.dumps({"success": True, "text": text}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def dispatch_command(cmd, args):
    import io
    from contextlib import redirect_stdout, redirect_stderr
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            if cmd == "dump":
                target = args[0] if len(args) > 0 else ""
                cmd_dump(target)
            elif cmd == "list_windows":
                cmd_list_windows()
            elif cmd == "focused":
                cmd_focused()
            elif cmd == "focus_window":
                title = args[0] if len(args) > 0 else ""
                cmd_focus_window(title)
            elif cmd == "window_control":
                title = args[0] if len(args) > 0 else ""
                action = args[1] if len(args) > 1 else "close"
                cmd_window_control(title, action)
            elif cmd == "system_info":
                cmd_system_info()
            elif cmd == "manage_process":
                action = args[0] if len(args) > 0 else "list"
                target = args[1] if len(args) > 1 else ""
                cmd_manage_process(action, target)
            elif cmd == "get_clipboard":
                cmd_get_clipboard()
            elif cmd == "set_clipboard":
                text = args[0] if len(args) > 0 else ""
                cmd_set_clipboard(text)
            elif cmd == "extents":
                target = args[0] if len(args) > 0 else ""
                cmd_extents(target)
            elif cmd == "interact":
                target = args[0] if len(args) > 0 else ""
                act = args[1] if len(args) > 1 else "click"
                cmd_interact(target, act)
            elif cmd == "set_text":
                target = args[0] if len(args) > 0 else ""
                val = args[1] if len(args) > 1 else ""
                auto_save = str(args[2]).lower() in ["true", "1", "yes"] if len(args) > 2 else False
                cmd_set_text(target, val, auto_save)
            elif cmd == "mouse_pos":
                cmd_mouse_pos()
            elif cmd == "click":
                x = args[0]
                y = args[1]
                btn = args[2] if len(args) > 2 else "left"
                clk = args[3] if len(args) > 3 else 1
                cmd_click_coords(x, y, btn, clk)
            elif cmd == "type":
                k = args[0] if len(args) > 0 else ""
                is_sc = str(args[1]).lower() in ["true", "1", "yes"] if len(args) > 1 else False
                cmd_type_keys(k, is_sc)
            elif cmd == "scroll":
                amt = args[0] if len(args) > 0 else 5
                dirn = args[1] if len(args) > 1 else "down"
                cmd_mouse_scroll(amt, dirn)
            elif cmd == "scratchpad":
                status = args[0] if len(args) > 0 else "Active"
                notes = args[1] if len(args) > 1 else ""
                cmd_update_scratchpad(status, notes)
            else:
                print(json.dumps({"error": f"Unknown command: {cmd}"}))
        except Exception as ex:
            print(json.dumps({"error": str(ex)}))
    return buf.getvalue().strip()

def run_daemon():
    import socket
    sock_path = "/tmp/swades_cua.sock"
    if os.path.exists(sock_path):
        try:
            os.unlink(sock_path)
        except Exception:
            pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    os.chmod(sock_path, 0o777)
    server.listen(16)
    print(f"🚀 Swades CUA Persistent Daemon active on {sock_path}")
    sys.stdout.flush()

    while True:
        try:
            conn, _ = server.accept()
            data = conn.recv(65536).decode("utf-8")
            if not data:
                conn.close()
                continue
            req = json.loads(data)
            cmd = req.get("cmd", "")
            args = req.get("args", [])
            out = dispatch_command(cmd, args)
            conn.sendall(out.encode("utf-8"))
            conn.close()
        except Exception as e:
            try:
                conn.sendall(json.dumps({"error": str(e)}).encode("utf-8"))
                conn.close()
            except Exception:
                pass

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: semantic_desktop.py [--daemon | <command> [args...]]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd in ["--daemon", "daemon"]:
        run_daemon()
    else:
        out = dispatch_command(cmd, sys.argv[2:])
        print(out)

