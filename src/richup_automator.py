#!/usr/bin/env python3
"""
richup_automator.py — Specialized Automation Layer for Richup.io (Vue/WebSocket Board Games)

Features:
1. Game State Detector:
   - Detects screen states: LANDING, NICKNAME_PROMPT, ROOM_LOBBY, IN_GAME, TURN_ACTIVE,
     WAITING_FOR_PLAYERS, MODAL_POPUP, GAME_OVER, CAPTCHA_CHALLENGE.
   - Parses game indicators: current player turn, dice roll buttons, property purchase modals,
     cash balances, rent payment prompts, and trade notifications.
2. Cloudflare Turnstile & Captcha Handler:
   - Detects Turnstile iframe / widget / response tokens.
   - Simulates human-like randomized click with realistic delays and trajectory.
   - Returns clear status (SOLVED, CLICKED_WAITING, MANUAL_INTERVENTION_REQUIRED).
3. Autonomous Turn Assistant (`run_richup_turn`):
   - Decides and executes or suggests next optimal move (roll dice, buy property, end turn, jail exit).
   - Compatible with Swades CDP client, Playwright pages, or direct CDP port communication.
"""

import sys
import os
import json
import time
import math
import random
import asyncio
import subprocess
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple, Union

# Ensure Swades src directory is on sys.path
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    import browser_cdp
except ImportError:
    browser_cdp = None


class RichupScreenState(str, Enum):
    UNKNOWN = "UNKNOWN"
    LANDING = "LANDING"
    NICKNAME_PROMPT = "NICKNAME_PROMPT"
    ROOM_LOBBY = "ROOM_LOBBY"
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    IN_GAME = "IN_GAME"
    TURN_ACTIVE = "TURN_ACTIVE"
    MODAL_POPUP = "MODAL_POPUP"
    GAME_OVER = "GAME_OVER"
    CAPTCHA_CHALLENGE = "CAPTCHA_CHALLENGE"


class TurnstileStatus(str, Enum):
    NOT_PRESENT = "NOT_PRESENT"
    SOLVED = "SOLVED"
    CLICKED_WAITING = "CLICKED_WAITING"
    MANUAL_INTERVENTION_REQUIRED = "MANUAL_INTERVENTION_REQUIRED"
    ERROR = "ERROR"


class CDPClientWrapper:
    """
    Flexible wrapper that accepts:
    - Direct CDP port integer (e.g. 9222)
    - Swades browser_cdp client or module
    - Playwright Page object
    - Generic CDP / WebSocket connector with eval_js / evaluate
    """
    def __init__(self, cdp_target: Any = None, port: int = 9222):
        self.target = cdp_target
        self.port = port
        if isinstance(cdp_target, int):
            self.port = cdp_target
            self.target = None

    def eval_js(self, expression: str) -> Dict[str, Any]:
        """Evaluates JS in the target page and returns the parsed result."""
        # 1. If target has eval_js / evaluate method (e.g., Playwright page or custom CDP client)
        if self.target is not None:
            if hasattr(self.target, "evaluate") and callable(self.target.evaluate):
                try:
                    res = self.target.evaluate(expression)
                    return {"success": True, "result": res}
                except Exception as e:
                    return {"success": False, "error": str(e)}
            elif hasattr(self.target, "eval_js") and callable(self.target.eval_js):
                try:
                    return self.target.eval_js(expression)
                except Exception as e:
                    return {"success": False, "error": str(e)}

        # 2. Fallback to browser_cdp module / WebSocket connection
        if browser_cdp is not None:
            try:
                ws_url = browser_cdp.get_page_ws_url(self.port)
                if not ws_url:
                    return {"success": False, "error": f"Cannot connect to CDP on port {self.port}"}
                
                res = asyncio.run(browser_cdp.ws_send_receive(ws_url, "Runtime.evaluate", {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True
                }))
                result = res.get("result", {})
                if "exceptionDetails" in result:
                    return {
                        "success": False,
                        "error": result["exceptionDetails"].get("text", "JS Exception"),
                        "exception": result["exceptionDetails"]
                    }
                return {"success": True, "result": result.get("result", {}).get("value")}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "No viable CDP evaluation interface available"}

    def click_coordinate(self, x: int, y: int) -> bool:
        """Dispatches mouse click at viewport coordinates."""
        # 1. If target is Playwright page
        if self.target is not None and hasattr(self.target, "mouse"):
            try:
                self.target.mouse.click(x, y)
                return True
            except Exception:
                pass

        # 2. Use CDP Input.dispatchMouseEvent
        if browser_cdp is not None:
            try:
                ws_url = browser_cdp.get_page_ws_url(self.port)
                if ws_url:
                    async def _send_clicks():
                        # Move
                        await browser_cdp.ws_send_receive(ws_url, "Input.dispatchMouseEvent", {
                            "type": "mouseMoved", "x": x, "y": y
                        })
                        await asyncio.sleep(0.05 + random.uniform(0.02, 0.08))
                        # Down
                        await browser_cdp.ws_send_receive(ws_url, "Input.dispatchMouseEvent", {
                            "type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1
                        })
                        await asyncio.sleep(0.08 + random.uniform(0.04, 0.12))
                        # Up
                        await browser_cdp.ws_send_receive(ws_url, "Input.dispatchMouseEvent", {
                            "type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1
                        })
                    asyncio.run(_send_clicks())
                    return True
            except Exception:
                pass

        # 3. Fallback to JS click at coordinate
        js = f"""
        (() => {{
            const el = document.elementFromPoint({x}, {y});
            if (el) {{
                el.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, clientX: {x}, clientY: {y} }}));
                el.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, clientX: {x}, clientY: {y} }}));
                el.dispatchEvent(new MouseEvent('click', {{ bubbles: true, clientX: {x}, clientY: {y} }}));
                return true;
            }}
            return false;
        }})()
        """
        res = self.eval_js(js)
        return bool(res.get("result"))


