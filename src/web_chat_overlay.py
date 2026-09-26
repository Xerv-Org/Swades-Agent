import pytesseract
from PIL import Image
import http.server
import socketserver
import json
import os
import re
import time
import shutil
import urllib.request
import urllib.parse
import threading
import subprocess
import traceback
import html2text

PORT = 6081
QUEUE_FILE = '/tmp/swades_message_queue.json'
LOGS_FILE = '/tmp/swades_chat_logs.json'
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
LOCAL_VLLM_URL = "http://localhost:8000/v1/chat/completions"

# 28 UNIVERSAL COMPREHENSIVE TOOLS
ALL_TOOLS = [
  {
    "type": "function",
    "function": {
      "name": "read_screen_ocr",
      "description": "Visual Optical Character Recognition (OCR): captures desktop framebuffer pixels and reads all visible text on the full screen or a specified bounding box region.",
      "parameters": {
        "type": "object",
        "properties": {
          "x": {"type": "integer", "description": "Optional bounding box left coordinate"},
          "y": {"type": "integer", "description": "Optional bounding box top coordinate"},
          "width": {"type": "integer", "description": "Optional bounding box width"},
          "height": {"type": "integer", "description": "Optional bounding box height"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "inspect_desktop_state",
      "description": "Comprehensive system & GUI inspector: dynamically returns active windows with PIDs and geometry, current mouse pointer position, top CPU/RAM processes, listening network ports, system load, and AMD ROCm GPU status.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_web_page",
      "description": "Fetch and extract the full text, markdown content, and links of any public webpage or URL.",
      "parameters": {
        "type": "object",
        "properties": {
          "url": {"type": "string", "description": "The target website URL to read"}
        },
        "required": ["url"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "scroll_page",
      "description": "Scroll the active window, viewport, or specified (x, y) coordinates up, down, to top, or to bottom.",
      "parameters": {
        "type": "object",
        "properties": {
          "direction": {"type": "string", "enum": ["down", "up", "top", "bottom"], "description": "Scroll direction"},
          "amount": {"type": "integer", "description": "Number of scroll clicks/pages (default: 5)"},
          "x": {"type": "integer", "description": "Optional X coordinate to hover before scrolling"},
          "y": {"type": "integer", "description": "Optional Y coordinate to hover before scrolling"}
        },
        "required": ["direction"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "run_os_command",
      "description": "Execute any Linux shell command on the host. Non-blocking for GUI apps, synchronous with full stdout/stderr capture for CLI commands.",
      "parameters": {
        "type": "object",
        "properties": {
          "command": {"type": "string", "description": "The exact shell command to execute"}
        },
        "required": ["command"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "type_keys",
      "description": "Type text directly on the active desktop screen, or send hotkeys and special keys (e.g. 'Return', 'ctrl+c', 'alt+tab', 'Page_Down', 'Home').",
      "parameters": {
        "type": "object",
        "properties": {
          "keys": {"type": "string", "description": "Text string or key combination to press"},
          "is_shortcut": {"type": "boolean", "description": "True if sending a key shortcut combination"}
        },
        "required": ["keys"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "mouse_action",
      "description": "Perform mouse click, right click, double click, middle click, or mouse move at exact (x, y) coordinates.",
      "parameters": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["click", "right_click", "double_click", "middle_click", "move"], "description": "Mouse action to perform"},
          "x": {"type": "integer", "description": "X coordinate on display"},
          "y": {"type": "integer", "description": "Y coordinate on display"}
        },
        "required": ["action"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "mouse_drag",
      "description": "Click and drag from a starting coordinate to an ending coordinate.",
      "parameters": {
        "type": "object",
        "properties": {
          "from_x": {"type": "integer", "description": "Starting X coordinate"},
          "from_y": {"type": "integer", "description": "Starting Y coordinate"},
          "to_x": {"type": "integer", "description": "Ending X coordinate"},
          "to_y": {"type": "integer", "description": "Ending Y coordinate"}
        },
        "required": ["from_x", "from_y", "to_x", "to_y"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "focus_window",
      "description": "Bring a window into focus by window title or application name.",
      "parameters": {
        "type": "object",
        "properties": {
          "title": {"type": "string", "description": "Window title substring or application name"}
        },
        "required": ["title"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "window_control",
      "description": "Maximize, minimize, or close a window.",
      "parameters": {
        "type": "object",
        "properties": {
          "title": {"type": "string", "description": "Window title or substring"},
          "action": {"type": "string", "enum": ["close", "maximize", "minimize"], "description": "Window action"}
        },
        "required": ["title", "action"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_open_windows",
      "description": "List all active GUI windows, their window IDs, positions, geometry, titles, and AT-SPI2 accessibility trees.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_screen_tree",
      "description": "Inspect active UI hierarchy, accessibility tree, and widget coordinates via AT-SPI2.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "interact_element",
      "description": "Click or trigger a GUI button, menu item, or input field by accessibility target name or ID.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {"type": "string", "description": "Element name, label, or accessibility ID"},
          "action": {"type": "string", "enum": ["click", "focus"], "description": "Action to perform"}
        },
        "required": ["target"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "set_field_value",
      "description": "Directly inject text into any UI text input or editor widget by accessibility target name.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {"type": "string", "description": "Target input field name or label"},
          "text": {"type": "string", "description": "Text to set"}
        },
        "required": ["target", "text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_clipboard",
      "description": "Read the current text content from the X11 clipboard.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "set_clipboard",
      "description": "Set the text content in the X11 clipboard.",
      "parameters": {
        "type": "object",
        "properties": {
          "text": {"type": "string", "description": "Text to copy to clipboard"}
        },
        "required": ["text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_file",
      "description": "Read file contents from filesystem.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "Absolute or relative file path"},
          "start_line": {"type": "integer", "description": "Optional starting line number (1-indexed)"},
          "end_line": {"type": "integer", "description": "Optional ending line number (1-indexed)"}
        },
        "required": ["path"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "write_file",
      "description": "Create or completely overwrite a file with contents.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File path to write"},
          "content": {"type": "string", "description": "Complete file text content"}
        },
        "required": ["path", "content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "edit_file",
      "description": "Replace a specific substring or code block in an existing file.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File path to edit"},
          "target_content": {"type": "string", "description": "Exact text to replace"},
          "replacement_content": {"type": "string", "description": "New replacement text"}
        },
        "required": ["path", "target_content", "replacement_content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "append_file",
      "description": "Append text to the end of a file.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File path to append to"},
          "content": {"type": "string", "description": "Text to append"}
        },
        "required": ["path", "content"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "delete_file",
      "description": "Delete a file or directory from the filesystem.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "File or directory path to remove"}
        },
        "required": ["path"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "list_dir",
      "description": "List files and directories in a path.",
      "parameters": {
        "type": "object",
        "properties": {
          "path": {"type": "string", "description": "Directory path (default: current directory)"},
          "recursive": {"type": "boolean", "description": "True to recursively list subdirectories"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "search_files",
      "description": "Search for a regex or string pattern inside files using ripgrep.",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Pattern or text to search for"},
          "path": {"type": "string", "description": "Directory or file path (default: .)"}
        },
        "required": ["query"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "find_files",
      "description": "Find files by filename pattern using glob.",
      "parameters": {
        "type": "object",
        "properties": {
          "pattern": {"type": "string", "description": "Filename pattern e.g. '*.py' or 'main.*'"},
          "path": {"type": "string", "description": "Root directory to search in"}
        },
        "required": ["pattern"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "take_screenshot",
      "description": "Capture a screenshot of the current virtual desktop display.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "http_request",
      "description": "Perform an HTTP GET, POST, PUT, or DELETE request to fetch web APIs or scrape pages.",
      "parameters": {
        "type": "object",
        "properties": {
          "url": {"type": "string", "description": "Full URL to request"},
          "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"], "description": "HTTP Method"},
          "data": {"type": "string", "description": "Optional payload body string"}
        },
        "required": ["url"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "manage_process",
      "description": "Full human-level process introspection and control: list all running processes, search by regex/name, view process tree, inspect deep details (open files, sockets, env, memory), or terminate processes.",
      "parameters": {
        "type": "object",
        "properties": {
          "action": {"type": "string", "enum": ["list", "search", "tree", "details", "kill"], "description": "Action: list, search, tree, details, kill"},
          "target": {"type": "string", "description": "PID or process name / search keyword"}
        },
        "required": ["action"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "system_info",
      "description": "Get detailed system hardware and OS status: CPU, RAM, Disk, Network, and AMD ROCm GPU status.",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "read_screen_tree",
      "description": "Zero-vision accessibility perception: reads full desktop AT-SPI2 widget hierarchy, states, and text.",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_focused_element",
      "description": "Inspect active UI focus, editable text caret, and geometry without moving the mouse.",
      "parameters": {"type": "object", "properties": {}, "required": []}
    }
  },
  {
    "type": "function",
    "function": {
      "name": "get_element_coordinates",
      "description": "Dynamically calculate exact bounding box (x, y, w, h) for any UI element by accessibility name/role.",
      "parameters": {
        "type": "object",
        "properties": {
          "target": {"type": "string", "description": "Element name or role"}
        },
        "required": ["target"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "browser_launch",
      "description": "Launch browser with Chrome DevTools Protocol (CDP) enabled on dynamic ephemeral port.",
      "parameters": {
        "type": "object",
        "properties": {
          "url": {"type": "string", "description": "Target URL to open"},
          "headless": {"type": "boolean", "description": "Run headless (default false)"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "browser_console_errors",
      "description": "Inspect live browser console errors, warnings, uncaught exceptions and stack traces via CDP.",
      "parameters": {
        "type": "object",
        "properties": {
          "port": {"type": "integer", "description": "Optional CDP port"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "browser_network_events",
      "description": "Inspect failed HTTP network requests (4xx, 5xx, CORS) via CDP.",
      "parameters": {
        "type": "object",
        "properties": {
          "port": {"type": "integer", "description": "Optional CDP port"}
        },
        "required": []
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "browser_eval_js",
      "description": "Execute arbitrary JavaScript in active browser tab context to inspect state or cookies.",
      "parameters": {
        "type": "object",
        "properties": {
          "expression": {"type": "string", "description": "JS expression to evaluate"},
          "port": {"type": "integer", "description": "Optional CDP port"}
        },
        "required": ["expression"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "browser_query_dom",
      "description": "Query DOM elements and exact bounding boxes (x, y, w, h) matching a CSS selector.",
      "parameters": {
        "type": "object",
        "properties": {
          "selector": {"type": "string", "description": "CSS selector"},
          "port": {"type": "integer", "description": "Optional CDP port"}
        },
        "required": ["selector"]
      }
    }
  }
]

import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEMANTIC_PY = os.path.join(SCRIPT_DIR, "semantic_desktop.py")
BROWSER_CDP_PY = os.path.join(SCRIPT_DIR, "browser_cdp.py")

def get_dynamic_env():
    env = os.environ.copy()
    if "DISPLAY" not in env or not env["DISPLAY"]:
        env["DISPLAY"] = ":0"
    if "XAUTHORITY" not in env or not os.path.exists(env.get("XAUTHORITY", "")):
        uid = os.getuid()
        mutter_auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
        if mutter_auths:
            env["XAUTHORITY"] = sorted(mutter_auths, key=os.path.getmtime)[-1]
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            env["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")
    env["GTK_MODULES"] = "gail:atk-bridge"
    env["NO_AT_BRIDGE"] = "0"
    return env

ENV_DISPLAY = get_dynamic_env()

def append_log(sender, text):
    try:
        logs = []
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, 'r') as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append({
            "sender": sender,
            "text": text,
            "time": time.strftime("%H:%M:%S")
        })
        logs = logs[-300:]
        with open(LOGS_FILE, 'w') as f:
            json.dump(logs, f, indent=2)
    except Exception as e:
        print(f"Log error: {e}")

def execute_master_tool(name, args):
    try:
        if name == "read_screen_ocr":
            shot = "/tmp/screen_ocr.png"
            p = subprocess.run(["scrot", "-z", shot], env=ENV_DISPLAY, capture_output=True, text=True)
            if p.returncode != 0:
                err = f"Failed to capture screen: {p.stderr.strip()}"
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            img = Image.open(shot)
            x = args.get("x")
            y = args.get("y")
            w = args.get("width")
            h = args.get("height")
            if x is not None and y is not None and w and h:
                img = img.crop((x, y, x + w, y + h))
            txt = pytesseract.image_to_string(img).strip()
            return f"=== VISUAL SCREEN OCR TEXT ===\n{txt[:4000] or '(No text detected in target region)'}"

        elif name == "inspect_desktop_state":
            res = []
            pw = subprocess.run("wmctrl -l -G -p", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
            res.append(f"=== OPEN WINDOWS ===\n{pw.stdout.strip() or 'None'}")
            
            pm = subprocess.run("xdotool getmouselocation", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
            res.append(f"=== MOUSE POSITION ===\n{pm.stdout.strip() or 'Unknown'}")
            
            pp = subprocess.run("ps aux --sort=-%cpu | head -n 20", shell=True, capture_output=True, text=True)
            res.append(f"=== TOP PROCESSES (CPU/MEM) ===\n{pp.stdout.strip()}")
            
            pn = subprocess.run("ss -tuln", shell=True, capture_output=True, text=True)
            res.append(f"=== LISTENING NETWORK PORTS ===\n{pn.stdout.strip()}")
            
            pu = subprocess.run("uptime", shell=True, capture_output=True, text=True)
            res.append(f"=== SYSTEM UPTIME & LOAD ===\n{pu.stdout.strip()}")
            
            pg = subprocess.run("/opt/rocm/bin/rocm-smi --showuse --showmeminfo", shell=True, capture_output=True, text=True)
            if pg.stdout.strip():
                res.append(f"=== AMD INSTINCT ROCm GPU STATUS ===\n{pg.stdout.strip()}")
            return "\n\n".join(res)

        elif name == "read_web_page":
            url = args.get("url", "").strip()
            if not url:
                err = "No URL provided."
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            if not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
                html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = True
                text = h.handle(html).strip()
                return f"--- WEBPAGE CONTENT ({url}) ---\n" + text[:6000]
            except Exception as e:
                err = f"Failed to fetch webpage '{url}': {e}"
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"

        elif name == "scroll_page":
            direction = args.get("direction", "down")
            amount = int(args.get("amount", 5))
            x = args.get("x")
            y = args.get("y")
            
            if x is not None and y is not None:
                subprocess.run(["xdotool", "mousemove", str(x), str(y)], env=ENV_DISPLAY)
            else:
                try:
                    geom = subprocess.run("xdotool getactivewindow getwindowgeometry --shell", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
                    gx, gy, gw, gh = 0, 0, 1920, 1080
                    for line in geom.stdout.splitlines():
                        if line.startswith("X="): gx = int(line.split("=")[1])
                        elif line.startswith("Y="): gy = int(line.split("=")[1])
                        elif line.startswith("WIDTH="): gw = int(line.split("=")[1])
                        elif line.startswith("HEIGHT="): gh = int(line.split("=")[1])
                    cx = gx + gw // 2
                    cy = gy + gh // 2
                    subprocess.run(["xdotool", "mousemove", str(cx), str(cy)], env=ENV_DISPLAY)
                except Exception:
                    pass

            if direction == "down":
                subprocess.run(["xdotool", "click", "--repeat", str(amount), "5"], env=ENV_DISPLAY)
                subprocess.run(["xdotool", "key", "Page_Down"], env=ENV_DISPLAY)
            elif direction == "up":
                subprocess.run(["xdotool", "click", "--repeat", str(amount), "4"], env=ENV_DISPLAY)
                subprocess.run(["xdotool", "key", "Page_Up"], env=ENV_DISPLAY)
            elif direction == "top":
                subprocess.run(["xdotool", "key", "Home"], env=ENV_DISPLAY)
            elif direction == "bottom":
                subprocess.run(["xdotool", "key", "End"], env=ENV_DISPLAY)
            time.sleep(0.2)
            return f"Scrolled {direction} (amount: {amount})"

        elif name == "run_os_command":
            cmd = args.get("command", "").strip()
            if not cmd:
                err = "Empty command supplied."
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            
            first_word = cmd.split()[0] if cmd else ""
            gui_apps = ["gedit", "mousepad", "xterm", "xfce4-terminal", "firefox", "chromium", "browser", "google-chrome", "gnome-calculator", "leafpad", "xeyes"]
            
            is_gui = (first_word in gui_apps) or any(re.search(rf'\b{re.escape(app)}\b', cmd) for app in ["mousepad", "gedit", "xfce4-terminal", "firefox", "chromium", "browser"]) or cmd.endswith("&")
            if any(cli in first_word for cli in ["python", "python3", "bash", "sh", "node", "pip", "git", "curl", "ls", "cat", "grep", "rg", "which", "ps", "kill", "apt"]):
                is_gui = False
            if cmd.endswith("&"):
                is_gui = True
            
            if is_gui:
                if not cmd.endswith("&"):
                    cmd = f"{cmd} &"
                p = subprocess.Popen(cmd, shell=True, env=ENV_DISPLAY, cwd="/root", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(1.2)
                poll = p.poll()
                if poll is not None and poll != 0:
                    err = p.stderr.read().decode('utf-8', errors='ignore')
                    msg = f"Failed to launch '{cmd}' (exit code {poll}): {err.strip() or 'Command not found or crashed'}"
                    append_log("Error Log", f"❌ {msg}")
                    return f"[ERROR]: {msg}"
                return f"Spawned GUI/Background process: {cmd}"
            else:
                p = subprocess.run(cmd, shell=True, env=ENV_DISPLAY, cwd="/root", capture_output=True, text=True, timeout=60)
                out = p.stdout.strip()
                err = p.stderr.strip()
                if p.returncode != 0:
                    err_msg = f"Command '{cmd}' exited with code {p.returncode}.\nSTDERR: {err}\nSTDOUT: {out}"
                    append_log("Error Log", f"❌ {err_msg[:300]}")
                    return f"[ERROR]: {err_msg}"
                res = []
                if out: res.append(f"STDOUT:\n{out}")
                if err: res.append(f"STDERR:\n{err}")
                if not res: res.append("Command executed with return code 0 (no output).")
                return "\n".join(res)

        elif name == "type_keys":
            keys = args.get("keys", "")
            is_shortcut = args.get("is_shortcut", False)
            special_keys = ["Return", "Enter", "Tab", "Escape", "BackSpace", "Delete", "Up", "Down", "Left", "Right", "Page_Up", "Page_Down", "Home", "End", "space"]
            has_modifier = any(mod in keys.lower() for mod in ["ctrl+", "alt+", "shift+", "super+"])
            
            if is_shortcut or keys in special_keys or has_modifier:
                key_to_press = "Return" if keys == "Enter" else keys
                subprocess.run(["xdotool", "key", key_to_press], env=ENV_DISPLAY)
                time.sleep(0.3)
                return f"Sent keypress: {key_to_press}"
            else:
                subprocess.run(["xdotool", "type", "--delay", "20", keys], env=ENV_DISPLAY)
                time.sleep(0.3)
                return f"Typed on screen: {keys}"

        elif name == "mouse_action":
            act = args.get("action", "click")
            x = args.get("x")
            y = args.get("y")
            if x is not None and y is not None:
                subprocess.run(["xdotool", "mousemove", str(x), str(y)], env=ENV_DISPLAY)
            
            if act == "click":
                subprocess.run(["xdotool", "click", "1"], env=ENV_DISPLAY)
            elif act == "right_click":
                subprocess.run(["xdotool", "click", "3"], env=ENV_DISPLAY)
            elif act == "double_click":
                subprocess.run(["xdotool", "click", "--repeat", "2", "1"], env=ENV_DISPLAY)
            elif act == "middle_click":
                subprocess.run(["xdotool", "click", "2"], env=ENV_DISPLAY)
            return f"Performed mouse {act}"

        elif name == "mouse_drag":
            fx = args.get("from_x", 0)
            fy = args.get("from_y", 0)
            tx = args.get("to_x", 0)
            ty = args.get("to_y", 0)
            subprocess.run(["xdotool", "mousemove", str(fx), str(fy)], env=ENV_DISPLAY)
            subprocess.run(["xdotool", "mousedown", "1"], env=ENV_DISPLAY)
            subprocess.run(["xdotool", "mousemove", str(tx), str(ty)], env=ENV_DISPLAY)
            subprocess.run(["xdotool", "mouseup", "1"], env=ENV_DISPLAY)
            return f"Dragged mouse from ({fx}, {fy}) to ({tx}, {ty})"

        elif name == "focus_window":
            title = args.get("title", "")
            p = subprocess.run(f"wmctrl -a '{title}' || xdotool search --name '{title}' windowactivate", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
            time.sleep(0.5)
            return f"Focused window matching: {title}"

        elif name == "window_control":
            title = args.get("title", "")
            action = args.get("action", "close")
            if action == "close":
                subprocess.run(f"wmctrl -c '{title}'", shell=True, env=ENV_DISPLAY)
            elif action == "maximize":
                subprocess.run(f"wmctrl -r '{title}' -b add,maximized_vert,maximized_horz", shell=True, env=ENV_DISPLAY)
            elif action == "minimize":
                subprocess.run(f"wmctrl -r '{title}' -b add,hidden", shell=True, env=ENV_DISPLAY)
            return f"Window '{title}' {action} triggered."

        elif name == "list_open_windows":
            p = subprocess.run("wmctrl -l -G -p", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
            wms = p.stdout.strip()
            p2 = subprocess.run(["python3", SEMANTIC_PY, "list_windows"], capture_output=True, text=True, env=ENV_DISPLAY)
            sem = p2.stdout.strip()
            return f"Active Windows (wmctrl):\n{wms}\n\nAccessibility Windows:\n{sem}"

        elif name == "read_screen_tree":
            p = subprocess.run(["python3", SEMANTIC_PY, "dump"], capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "get_focused_element":
            p = subprocess.run(["python3", SEMANTIC_PY, "focused"], capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "get_element_coordinates":
            target = args.get("target", "")
            p = subprocess.run(["python3", SEMANTIC_PY, "extents", target], capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "interact_element":
            target = args.get("target", "")
            act = args.get("action", "click")
            p = subprocess.run(["python3", SEMANTIC_PY, "interact", target, act], capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "set_field_value":
            target = args.get("target", "")
            text = args.get("text", "")
            p = subprocess.run(["python3", SEMANTIC_PY, "set_text", target, text], capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "browser_launch":
            url = args.get("url", "about:blank")
            cmd = ["python3", BROWSER_CDP_PY, "launch", url]
            if args.get("headless"): cmd.append("--headless")
            p = subprocess.run(cmd, capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "browser_console_errors":
            port = args.get("port")
            cmd = ["python3", BROWSER_CDP_PY, "console"]
            if port: cmd.append(f"--port={port}")
            p = subprocess.run(cmd, capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "browser_network_events":
            port = args.get("port")
            cmd = ["python3", BROWSER_CDP_PY, "network"]
            if port: cmd.append(f"--port={port}")
            p = subprocess.run(cmd, capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "browser_eval_js":
            port = args.get("port")
            expr = args.get("expression", "window.location.href")
            cmd = ["python3", BROWSER_CDP_PY, "eval", expr]
            if port: cmd.append(f"--port={port}")
            p = subprocess.run(cmd, capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "browser_query_dom":
            port = args.get("port")
            sel = args.get("selector", "*")
            cmd = ["python3", BROWSER_CDP_PY, "query", sel]
            if port: cmd.append(f"--port={port}")
            p = subprocess.run(cmd, capture_output=True, text=True, env=ENV_DISPLAY)
            return p.stdout.strip() or p.stderr.strip()

        elif name == "get_clipboard":
            p = subprocess.run("xclip -o -selection clipboard || xsel -b -o", shell=True, env=ENV_DISPLAY, capture_output=True, text=True)
            return p.stdout.strip() or "(Clipboard empty)"

        elif name == "set_clipboard":
            text = args.get("text", "")
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, env=ENV_DISPLAY, text=True)
            p.communicate(input=text)
            return f"Copied {len(text)} characters to clipboard."

        elif name == "read_file":
            path = args.get("path", "")
            if not os.path.exists(path):
                err = f"File '{path}' does not exist."
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            s_line = args.get("start_line")
            e_line = args.get("end_line")
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            if s_line is not None or e_line is not None:
                start = max(0, (s_line or 1) - 1)
                end = min(len(lines), e_line or len(lines))
                sliced = lines[start:end]
                numbered = [f"{start + i + 1}: {line}" for i, line in enumerate(sliced)]
                return "".join(numbered) or "(Empty line range)"
            return "".join(lines)

        elif name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Wrote {len(content)} bytes to {path}"

        elif name == "edit_file":
            path = args.get("path", "")
            target = args.get("target_content", "")
            repl = args.get("replacement_content", "")
            if not os.path.exists(path):
                err = f"File '{path}' does not exist."
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if target not in content:
                err = f"Target content not found in {path}"
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            new_content = content.replace(target, repl, 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return f"Successfully edited {path}"

        elif name == "append_file":
            path = args.get("path", "")
            content = args.get("content", "")
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return f"Appended {len(content)} bytes to {path}"

        elif name == "delete_file":
            path = args.get("path", "")
            if os.path.isdir(path):
                shutil.rmtree(path)
                return f"Removed directory {path}"
            elif os.path.exists(path):
                os.remove(path)
                return f"Removed file {path}"
            err = f"Path '{path}' does not exist."
            append_log("Error Log", f"❌ {err}")
            return f"[ERROR]: {err}"

        elif name == "list_dir":
            path = args.get("path", ".")
            if not os.path.exists(path):
                err = f"Directory '{path}' does not exist."
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            rec = args.get("recursive", False)
            res = []
            if rec:
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        res.append(f"[DIR]  {os.path.relpath(os.path.join(root, d), path)}")
                    for file in files:
                        fp = os.path.join(root, file)
                        res.append(f"[FILE] {os.path.relpath(fp, path)} ({os.path.getsize(fp)} bytes)")
            else:
                for e in os.listdir(path):
                    fp = os.path.join(path, e)
                    is_d = os.path.isdir(fp)
                    sz = os.path.getsize(fp) if not is_d else 0
                    res.append(f"{'[DIR] ' if is_d else '[FILE]'} {e} ({sz} bytes)")
            return "\n".join(res[:200])

        elif name == "search_files":
            query = args.get("query", "")
            path = args.get("path", ".")
            p = subprocess.run(["rg", "-n", query, path], capture_output=True, text=True, timeout=20)
            return p.stdout.strip() or p.stderr.strip() or "No matches found."

        elif name == "find_files":
            pattern = args.get("pattern", "*")
            path = args.get("path", ".")
            p = subprocess.run(["fdfind", "-p", pattern, path] if shutil.which("fdfind") else ["find", path, "-name", pattern], capture_output=True, text=True, timeout=20)
            return p.stdout.strip() or "No matching files."

        elif name == "take_screenshot":
            shot_path = "/tmp/desktop_shot.png"
            p = subprocess.run(["scrot", "-z", shot_path], env=ENV_DISPLAY, capture_output=True, text=True)
            if p.returncode != 0:
                err = f"Failed to take screenshot: {p.stderr.strip()}"
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"
            return f"Screenshot captured to {shot_path}"

        elif name == "http_request":
            url = args.get("url", "")
            method = args.get("method", "GET").upper()
            data = args.get("data", None)
            req_data = data.encode("utf-8") if data else None
            req = urllib.request.Request(url, data=req_data, method=method)
            req.add_header("User-Agent", "Mozilla/5.0 SwadesAgent/1.0")
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    return body[:4000]
            except Exception as e:
                err = f"HTTP request failed: {e}"
                append_log("Error Log", f"❌ {err}")
                return f"[ERROR]: {err}"

        elif name == "manage_process":
            action = args.get("action", "list")
            target = args.get("target", "").strip()
            if action in ("list", "search"):
                if target:
                    p1 = subprocess.run(f"ps aux | grep -i '{target}' | grep -v grep", shell=True, capture_output=True, text=True)
                    p2 = subprocess.run(f"pstree -ap | grep -i '{target}'", shell=True, capture_output=True, text=True)
                    res = []
                    if p1.stdout.strip(): res.append(f"=== MATCHING PROCESSES (ps) ===\n{p1.stdout.strip()}")
                    if p2.stdout.strip(): res.append(f"=== MATCHING PROCESS TREE (pstree) ===\n{p2.stdout.strip()[:2000]}")
                    return "\n\n".join(res) or f"No running processes found matching '{target}'."
                else:
                    p1 = subprocess.run("ps aux --sort=-%cpu | head -n 40", shell=True, capture_output=True, text=True)
                    p2 = subprocess.run("pstree -p | head -n 30", shell=True, capture_output=True, text=True)
                    return f"=== TOP PROCESSES (CPU/MEM) ===\n{p1.stdout.strip()}\n\n=== PROCESS TREE HIERARCHY ===\n{p2.stdout.strip()}"
            elif action == "tree":
                cmd = f"pstree -ap {target}" if target.isdigit() else "pstree -ap | head -n 60"
                p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                return p.stdout.strip() or p.stderr.strip() or "(No process tree output)"
            elif action in ("details", "inspect"):
                if not target:
                    return "Error: target PID or name required for detailed process inspection."
                pid = target.strip()
                if not pid.isdigit():
                    pg = subprocess.run(f"pgrep -f '{target}' | head -n 1", shell=True, capture_output=True, text=True)
                    pid = pg.stdout.strip().split()[0] if pg.stdout.strip() else ""
                if not pid:
                    return f"No running process found matching '{target}'."
                res = []
                try:
                    with open(f"/proc/{pid}/status", "r") as sf:
                        status_lines = [sf.readline() for _ in range(30)]
                        res.append(f"=== STATUS (PID {pid}) ===\n{''.join(status_lines).strip()}")
                except Exception as ex:
                    res.append(f"Status error: {ex}")
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as cf:
                        cmdline = cf.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
                        res.append(f"=== FULL CMDLINE ===\n{cmdline}")
                except Exception as ex:
                    res.append(f"Cmdline error: {ex}")
                try:
                    p_fd = subprocess.run(f"ls -la /proc/{pid}/fd 2>/dev/null | head -n 25", shell=True, capture_output=True, text=True)
                    res.append(f"=== OPEN FILE DESCRIPTORS ===\n{p_fd.stdout.strip() or 'None or access denied'}")
                except Exception:
                    pass
                p_sock = subprocess.run(f"lsof -p {pid} -i 2>/dev/null", shell=True, capture_output=True, text=True)
                if p_sock.stdout.strip():
                    res.append(f"=== OPEN NETWORK CONNECTIONS ===\n{p_sock.stdout.strip()}")
                return "\n\n".join(res)
            elif action == "kill":
                if not target:
                    return "Error: target PID or process name required to kill."
                if target.isdigit():
                    p = subprocess.run(["kill", "-9", target], capture_output=True, text=True)
                else:
                    p = subprocess.run(["pkill", "-9", "-f", target], capture_output=True, text=True)
                return f"Sent SIGKILL to {target}"

        elif name == "system_info":
            res = []
            p1 = subprocess.run("uptime", shell=True, capture_output=True, text=True)
            res.append(f"UPTIME & LOAD:\n{p1.stdout.strip()}")
            p2 = subprocess.run("free -h", shell=True, capture_output=True, text=True)
            res.append(f"MEMORY:\n{p2.stdout.strip()}")
            p3 = subprocess.run("df -h /", shell=True, capture_output=True, text=True)
            res.append(f"DISK:\n{p3.stdout.strip()}")
            p4 = subprocess.run("/opt/rocm/bin/rocm-smi --showuse --showmeminfo", shell=True, capture_output=True, text=True)
            if p4.stdout.strip():
                res.append(f"AMD INSTINCT ROCm GPU STATUS:\n{p4.stdout.strip()}")
            return "\n\n".join(res)

        else:
            err = f"Unknown tool: {name}"
            append_log("Error Log", f"❌ {err}")
            return f"[ERROR]: {err}"

    except Exception as e:
        err = f"Exception in tool '{name}': {e}\n{traceback.format_exc()}"
        append_log("Error Log", f"❌ {err[:300]}")
        return f"[FATAL TOOL ERROR in {name}]: {e}"

def sanitize_messages_for_api(messages):
    """Ensure message sequence strictly complies with OpenAI/Groq API tool-call schema."""
    clean = []
    for m in messages:
        role = m.get("role")
        if role == "system" or role == "user":
            clean.append({"role": role, "content": str(m.get("content", ""))})
        elif role == "assistant":
            item = {"role": "assistant"}
            if m.get("content"):
                item["content"] = str(m["content"])
            if m.get("tool_calls"):
                item["tool_calls"] = m["tool_calls"]
            clean.append(item)
        elif role == "tool":
            clean.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", f"call_{int(time.time()*1000)}"),
                "content": str(m.get("content", ""))
            })
    return clean

def call_llm_api(messages):
    models = ["llama-3.3-70b-versatile", "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
    last_err = None

    sanitized = sanitize_messages_for_api(messages)

    for model in models:
        payload = {
            "model": model,
            "messages": sanitized,
            "tools": ALL_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 4096
        }
        try:
            req = urllib.request.Request(
                GROQ_URL,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {GROQ_KEY}"
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                choice = data["choices"][0]["message"]
                return choice
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            last_err = e
            if e.code == 429:
                append_log("System", f"⚠️ Groq Rate Limit (429) hit on {model} -> Failing over immediately to local AMD MI300X vLLM...")
                break
            elif e.code == 400:
                append_log("Error Log", f"⚠️ Groq HTTP 400 on {model}: {err_body[:200]} -> Failing over to local MI300X vLLM...")
                break
            else:
                append_log("Error Log", f"❌ Groq API error ({e.code}) on {model}: {err_body[:200]}")
        except Exception as e:
            last_err = e
            append_log("Error Log", f"❌ Connection error on {model}: {e}")

    # Failover to Local AMD MI300X vLLM
    try:
        append_log("System", "⚡ Running on local AMD Instinct MI300X vLLM (Qwen2.5-Coder-32B)...")
        payload = {
            "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
            "messages": sanitized,
            "tools": ALL_TOOLS,
            "tool_choice": "auto",
            "temperature": 0.2,
            "max_tokens": 4096
        }
        req = urllib.request.Request(
            LOCAL_VLLM_URL,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            msg = data["choices"][0]["message"]
            if not msg.get("tool_calls") and msg.get("content"):
                content = msg["content"]
                m = re.search(r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{.*?\})\s*\}', content, re.DOTALL)
                if m:
                    t_name = m.group(1)
                    t_args = m.group(2)
                    msg["tool_calls"] = [{
                        "id": f"call_local_{int(time.time()*1000)}",
                        "type": "function",
                        "function": {
                            "name": t_name,
                            "arguments": t_args
                        }
                    }]
            return msg
    except Exception as vllm_err:
        fatal = f"All inference backends failed! Groq: {last_err}, Local vLLM: {vllm_err}"
        append_log("Crash Log", f"❌ {fatal}")
        raise Exception(fatal)

def stream_groq_react(task_item):
    user_prompt = task_item["text"]
    append_log("System", f"🚀 Starting execution for: '{user_prompt}'")

    messages = [
        {
            "role": "system",
            "content": (
                "You are an autonomous AI Desktop & Software Engineering Agent operating on Ubuntu Linux 24.04.\n"
                "You have 28 universal tools with max human-level flexibility to observe and execute ANY task:\n"
                "- read_screen_ocr: Optical Character Recognition on screen pixels to read any visible text/UI.\n"
                "- inspect_desktop_state: Comprehensive system & GUI overview (open windows, mouse, processes, ports, load, GPU).\n"
                "- read_web_page: Fetch and parse clean text and markdown from any URL.\n"
                "- scroll_page: Scroll webpage/window up, down, to top, or bottom.\n"
                "- run_os_command: Run any bash command, compile, test, or launch GUI apps (e.g. `browser <url> &`).\n"
                "- type_keys: Type text or send hotkeys (`ctrl+s`, `Return`, `Page_Down`, `Home`, `End`).\n"
                "- mouse_action / mouse_drag: Click, move, drag, or scroll at any coordinate.\n"
                "- focus_window / window_control / list_open_windows: Full window management.\n"
                "- read_screen_tree / interact_element / set_field_value: AT-SPI2 accessibility tree.\n"
                "- get_clipboard / set_clipboard: System clipboard operations.\n"
                "- read_file / write_file / edit_file / append_file / delete_file: Complete filesystem tools.\n"
                "- list_dir / search_files / find_files: Directory tree and ripgrep code search.\n"
                "- take_screenshot: Display screenshot capture.\n"
                "- manage_process: Inspect and kill processes.\n"
                "- system_info: Hardware, CPU, memory, and ROCm GPU stats.\n\n"
                "CRITICAL OPERATIONAL INSTRUCTIONS:\n"
                "1. NO SILENT FAILURES: Every error or warning must be addressed. If a command or tool returns an error, analyze it and report it to the user with solutions.\n"
                "2. WEB & VISUAL TASKS: When asked to visit a website or use a web app, open the visual browser (`run_os_command: {'command': 'browser <URL> &'}`) and read its content (`read_web_page: {'url': '<URL>'}`).\n"
                "3. SCROLLING: Use `scroll_page: {'direction': 'down'}` or `scroll_page: {'direction': 'up'}` to scroll the visual desktop browser.\n"
                "4. DYNAMIC INSPECTION: Use `inspect_desktop_state`, `list_open_windows`, or `manage_process` to dynamically observe processes and windows.\n"
                "5. CONTINUOUS REASONING: Always call tools to gather facts before producing your final synthesized answer."
            )
        },
        {"role": "user", "content": user_prompt}
    ]

    max_steps = 15
    for step in range(1, max_steps + 1):
        append_log("AI Step", f"⚡ Step {step}: Reasoning on LPU...")

        try:
            msg = call_llm_api(messages)
        except Exception as e:
            append_log("Error Log", f"❌ LLM Inference Error: {e}")
            break

        reasoning = msg.get("reasoning")
        if reasoning:
            append_log("AI Thought", reasoning)

        content = msg.get("content")
        if content:
            append_log("AI Message", content)

        tool_calls = msg.get("tool_calls")
        if tool_calls and len(tool_calls) > 0:
            messages.append(msg)
            for call in tool_calls:
                fn_name = call["function"]["name"]
                fn_args = {}
                try:
                    fn_args = json.loads(call["function"]["arguments"])
                except Exception as parse_err:
                    append_log("Error Log", f"❌ Error parsing tool arguments for {fn_name}: {parse_err}")

                append_log("AI Action", f"🔧 Tool Call: {fn_name} with args: {json.dumps(fn_args)}")

                obs = execute_master_tool(fn_name, fn_args)
                append_log("Observation", str(obs)[:500])

                call_id = call.get("id") or f"call_{int(time.time()*1000)}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(obs)
                })
        else:
            append_log("AI Done", content or "Task finished.")
            break

def worker_thread():
    while True:
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r') as f:
                    queue = json.load(f)
                
                # Pick any pending or uncompleted task
                pending = [q for q in queue if q.get('status') == 'pending']
                if pending:
                    item = pending[0]
                    item['status'] = 'running'
                    with open(QUEUE_FILE, 'w') as f:
                        json.dump(queue, f, indent=2)

                    try:
                        task_text = item.get("text", "")
                        proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                        proc = subprocess.Popen(["node", "src/index.js", "cua", task_text], cwd=proj_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        proc.communicate()
                    except Exception as loop_err:
                        append_log("Crash Log", f"❌ Fatal Loop Error: {loop_err}\n{traceback.format_exc()}")

                    item['status'] = 'completed'
                    with open(QUEUE_FILE, 'w') as f:
                        json.dump(queue, f, indent=2)
        except Exception as q_err:
            print(f"Queue error: {q_err}")
        time.sleep(0.3)

threading.Thread(target=worker_thread, daemon=True).start()

HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
<meta http-equiv="Pragma" content="no-cache" />
<meta http-equiv="Expires" content="0" />
<title>Swades Agent - Universal CUA & SWE ReAct</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background-color: #0b0f19;
    color: #f1f5f9;
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    height: 100vh;
    overflow: hidden;
    position: relative;
    user-select: none;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  #desktop-container {
    width: 100vw;
    height: 100vh;
    position: absolute;
    top: 0;
    left: 0;
    z-index: 1;
    pointer-events: none !important;
  }
  iframe#desktop-frame {
    width: 100%;
    height: 100%;
    border: none;
    pointer-events: none !important;
  }
  #hud-overlay {
    position: absolute;
    bottom: 24px;
    right: 24px;
    width: 560px;
    height: 680px;
    min-width: 380px;
    min-height: 420px;
    max-width: 92vw;
    max-height: 92vh;
    resize: both;
    overflow: hidden;
    background: rgba(15, 23, 42, 0.90);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 20px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 30px rgba(56, 189, 248, 0.18);
    display: flex;
    flex-direction: column;
    z-index: 99999;
    user-select: auto;
  }
  .hud-header {
    background: linear-gradient(90deg, rgba(30, 41, 59, 0.98), rgba(15, 23, 42, 0.98));
    padding: 14px 18px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    cursor: move;
    user-select: none;
  }
  .hud-title {
    font-size: 14.5px;
    font-weight: 700;
    color: #38bdf8;
    display: flex;
    align-items: center;
    gap: 10px;
    letter-spacing: -0.2px;
  }
  .drag-handle {
    color: #64748b;
    font-size: 17px;
    cursor: grab;
  }
  .hud-badge {
    background: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.35);
    font-size: 11.5px;
    padding: 3px 10px;
    border-radius: 999px;
    font-weight: 600;
    letter-spacing: 0.2px;
  }
  .chat-stream {
    flex: 1;
    overflow-y: auto;
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    font-size: 13.5px;
    line-height: 1.55;
    scroll-behavior: smooth;
  }
  .chat-bubble {
    padding: 11px 15px;
    border-radius: 14px;
    line-height: 1.55;
    word-break: break-word;
    max-width: 95%;
    font-size: 13.5px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  }
  .bubble-user {
    align-self: flex-end;
    background: linear-gradient(135deg, #0284c7, #2563eb);
    color: #ffffff;
    font-weight: 500;
    border-bottom-right-radius: 3px;
  }
  .bubble-system {
    align-self: flex-start;
    background: rgba(30, 41, 59, 0.85);
    color: #94a3b8;
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  .bubble-thought {
    align-self: flex-start;
    background: rgba(245, 158, 11, 0.12);
    border-left: 3.5px solid #f59e0b;
    color: #fde68a;
    font-style: italic;
  }
  .bubble-action {
    align-self: flex-start;
    background: rgba(56, 189, 248, 0.12);
    border-left: 3.5px solid #38bdf8;
    color: #7dd3fc;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12.5px;
  }
  .bubble-obs {
    align-self: flex-start;
    background: rgba(15, 23, 42, 0.85);
    border-left: 3.5px solid #10b981;
    color: #a7f3d0;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    white-space: pre-wrap;
  }
  .bubble-error {
    align-self: flex-start;
    background: rgba(239, 68, 68, 0.18);
    border-left: 3.5px solid #ef4444;
    border: 1px solid rgba(239, 68, 68, 0.35);
    color: #fca5a5;
    font-weight: 600;
  }
  .bubble-done {
    align-self: flex-start;
    background: rgba(16, 185, 129, 0.18);
    border: 1px solid rgba(16, 185, 129, 0.35);
    color: #6ee7b7;
    font-weight: 600;
  }
  .hud-input-bar {
    padding: 14px 18px;
    background: rgba(15, 23, 42, 0.98);
    border-top: 1px solid rgba(255, 255, 255, 0.08);
    display: flex;
    gap: 12px;
  }
  .hud-input {
    flex: 1;
    background: rgba(30, 41, 59, 0.85);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    color: #ffffff;
    padding: 12px 16px;
    font-size: 13.5px;
    font-family: 'Plus Jakarta Sans', sans-serif;
    outline: none;
    transition: all 0.2s;
  }
  .hud-input:focus {
    border-color: #38bdf8;
    box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.2);
  }
  .hud-btn {
    background: linear-gradient(135deg, #0284c7, #2563eb);
    color: #ffffff;
    border: none;
    border-radius: 12px;
    padding: 0 20px;
    font-weight: 700;
    font-size: 13.5px;
    font-family: 'Plus Jakarta Sans', sans-serif;
    cursor: pointer;
    transition: all 0.2s;
  }
  .hud-btn:hover {
    background: linear-gradient(135deg, #0369a1, #1d4ed8);
    transform: translateY(-1px);
  }
  .hud-btn:active {
    transform: translateY(0);
  }
</style>
</head>
<body>

<div id="desktop-container" style="display:flex; flex-direction:column; justify-content:center; align-items:center; height:100%; opacity:0.12; font-family:'JetBrains Mono',monospace;">
  <h1 style="font-size:42px; margin-bottom:12px; letter-spacing:1px;">⚡ SWADES AGENT CUA</h1>
  <p style="font-size:16px;">Omni-Inspector • 28 Universal Tools • Live ReAct Telemetry</p>
</div>

<div id="hud-overlay">
  <div class="hud-header" id="hud-header">
    <div class="hud-title">
      <span class="drag-handle">⠿</span>
      <span>⚡ Swades Agent ReAct CUA</span>
    </div>
    <div class="hud-badge">28 Tools • Deep Observability</div>
  </div>
  <div class="chat-stream" id="chat-stream"></div>
  <div class="hud-input-bar">
    <input type="text" id="hud-input" class="hud-input" placeholder="Instruct agent..." />
    <button id="send-btn" class="hud-btn">Execute</button>
  </div>
</div>

<script>
  // Draggable HUD functionality
  const hud = document.getElementById('hud-overlay');
  const header = document.getElementById('hud-header');
  let isDragging = false;
  let currentX, currentY, initialX, initialY;
  let xOffset = 0, yOffset = 0;

  header.addEventListener('mousedown', dragStart);
  document.addEventListener('mousemove', drag);
  document.addEventListener('mouseup', dragEnd);

  function dragStart(e) {
    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;
    if (e.target === header || header.contains(e.target)) {
      isDragging = true;
    }
  }

  function drag(e) {
    if (isDragging) {
      e.preventDefault();
      currentX = e.clientX - initialX;
      currentY = e.clientY - initialY;
      xOffset = currentX;
      yOffset = currentY;
      hud.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
    }
  }

  function dragEnd() {
    initialX = currentX;
    initialY = currentY;
    isDragging = false;
  }

  // Live polling of logs
  let lastLogStr = "";
  async function pollLogs() {
    try {
      const res = await fetch('/api/logs?t=' + Date.now());
      const logs = await res.json();
      const newStr = JSON.stringify(logs);
      if (newStr !== lastLogStr) {
        lastLogStr = newStr;
        const container = document.getElementById('chat-stream');
        container.innerHTML = '';
        logs.forEach(msg => {
          const div = document.createElement('div');
          let cls = "bubble-system";
          if (msg.sender === "User") cls = "bubble-user";
          else if (msg.sender === "AI Thought") cls = "bubble-thought";
          else if (msg.sender === "AI Action") cls = "bubble-action";
          else if (msg.sender === "Observation") cls = "bubble-obs";
          else if (msg.sender === "AI Done") cls = "bubble-done";
          else if (msg.sender === "Error Log" || msg.sender === "Crash Log" || (msg.sender && msg.sender.includes("Error")) || (msg.text && (msg.text.startsWith("❌") || msg.text.startsWith("Error:") || msg.text.startsWith("[ERROR")))) {
            cls = "bubble-error";
          }

          div.className = `chat-bubble ${cls}`;
          div.innerHTML = `<strong>${msg.sender} <span style="font-size:10.5px; opacity:0.6; font-weight:normal; margin-left:6px;">${msg.time || ''}</span></strong><br/>${escapeHtml(msg.text)}`;
          container.appendChild(div);
        });
        container.scrollTop = container.scrollHeight;
      }
    } catch (e) {
      console.error(e);
    }
  }

  function escapeHtml(text) {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\\n/g, "<br/>");
  }

  async function sendMessage() {
    const input = document.getElementById('hud-input');
    const txt = input.value.trim();
    if (!txt) return;
    input.value = '';

    // Optimistically render user message immediately
    const container = document.getElementById('chat-stream');
    const div = document.createElement('div');
    div.className = 'chat-bubble bubble-user';
    const now = new Date().toTimeString().split(' ')[0];
    div.innerHTML = `<strong>User <span style="font-size:10.5px; opacity:0.6; font-weight:normal; margin-left:6px;">${now}</span></strong><br/>${escapeHtml(txt)}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;

    try {
      await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: txt })
      });
      pollLogs();
    } catch (err) {
      console.error("Failed to send message:", err);
    }
  }

  document.getElementById('send-btn').addEventListener('click', sendMessage);
  document.getElementById('hud-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  setInterval(pollLogs, 700);
  pollLogs();
</script>

</body>
</html>
"""

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        if self.path == '/' or self.path.startswith('/?'):
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode('utf-8'))
        elif self.path.startswith('/api/logs'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            logs = []
            if os.path.exists(LOGS_FILE):
                try:
                    with open(LOGS_FILE, 'r') as f:
                        logs = json.load(f)
                except Exception:
                    pass
            self.wfile.write(json.dumps(logs).encode('utf-8'))
        elif self.path.startswith('/api/state'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "active", "tools_count": len(ALL_TOOLS), "running": True}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/api/message':
            length = int(self.headers.get('Content-Length', 0))
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            msg = data.get('message', '').strip()

            if msg:
                append_log("User", msg)

                queue = []
                if os.path.exists(QUEUE_FILE):
                    try:
                        with open(QUEUE_FILE, 'r') as f:
                            queue = json.load(f)
                    except Exception:
                        pass

                queue.append({
                    "id": str(time.time()),
                    "text": msg,
                    "status": "pending"
                })

                with open(QUEUE_FILE, 'w') as f:
                    json.dump(queue, f, indent=2)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        print(f"Universal ReAct CUA Overlay Web Server running on port {PORT}")
        httpd.serve_forever()

if __name__ == '__main__':
    run()
