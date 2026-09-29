#!/usr/bin/env python3
"""
native_cua_engine.py — Unified Native Playwright & Desktop CUA Engine with Compact Indexed DOM
Features:
1. Closed-world compact indexed DOM representation ([@0], [@1], ...).
2. Closed-world indexed tool actions:
   - browser_click(index: int)
   - browser_type(index: int, text: str, clear: bool = True, submit: bool = False)
   - browser_select(index: int, value: str)
   - browser_scroll(direction: str, amount: int = 500)
   - browser_navigate(url: str)
   - browser_wait(seconds: float)
   - browser_snapshot()
3. Multi-Tier Action Dispatch:
   - Tier 1: Direct DOM click via [data-swades-id="<index>"]
   - Tier 2: Synthetic framework event dispatcher (pointerdown, mousedown, focus, pointerup, mouseup, click)
   - Tier 3: CDP coordinate click via Input.dispatchMouseEvent / Playwright mouse at exact center (x, y)
4. Automatic Inline Observation Return:
   - Every mutating tool call (click, type, select, navigate, scroll, wait) runs perception after 300-500ms settlement and returns updated compact DOM.
"""

import sys
import os
import re
import json
import time
import shutil
import glob
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

def find_browser_binary(preference=None):
    if preference:
        p = shutil.which(preference)
        if p: return p

    candidates = [
        "google-chrome", "google-chrome-stable", "google-chrome-unstable", "google-chrome-beta",
        "chromium", "chromium-browser",
        "brave-browser", "brave",
        "microsoft-edge", "microsoft-edge-stable",
        "vivaldi", "opera"
    ]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path

    home = os.path.expanduser("~")
    playwright_chromes = glob.glob(f"{home}/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")
    if playwright_chromes:
        return sorted(playwright_chromes)[-1]

    firefox_path = shutil.which("firefox")
    if firefox_path:
        return firefox_path

    return None


def ensure_chrome():
    """Ensure Google Chrome / Chromium is running with remote debugging port enabled."""
    try:
        urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=0.6)
        return True
    except Exception:
        pass

    chrome_bin = find_browser_binary()
    if not chrome_bin:
        return False

    cmd = [
        chrome_bin,
        "--no-sandbox",
        "--test-type",
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
            urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=0.3)
            return True
        except Exception:
            time.sleep(0.12)
    return False


def get_playwright_page(p):
    """Connects over CDP or launches Playwright Chromium and returns the active page."""
    ensure_chrome()
    browser = None
    try:
        browser = p.chromium.connect_over_cdp(CDP_URL, timeout=3000)
    except Exception:
        browser = p.chromium.launch(headless=False)

    context = browser.contexts[0] if browser.contexts else browser.new_context()
    
    best_page = None
    best_score = -1

    for pg in context.pages:
        url = pg.url or ""
        if url.startswith(("chrome://", "devtools://", "chrome-extension://")):
            continue
        try:
            title = pg.title() or ""
            # Filter obvious ad/sync pixels
            if any(bad in title.lower() for bad in ["sync pixel", "tracker", "ad banner", "about:blank"]):
                continue
            
            # Score by button/input density and viewport
            btn_count = pg.locator("button, input, a, select").count()
            score = btn_count * 10 + (100 if "richup" in url.lower() or "google" in url.lower() else 0)
            if score > best_score:
                best_score = score
                best_page = pg
        except Exception:
            continue

    if not best_page:
        for pg in context.pages:
            url = pg.url or ""
            if url and not url.startswith("chrome://") and not url.startswith("about:"):
                best_page = pg
                break

    target_page = best_page or (context.pages[0] if context.pages else context.new_page())

    try:
        target_page.bring_to_front()
    except Exception:
        pass

    return browser, target_page


# =====================================================================
# Compact Indexed DOM Perception
# =====================================================================