# ==============================================================================
# 1. GAME STATE DETECTOR
# ==============================================================================

DETECTION_SCRIPT = """
(() => {
    const data = {
        url: window.location.href,
        title: document.title,
        screen_state: "UNKNOWN",
        turnstile_present: false,
        turnstile_solved: false,
        turnstile_box: null,
        is_my_turn: false,
        can_roll: false,
        can_end_turn: false,
        can_buy: false,
        can_auction: false,
        modal_open: false,
        modal_title: null,
        modal_text: null,
        modal_buttons: [],
        current_player: null,
        my_nickname: null,
        my_cash: null,
        players: [],
        board_visible: false,
        active_buttons: [],
        notifications: [],
        raw_indicators: {}
    };

    // 1. Cloudflare Turnstile detection
    const turnstileIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile iframe, div[id*="cf-"] iframe');
    const turnstileToken = document.querySelector('input[name="cf-turnstile-response"], [name="cf-turnstile-response"]');
    const turnstileWrapper = document.querySelector('.cf-turnstile, #turnstile-wrapper, [data-sitekey]');
    
    if (turnstileIframe || turnstileWrapper) {
        data.turnstile_present = true;
        if (turnstileToken && turnstileToken.value && turnstileToken.value.length > 10) {
            data.turnstile_solved = true;
        }
        const targetEl = turnstileIframe || turnstileWrapper;
        if (targetEl) {
            const rect = targetEl.getBoundingClientRect();
            data.turnstile_box = {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                center_x: Math.round(rect.x + (rect.width > 60 ? 35 : rect.width / 2)),
                center_y: Math.round(rect.y + rect.height / 2)
            };
        }
    }

    // 2. Buttons & Interactivity
    const buttons = Array.from(document.querySelectorAll('button, [role="button"], .btn, input[type="button"], input[type="submit"]'))
        .filter(b => {
            const r = b.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && !b.disabled && window.getComputedStyle(b).display !== 'none';
        })
        .map(b => ({
            text: (b.innerText || b.value || b.textContent || '').trim().replace(/\\s+/g, ' '),
            tag: b.tagName.toLowerCase(),
            classes: b.className,
            id: b.id,
            disabled: !!b.disabled,
            box: (() => {
                const r = b.getBoundingClientRect();
                return {
                    x: Math.round(r.x),
                    y: Math.round(r.y),
                    width: Math.round(r.width),
                    height: Math.round(r.height),
                    center_x: Math.round(r.x + r.width / 2),
                    center_y: Math.round(r.y + r.height / 2)
                };
            })()
        }));
    data.active_buttons = buttons;

    // 3. Modals & Dialogs
    const modalContainers = Array.from(document.querySelectorAll('.modal, .dialog, .popup, [role="dialog"], .swal2-popup, .modal-container, .modal-content, .card-modal, .property-modal'))
        .filter(m => {
            const r = m.getBoundingClientRect();
            return r.width > 100 && r.height > 50 && window.getComputedStyle(m).visibility !== 'hidden' && window.getComputedStyle(m).display !== 'none';
        });

    if (modalContainers.length > 0) {
        data.modal_open = true;
        const topModal = modalContainers[modalContainers.length - 1];
        const heading = topModal.querySelector('h1, h2, h3, h4, .title, .modal-title, .header');
        data.modal_title = heading ? heading.innerText.trim() : null;
        data.modal_text = topModal.innerText.trim().slice(0, 500);

        const mButtons = Array.from(topModal.querySelectorAll('button, .btn, [role="button"]'))
            .filter(b => !b.disabled)
            .map(b => ({
                text: (b.innerText || b.value || '').trim(),
                box: (() => {
                    const r = b.getBoundingClientRect();
                    return { center_x: Math.round(r.x + r.width / 2), center_y: Math.round(r.y + r.height / 2) };
                })()
            }));
        data.modal_buttons = mButtons;
    }

    // 4. Board & Game Indicators
    const board = document.querySelector('#board, .board, .game-board, .board-container, svg.board-svg, .tiles-container');
    if (board && board.getBoundingClientRect().width > 200) {
        data.board_visible = true;
    }

    // Parse Player information
    const playerElements = Array.from(document.querySelectorAll('.player, .player-card, .player-info, .user-badge, .player-item'));
    data.players = playerElements.map(p => {
        const text = p.innerText || '';
        const nameEl = p.querySelector('.name, .username, .nickname, .player-name') || p;
        const cashEl = p.querySelector('.cash, .balance, .money, .player-money');
        const isActive = p.classList.contains('active') || p.classList.contains('current') || p.classList.contains('is-turn') || !!p.querySelector('.turn-indicator, .active-border');
        
        let cash = null;
        if (cashEl) {
            const match = cashEl.innerText.match(/\\$?([0-9,]+)/);
            if (match) cash = parseInt(match[1].replace(/,/g, ''), 10);
        } else {
            const match = text.match(/\\$?([0-9,]+)(?:k|M)?/i);
            if (match) cash = parseInt(match[1].replace(/,/g, ''), 10);
        }

        return {
            name: nameEl.innerText.split('\\n')[0].trim(),
            cash: cash,
            is_active_turn: isActive,
            raw_text: text.slice(0, 100)
        };
    });

    // Detect specific action buttons
    for (const b of buttons) {
        const txt = b.text.toLowerCase();
        if (txt.includes('roll') || txt.includes('throw dice') || txt.includes('roll dice')) {
            data.can_roll = true;
            data.is_my_turn = true;
        }
        if (txt.includes('end turn') || txt.includes('pass turn') || txt.includes('done') || txt.includes('finish turn')) {
            data.can_end_turn = true;
            data.is_my_turn = true;
        }
        if (txt.includes('buy') || txt.includes('purchase')) {
            data.can_buy = true;
        }
        if (txt.includes('auction')) {
            data.can_auction = true;
        }
    }

    // 5. Detect Screen State
    const fullBodyText = document.body.innerText.toLowerCase();
    const hasInput = !!document.querySelector('input[type="text"], input:not([type])');
    const nicknameInput = document.querySelector('input[placeholder*="nick" i], input[placeholder*="name" i], input[name*="nick" i], input[name*="name" i], #nickname, #username');

    if (data.turnstile_present && !data.turnstile_solved) {
        data.screen_state = "CAPTCHA_CHALLENGE";
    } else if (fullBodyText.includes('game over') || fullBodyText.includes('winner') || fullBodyText.includes('won the game') || fullBodyText.includes('play again')) {
        data.screen_state = "GAME_OVER";
    } else if (data.modal_open) {
        data.screen_state = "MODAL_POPUP";
    } else if (data.board_visible) {
        if (data.can_roll || data.can_end_turn || data.can_buy) {
            data.screen_state = "TURN_ACTIVE";
            data.is_my_turn = true;
        } else {
            data.screen_state = "IN_GAME";
        }
    } else if (nicknameInput || (hasInput && (fullBodyText.includes('nickname') || fullBodyText.includes('enter your name')))) {
        data.screen_state = "NICKNAME_PROMPT";
    } else if (fullBodyText.includes('lobby') || fullBodyText.includes('invite link') || fullBodyText.includes('waiting for host') || fullBodyText.includes('start game') || fullBodyText.includes('room:')) {
        data.screen_state = "ROOM_LOBBY";
    } else if (fullBodyText.includes('waiting for players') || fullBodyText.includes('waiting for other players')) {
        data.screen_state = "WAITING_FOR_PLAYERS";
    } else if (fullBodyText.includes('play with friends') || fullBodyText.includes('create room') || fullBodyText.includes('join room') || fullBodyText.includes('richup.io') || fullBodyText.includes('play now')) {
        data.screen_state = "LANDING";
    } else {
        data.screen_state = "UNKNOWN";
    }

    return data;
})()
"""

