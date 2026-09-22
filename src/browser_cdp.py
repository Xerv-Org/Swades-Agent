#!/usr/bin/env python3
"""
browser_cdp.py — Chrome DevTools Protocol (CDP) & Browser Inspection Engine for Swades CUA
Zero-screenshot low-level browser introspection:
- Capture live console.error, console.warn, unhandled exceptions & JS stack traces.
- Capture network failures (4xx, 5xx, CORS, net::ERR_*).
- Query DOM nodes, styles, and exact bounding boxes (x, y, w, h).
- Execute arbitrary JS expressions in active tab context.
- Dynamic browser discovery and ephemeral debugging port allocation (zero hardcoding).
"""

import sys
import os
import json
import socket
import glob
import time
import shutil
import asyncio
import subprocess
import urllib.request
import urllib.error

# Auto-detect display & auth
def ensure_display_and_auth():
    if "DISPLAY" not in os.environ or not os.environ["DISPLAY"]:
        os.environ["DISPLAY"] = ":0"
    if "XAUTHORITY" not in os.environ or not os.path.exists(os.environ.get("XAUTHORITY", "")):
        uid = os.getuid()
        mutter_auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
        if mutter_auths:
            os.environ["XAUTHORITY"] = sorted(mutter_auths, key=os.path.getmtime)[-1]
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

ensure_display_and_auth()

def find_browser_binary():
    # 1. Check Playwright Chromium installs
    home = os.path.expanduser("~")
    playwright_chromes = glob.glob(f"{home}/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")
    if playwright_chromes:
        return sorted(playwright_chromes)[-1]

    # 2. Check standard PATH binaries
    for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser"]:
        path = shutil.which(name)
        if path:
            return path

    return None

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

def get_cdp_targets(port):
    try:
        url = f"http://127.0.0.1:{port}/json/list"
        req = urllib.request.urlopen(url, timeout=3)
        return json.loads(req.read().decode())
    except Exception:
        try:
            url = f"http://127.0.0.1:{port}/json"
            req = urllib.request.urlopen(url, timeout=3)
            return json.loads(req.read().decode())
        except Exception:
            return []

def get_page_ws_url(port):
    targets = get_cdp_targets(port)
    for t in targets:
        if t.get("type") == "page" and "webSocketDebuggerUrl" in t:
            return t["webSocketDebuggerUrl"]
    if targets and "webSocketDebuggerUrl" in targets[0]:
        return targets[0]["webSocketDebuggerUrl"]
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.urlopen(url, timeout=3)
        ver = json.loads(req.read().decode())
        return ver.get("webSocketDebuggerUrl")
    except Exception:
        return None

def launch_browser(url="about:blank", port=0, headless=False):
    binary = find_browser_binary()
    if not binary:
        return {"success": False, "error": "No compatible Chromium binary found. Run 'npx playwright install chromium'."}

    if not port or port == 0:
        port = get_free_port()

    home = os.path.expanduser("~")
    profile_dir = os.path.join(home, ".cache", f"swades_browser_profile_{port}")
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1280,800",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]

    if headless:
        cmd.append("--headless=new")

    cmd.append(url)

    env = os.environ.copy()
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    # Wait for CDP endpoint to become ready
    max_wait = 10
    start_time = time.time()
    ws_url = None

    while time.time() - start_time < max_wait:
        ws_url = get_page_ws_url(port)
        if ws_url:
            break
        time.sleep(0.3)

    if not ws_url:
        return {
            "success": False,
            "error": f"Browser started (PID {proc.pid}) but CDP port {port} did not respond within {max_wait}s.",
            "port": port,
            "pid": proc.pid
        }

    # Save active port reference
    with open("/tmp/swades_active_browser_port.txt", "w") as f:
        f.write(str(port))

    return {
        "success": True,
        "port": port,
        "pid": proc.pid,
        "ws_url": ws_url,
        "url": url,
        "binary": binary
    }