INDEX_DOM_SCRIPT = """
() => {
    // 1. Clear any prior swades index markers
    document.querySelectorAll('[data-swades-id]').forEach(el => el.removeAttribute('data-swades-id'));

    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        return true;
    };

    const isElementInViewport = (rect) => {
        const vh = window.innerHeight || document.documentElement.clientHeight;
        const vw = window.innerWidth || document.documentElement.clientWidth;
        return (
            rect.top < vh + 100 &&
            rect.bottom > -100 &&
            rect.left < vw + 100 &&
            rect.right > -100
        );
    };

    const selector = [
        'button',
        'a[href]',
        'input',
        'select',
        'textarea',
        '[role="button"]',
        '[role="link"]',
        '[role="checkbox"]',
        '[role="radio"]',
        '[role="combobox"]',
        '[role="menuitem"]',
        '[role="tab"]',
        '[role="searchbox"]',
        '[role="switch"]',
        '[role="option"]',
        '[tabindex="0"]',
        'summary',
        'details',
        'h1, h2, h3',
        '[onclick]'
    ].join(', ');

    const nodes = Array.from(document.querySelectorAll(selector));
    const seen = new Set();
    const elements = [];
    let idx = 0;

    for (const el of nodes) {
        if (seen.has(el)) continue;
        if (!isVisible(el)) continue;

        const rect = el.getBoundingClientRect();
        const tag = el.tagName.toLowerCase();
        const roleAttr = (el.getAttribute('role') || '').toLowerCase();
        const typeAttr = (el.getAttribute('type') || '').toLowerCase();

        // Effective role
        let role = roleAttr;
        if (!role) {
            if (tag.startsWith('h') && tag.length === 2) role = `heading:${tag}`;
            else if (tag === 'a') role = 'link';
            else if (tag === 'button' || typeAttr === 'button' || typeAttr === 'submit') role = 'button';
            else if (tag === 'input') {
                if (['checkbox', 'radio'].includes(typeAttr)) role = typeAttr;
                else role = `input:${typeAttr || 'text'}`;
            } else if (tag === 'select') role = 'select';
            else if (tag === 'textarea') role = 'textarea';
            else role = tag;
        }

        // Visible text / label
        let label = '';
        const ariaLabel = el.getAttribute('aria-label') || el.getAttribute('aria-placeholder') || el.getAttribute('title') || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const innerTxt = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');

        if (ariaLabel) {
            label = ariaLabel;
        } else if (placeholder && (!innerTxt || tag === 'input')) {
            label = placeholder;
        } else if (innerTxt) {
            label = innerTxt.slice(0, 120);
        } else if (el.value && tag === 'input') {
            label = String(el.value).slice(0, 120);
        }

        let val = undefined;
        if (tag === 'input' || tag === 'textarea') {
            val = el.value || '';
        } else if (tag === 'select') {
            val = el.value || (el.options && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '');
        }

        let options = undefined;
        if (tag === 'select') {
            options = Array.from(el.options || []).map(o => (o.text || o.value || '').trim()).filter(Boolean).slice(0, 25);
        }

        const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
        const checked = el.checked || el.getAttribute('aria-checked') === 'true';
        const href = el.getAttribute('href') || undefined;

        // Skip non-interactive items with empty labels (except inputs/selects/headings)
        if (!label && !val && !href && !['select', 'input', 'textarea'].includes(tag) && !role.startsWith('heading')) {
            continue;
        }

        el.setAttribute('data-swades-id', String(idx));
        seen.add(el);

        const bounds = {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            center_x: Math.round(rect.x + rect.width / 2),
            center_y: Math.round(rect.y + rect.height / 2),
            in_viewport: isElementInViewport(rect)
        };

        elements.push({
            index: idx,
            tag: tag,
            role: role,
            label: label ? label.slice(0, 120) : '',
            value: val,
            options: options,
            href: href ? href.slice(0, 150) : undefined,
            disabled: disabled || undefined,
            checked: checked || undefined,
            bounds: bounds
        });

        idx++;
        if (idx >= 150) break;
    }

    return elements;
}
"""

def _ensure_indexed(page):
    """Ensures that elements in the active page have data-swades-id attributes freshly assigned."""
    try:
        page.evaluate(INDEX_DOM_SCRIPT)
    except Exception:
        time.sleep(0.2)
        try:
            page.evaluate(INDEX_DOM_SCRIPT)
        except Exception:
            pass