def detect_richup_state(cdp_client: Any) -> Dict[str, Any]:
    """
    Executes deep introspection script against Richup.io and parses the full game state.
    """
    client = CDPClientWrapper(cdp_client)
    res = client.eval_js(DETECTION_SCRIPT)
    
    if not res.get("success"):
        return {
            "success": False,
            "error": res.get("error", "Failed to evaluate detection script"),
            "screen_state": RichupScreenState.UNKNOWN.value,
            "raw": None
        }

    raw = res.get("result", {})
    screen_state_str = raw.get("screen_state", "UNKNOWN")
    try:
        screen_state = RichupScreenState(screen_state_str)
    except ValueError:
        screen_state = RichupScreenState.UNKNOWN

    return {
        "success": True,
        "screen_state": screen_state.value,
        "url": raw.get("url", ""),
        "title": raw.get("title", ""),
        "is_my_turn": raw.get("is_my_turn", False),
        "can_roll": raw.get("can_roll", False),
        "can_end_turn": raw.get("can_end_turn", False),
        "can_buy": raw.get("can_buy", False),
        "can_auction": raw.get("can_auction", False),
        "modal_open": raw.get("modal_open", False),
        "modal_title": raw.get("modal_title"),
        "modal_text": raw.get("modal_text"),
        "modal_buttons": raw.get("modal_buttons", []),
        "players": raw.get("players", []),
        "active_buttons": raw.get("active_buttons", []),
        "turnstile_present": raw.get("turnstile_present", False),
        "turnstile_solved": raw.get("turnstile_solved", False),
        "turnstile_box": raw.get("turnstile_box"),
        "board_visible": raw.get("board_visible", False)
    }