async def ws_send_receive(ws_url, method, params=None, msg_id=1):
    import websockets
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        await ws.send(json.dumps(msg))
        
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data

async def ws_collect_events(ws_url, enable_methods, listen_seconds=1.5):
    import websockets
    events = []
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        for i, m in enumerate(enable_methods, start=1):
            await ws.send(json.dumps({"id": i, "method": m}))

        end_time = asyncio.get_event_loop().time() + listen_seconds
        while True:
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
                ev = json.loads(raw)
                if "method" in ev:
                    events.append(ev)
            except asyncio.TimeoutError:
                break
            except Exception:
                break
    return events

def cmd_get_console_errors(port=0):
    if not port or port == 0:
        if os.path.exists("/tmp/swades_active_browser_port.txt"):
            try:
                with open("/tmp/swades_active_browser_port.txt") as f:
                    port = int(f.read().strip())
            except Exception:
                port = 9222
        else:
            port = 9222

    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({"success": False, "error": f"Cannot connect to browser CDP on port {port}. Is the browser open?"}))
        return

    try:
        events = asyncio.run(ws_collect_events(ws_url, ["Runtime.enable", "Log.enable", "Console.enable"], listen_seconds=1.2))
        
        errors = []
        for ev in events:
            method = ev.get("method")
            params = ev.get("params", {})
            
            if method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                exc = details.get("exception", {})
                errors.append({
                    "type": "uncaught_exception",
                    "text": details.get("text", "") or exc.get("description", ""),
                    "url": details.get("url", ""),
                    "line": details.get("lineNumber", 0),
                    "column": details.get("columnNumber", 0),
                    "stackTrace": details.get("stackTrace", None)
                })
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                level = entry.get("level", "")
                if level in ["error", "warning"]:
                    errors.append({
                        "type": f"log_{level}",
                        "text": entry.get("text", ""),
                        "source": entry.get("source", ""),
                        "url": entry.get("url", ""),
                        "line": entry.get("lineNumber", 0)
                    })
            elif method == "Console.messageAdded":
                msg = params.get("message", {})
                level = msg.get("level", "")
                if level in ["error", "warning"]:
                    errors.append({
                        "type": f"console_{level}",
                        "text": msg.get("text", ""),
                        "url": msg.get("url", ""),
                        "line": msg.get("line", 0)
                    })

        print(json.dumps({
            "success": True,
            "port": port,
            "count": len(errors),
            "errors": errors
        }, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_get_network_activity(port=0):
    if not port or port == 0:
        if os.path.exists("/tmp/swades_active_browser_port.txt"):
            try:
                with open("/tmp/swades_active_browser_port.txt") as f:
                    port = int(f.read().strip())
            except Exception:
                port = 9222
        else:
            port = 9222

    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({"success": False, "error": f"Cannot connect to browser CDP on port {port}."}))
        return

    try:
        events = asyncio.run(ws_collect_events(ws_url, ["Network.enable"], listen_seconds=1.2))
        failures = []
        for ev in events:
            method = ev.get("method")
            params = ev.get("params", {})
            if method == "Network.responseReceived":
                resp = params.get("response", {})
                status = resp.get("status", 200)
                if status >= 400:
                    failures.append({
                        "type": "http_error",
                        "status": status,
                        "statusText": resp.get("statusText", ""),
                        "url": resp.get("url", ""),
                        "mimeType": resp.get("mimeType", ""),
                    })
            elif method == "Network.loadingFailed":
                failures.append({
                    "type": "loading_failed",
                    "errorText": params.get("errorText", ""),
                    "canceled": params.get("canceled", False),
                    "url": params.get("requestId", "")
                })

        print(json.dumps({
            "success": True,
            "port": port,
            "count": len(failures),
            "failures": failures
        }, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_eval_js(port=0, expression=""):
    if not port or port == 0:
        if os.path.exists("/tmp/swades_active_browser_port.txt"):
            try:
                with open("/tmp/swades_active_browser_port.txt") as f:
                    port = int(f.read().strip())
            except Exception:
                port = 9222
        else:
            port = 9222

    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({"success": False, "error": f"Cannot connect to browser CDP on port {port}."}))
        return

    try:
        res = asyncio.run(ws_send_receive(ws_url, "Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        }))
        result = res.get("result", {})
        if "exceptionDetails" in result:
            print(json.dumps({
                "success": False,
                "error": result["exceptionDetails"].get("text", "JS Exception"),
                "exception": result["exceptionDetails"]
            }, indent=2))
        else:
            print(json.dumps({
                "success": True,
                "result": result.get("result", {}).get("value")
            }, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_query_dom(port=0, selector="*"):
    js_query = f"""
    (() => {{
      const els = Array.from(document.querySelectorAll('{selector}'));
      return els.slice(0, 50).map((el, i) => {{
        const rect = el.getBoundingClientRect();
        return {{
          index: i,
          tag: el.tagName.toLowerCase(),
          id: el.id || null,
          className: el.className || null,
          text: (el.innerText || el.textContent || '').trim().slice(0, 200),
          value: el.value !== undefined ? el.value : null,
          geometry: {{
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            center_x: Math.round(rect.x + rect.width / 2),
            center_y: Math.round(rect.y + rect.height / 2),
            visible: rect.width > 0 && rect.height > 0
          }}
        }};
      }});
    }})()
    """
    cmd_eval_js(port, js_query)

def cmd_navigate(port=0, url=""):
    if not port or port == 0:
        if os.path.exists("/tmp/swades_active_browser_port.txt"):
            try:
                with open("/tmp/swades_active_browser_port.txt") as f:
                    port = int(f.read().strip())
            except Exception:
                port = 9222
        else:
            port = 9222

    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({"success": False, "error": f"Cannot connect to browser CDP on port {port}."}))
        return

    try:
        res = asyncio.run(ws_send_receive(ws_url, "Page.navigate", {"url": url}))
        print(json.dumps({"success": True, "result": res.get("result", {})}, indent=2))
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))

def cmd_targets(port=0):
    if not port or port == 0:
        if os.path.exists("/tmp/swades_active_browser_port.txt"):
            try:
                with open("/tmp/swades_active_browser_port.txt") as f:
                    port = int(f.read().strip())
            except Exception:
                port = 9222
        else:
            port = 9222
    targets = get_cdp_targets(port)
    print(json.dumps({"success": True, "port": port, "targets": targets}, indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: browser_cdp.py [launch [url] [--port=N] [--headless] | console [--port=N] | network [--port=N] | eval <expr> [--port=N] | query <sel> [--port=N] | nav <url> [--port=N] | targets [--port=N]]")
        sys.exit(1)

    cmd = sys.argv[1]
    
    # Extract --port if present
    port = 0
    headless = False
    clean_args = []
    for arg in sys.argv[2:]:
        if arg.startswith("--port="):
            port = int(arg.split("=")[1])
        elif arg == "--headless":
            headless = True
        else:
            clean_args.append(arg)

    if cmd == "launch":
        url = clean_args[0] if clean_args else "about:blank"
        res = launch_browser(url, port, headless)
        print(json.dumps(res, indent=2))
    elif cmd == "console":
        cmd_get_console_errors(port)
    elif cmd == "network":
        cmd_get_network_activity(port)
    elif cmd == "eval":
        expr = clean_args[0] if clean_args else "window.location.href"
        cmd_eval_js(port, expr)
    elif cmd == "query":
        selector = clean_args[0] if clean_args else "*"
        cmd_query_dom(port, selector)
    elif cmd == "nav":
        url = clean_args[0] if clean_args else "about:blank"
        cmd_navigate(port, url)
    elif cmd == "targets":
        cmd_targets(port)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