def _build_compact_dom_representation(elements):
    """Formats the list of indexed elements into a clean, compact token-efficient string ([@0], [@1], ...)."""
    lines = []
    for el in elements:
        idx = el.get("index", 0)
        role = el.get("role", "element")
        label = el.get("label", "").strip()
        val = el.get("value")
        options = el.get("options")
        checked = el.get("checked")
        disabled = el.get("disabled")
        href = el.get("href")
        bounds = el.get("bounds", {})
        cx = bounds.get("center_x", 0)
        cy = bounds.get("center_y", 0)
        in_vp = bounds.get("in_viewport", True)

        parts = [f"[@{idx}]", f"[{role}]"]

        if label:
            parts.append(f'"{label}"')
        
        if val is not None and val != "":
            parts.append(f'value="{val}"')

        if options:
            opts_str = ", ".join([f'"{o}"' for o in options[:5]])
            if len(options) > 5:
                opts_str += f", ... (+{len(options)-5} more)"
            parts.append(f"options=[{opts_str}]")

        if checked is not None:
            parts.append(f"checked={str(checked).lower()}")

        if disabled:
            parts.append("disabled")

        if href and not label:
            parts.append(f'href="{href}"')

        loc_str = f"(center: {cx}, {cy})"
        if not in_vp:
            loc_str += " [offscreen]"
        parts.append(loc_str)

        lines.append(" ".join(parts))

    return "\n".join(lines)


