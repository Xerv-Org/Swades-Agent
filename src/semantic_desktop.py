import sys
import json
import os
import subprocess
import gi

gi.require_version('Atspi', '2.0')
from gi.repository import Atspi

# Ensure accessibility bridge is aware
os.environ["GTK_MODULES"] = "gail:atk-bridge"
os.environ["NO_AT_BRIDGE"] = "0"

def get_accessible_tree(node, max_depth=6, current_depth=0):
    if not node or current_depth > max_depth:
        return None

    try:
        role = node.get_role_name() or "unknown"
        name = node.get_name() or ""
        state_set = node.get_state_set()
        states = []
        if state_set:
            if state_set.contains(Atspi.StateType.VISIBLE): states.append("visible")
            if state_set.contains(Atspi.StateType.SHOWING): states.append("showing")
            if state_set.contains(Atspi.StateType.FOCUSABLE): states.append("focusable")
            if state_set.contains(Atspi.StateType.FOCUSED): states.append("focused")
            if state_set.contains(Atspi.StateType.EDITABLE): states.append("editable")
            if state_set.contains(Atspi.StateType.ENABLED): states.append("enabled")

        # Skip non-visible noise to save token window
        if "visible" not in states and current_depth > 1:
            return None

        tree = {
            "id": f"{role}:{name}" if name else f"{role}",
            "role": role,
            "name": name,
            "states": states
        }

        # Available actions
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

        # Value / text
        text_iface = node.get_text_iface()
        if text_iface:
            try:
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
    except Exception as e:
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

def cmd_dump():
    desktop = Atspi.get_desktop(0)
    tree = get_accessible_tree(desktop)
    print(json.dumps(tree, indent=2))

def cmd_list_windows():
    desktop = Atspi.get_desktop(0)
    windows = []
    for i in range(desktop.get_child_count()):
        child = desktop.get_child_at_index(i)
        if not child:
            continue
        try:
            name = child.get_name() or ""
            role = child.get_role_name() or ""
            child_count = child.get_child_count()
            windows.append({
                "index": i,
                "name": name,
                "role": role,
                "children": child_count
            })
        except Exception:
            continue
    print(json.dumps(windows, indent=2))

def cmd_interact(target, action_name="click"):
    desktop = Atspi.get_desktop(0)
    node = find_node_by_name_or_role(desktop, target)
    if not node:
        print(json.dumps({"success": False, "error": f"Element '{target}' not found"}))
        return

    action_iface = node.get_action_iface()
    if not action_iface:
        print(json.dumps({"success": False, "error": f"Element '{target}' has no actions"}))
        return

    n = action_iface.get_n_actions()
    for i in range(n):
        act = action_iface.get_action_name(i)
        if action_name.lower() in act.lower() or act.lower() in action_name.lower():
            ok = action_iface.do_action(i)
            print(json.dumps({"success": ok, "action": act, "element": node.get_name() or node.get_role_name()}))
            return

    # Fallback to first action
    if n > 0:
        ok = action_iface.do_action(0)
        print(json.dumps({"success": ok, "action": action_iface.get_action_name(0), "element": node.get_name() or node.get_role_name()}))
    else:
        print(json.dumps({"success": False, "error": f"No matching action '{action_name}'"}))

def cmd_set_text(target, text):
    desktop = Atspi.get_desktop(0)
    node = find_node_by_name_or_role(desktop, target, "text")
    if not node:
        node = find_node_by_name_or_role(desktop, target, "entry")
    if not node:
        print(json.dumps({"success": False, "error": f"Element '{target}' not found"}))
        return

    editable = node.get_editable_text_iface()
    if not editable:
        print(json.dumps({"success": False, "error": f"Element '{target}' is not editable"}))
        return

    ok = editable.set_text_contents(text)
    print(json.dumps({"success": ok, "text": text, "element": node.get_name() or node.get_role_name()}))

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
        print("Usage: semantic_desktop.py [dump | list_windows | interact <id_or_name> [action] | set_text <id_or_name> <text> | scratchpad <status> <notes>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "dump":
        cmd_dump()
    elif cmd == "list_windows":
        cmd_list_windows()
    elif cmd == "interact":
        target = sys.argv[2]
        act = sys.argv[3] if len(sys.argv) > 3 else "click"
        cmd_interact(target, act)
    elif cmd == "set_text":
        target = sys.argv[2]
        val = sys.argv[3]
        cmd_set_text(target, val)
    elif cmd == "scratchpad":
        status = sys.argv[2] if len(sys.argv) > 2 else "Active"
        notes = sys.argv[3] if len(sys.argv) > 3 else ""
        cmd_update_scratchpad(status, notes)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
