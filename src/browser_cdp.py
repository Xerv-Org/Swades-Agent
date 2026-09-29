#!/usr/bin/env python3
"""
browser_cdp.py — High-Performance Playwright & CDP Browser Controller for Swades CUA
Features:
1. Resilient Playwright CDP connection to Chrome on :99 or http://localhost:9222.
2. CRITICAL SAFETY: NEVER calls browser.close() on CDP sessions; disconnects cleanly.
3. Accurate Target Selection: Filters context.pages for real interactive tabs, ignoring 0x0 ad/tracking frames.
4. Fast Navigation: Uses 'domcontentloaded' with explicit state/element polling (no networkidle hangs).
5. Auto-recovery: Retries page evaluations if execution context is destroyed during navigation.
6. Compact DOM Integration: Executes compact_dom.js to extract structured elements + compact DSL.
7. Rich Helper Methods: get_compact_dom, click_element, type_element, click_coordinate, scroll, navigate.
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
import warnings

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPACT_DOM_JS_PATH = os.path.join(SCRIPT_DIR, "compact_dom.js")

# Auto-detect display & authentication
def ensure_display_and_auth():
    if not os.environ.get("DISPLAY"):
        if os.path.exists("/tmp/.X11-unix/X99"):
            os.environ["DISPLAY"] = ":99"
        else:
            os.environ["DISPLAY"] = ":0"

    if "XAUTHORITY" not in os.environ or not os.path.exists(os.environ.get("XAUTHORITY", "")):
        uid = os.getuid()
        mutter_auths = glob.glob(f"/run/user/{uid}/.mutter-Xwaylandauth.*")
        if mutter_auths:
            os.environ["XAUTHORITY"] = sorted(mutter_auths, key=os.path.getmtime)[-1]
        elif os.path.exists(os.path.expanduser("~/.Xauthority")):
            os.environ["XAUTHORITY"] = os.path.expanduser("~/.Xauthority")

    os.environ["GTK_MODULES"] = "gail:atk-bridge"
    os.environ["NO_AT_BRIDGE"] = "0"
    os.environ["QT_ACCESSIBILITY"] = "1"
    os.environ["AX_ENABLED"] = "1"

ensure_display_and_auth()


def find_browser_binary(preference=None):
    if preference:
        p = shutil.which(preference)
        if p: return p

    # 1. System Chromium-based browsers
    candidates = [
        "google-chrome", "google-chrome-stable", "google-chrome-unstable", "google-chrome-beta",
        "chromium", "chromium-browser",
        "brave-browser", "brave",
        "microsoft-edge", "microsoft-edge-stable",
        "vivaldi", "vivaldi-stable", "opera"
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path

    # 2. Playwright Chromium caches
    home = os.path.expanduser("~")
    playwright_chromes = glob.glob(f"{home}/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")
    if playwright_chromes:
        return sorted(playwright_chromes)[-1]

    # 3. Firefox fallback
    firefox_path = shutil.which("firefox")
    if firefox_path:
        return firefox_path

    return None


def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def get_active_port(fallback=9222):
    if os.path.exists("/tmp/swades_active_browser_port.txt"):
        try:
            with open("/tmp/swades_active_browser_port.txt") as f:
                p = int(f.read().strip())
                if p > 0:
                    return p
        except Exception:
            pass
    return fallback


def is_cdp_ready(port=9222, timeout=1.0):
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        req = urllib.request.urlopen(url, timeout=timeout)
        return req.status == 200
    except Exception:
        return False


def get_cdp_targets(port=9222):
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


def get_page_ws_url(port=9222):
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


def ensure_chrome_running(port=9222, url="about:blank", headless=False):
    """Ensure Google Chrome / Chromium is running with remote debugging port enabled."""
    if is_cdp_ready(port, timeout=0.8):
        return True, None

    binary = find_browser_binary()
    if not binary:
        return False, "No compatible Chromium binary found. Run 'npx playwright install chromium'."

    profile_dir = f"/tmp/swades_chrome_profile_{port}"
    os.makedirs(profile_dir, exist_ok=True)

    cmd = [
        binary,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--test-type",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--password-store=basic",
        "--disable-session-crashed-bubble",
        "--noerrdialogs",
        "--hide-crash-restore-bubble",
        "--disable-infobars",
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

    # Poll for CDP readiness
    max_wait = 12
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if is_cdp_ready(port, timeout=0.4):
            with open("/tmp/swades_active_browser_port.txt", "w") as f:
                f.write(str(port))
            return True, proc.pid
        time.sleep(0.2)

    return False, f"Browser started (PID {proc.pid}) but CDP port {port} did not respond within {max_wait}s."


# Embedded fallback for compact_dom.js
DEFAULT_COMPACT_DOM_JS = """
(() => {
  try {
    const INTERACTIVE_SELECTOR = [
      'a[href]', 'button', 'input', 'textarea', 'select', 'details', 'summary',
      '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
      '[role="textbox"]', '[role="combobox"]', '[role="tab"]', '[role="menuitem"]',
      '[role="switch"]', '[role="searchbox"]', '[role="option"]',
      '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])', '[onclick]',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
    ].join(', ');

    const winW = window.innerWidth || document.documentElement.clientWidth || 1280;
    const winH = window.innerHeight || document.documentElement.clientHeight || 800;

    function isElementVisible(el) {
      if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      if (rect.bottom < -500 || rect.top > winH + 1500 || rect.right < -500 || rect.left > winW + 500) return false;
      return true;
    }

    function cleanText(text, maxLen = 120) {
      if (!text) return '';
      const cleaned = text.replace(/\\s+/g, ' ').trim();
      return cleaned.length > maxLen ? cleaned.slice(0, maxLen) + '…' : cleaned;
    }

    function getRole(el) {
      const explicitRole = el.getAttribute('role');
      if (explicitRole) return explicitRole.toLowerCase();
      const tag = el.tagName.toLowerCase();
      if (tag === 'a') return 'link';
      if (tag === 'button') return 'button';
      if (tag === 'textarea') return 'textbox';
      if (tag === 'select') return 'combobox';
      if (tag === 'input') {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        if (['button', 'submit', 'reset'].includes(type)) return 'button';
        if (['checkbox', 'radio'].includes(type)) return type;
        return 'textbox';
      }
      if (/^h[1-6]$/.test(tag)) return 'heading';
      return tag;
    }

    const oldMarkers = document.querySelectorAll('[data-swades-cdp-id]');
    oldMarkers.forEach(el => el.removeAttribute('data-swades-cdp-id'));

    const allMatches = Array.from(document.querySelectorAll(INTERACTIVE_SELECTOR));
    const allDivsSpans = Array.from(document.querySelectorAll('div, span, li, tr'));
    for (const el of allDivsSpans) {
      if (allMatches.includes(el)) continue;
      try {
        const style = window.getComputedStyle(el);
        if (style.cursor === 'pointer' && isElementVisible(el)) {
          allMatches.push(el);
        }
      } catch (e) {}
    }

    const seenElements = new Set();
    const extracted = [];
    let currentIndex = 0;

    for (const el of allMatches) {
      if (!isElementVisible(el)) continue;
      if (seenElements.has(el)) continue;

      const rect = el.getBoundingClientRect();
      const tag = el.tagName.toLowerCase();
      const role = getRole(el);
      
      let text = '';
      if (tag === 'input' || tag === 'textarea') {
        text = el.value || el.placeholder || el.getAttribute('aria-label') || '';
      } else if (tag === 'select') {
        text = el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : '';
      } else {
        text = el.innerText || el.textContent || '';
      }

      text = cleanText(text);
      if (!text && !['input', 'select', 'textarea'].includes(tag) && !el.getAttribute('aria-label') && !el.getAttribute('title')) {
        continue;
      }

      el.setAttribute('data-swades-cdp-id', String(currentIndex));
      seenElements.add(el);

      const elemInfo = {
        index: currentIndex,
        tag: tag,
        role: role,
        type: el.getAttribute('type') || null,
        text: text,
        value: el.value !== undefined ? String(el.value) : null,
        placeholder: el.getAttribute('placeholder') || null,
        ariaLabel: el.getAttribute('aria-label') || null,
        id: el.id || null,
        name: el.getAttribute('name') || null,
        href: el.getAttribute('href') || null,
        disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
        checked: el.checked || el.getAttribute('aria-checked') === 'true',
        bounds: {
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          center_x: Math.round(rect.x + rect.width / 2),
          center_y: Math.round(rect.y + rect.height / 2)
        },
        inViewport: rect.top >= 0 && rect.top <= winH && rect.left >= 0 && rect.left <= winW
      };

      extracted.push(elemInfo);
      currentIndex++;
      if (extracted.length >= 150) break;
    }

    const dslLines = [];
    for (const item of extracted) {
      const parts = [`[${item.index}]`, `<${item.tag}`];
      if (item.type) parts.push(`type="${item.type}"`);
      if (item.role && item.role !== item.tag) parts.push(`role="${item.role}"`);
      parts[parts.length - 1] += '>';

      if (item.text) parts.push(`"${item.text}"`);
      if (item.placeholder) parts.push(`placeholder="${cleanText(item.placeholder, 40)}"`);
      if (item.value && item.value !== item.text) parts.push(`value="${cleanText(item.value, 40)}"`);
      if (item.href) parts.push(`href="${item.href.slice(0, 60)}"`);
      if (item.checked) parts.push(`[checked]`);
      if (item.disabled) parts.push(`[disabled]`);

      parts.push(`(x:${item.bounds.center_x}, y:${item.bounds.center_y})`);
      dslLines.push(parts.join(' '));
    }

    return {
      success: true,
      url: window.location.href,
      title: document.title || '',
      viewport: { width: winW, height: winH },
      scroll: {
        x: Math.round(window.scrollX || 0),
        y: Math.round(window.scrollY || 0),
        scrollWidth: Math.round(document.documentElement.scrollWidth || winW),
        scrollHeight: Math.round(document.documentElement.scrollHeight || winH)
      },
      count: extracted.length,
      elements: extracted,
      compact_dsl: dslLines.join('\\n')
    };
  } catch (err) {
    return { success: false, error: String(err && err.stack ? err.stack : err) };
  }
})();
"""


class BrowserCDP:
    """
    Persistent and resilient Playwright CDP Controller for Chrome / Chromium.
    CRITICAL: Never calls browser.close() on CDP sessions to prevent destroying Chrome.
    """

    def __init__(self, port=None, cdp_url=None):
        self.port = port or get_active_port(9222)
        self.cdp_url = cdp_url or f"http://127.0.0.1:{self.port}"
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._cached_elements = []

    def connect(self, auto_launch=True):
        """Connects over CDP to the remote Chrome instance."""
        from playwright.sync_api import sync_playwright

        if auto_launch and not is_cdp_ready(self.port):
            ok, err = ensure_chrome_running(self.port)
            if not ok:
                raise RuntimeError(f"Failed to launch Chrome on port {self.port}: {err}")

        if not self._playwright:
            self._playwright = sync_playwright().start()

        if not self._browser or not self._browser.is_connected():
            # Connect over CDP with timeout
            self._browser = self._playwright.chromium.connect_over_cdp(self.cdp_url, timeout=10000)
            self._context = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
            self._page = None

        return self

    def disconnect(self):
        """
        Disconnects client session safely.
        CRITICAL: NEVER CALL browser.close() on CDP connections!
        """
        try:
            if self._browser and self._browser.is_connected():
                # Disconnects CDP client connection without terminating the Chrome process
                self._browser.disconnect()
        except Exception:
            pass
        finally:
            self._browser = None
            self._context = None
            self._page = None
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def get_active_page(self, force_refresh=False):
        """
        Target Selection: Filters context.pages to find the real interactive tab
        with positive viewport dimensions and non-empty DOM content, ignoring
        0x0 background tracking/ad iframes.
        """
        self.connect()

        if self._page and not force_refresh:
            try:
                if not self._page.is_closed():
                    return self._page
            except Exception:
                pass

        pages = self._context.pages if self._context else []
        candidates = []

        for pg in pages:
            try:
                if pg.is_closed():
                    continue

                url = pg.url or ""
                # Ignore system & devtools internal pages
                if any(url.startswith(prefix) for prefix in [
                    "chrome://", "chrome-extension://", "devtools://", "edge://", "view-source:"
                ]):
                    continue

                # Query page dimensions and DOM content
                info = pg.evaluate("""() => {
                    const winW = window.innerWidth || 0;
                    const winH = window.innerHeight || 0;
                    const bodyText = (document.body ? (document.body.innerText || '') : '').trim();
                    const elCount = document.querySelectorAll('*').length;
                    const inputCount = document.querySelectorAll('input, button, a, select, textarea').length;
                    return {
                        winW,
                        winH,
                        bodyLength: bodyText.length,
                        elCount,
                        inputCount,
                        title: document.title || '',
                        url: window.location.href,
                        hasBody: !!document.body
                    };
                }""")

                # Strict check: positive viewport dimensions (> 0)
                winW = info.get("winW", 0)
                winH = info.get("winH", 0)
                if winW <= 0 or winH <= 0:
                    continue

                body_len = info.get("bodyLength", 0)
                el_count = info.get("elCount", 0)
                input_count = info.get("inputCount", 0)
                has_body = info.get("hasBody", False)

                # Ignore 0x0 or empty tracking iframes
                if not has_body and el_count < 2:
                    continue

                score = 100
                if body_len > 20:
                    score += min(body_len, 500)
                if input_count > 0:
                    score += input_count * 10
                if not url.startswith("about:blank"):
                    score += 50
                if info.get("title"):
                    score += 20

                candidates.append((score, pg))
            except Exception:
                continue

        if candidates:
            # Pick the candidate with the highest interaction/content score
            candidates.sort(key=lambda c: c[0], reverse=True)
            chosen_page = candidates[0][1]
            try:
                chosen_page.bring_to_front()
            except Exception:
                pass
            self._page = chosen_page
            return self._page

        # Fallback to existing page or create new
        if pages:
            self._page = pages[-1]
            try:
                self._page.bring_to_front()
            except Exception:
                pass
            return self._page

        self._page = self._context.new_page()
        return self._page

    def safe_evaluate(self, expression_or_script, *args, max_retries=4, retry_delay=0.3):
        """
        Evaluates JavaScript with auto-recovery and retry logic against
        'Execution context was destroyed' or frame detachment during navigation.
        """
        page = self.get_active_page()
        last_error = None

        for attempt in range(max_retries):
            try:
                return page.evaluate(expression_or_script, *args)
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Auto-recovery for execution context destruction during navigation
                if any(phrase in err_str for phrase in [
                    "Execution context was destroyed",
                    "Target closed",
                    "frame was detached",
                    "Cannot find context with specified id",
                    "Navigating frame was detached"
                ]):
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        try:
                            page = self.get_active_page(force_refresh=True)
                            page.wait_for_load_state("domcontentloaded", timeout=3000)
                        except Exception:
                            pass
                        continue
                raise last_error

        raise last_error

    def _wait_for_page_ready(self, page, timeout_sec=10.0):
        """
        Explicit element and state wait loop (fast and non-hanging compared to networkidle).
        """
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            try:
                state = page.evaluate("""() => {
                    return {
                        readyState: document.readyState,
                        hasBody: !!document.body,
                        bodyLength: document.body ? (document.body.innerText || '').length : 0,
                        elementCount: document.querySelectorAll('*').length
                    };
                }""")
                if state.get("readyState") in ["interactive", "complete"] and state.get("hasBody") and state.get("elementCount", 0) > 0:
                    time.sleep(0.15)  # brief settle for micro-animations
                    return True
            except Exception:
                pass
            time.sleep(0.2)
        return False

    def navigate(self, url: str, wait_timeout_ms: int = 15000) -> dict:
        """
        Navigates to URL using 'domcontentloaded' with explicit state wait loops.
        Never uses 'networkidle' which hangs indefinitely on WebSockets/SPAs.
        """
        if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("about:") and not url.startswith("file://"):
            url = "https://" + url

        page = self.get_active_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=wait_timeout_ms)
        except Exception as e:
            # Navigation might have triggered client-side rendering or redirect
            pass

        self._wait_for_page_ready(page, timeout_sec=min(wait_timeout_ms / 1000.0, 8.0))

        title = ""
        final_url = url
        try:
            title = page.title()
            final_url = page.url
        except Exception:
            pass

        return {
            "success": True,
            "url": final_url,
            "title": title
        }

    def get_compact_dom(self) -> dict:
        """
        Executes compact_dom.js in the active tab context.
        Returns structured element objects, metadata, and the compact DSL string.
        """
        raw_script = None
        if os.path.exists(COMPACT_DOM_JS_PATH):
            try:
                with open(COMPACT_DOM_JS_PATH, "r", encoding="utf-8") as f:
                    raw_script = f.read()
            except Exception:
                raw_script = None

        if not raw_script:
            raw_script = DEFAULT_COMPACT_DOM_JS

        import re
        sanitized_script = re.sub(r'export\s*\{[^}]*\}\s*;?', '', raw_script)
        sanitized_script = re.sub(r'^\s*export\s+default\s+.*$', '', sanitized_script, flags=re.MULTILINE)
        sanitized_script = re.sub(r'^\s*export\s+(function|const|let|var|class)\s+', r'\1 ', sanitized_script, flags=re.MULTILINE)

        wrapper_script = f"""
        (() => {{
            {sanitized_script}
            try {{
                if (typeof getCompactDom === 'function') {{
                    const out = getCompactDom();
                    const winW = window.innerWidth || 1280;
                    const winH = window.innerHeight || 800;
                    return {{
                        success: true,
                        url: window.location.href,
                        title: document.title || '',
                        viewport: {{ width: winW, height: winH }},
                        scroll: {{
                            x: Math.round(window.scrollX || 0),
                            y: Math.round(window.scrollY || 0),
                            scrollWidth: Math.round(document.documentElement ? document.documentElement.scrollWidth : winW),
                            scrollHeight: Math.round(document.documentElement ? document.documentElement.scrollHeight : winH)
                        }},
                        count: out.elements ? out.elements.length : 0,
                        elements: out.elements || [],
                        compact_dsl: out.dsl || out.compact_dsl || '',
                        dsl: out.dsl || out.compact_dsl || ''
                    }};
                }}
            }} catch (err) {{
                return {{ success: false, error: String(err && err.stack ? err.stack : err) }};
            }}
            return {{ success: false, error: "Perception script failed to initialize getCompactDom" }};
        }})()
        """

        page = self.get_active_page()
        result = self.safe_evaluate(wrapper_script)

        if isinstance(result, dict) and result.get("success"):
            self._cached_elements = result.get("elements", [])
        return result

    def click_element(self, index: int) -> dict:
        """Clicks an element identified by its unique numeric index in compact DOM."""
        page = self.get_active_page()

        # Try to locate by data-swades-id or data-swades-cdp-id attribute
        for attr in ["data-swades-id", "data-swades-cdp-id"]:
            try:
                locator = page.locator(f"[{attr}='{index}']")
                if locator.count() > 0:
                    target = locator.first
                    target.scroll_into_view_if_needed(timeout=1500)
                    target.click(timeout=3000)
                    time.sleep(0.2)
                    return {
                        "success": True,
                        "clicked_index": index,
                        "method": f"locator_{attr}"
                    }
            except Exception:
                pass

        # Fallback 1: check cached element coordinates
        target_elem = None
        for el in self._cached_elements:
            if el.get("index") == index:
                target_elem = el
                break

        if target_elem:
            if "center" in target_elem and isinstance(target_elem["center"], dict):
                cx = target_elem["center"].get("x")
                cy = target_elem["center"].get("y")
                if cx is not None and cy is not None:
                    return self.click_coordinate(cx, cy)
            elif "bounds" in target_elem and isinstance(target_elem["bounds"], dict):
                cx = target_elem["bounds"].get("center_x")
                cy = target_elem["bounds"].get("center_y")
                if cx is not None and cy is not None:
                    return self.click_coordinate(cx, cy)
            elif "bbox" in target_elem and isinstance(target_elem["bbox"], list) and len(target_elem["bbox"]) >= 4:
                cx = target_elem["bbox"][0] + target_elem["bbox"][2] // 2
                cy = target_elem["bbox"][1] + target_elem["bbox"][3] // 2
                return self.click_coordinate(cx, cy)

        # Fallback 2: evaluate JS click directly
        try:
            click_res = self.safe_evaluate("""(targetIndex) => {
                const el = document.querySelector(`[data-swades-id="${targetIndex}"], [data-swades-cdp-id="${targetIndex}"]`);
                if (!el) return { success: false, error: 'Element not found by index in DOM' };
                el.scrollIntoView({ block: 'center', inline: 'center' });
                el.click();
                return { success: true };
            }""", index)
            if click_res.get("success"):
                time.sleep(0.2)
                return { "success": True, "clicked_index": index, "method": "js_eval" }
        except Exception as e:
            return { "success": False, "error": f"Failed to click element {index}: {e}" }

        return { "success": False, "error": f"Element with index {index} not found in DOM or cache." }

    def type_element(self, index: int, text: str, clear: bool = True, press_enter: bool = False) -> dict:
        """Types text into an input/textarea identified by index."""
        page = self.get_active_page()

        for attr in ["data-swades-id", "data-swades-cdp-id"]:
            try:
                locator = page.locator(f"[{attr}='{index}']")
                if locator.count() > 0:
                    target = locator.first
                    target.scroll_into_view_if_needed(timeout=1500)
                    target.click(timeout=2000)
                    
                    if clear:
                        try:
                            target.fill("")
                        except Exception:
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Backspace")
                    
                    target.type(text, delay=20)
                    if press_enter:
                        page.keyboard.press("Enter")
                    
                    time.sleep(0.2)
                    return {
                        "success": True,
                        "typed_index": index,
                        "text": text,
                        "cleared": clear,
                        "pressed_enter": press_enter,
                        "method": f"locator_{attr}"
                    }
            except Exception:
                pass

        # Fallback JS fill/type
        try:
            res = self.safe_evaluate("""({ targetIndex, text, clear, pressEnter }) => {
                const el = document.querySelector(`[data-swades-id="${targetIndex}"], [data-swades-cdp-id="${targetIndex}"]`);
                if (!el) return { success: false, error: 'Element not found by index in DOM' };
                el.scrollIntoView({ block: 'center', inline: 'center' });
                el.focus();
                if (clear) el.value = '';
                el.value = (clear ? '' : el.value) + text;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (pressEnter && el.form) {
                    el.form.dispatchEvent(new Event('submit', { bubbles: true }));
                }
                return { success: true };
            }""", { "targetIndex": index, "text": text, "clear": clear, "pressEnter": press_enter })

            if res.get("success"):
                time.sleep(0.2)
                return { "success": True, "typed_index": index, "text": text, "method": "js_eval" }
        except Exception as e:
            return { "success": False, "error": f"Failed to type in element {index}: {e}" }

        return { "success": False, "error": f"Input element with index {index} not found." }

    def click_coordinate(self, x: int, y: int) -> dict:
        """Clicks at viewport coordinates (x, y)."""
        page = self.get_active_page()
        try:
            page.mouse.move(x, y)
            page.mouse.click(x, y)
            time.sleep(0.15)
            return { "success": True, "x": x, "y": y }
        except Exception as e:
            return { "success": False, "error": f"Failed clicking coordinate ({x}, {y}): {e}" }

    def scroll(self, direction: str = "down", amount: int = 500) -> dict:
        """Scrolls the active webpage."""
        page = self.get_active_page()
        dir_clean = direction.lower().strip()

        try:
            if dir_clean == "down":
                self.safe_evaluate(f"window.scrollBy(0, {amount})")
            elif dir_clean == "up":
                self.safe_evaluate(f"window.scrollBy(0, {-amount})")
            elif dir_clean == "top":
                self.safe_evaluate("window.scrollTo(0, 0)")
            elif dir_clean == "bottom":
                self.safe_evaluate("window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight)")
            elif dir_clean == "left":
                self.safe_evaluate(f"window.scrollBy({-amount}, 0)")
            elif dir_clean == "right":
                self.safe_evaluate(f"window.scrollBy({amount}, 0)")
            else:
                self.safe_evaluate(f"window.scrollBy(0, {amount})")

            time.sleep(0.15)
            scroll_pos = self.safe_evaluate("""() => ({
                x: Math.round(window.scrollX || 0),
                y: Math.round(window.scrollY || 0),
                scrollHeight: Math.round(document.documentElement.scrollHeight || 0)
            })""")
            return {
                "success": True,
                "direction": dir_clean,
                "amount": amount,
                "scroll": scroll_pos
            }
        except Exception as e:
            return { "success": False, "error": f"Scroll failed: {e}" }


# Global shared BrowserCDP instance for functional calls
_GLOBAL_BROWSER_CDP = None

def get_browser_instance(port=None):
    global _GLOBAL_BROWSER_CDP
    port = port or get_active_port(9222)
    if _GLOBAL_BROWSER_CDP is None or _GLOBAL_BROWSER_CDP.port != port:
        _GLOBAL_BROWSER_CDP = BrowserCDP(port=port)
    return _GLOBAL_BROWSER_CDP


# Convenience top-level functions
def get_compact_dom(port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.get_compact_dom()

def click_element(index: int, port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.click_element(index)

def type_element(index: int, text: str, clear: bool = True, press_enter: bool = False, port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.type_element(index, text, clear=clear, press_enter=press_enter)

def click_coordinate(x: int, y: int, port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.click_coordinate(x, y)

def scroll(direction: str = "down", amount: int = 500, port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.scroll(direction=direction, amount=amount)

def navigate(url: str, port=None):
    with BrowserCDP(port=port) as cdp:
        return cdp.navigate(url)


# Legacy raw CDP websocket helpers for 100% backward compatibility
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
    port = port or get_active_port(9222)
    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({
            "success": False,
            "port": port,
            "notice": f"No active browser remote debugging listener found on port {port}."
        }))
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
    port = port or get_active_port(9222)
    ws_url = get_page_ws_url(port)
    if not ws_url:
        print(json.dumps({
            "success": False,
            "port": port,
            "notice": f"No active browser remote debugging listener found on port {port}."
        }))
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


def launch_browser(url="about:blank", port=0, headless=False):
    if not port or port == 0:
        port = 9222
    ok, res = ensure_chrome_running(port, url=url, headless=headless)
    if ok:
        ws_url = get_page_ws_url(port)
        return {
            "success": True,
            "port": port,
            "pid": res,
            "ws_url": ws_url,
            "url": url
        }
    return {
        "success": False,
        "port": port,
        "error": res
    }


def cmd_eval_js(port=0, expression=""):
    try:
        with BrowserCDP(port=port or get_active_port(9222)) as cdp:
            res = cdp.safe_evaluate(expression)
            print(json.dumps({"success": True, "result": res}, indent=2))
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
    port = port or get_active_port(9222)
    res = navigate(url, port=port)
    print(json.dumps(res, indent=2))


def cmd_targets(port=0):
    port = port or get_active_port(9222)
    targets = get_cdp_targets(port)
    print(json.dumps({"success": True, "port": port, "targets": targets}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: browser_cdp.py [launch|dom|click|type|scroll|coord|nav|console|network|eval|query|targets] [args...] [--port=N] [--headless]")
        sys.exit(1)

    cmd = sys.argv[1]
    
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
    elif cmd in ["dom", "compact_dom", "get_compact_dom"]:
        res = get_compact_dom(port=port)
        print(json.dumps(res, indent=2))
    elif cmd == "click":
        if not clean_args:
            print(json.dumps({"success": False, "error": "Index required: browser_cdp.py click <index>"}))
            sys.exit(1)
        if "," in clean_args[0]:
            parts = clean_args[0].split(",")
            res = click_coordinate(int(parts[0]), int(parts[1]), port=port)
        else:
            res = click_element(int(clean_args[0]), port=port)
        print(json.dumps(res, indent=2))
    elif cmd == "type":
        if len(clean_args) < 2:
            print(json.dumps({"success": False, "error": "Usage: browser_cdp.py type <index> <text>"}))
            sys.exit(1)
        idx = int(clean_args[0])
        text = clean_args[1]
        enter = "--enter" in sys.argv
        res = type_element(idx, text, clear=True, press_enter=enter, port=port)
        print(json.dumps(res, indent=2))
    elif cmd == "coord":
        if len(clean_args) < 2:
            print(json.dumps({"success": False, "error": "Usage: browser_cdp.py coord <x> <y>"}))
            sys.exit(1)
        res = click_coordinate(int(clean_args[0]), int(clean_args[1]), port=port)
        print(json.dumps(res, indent=2))
    elif cmd == "scroll":
        direction = clean_args[0] if clean_args else "down"
        amount = int(clean_args[1]) if len(clean_args) > 1 else 500
        res = scroll(direction=direction, amount=amount, port=port)
        print(json.dumps(res, indent=2))
    elif cmd in ["nav", "navigate"]:
        url = clean_args[0] if clean_args else "about:blank"
        cmd_navigate(port, url)
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
    elif cmd == "targets":
        cmd_targets(port)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