def safe_eval_compact_dom(page):
    """Executes compact_dom.js with automatic retry, load state sync, and fallback to direct DOM indexing."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compact_dom.js")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            js_code = f.read()
    except Exception:
        js_code = ""

    for attempt in range(3):
        try:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=2000)
            except Exception:
                pass
            if js_code:
                res = page.evaluate(f"() => {{\n{js_code}\nreturn getCompactDom();\n}}")
                if res and isinstance(res, dict) and res.get("elements"):
                    return res
        except Exception:
            time.sleep(0.2)

    # Robust In-Page Fallback
    try:
        elements = page.evaluate(INDEX_DOM_SCRIPT)
        if elements:
            dsl = _build_compact_dom_representation(elements)
            return {"elements": elements, "dsl": dsl}
    except Exception:
        pass

    return {"elements": [], "dsl": ""}


def _extract_page_snapshot(page, browser=None):
    """Extracts structured content, compact indexed DOM ([@0], [@1], ...), and interactive elements from active page."""
    try:
        title = ""
        url = page.url or ""
        for _ in range(8):
            try:
                title = page.title()
                raw_body = page.locator("body").inner_text(timeout=300).strip()
                if "loading game" in raw_body.lower() or len(raw_body) < 5 or not title:
                    time.sleep(0.25)
                else:
                    break
            except Exception:
                time.sleep(0.2)

        url = page.url or ""

        # Extract main text
        main_text = ""
        try:
            body_txt = page.locator("body").inner_text(timeout=1000)
            if body_txt:
                lines = [l.strip() for l in body_txt.split("\n") if l.strip()]
                main_text = "\n".join(lines[:25])
        except Exception:
            pass

        # Structured search results extraction if on google
        search_cards = []
        if "google.com/search" in url:
            try:
                js_cards = "() => Array.from(document.querySelectorAll('#rso .g, #rso div[data-hveid]')).map(el => ({ title: el.querySelector('h3')?.innerText?.trim() || '', snippet: (el.innerText || '').slice(0, 300) })).filter(c => c.title).slice(0, 6)"
                card_data = page.evaluate(js_cards)
                if card_data:
                    search_cards = card_data
            except Exception:
                pass

        # Run compact DOM perception engine
        dom_res = safe_eval_compact_dom(page)
        elements = dom_res.get("elements", [])
        compact_dom = dom_res.get("dsl", "")

        desktop_wins = get_desktop_windows()

        return {
            "success": True,
            "compact_dom": compact_dom,
            "browser_context": {
                "role": "WebArea",
                "title": title or "Active Page",
                "url": url,
                "compact_dom": compact_dom,
                "content_summary": main_text[:1400] if main_text else "",
                "search_results": search_cards if search_cards else None,
                "elements_count": len(elements),
                "elements": elements
            },
            "desktop_context": desktop_wins
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "compact_dom": "",
            "browser_context": {"status": f"CDP Offline: {str(e)}"},
            "desktop_context": get_desktop_windows()
        }


# =====================================================================
# Multi-Tier Action Dispatchers
# =====================================================================

def _parse_index_target(target):
    """Extracts integer index from int, string index ('3', '[@3]'), or returns clean text target."""
    if isinstance(target, int):
        return target, None
    s = str(target).strip()
    match = re.search(r"^\[?@?(\d+)\]?$", s)
    if match:
        return int(match.group(1)), None
    if s.isdigit():
        return int(s), None
    return None, s


def _dispatch_click(page, target):
    """
    Multi-Tier Click Dispatcher:
    Tier 1: Direct DOM click via [data-swades-id="<index>"]
    Tier 2: Synthetic framework event dispatcher (pointerdown, mousedown, focus, pointerup, mouseup, click)
    Tier 3: CDP coordinate click via Input.dispatchMouseEvent / Playwright mouse at exact center (x, y)
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=2000)
    except Exception:
        pass

    _ensure_indexed(page)
    index, text_target = _parse_index_target(target)
    
    js_multi_tier_click = """
    ([idx, txt]) => {
        let el = null;
        if (idx !== null && idx !== undefined) {
            el = document.querySelector(`[data-swades-id="${idx}"]`);
        }
        if (!el && txt) {
            const cleanTxt = txt.toLowerCase().replace(/['"™®©]/g, '').trim();
            const candidates = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"], [tabindex="0"], div, span, h1, h2, h3'));
            for (const c of candidates) {
                const cText = (c.innerText || c.textContent || c.value || c.getAttribute('aria-label') || '').trim().toLowerCase();
                if (cText && (cText === cleanTxt || cText.includes(cleanTxt) || cleanTxt.includes(cText))) {
                    el = c;
                    break;
                }
            }
            if (!el) {
                try { el = document.querySelector(txt); } catch(_) {}
            }
        }

        if (!el) return { success: false, error: 'Element not found in DOM' };

        try {
            el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
        } catch (_) {}

        const rect = el.getBoundingClientRect();
        const cx = Math.round(rect.x + rect.width / 2);
        const cy = Math.round(rect.y + rect.height / 2);

        // Tier 1: Direct DOM click
        let tier1_ok = false;
        try {
            if (typeof el.focus === 'function') el.focus();
            if (typeof el.click === 'function') {
                el.click();
                tier1_ok = true;
            }
        } catch (e) {}

        // Tier 2: Synthetic Framework Event Dispatcher
        let tier2_ok = false;
        try {
            const evList = ['pointerover', 'mouseover', 'pointerdown', 'mousedown', 'focus', 'pointerup', 'mouseup', 'click'];
            for (const name of evList) {
                const isPtr = name.startsWith('pointer');
                const EvClass = isPtr && window.PointerEvent ? PointerEvent : MouseEvent;
                const ev = new EvClass(name, {
                    bubbles: true,
                    cancelable: true,
                    composed: true,
                    view: window,
                    clientX: cx,
                    clientY: cy,
                    screenX: cx,
                    screenY: cy,
                    button: 0,
                    buttons: name.includes('down') ? 1 : 0
                });
                el.dispatchEvent(ev);
            }
            tier2_ok = true;
        } catch (e) {}

        return {
            success: true,
            tier1: tier1_ok,
            tier2: tier2_ok,
            center_x: cx,
            center_y: cy,
            width: rect.width,
            height: rect.height
        };
    }
    """

    res = {}
    for _ in range(3):
        try:
            res = page.evaluate(js_multi_tier_click, [index, text_target])
            if res.get("success"):
                break
        except Exception:
            time.sleep(0.2)

    # Tier 3: CDP / Playwright hardware coordinate click
    if res.get("success") and res.get("center_x") and res.get("center_y"):
        cx = res["center_x"]
        cy = res["center_y"]
        if cx > 0 and cy > 0:
            try:
                page.mouse.move(cx, cy)
                page.mouse.down(button="left")
                time.sleep(0.05)
                page.mouse.up(button="left")
            except Exception:
                pass
        return {"success": True, "tier_dispatch": "Tier 1 (DOM) + Tier 2 (Synthetic) + Tier 3 (CDP)", "target": target}

    # Fallback to Playwright locator if JS lookup missed
    if index is not None:
        loc = page.locator(f'[data-swades-id="{index}"]').first
        if loc.count() > 0:
            loc.click(timeout=3000, no_wait_after=True)
            return {"success": True, "tier_dispatch": "Playwright Locator", "target": target}
    elif text_target:
        for role in ["button", "link"]:
            try:
                loc = page.get_by_role(role, name=text_target, exact=False).first
                if loc.count() > 0:
                    loc.click(timeout=2500, no_wait_after=True)
                    return {"success": True, "tier_dispatch": "Playwright Role", "target": target}
            except Exception:
                pass

    return {"success": False, "error": f"Failed to dispatch click to target: {target}"}