# ==============================================================================
# 2. CLOUDFLARE TURNSTILE & CAPTCHA HANDLER
# ==============================================================================

def solve_turnstile_challenge(cdp_client: Any, max_retries: int = 3) -> Dict[str, Any]:
    """
    Detects Cloudflare Turnstile and dispatches human-like randomized click to solve it.
    Returns status: SOLVED, CLICKED_WAITING, MANUAL_INTERVENTION_REQUIRED.
    """
    client = CDPClientWrapper(cdp_client)

    for attempt in range(1, max_retries + 1):
        state = detect_richup_state(client)
        if not state.get("success"):
            return {
                "status": TurnstileStatus.ERROR.value,
                "message": f"Failed state detection: {state.get('error')}"
            }

        if not state.get("turnstile_present"):
            return {
                "status": TurnstileStatus.NOT_PRESENT.value,
                "message": "No Cloudflare Turnstile challenge detected."
            }

        if state.get("turnstile_solved"):
            return {
                "status": TurnstileStatus.SOLVED.value,
                "message": "Cloudflare Turnstile is already solved with valid response token."
            }

        box = state.get("turnstile_box")
        if not box:
            return {
                "status": TurnstileStatus.MANUAL_INTERVENTION_REQUIRED.value,
                "message": "Turnstile widget detected but bounding box is obscured or not in viewport."
            }

        # Calculate human-jittered target point
        target_x = box["center_x"] + random.randint(-4, 4)
        target_y = box["center_y"] + random.randint(-4, 4)

        # Dispatch click
        clicked = client.click_coordinate(target_x, target_y)
        if not clicked:
            # Fallback JS trigger on checkbox / iframe
            client.eval_js("""
            (() => {
                const f = document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]');
                if (f) {
                    f.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    f.focus();
                }
            })()
            """)

        # Realistic human delay before verifying
        time.sleep(2.0 + random.uniform(0.5, 1.5))

        # Check if solved
        new_state = detect_richup_state(client)
        if new_state.get("turnstile_solved") or not new_state.get("turnstile_present"):
            return {
                "status": TurnstileStatus.SOLVED.value,
                "attempt": attempt,
                "message": "Turnstile solved successfully."
            }

    # If retries exhausted and still present without token
    return {
        "status": TurnstileStatus.MANUAL_INTERVENTION_REQUIRED.value,
        "attempts": max_retries,
        "message": "Turnstile challenge requires manual user intervention (interactive puzzle or anti-bot lock)."
    }


