#!/usr/bin/env python3
import sys
import json
import os
import glob
import subprocess
import re

# Ensure dist-packages is available for system PyGObject / Atspi
if "/usr/lib/python3/dist-packages" not in sys.path:
    sys.path.append("/usr/lib/python3/dist-packages")

# Dynamic Display & Auth Auto-Discovery
def ensure_display_and_auth():
    if "DISPLAY" not in os.environ or not os.environ["DISPLAY"]:
        os.environ["DISPLAY"] = ":0"
    
    # Check for Mutter Xwayland auth cookie if not set
    if "XAUTHORITY" not in os.environ or not os.path.exists(os.environ.get("XAUTHORITY", "")):
        uid = os.getuid()
        mutter_auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
        if mutter_auths:
            latest_auth = sorted(mutter_auths, key=os.path.getmtime)[-1]
            os.environ["XAUTHORITY"] = latest_auth
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

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

def get_accessible_tree(node, max_depth=5, current_depth=0):
    if not node or current_depth > max_depth:
        return None

    try:
        role = node.get_role_name() or "unknown"
        name = node.get_name() or ""
        states = get_node_states(node)

        # Skip non-visible noise to save context window
        if "visible" not in states and current_depth > 1:
            return None

        tree = {
            "id": f"{role}:{name}" if name else f"{role}",
            "role": role,
            "name": name,
            "states": states
        }

        # Available actions
        try:
            action_iface = node.get_action_iface()
            if action_iface:
                n_actions = action_iface.get_n_actions()
                actions = []
                for i in range(n_actions):
                    act_name = action_iface.get_action_name(i)
                    if act_name:
                        actions.append(act_name)
                if actions:
                    tree["actions"] = actions
        except Exception:
            pass

        # Extents (bounding box)
        extents = get_node_extents(node)
        if extents and (extents["width"] > 0 or extents["height"] > 0):
            tree["geometry"] = extents

        # Value / text
        try:
            text_iface = node.get_text_iface()
            if text_iface:
                char_count = text_iface.get_character_count()
                if char_count > 0:
                    tree["text"] = text_iface.get_text(0, min(char_count, 1000))
        except Exception:
            pass

        # Children
        child_count = node.get_child_count()
        if child_count > 0:
            children = []
            for i in range(child_count):
                child = node.get_child_at_index(i)
                child_data = get_accessible_tree(child, max_depth, current_depth + 1)
                if child_data:
                    children.append(child_data)
            if children:
                tree["children"] = children

        return tree
    except Exception:
        return None

def find_node_by_name_or_role(node, target_name, target_role=None):
    if not node:
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
        for i in range(child_count):
            found = find_node_by_name_or_role(node.get_child_at_index(i), target_name, target_role)
            if found:
                return found
    except Exception:
        pass
    return None

def find_focused_node(node, depth=0, max_depth=8):
    if not node or depth > max_depth:
        return None
    try:
        states = get_node_states(node)
        if "focused" in states:
            return node

        child_count = node.get_child_count()
        for i in range(child_count):
            res = find_focused_node(node.get_child_at_index(i), depth + 1, max_depth)
            if res:
                return res
    except Exception:
        pass
    return None

def cmd_dump():
    desktop = Atspi.get_desktop(0)
    tree = get_accessible_tree(desktop)
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
                extents = get_node_extents(child)
                pid, rss_kb = get_proc_info_by_name(name)
                atspi_windows.append({
                    "index": i,
                    "name": name,
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

    print(json.dumps(unified, indent=2))

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
    node = find_node_by_name_or_role(desktop, target)
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

def cmd_set_text(target, text):
    desktop = Atspi.get_desktop(0)
    node = find_node_by_name_or_role(desktop, target, "text")
    if not node:
        node = find_node_by_name_or_role(desktop, target, "entry")
    if not node:
        node = find_node_by_name_or_role(desktop, target)
    if not node:
        print(json.dumps({"success": False, "error": f"Element '{target}' not found"}))
        return

    editable = node.get_editable_text_iface()
    if not editable:
        print(json.dumps({"success": False, "error": f"Element '{target}' is not editable"}))
        return

    ok = editable.set_text_contents(text)
    print(json.dumps({"success": ok, "text": text, "element": node.get_name() or node.get_role_name()}))

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
    try:
        import pyautogui
        if is_shortcut or "+" in keys or keys in ["Return", "enter", "tab", "escape", "space", "backspace"]:
            parts = [p.strip().lower() for p in keys.split("+")]
            # Map common names
            key_map = {"enter": "return", "ctrl": "ctrl", "alt": "alt", "shift": "shift"}
            mapped = [key_map.get(p, p) for p in parts]
            pyautogui.hotkey(*mapped)
            print(json.dumps({"success": True, "hotkey": mapped}))
        else:
            pyautogui.write(keys, interval=0.01)
            print(json.dumps({"success": True, "typed": keys}))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_mouse_scroll(clicks=5, direction="down"):
    try:
        import pyautogui
        amount = -int(clicks) if direction == "down" else int(clicks)
        pyautogui.scroll(amount)
        print(json.dumps({"success": True, "direction": direction, "clicks": int(clicks)}))
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

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: semantic_desktop.py [dump | list_windows | focused | extents <target> | interact <target> [action] | set_text <target> <text> | mouse_pos | click <x> <y> [button] [clicks] | type <keys> [is_shortcut] | scroll <clicks> [dir] | scratchpad <status> <notes>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "dump":
        cmd_dump()
    elif cmd == "list_windows":
        cmd_list_windows()
    elif cmd == "focused":
        cmd_focused()
    elif cmd == "extents":
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        cmd_extents(target)
    elif cmd == "interact":
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        act = sys.argv[3] if len(sys.argv) > 3 else "click"
        cmd_interact(target, act)
    elif cmd == "set_text":
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        val = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_set_text(target, val)
    elif cmd == "mouse_pos":
        cmd_mouse_pos()
    elif cmd == "click":
        x = sys.argv[2]
        y = sys.argv[3]
        btn = sys.argv[4] if len(sys.argv) > 4 else "left"
        clk = sys.argv[5] if len(sys.argv) > 5 else 1
        cmd_click_coords(x, y, btn, clk)
    elif cmd == "type":
        k = sys.argv[2] if len(sys.argv) > 2 else ""
        is_sc = sys.argv[3].lower() in ["true", "1", "yes"] if len(sys.argv) > 3 else False
        cmd_type_keys(k, is_sc)
    elif cmd == "scroll":
        amt = sys.argv[2] if len(sys.argv) > 2 else 5
        dirn = sys.argv[3] if len(sys.argv) > 3 else "down"
        cmd_mouse_scroll(amt, dirn)
    elif cmd == "scratchpad":
        status = sys.argv[2] if len(sys.argv) > 2 else "Active"
        notes = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_update_scratchpad(status, notes)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