def _dispatch_type(page, target, text, clear=True, submit=False):
    """
    Multi-Tier Type Dispatcher:
    Tier 1 & 2: Focus, Clear, Input/Change synthetic event bubbling on [data-swades-id="<index>"]
    Tier 3: CDP / Playwright keyboard typing and Enter submission
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=2000)
    except Exception:
        pass

    _ensure_indexed(page)
    index, text_target = _parse_index_target(target)

    js_multi_tier_type = """
    ([idx, txt, newText, shouldClear, shouldSubmit]) => {
        let el = null;
        if (idx !== null && idx !== undefined) {
            el = document.querySelector(`[data-swades-id="${idx}"]`);
        }
        if (!el) {
            const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea, [contenteditable="true"]')).filter(i => {
                const r = i.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            });
            if (txt) {
                const cleanTxt = txt.toLowerCase().trim();
                el = inputs.find(i => 
                    (i.placeholder || '').toLowerCase().includes(cleanTxt) ||
                    (i.getAttribute('aria-label') || '').toLowerCase().includes(cleanTxt) ||
                    (i.name || '').toLowerCase().includes(cleanTxt) ||
                    (i.value || '').toLowerCase().includes(cleanTxt)
                );
            }
            if (!el && inputs.length > 0) {
                el = inputs[0];
            }
        }

        if (!el) return { success: false, error: 'Target input not found in DOM' };

        try {
            el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
        } catch (_) {}

        const rect = el.getBoundingClientRect();
        const cx = Math.round(rect.x + rect.width / 2);
        const cy = Math.round(rect.y + rect.height / 2);

        try {
            if (typeof el.focus === 'function') el.focus();
            if (typeof el.click === 'function') el.click();
        } catch (_) {}

        // Tier 1 & 2: Set value & trigger synthetic input / change events
        if (el.tagName && (el.tagName.toLowerCase() === 'input' || el.tagName.toLowerCase() === 'textarea')) {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
            const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
            const finalVal = shouldClear ? newText : (el.value + newText);
            
            if (el.tagName.toLowerCase() === 'input' && nativeInputValueSetter) {
                nativeInputValueSetter.call(el, finalVal);
            } else if (el.tagName.toLowerCase() === 'textarea' && nativeTextAreaValueSetter) {
                nativeTextAreaValueSetter.call(el, finalVal);
            } else {
                el.value = finalVal;
            }
        } else if (el.isContentEditable) {
            if (shouldClear) el.innerText = '';
            el.innerText = shouldClear ? newText : (el.innerText + newText);
        }

        el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true, composed: true }));
        el.dispatchEvent(new Event('change', { bubbles: true, cancelable: true, composed: true }));

        if (shouldSubmit && el.form) {
            try {
                if (typeof el.form.requestSubmit === 'function') {
                    el.form.requestSubmit();
                } else {
                    el.form.submit();
                }
            } catch (_) {}
        }

        return {
            success: true,
            center_x: cx,
            center_y: cy
        };
    }
    """

    res = {}
    for _ in range(4):
        try:
            res = page.evaluate(js_multi_tier_type, [index, text_target, text, clear, submit])
            if res.get("success"):
                break
        except Exception:
            time.sleep(0.25)

    # Tier 3: Hardware keyboard events & Enter submission
    if res.get("success"):
        cx = res.get("center_x")
        cy = res.get("center_y")
        if cx and cy and cx > 0 and cy > 0:
            try:
                page.mouse.click(cx, cy)
                if clear:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                page.keyboard.type(text)
            except Exception:
                pass

        if submit:
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass
        return {"success": True, "tier_dispatch": "Multi-tier Type + Events + Keyboard", "target": target, "text": text}

    # Fallback to Playwright locator
    if index is not None:
        loc = page.locator(f'[data-swades-id="{index}"]').first
        if loc.count() > 0:
            if clear:
                loc.fill(text, timeout=3000, no_wait_after=True)
            else:
                loc.type(text, timeout=3000, no_wait_after=True)
            if submit:
                page.keyboard.press("Enter")
            return {"success": True, "tier_dispatch": "Playwright Locator Fill", "target": target}

    return {"success": False, "error": f"Failed to type into target: {target}"}


def _dispatch_select(page, target, value):
    """
    Multi-Tier Select Dispatcher for dropdown elements:
    Tier 1: DOM selectedIndex and option.selected
    Tier 2: Synthetic input and change event bubbling
    Tier 3: Playwright select_option fallback
    """
    _ensure_indexed(page)
    index, text_target = _parse_index_target(target)

    js_multi_tier_select = """
    ([idx, txt, val]) => {
        let el = null;
        if (idx !== null && idx !== undefined) {
            el = document.querySelector(`[data-swades-id="${idx}"]`);
        }
        if (!el && txt) {
            try { el = document.querySelector(txt); } catch(_) {}
            if (!el) {
                const selects = Array.from(document.querySelectorAll('select'));
                el = selects.find(s => (s.name || '').toLowerCase().includes(txt.toLowerCase()) || (s.getAttribute('aria-label') || '').toLowerCase().includes(txt.toLowerCase())) || selects[0];
            }
        }

        if (!el || el.tagName.toLowerCase() !== 'select') {
            return { success: false, error: 'Select element not found' };
        }

        try {
            el.scrollIntoView({ behavior: 'instant', block: 'center', inline: 'center' });
        } catch (_) {}

        if (typeof el.focus === 'function') el.focus();

        const valClean = String(val).toLowerCase().trim();
        let matched = false;

        for (let i = 0; i < el.options.length; i++) {
            const opt = el.options[i];
            const optText = (opt.text || '').toLowerCase().trim();
            const optVal = (opt.value || '').toLowerCase().trim();
            if (optVal === valClean || optText === valClean || optText.includes(valClean) || valClean.includes(optText)) {
                el.selectedIndex = i;
                opt.selected = true;
                matched = true;
                break;
            }
        }

        if (!matched && el.options.length > 0) {
            el.value = val;
        }

        el.dispatchEvent(new Event('input', { bubbles: true, cancelable: true, composed: true }));
        el.dispatchEvent(new Event('change', { bubbles: true, cancelable: true, composed: true }));

        return { success: true };
    }
    """

    res = page.evaluate(js_multi_tier_select, [index, text_target, value])
    if res.get("success"):
        return {"success": True, "tier_dispatch": "Multi-tier Select", "target": target, "value": value}

    # Playwright fallback
    try:
        sel_loc = page.locator(f'[data-swades-id="{index}"]').first if index is not None else page.locator(text_target or "select").first
        if sel_loc.count() > 0:
            sel_loc.select_option(label=value, timeout=2500)
            return {"success": True, "tier_dispatch": "Playwright Select Option", "target": target, "value": value}
    except Exception:
        try:
            sel_loc.select_option(value=value, timeout=2500)
            return {"success": True, "tier_dispatch": "Playwright Select Option (by value)", "target": target, "value": value}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"success": False, "error": f"Failed to select '{value}' on target '{target}'"}


def _dispatch_scroll(page, direction="down", amount=500):
    """Scrolls webpage smoothly and handles settlement."""
    dir_clean = str(direction).lower().strip()
    amt = int(amount) if amount else 500

    delta_x = 0
    delta_y = 0
    if dir_clean == "up":
        delta_y = -amt
    elif dir_clean == "down":
        delta_y = amt
    elif dir_clean == "left":
        delta_x = -amt
    elif dir_clean == "right":
        delta_x = amt
    else:
        delta_y = amt

    page.evaluate(f"window.scrollBy({delta_x}, {delta_y})")
    try:
        page.mouse.wheel(delta_x, delta_y)
    except Exception:
        pass
    return {"success": True, "action": "scroll", "direction": dir_clean, "amount": amt}


# =====================================================================
# Closed-World Indexed Tool API (with Automatic Inline Observations)
# =====================================================================

def browser_navigate(url: str):
    """Navigates to URL, waits for settlement (300-500ms), and returns the live compact indexed snapshot."""
    target_url = url.strip()
    if not target_url.startswith(("http://", "https://", "file://", "about:", "data:")):
        target_url = f"https://{target_url}"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            page.goto(target_url, timeout=15000, wait_until="domcontentloaded")
            time.sleep(0.4)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_navigate"
            obs["target_url"] = target_url
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_navigate", "error": str(e)}


def browser_snapshot():
    """Explicitly extracts compact indexed DOM ([@0], [@1], ...), search results, and page summary."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_snapshot"
            return obs
    except Exception as e:
        return {
            "success": False,
            "action": "browser_snapshot",
            "error": str(e),
            "compact_dom": "",
            "browser_context": {"status": f"CDP Offline: {str(e)}"},
            "desktop_context": get_desktop_windows()
        }


