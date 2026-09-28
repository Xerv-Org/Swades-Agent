#!/usr/bin/env python3
"""
native_cua_engine.py — Unified Native Playwright & Desktop CUA Engine
Provides direct Playwright browser automation (navigate, snapshot, click, type, scroll)
and lightweight Linux desktop window/input controls via AT-SPI2 / xdotool / wmctrl.
"""

import sys
import os
import json
import time
import subprocess
import urllib.request
import warnings

warnings.filterwarnings("ignore")

if "/usr/lib/python3/dist-packages" not in sys.path:
    sys.path.append("/usr/lib/python3/dist-packages")

def ensure_env():
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":99" if os.path.exists("/tmp/.X11-unix/X99") else ":0"
    os.environ["GTK_MODULES"] = "gail:atk-bridge"
    os.environ["NO_AT_BRIDGE"] = "0"
    os.environ["QT_ACCESSIBILITY"] = "1"
    os.environ["AX_ENABLED"] = "1"

ensure_env()

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

def ensure_chrome():
    """Ensure Google Chrome / Chromium is running with remote debugging port enabled."""
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=0.8)
        return True
    except Exception:
        pass

    chrome_bin = None
    for b in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
        res = subprocess.run(["which", b], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0 and res.stdout.strip():
            chrome_bin = res.stdout.strip()
            break

    if not chrome_bin:
        return False

    cmd = [
        chrome_bin,
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--password-store=basic",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        "--hide-crash-restore-bubble",
        "--disable-infobars",
        f"--remote-debugging-port={CDP_PORT}",
        "--remote-allow-origins=*",
        "--user-data-dir=/tmp/chrome_profile",
        "about:blank"
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    for _ in range(25):
        try:
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=0.4)
            return True
        except Exception:
            time.sleep(0.15)
    return False


def get_playwright_page(p):
    """Connects over CDP and returns the active or newest page."""
    ensure_chrome()
    browser = p.chromium.connect_over_cdp(CDP_URL, timeout=4000)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return browser, page


def browser_navigate(url: str):
    """Navigates to URL using Playwright."""
    target_url = url.strip()
    if not target_url.startswith(("http://", "https://", "file://", "about:")):
        target_url = f"https://{target_url}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            page.goto(target_url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(0.5)
            title = page.title()
            final_url = page.url
            browser.close()
            return {"success": True, "url": final_url, "title": title}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_snapshot():
    """Extracts structured content, search results, and interactive elements using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            title = page.title()
            url = page.url

            # Extract main content text (excluding boilerplate header navigation)
            main_text = ""
            for selector in ['#rso', '[role="main"]', 'main', 'article', '#main', 'body']:
                loc = page.locator(selector).first
                try:
                    if loc.count() > 0:
                        txt = loc.inner_text(timeout=1000).strip()
                        if len(txt) > 40:
                            lines = [l.strip() for l in txt.split("\n") if l.strip()]
                            clean_lines = [l for l in lines if l not in [
                                "Web results", "Search Results", "AI Mode", "All", 
                                "Images", "Shopping", "Videos", "News", "Forums", "More", "Tools"
                            ]]
                            main_text = "\n".join(clean_lines)
                            break
                except Exception:
                    pass

            # Structured search results extraction (Google / DuckDuckGo / Bing cards)
            search_cards = []
            try:
                card_data = page.evaluate("""() => {
                    const cards = [];
                    // Google search cards
                    const gCards = document.querySelectorAll('#rso .g');
                    for (const el of gCards) {
                        const h = el.querySelector('h3');
                        const a = el.querySelector('a[href]');
                        const txt = (el.innerText || '').trim();
                        if (h && txt) {
                            cards.push({
                                title: h.innerText.trim(),
                                snippet: txt.slice(0, 300).replace(/\\n+/g, ' ')
                            });
                        }
                    }
                    return cards.slice(0, 5);
                }""")
                if card_data:
                    search_cards = card_data
            except Exception:
                pass

            # Key interactive elements
            interactive_items = []
            try:
                interactive_items = page.evaluate("""() => {
                    const items = [];
                    const els = document.querySelectorAll('h1, h2, h3, a[href], button');
                    const seen = new Set();
                    for (const el of els) {
                        const txt = (el.innerText || el.textContent || '').trim();
                        if (txt && txt.length > 2 && !seen.has(txt)) {
                            seen.add(txt);
                            const tag = el.tagName.toLowerCase();
                            const role = el.getAttribute('role') || (tag.startsWith('h') ? 'heading' : (tag === 'a' ? 'link' : tag));
                            items.push({
                                role: role,
                                name: txt.slice(0, 80)
                            });
                            if (items.length >= 20) break;
                        }
                    }
                    return items;
                }""")
            except Exception:
                pass

            browser.close()

            # Also include desktop windows context
            desktop_wins = get_desktop_windows()

            return {
                "browser_context": {
                    "role": "WebArea",
                    "title": title,
                    "url": url,
                    "content_summary": main_text[:1400] if main_text else "",
                    "search_results": search_cards if search_cards else None,
                    "elements": interactive_items[:15]
                },
                "desktop_context": desktop_wins
            }
    except Exception as e:
        return {
            "browser_context": {"status": f"CDP Offline: {str(e)}"},
            "desktop_context": get_desktop_windows()
        }


def browser_click(target: str):
    """Clicks an element by role, text, or selector using Playwright with fuzzy matching."""
    try:
        import re
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            clicked = False
            last_err = None

            clean_target = re.sub(r"[™®©'\"\[\]]", "", target).strip()
            words = [w for w in clean_target.split() if len(w) > 2]
            first_keywords = " ".join(words[:2]) if len(words) >= 2 else clean_target

            # 1. Try get_by_role (button or link)
            for role in ["button", "link"]:
                try:
                    loc = page.get_by_role(role, name=clean_target, exact=False).first
                    if loc.count() > 0:
                        loc.click(timeout=4000)
                        clicked = True
                        break
                except Exception as e:
                    last_err = e

            # 2. Try get_by_text with clean target
            if not clicked:
                try:
                    loc = page.get_by_text(clean_target, exact=False).first
                    if loc.count() > 0:
                        loc.click(timeout=4000)
                        clicked = True
                except Exception as e:
                    last_err = e

            # 3. Try locator with regex keywords (e.g. "AMD Instinct")
            if not clicked and first_keywords:
                try:
                    pattern = re.compile(re.escape(first_keywords), re.IGNORECASE)
                    loc = page.locator("a, button, [role='button'], h3").filter(has_text=pattern).first
                    if loc.count() > 0:
                        loc.click(timeout=4000)
                        clicked = True
                except Exception as e:
                    last_err = e

            # 4. Try direct locator
            if not clicked:
                try:
                    loc = page.locator(target).first
                    if loc.count() > 0:
                        loc.click(timeout=4000)
                        clicked = True
                except Exception as e:
                    last_err = e

            if clicked:
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=4000)
                except Exception:
                    pass
                time.sleep(0.5)
                browser.close()
                return {"success": True, "action": "click", "target": target}

            browser.close()
            return {"success": False, "error": f"Element '{target}' not found: {str(last_err)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_type(target: str, text: str, press_enter: bool = False):
    """Types text into an element using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            typed = False
            last_err = None

            # Try by role, placeholder, or locator
            for try_func in [
                lambda: page.get_by_placeholder(target, exact=False).first,
                lambda: page.get_by_role("textbox", name=target, exact=False).first,
                lambda: page.locator(target).first,
                lambda: page.locator("textarea:visible, input[type='text']:visible, input[name='q']:visible, input:not([type='hidden']):visible").first
            ]:
                try:
                    loc = try_func()
                    if loc.count() > 0:
                        loc.fill(text, timeout=3000)
                        if press_enter:
                            loc.press("Enter")
                        typed = True
                        break
                except Exception as e:
                    last_err = e

            browser.close()
            if typed:
                return {"success": True, "action": "type", "text": text, "enter": press_enter}
            return {"success": False, "error": f"Target '{target}' not found for typing: {str(last_err)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def browser_scroll(direction: str = "down", amount: int = 500):
    """Scrolls webpage using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            delta = amount if direction == "down" else -amount
            page.evaluate(f"window.scrollBy(0, {delta})")
            time.sleep(0.3)
            browser.close()
            return {"success": True, "action": "scroll", "direction": direction, "amount": amount}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_desktop_windows():
    """Lists desktop application windows via wmctrl / xdotool."""
    windows = []
    try:
        res = subprocess.run(["wmctrl", "-l", "-p"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            for line in res.stdout.strip().split("\n"):
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    win_id, desktop, pid, host, title = parts[0], parts[1], parts[2], parts[3], parts[4]
                    if not any(ign in title.lower() for ign in ["xfwm4", "xfce4-panel", "desktop"]):
                        windows.append({
                            "window_id": win_id,
                            "pid": pid,
                            "title": title
                        })
    except Exception:
        pass
    return windows


def desktop_window_control(action: str, target: str = None):
    """Controls desktop windows: list, focus, or close."""
    if action == "list":
        return get_desktop_windows()

    if action == "focus" and target:
        subprocess.run(["wmctrl", "-a", target], check=False)
        return {"success": True, "action": "focus", "target": target}

    if action == "close" and target:
        if target.lower() in ["all", "*"]:
            wins = get_desktop_windows()
            closed = []
            for w in wins:
                title = w["title"]
                if not any(ign in title.lower() for ign in ["swades", "xfce", "panel", "desktop"]):
                    subprocess.run(["wmctrl", "-c", title], check=False)
                    closed.append(title)
            return {"success": True, "action": "close_all", "closed": closed}
        else:
            subprocess.run(["wmctrl", "-c", target], check=False)
            return {"success": True, "action": "close", "target": target}

    return {"error": f"Unknown window control action '{action}'"}


def desktop_interact(action: str, x: int = None, y: int = None, keys: str = None):
    """Interacts with native desktop apps using xdotool."""
    if action == "click" and x is not None and y is not None:
        subprocess.run(["xdotool", "mousemove", str(x), str(y), "click", "1"], check=False)
        return {"success": True, "action": "click", "coords": [x, y]}

    if action == "type" and keys:
        subprocess.run(["xdotool", "type", "--delay", "12", keys], check=False)
        return {"success": True, "action": "type", "keys": keys}

    if action == "key" and keys:
        subprocess.run(["xdotool", "key", keys], check=False)
        return {"success": True, "action": "key", "keys": keys}

    return {"error": f"Invalid desktop interact arguments: action={action}"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps(browser_snapshot(), indent=2))
        return

    cmd = sys.argv[1].lower()

    if cmd in ["snapshot", "read_screen_tree", "dump"]:
        print(json.dumps(browser_snapshot(), indent=2))
    elif cmd in ["navigate", "goto", "open"]:
        url = sys.argv[2] if len(sys.argv) > 2 else "https://google.com"
        print(json.dumps(browser_navigate(url), indent=2))
    elif cmd in ["click"]:
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(browser_click(target), indent=2))
    elif cmd in ["type", "fill"]:
        target = sys.argv[2] if len(sys.argv) > 2 else ""
        text = sys.argv[3] if len(sys.argv) > 3 else ""
        press_enter = ("--enter" in sys.argv or "-e" in sys.argv)
        print(json.dumps(browser_type(target, text, press_enter), indent=2))
    elif cmd in ["scroll"]:
        direction = sys.argv[2] if len(sys.argv) > 2 else "down"
        amount = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        print(json.dumps(browser_scroll(direction, amount), indent=2))
    elif cmd in ["windows", "window_control"]:
        action = sys.argv[2] if len(sys.argv) > 2 else "list"
        target = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(desktop_window_control(action, target), indent=2))
    elif cmd in ["interact", "desktop_interact"]:
        action = sys.argv[2] if len(sys.argv) > 2 else "click"
        if action == "click":
            x = int(sys.argv[3]) if len(sys.argv) > 3 else 0
            y = int(sys.argv[4]) if len(sys.argv) > 4 else 0
            print(json.dumps(desktop_interact("click", x=x, y=y), indent=2))
        elif action in ["type", "key"]:
            keys = sys.argv[3] if len(sys.argv) > 3 else ""
            print(json.dumps(desktop_interact(action, keys=keys), indent=2))
    else:
        print(json.dumps({"error": f"Unknown command '{cmd}'"}))


if __name__ == "__main__":
    main()