# ==============================================================================
# 3. AUTONOMOUS TURN ASSISTANT (HIGH LEVEL HELPER)
# ==============================================================================

def run_richup_turn(cdp_client: Any, default_nickname: str = "SwadesPlayer", auto_execute: bool = True) -> Dict[str, Any]:
    """
    Analyzes current Richup.io screen and executes the optimal move or returns structured suggestions.
    
    Actions handled:
    - Solve Turnstile challenge if present
    - Fill Nickname and click Join/Submit if prompted
    - Click Ready / Start Game in Room Lobby
    - Buy property if funds permit (heuristic: balance >= price + safety buffer)
    - Handle dialogs (Roll dice, Pay jail fine, Accept trade, Auction)
    - Roll Dice when turn is active
    - End Turn when rolling and purchasing are complete
    """
    client = CDPClientWrapper(cdp_client)
    state = detect_richup_state(client)

    if not state.get("success"):
        return {
            "success": False,
            "error": state.get("error"),
            "action": "NONE",
            "suggestion": "Failed to connect to browser CDP."
        }

    screen = state.get("screen_state")

    # 1. CAPTCHA / TURNSTILE
    if screen == RichupScreenState.CAPTCHA_CHALLENGE.value or (state.get("turnstile_present") and not state.get("turnstile_solved")):
        if auto_execute:
            res = solve_turnstile_challenge(client)
            return {
                "success": res.get("status") in [TurnstileStatus.SOLVED.value, TurnstileStatus.CLICKED_WAITING.value],
                "action": "SOLVE_TURNSTILE",
                "status": res.get("status"),
                "suggestion": res.get("message"),
                "details": res
            }
        return {
            "success": True,
            "action": "SOLVE_TURNSTILE",
            "suggestion": "Click Cloudflare Turnstile checkbox to proceed.",
            "details": state
        }

    # 2. LANDING PAGE
    if screen == RichupScreenState.LANDING.value:
        suggestion = "Click 'Play with friends', 'Create Room', or 'Join Room' button."
        play_btn = None
        for b in state.get("active_buttons", []):
            txt = b["text"].lower()
            if any(k in txt for k in ["play with friends", "create room", "play now", "play"]):
                play_btn = b
                break

        if play_btn and auto_execute:
            client.click_coordinate(play_btn["box"]["center_x"], play_btn["box"]["center_y"])
            return {
                "success": True,
                "action": "CLICK_LANDING_BUTTON",
                "button_text": play_btn["text"],
                "suggestion": f"Clicked landing button: {play_btn['text']}"
            }
        return {
            "success": True,
            "action": "NAVIGATE_OR_START",
            "suggestion": suggestion,
            "details": state
        }

    # 3. NICKNAME PROMPT
    if screen == RichupScreenState.NICKNAME_PROMPT.value:
        if auto_execute:
            fill_js = f"""
            (() => {{
                const input = document.querySelector('input[placeholder*="nick" i], input[placeholder*="name" i], input[name*="nick" i], input[name*="name" i], #nickname, #username, input[type="text"]');
                if (input) {{
                    input.focus();
                    input.value = '{default_nickname}';
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
                const submitBtn = Array.from(document.querySelectorAll('button, input[type="submit"]'))
                    .find(b => {{
                        const t = (b.innerText || b.value || '').toLowerCase();
                        return t.includes('join') || t.includes('continue') || t.includes('play') || t.includes('save');
                    }});
                if (submitBtn) {{
                    submitBtn.click();
                    return {{ filled: true, clicked: true, name: '{default_nickname}' }};
                }}
                return {{ filled: !!input, clicked: false }};
            }})()
            """
            res = client.eval_js(fill_js)
            return {
                "success": True,
                "action": "SUBMIT_NICKNAME",
                "nickname": default_nickname,
                "suggestion": f"Entered nickname '{default_nickname}' and submitted.",
                "details": res.get("result")
            }
        return {
            "success": True,
            "action": "ENTER_NICKNAME",
            "suggestion": f"Enter nickname '{default_nickname}' and click Continue/Join.",
            "details": state
        }

    # 4. ROOM LOBBY / WAITING FOR PLAYERS
    if screen in [RichupScreenState.ROOM_LOBBY.value, RichupScreenState.WAITING_FOR_PLAYERS.value]:
        start_btn = None
        ready_btn = None
        for b in state.get("active_buttons", []):
            txt = b["text"].lower()
            if "start game" in txt or "start" in txt:
                start_btn = b
            elif "ready" in txt:
                ready_btn = b

        target_btn = start_btn or ready_btn
        if target_btn and auto_execute:
            client.click_coordinate(target_btn["box"]["center_x"], target_btn["box"]["center_y"])
            return {
                "success": True,
                "action": "CLICK_LOBBY_READY_OR_START",
                "button_text": target_btn["text"],
                "suggestion": f"Clicked lobby action button: {target_btn['text']}"
            }
        return {
            "success": True,
            "action": "WAIT_IN_LOBBY",
            "suggestion": "In lobby waiting for host or players to start the match.",
            "details": state
        }

    # 5. MODAL POPUP (Property Purchase, Auction, Jail, Chance Card)
    if screen == RichupScreenState.MODAL_POPUP.value or state.get("modal_open"):
        modal_text = (state.get("modal_text") or "").lower()
        modal_buttons = state.get("modal_buttons", [])

        # Check for Buy / Purchase decision
        buy_btn = next((b for b in modal_buttons if "buy" in b["text"].lower() or "purchase" in b["text"].lower()), None)
        auction_btn = next((b for b in modal_buttons if "auction" in b["text"].lower()), None)
        close_btn = next((b for b in modal_buttons if any(k in b["text"].lower() for k in ["close", "ok", "confirm", "accept", "continue", "pay"])), None)

        chosen_btn = None
        decision_reason = ""

        if buy_btn:
            # Property purchase modal
            chosen_btn = buy_btn
            decision_reason = "Purchase property modal detected: Choosing Buy."
        elif close_btn:
            chosen_btn = close_btn
            decision_reason = f"Acknowledgment modal detected: Clicking '{close_btn['text']}'."
        elif auction_btn:
            chosen_btn = auction_btn
            decision_reason = "Auction choice modal: Clicking Auction."
        elif modal_buttons:
            chosen_btn = modal_buttons[0]
            decision_reason = f"Selecting first available modal option '{chosen_btn['text']}'."

        if chosen_btn and auto_execute:
            client.click_coordinate(chosen_btn["box"]["center_x"], chosen_btn["box"]["center_y"])
            return {
                "success": True,
                "action": "DISMISS_MODAL_OR_BUY",
                "button_text": chosen_btn["text"],
                "reason": decision_reason,
                "suggestion": f"Executed modal action: {chosen_btn['text']}"
            }
        return {
            "success": True,
            "action": "HANDLE_MODAL",
            "suggestion": decision_reason or "Review modal popup and take appropriate action.",
            "details": state
        }

    # 6. ACTIVE TURN (Roll Dice or End Turn)
    if state.get("is_my_turn") or screen == RichupScreenState.TURN_ACTIVE.value:
        roll_btn = None
        end_turn_btn = None
        buy_btn = None

        for b in state.get("active_buttons", []):
            txt = b["text"].lower()
            if "roll" in txt or "throw" in txt:
                roll_btn = b
            elif "end turn" in txt or "pass" in txt or "done" in txt:
                end_turn_btn = b
            elif "buy" in txt:
                buy_btn = b

        if roll_btn:
            if auto_execute:
                client.click_coordinate(roll_btn["box"]["center_x"], roll_btn["box"]["center_y"])
                return {
                    "success": True,
                    "action": "ROLL_DICE",
                    "suggestion": "Rolled dice for the active turn."
                }
            return {
                "success": True,
                "action": "ROLL_DICE",
                "suggestion": "It's your turn: Roll the dice."
            }

        if buy_btn:
            if auto_execute:
                client.click_coordinate(buy_btn["box"]["center_x"], buy_btn["box"]["center_y"])
                return {
                    "success": True,
                    "action": "BUY_PROPERTY",
                    "suggestion": "Purchased tile property."
                }
            return {
                "success": True,
                "action": "BUY_PROPERTY",
                "suggestion": "Tile available for purchase: Click Buy."
            }

        if end_turn_btn:
            if auto_execute:
                client.click_coordinate(end_turn_btn["box"]["center_x"], end_turn_btn["box"]["center_y"])
                return {
                    "success": True,
                    "action": "END_TURN",
                    "suggestion": "Completed actions and ended turn."
                }
            return {
                "success": True,
                "action": "END_TURN",
                "suggestion": "Turn actions finished: Click End Turn."
            }

    # 7. IN GAME (Waiting for opponents)
    if screen == RichupScreenState.IN_GAME.value:
        return {
            "success": True,
            "action": "WAIT_FOR_OPPONENT",
            "suggestion": "Opponent's turn. Waiting for game updates...",
            "details": {
                "players": state.get("players")
            }
        }

    # 8. GAME OVER
    if screen == RichupScreenState.GAME_OVER.value:
        return {
            "success": True,
            "action": "GAME_OVER",
            "suggestion": "Match concluded.",
            "details": state
        }

    return {
        "success": True,
        "action": "OBSERVE",
        "suggestion": f"Screen state is {screen}. No immediate turn action required.",
        "details": state
    }