def browser_click(index):
    """
    Clicks element by closed-world index (e.g. 0, 1, '[@0]') using Multi-Tier Action Dispatch,
    waits 300-500ms for settlement, and automatically returns the updated compact indexed DOM snapshot!
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            dispatch_res = _dispatch_click(page, index)
            if not dispatch_res.get("success"):
                return {"success": False, "action": "browser_click", "error": dispatch_res.get("error")}

            # Settlement wait
            time.sleep(0.4)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_click"
            obs["dispatch"] = dispatch_res.get("tier_dispatch")
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_click", "error": str(e)}


def browser_type(index, text: str, clear: bool = True, submit: bool = False):
    """
    Types into input/textarea by closed-world index using Multi-Tier Action Dispatch,
    waits 300-500ms for settlement, and automatically returns the updated compact indexed DOM snapshot!
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            dispatch_res = _dispatch_type(page, index, text, clear=clear, submit=submit)
            if not dispatch_res.get("success"):
                return {"success": False, "action": "browser_type", "error": dispatch_res.get("error")}

            # Settlement wait
            time.sleep(0.4)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_type"
            obs["dispatch"] = dispatch_res.get("tier_dispatch")
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_type", "error": str(e)}


def browser_select(index, value: str):
    """
    Selects dropdown option on select element by closed-world index using Multi-Tier Action Dispatch,
    waits 300-500ms for settlement, and automatically returns the updated compact indexed DOM snapshot!
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            dispatch_res = _dispatch_select(page, index, value)
            if not dispatch_res.get("success"):
                return {"success": False, "action": "browser_select", "error": dispatch_res.get("error")}

            # Settlement wait
            time.sleep(0.4)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_select"
            obs["dispatch"] = dispatch_res.get("tier_dispatch")
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_select", "error": str(e)}


def browser_scroll(direction: str = "down", amount: int = 500):
    """
    Scrolls webpage smoothly, waits 300-500ms for settlement,
    and automatically returns newly visible compact indexed DOM snapshot!
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            _dispatch_scroll(page, direction, amount)
            time.sleep(0.4)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_scroll"
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_scroll", "error": str(e)}


def browser_wait(seconds: float = 1.0):
    """Waits for specified seconds and returns fresh compact indexed DOM snapshot."""
    try:
        wait_s = max(0.1, float(seconds))
        time.sleep(wait_s)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, page = get_playwright_page(p)
            obs = _extract_page_snapshot(page, browser)
            obs["action"] = "browser_wait"
            obs["waited_seconds"] = wait_s
            return obs
    except Exception as e:
        return {"success": False, "action": "browser_wait", "error": str(e)}


# =====================================================================
# Desktop Application Window & Keyboard Control
# =====================================================================

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

    if not windows:
        try:
            res = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", ""], stdout=subprocess.PIPE, text=True)
            for wid in res.stdout.strip().split("\n"):
                if wid.strip():
                    name_res = subprocess.run(["xdotool", "getwindowname", wid.strip()], stdout=subprocess.PIPE, text=True)
                    t = name_res.stdout.strip()
                    if t and not any(ign in t.lower() for ign in ["xfwm4", "xfce4-panel", "desktop", "wrapper"]):
                        windows.append({"window_id": wid.strip(), "title": t})
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
                win_id = w["window_id"]
                if not any(ign in title.lower() for ign in ["swades", "xfce", "panel", "desktop"]):
                    subprocess.run(["wmctrl", "-i", "-c", win_id], check=False)
                    closed.append(title)
            subprocess.run(["pkill", "-f", "google-chrome"], check=False)
            subprocess.run(["pkill", "-f", "chromium"], check=False)
            if not closed:
                closed = ["Browser and desktop applications"]
            return {"success": True, "action": "close_all", "closed": closed}
        else:
            wins = get_desktop_windows()
            closed = []
            for w in wins:
                title = w["title"]
                if target.lower() in title.lower():
                    subprocess.run(["wmctrl", "-i", "-c", w["window_id"]], check=False)
                    closed.append(title)
            if not closed:
                subprocess.run(["wmctrl", "-c", target], check=False)
                closed.append(target)
            return {"success": True, "action": "close", "closed": closed}

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