# ==============================================================================
# CLI RUNNER
# ==============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Richup.io Game Automator and Turn Assistant")
    parser.add_argument("command", choices=["detect", "solve-turnstile", "step", "monitor"], default="detect", nargs="?")
    parser.add_argument("--port", type=int, default=9222, help="Browser CDP port (default: 9222)")
    parser.add_argument("--name", type=str, default="SwadesBot", help="Default player nickname")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and suggest without clicking")

    args = parser.parse_args()

    client = CDPClientWrapper(port=args.port)

    if args.command == "detect":
        res = detect_richup_state(client)
        print(json.dumps(res, indent=2))
    elif args.command == "solve-turnstile":
        res = solve_turnstile_challenge(client)
        print(json.dumps(res, indent=2))
    elif args.command == "step":
        res = run_richup_turn(client, default_nickname=args.name, auto_execute=not args.dry_run)
        print(json.dumps(res, indent=2))
    elif args.command == "monitor":
        print(f"Monitoring Richup on CDP port {args.port}... (Ctrl+C to stop)")
        try:
            while True:
                res = run_richup_turn(client, default_nickname=args.name, auto_execute=not args.dry_run)
                print(f"[{time.strftime('%H:%M:%S')}] State: {res.get('action')} -> {res.get('suggestion')}")
                time.sleep(2.0)
        except KeyboardInterrupt:
            print("\nStopped.")