# =====================================================================
# CLI Entry Point
# =====================================================================

def main():
    if len(sys.argv) < 2:
        print(json.dumps(browser_snapshot(), indent=2))
        return

    # Check for --json input
    if "--json" in sys.argv:
        try:
            json_idx = sys.argv.index("--json")
            if json_idx + 1 < len(sys.argv):
                payload = json.loads(sys.argv[json_idx + 1])
            else:
                payload = json.loads(sys.stdin.read())
            
            action = payload.get("action") or payload.get("tool") or ""
            if action in ["navigate", "browser_navigate"]:
                print(json.dumps(browser_navigate(payload.get("url", ""))))
            elif action in ["snapshot", "browser_snapshot"]:
                print(json.dumps(browser_snapshot()))
            elif action in ["click", "browser_click"]:
                print(json.dumps(browser_click(payload.get("index") if payload.get("index") is not None else payload.get("target"))))
            elif action in ["type", "browser_type"]:
                print(json.dumps(browser_type(
                    payload.get("index") if payload.get("index") is not None else payload.get("target"),
                    payload.get("text", ""),
                    clear=payload.get("clear", True),
                    submit=payload.get("submit", False)
                )))
            elif action in ["select", "browser_select"]:
                print(json.dumps(browser_select(
                    payload.get("index") if payload.get("index") is not None else payload.get("target"),
                    payload.get("value", "")
                )))
            elif action in ["scroll", "browser_scroll"]:
                print(json.dumps(browser_scroll(
                    direction=payload.get("direction", "down"),
                    amount=int(payload.get("amount", 500))
                )))
            elif action in ["wait", "browser_wait"]:
                print(json.dumps(browser_wait(float(payload.get("seconds", 1.0)))))
            elif action in ["windows", "window_control", "desktop_window_control"]:
                print(json.dumps(desktop_window_control(payload.get("action", "list"), payload.get("target"))))
            elif action in ["interact", "desktop_interact"]:
                print(json.dumps(desktop_interact(
                    payload.get("action", "click"),
                    x=payload.get("x"),
                    y=payload.get("y"),
                    keys=payload.get("keys")
                )))
            else:
                print(json.dumps({"error": f"Unknown action '{action}' in JSON payload"}))
            return
        except Exception as e:
            print(json.dumps({"error": f"Failed to parse JSON payload: {str(e)}"}))
            return

    cmd = sys.argv[1].lower()

    if cmd in ["snapshot", "browser_snapshot", "read_screen_tree", "dump"]:
        print(json.dumps(browser_snapshot(), indent=2))
    elif cmd in ["navigate", "browser_navigate", "goto", "open"]:
        url = sys.argv[2] if len(sys.argv) > 2 else "https://google.com"
        print(json.dumps(browser_navigate(url), indent=2))
    elif cmd in ["click", "browser_click"]:
        target = sys.argv[2] if len(sys.argv) > 2 else "0"
        print(json.dumps(browser_click(target), indent=2))
    elif cmd in ["type", "browser_type", "fill"]:
        target = sys.argv[2] if len(sys.argv) > 2 else "0"
        text = sys.argv[3] if len(sys.argv) > 3 else ""
        clear = "--no-clear" not in sys.argv
        submit = "--submit" in sys.argv or "--enter" in sys.argv or "-e" in sys.argv
        print(json.dumps(browser_type(target, text, clear=clear, submit=submit), indent=2))
    elif cmd in ["select", "browser_select"]:
        target = sys.argv[2] if len(sys.argv) > 2 else "0"
        value = sys.argv[3] if len(sys.argv) > 3 else ""
        print(json.dumps(browser_select(target, value), indent=2))
    elif cmd in ["scroll", "browser_scroll"]:
        direction = sys.argv[2] if len(sys.argv) > 2 else "down"
        amount = int(sys.argv[3]) if len(sys.argv) > 3 else 500
        print(json.dumps(browser_scroll(direction, amount), indent=2))
    elif cmd in ["wait", "browser_wait"]:
        seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
        print(json.dumps(browser_wait(seconds), indent=2))
    elif cmd in ["windows", "window_control", "desktop_window_control"]:
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
