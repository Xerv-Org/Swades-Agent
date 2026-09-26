#!/usr/bin/env python3
"""
web_copilot_server.py — Clean Antigravity-Style Copilot Studio & Live Desktop Stream
Features:
- Live process status tracking (/api/status & log completion detection)
- Collapsible "Worked for Xs ▶" thinking accordions (collapsed by default)
- Tool execution disclosure cards with clean syntax styling
- Clean markdown final response rendering
- Suggestion chips & instant action bar
- Live 1920x1080 virtual desktop stream in right pane
"""

import os
import sys
import json
import time
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

PORT = 8080
LOGS_FILE = "/tmp/swades_chat_logs.json"

current_worker = None
is_task_running = False

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Swades Copilot Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-canvas: #090d16;
      --bg-panel: #0f172a;
      --bg-card: #1e293b;
      --bg-code: #0b1120;
      --border: #334155;
      --border-subtle: #1e293b;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --success: #34d399;
      --warning: #fbbf24;
      --danger: #f87171;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-canvas);
      color: var(--text-main);
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      font-size: 14px;
    }
    header {
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      height: 54px;
      flex-shrink: 0;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-logo {
      background: linear-gradient(135deg, #0284c7, #38bdf8);
      width: 28px;
      height: 28px;
      border-radius: 6px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 15px;
      font-weight: 700;
      color: #fff;
    }
    .brand-title {
      font-size: 15px;
      font-weight: 700;
      letter-spacing: -0.2px;
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 10px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 600;
      background: rgba(52, 211, 153, 0.12);
      color: var(--success);
      border: 1px solid rgba(52, 211, 153, 0.25);
      transition: all 0.2s ease;
    }
    .status-badge.busy {
      background: rgba(56, 189, 248, 0.12);
      color: var(--accent);
      border-color: rgba(56, 189, 248, 0.25);
    }
    .status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    .layout-root {
      display: flex;
      flex: 1;
      height: calc(100vh - 54px);
      overflow: hidden;
    }
    /* Left Chat Pane */
    .chat-pane {
      width: 500px;
      min-width: 400px;
      max-width: 680px;
      background: var(--bg-panel);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    .chips-bar {
      padding: 10px 16px 6px;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      flex-shrink: 0;
      border-bottom: 1px solid var(--border-subtle);
    }
    .chip-item {
      background: var(--bg-card);
      border: 1px solid var(--border);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-muted);
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s ease;
    }
    .chip-item:hover {
      background: #334155;
      color: #fff;
      border-color: #64748b;
    }
    .messages-scroll {
      flex: 1;
      padding: 16px 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    /* User Message */
    .user-msg {
      align-self: flex-end;
      max-width: 88%;
      background: #0284c7;
      color: #ffffff;
      padding: 10px 14px;
      border-radius: 12px 12px 2px 12px;
      font-size: 13.5px;
      line-height: 1.45;
      word-break: break-word;
    }
    /* Collapsible Thought Header ("Worked for Xs ▶") */
    .accordion-header {
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-dim);
      font-size: 12.5px;
      font-weight: 500;
      cursor: pointer;
      user-select: none;
      padding: 4px 0;
      transition: color 0.15s ease;
    }
    .accordion-header:hover {
      color: var(--text-muted);
    }
    .accordion-icon {
      font-size: 9px;
      transition: transform 0.2s ease;
      display: inline-block;
    }
    .accordion-header.open .accordion-icon {
      transform: rotate(90deg);
    }
    .accordion-body {
      display: none;
      margin-top: 6px;
      margin-bottom: 8px;
    }
    .accordion-body.open {
      display: block;
    }
    /* Tool card with embedded output box */
    .tool-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-top: 6px;
      font-size: 12px;
    }
    .tool-header {
      padding: 7px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      background: rgba(255, 255, 255, 0.02);
      font-weight: 500;
      color: var(--text-muted);
    }
    .tool-header:hover {
      background: rgba(255, 255, 255, 0.04);
      color: var(--text-main);
    }
    .tool-title-grp {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .tool-badge {
      font-size: 10.5px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
      background: rgba(56, 189, 248, 0.15);
      color: var(--accent);
    }
    .tool-body {
      background: var(--bg-code);
      border-top: 1px solid var(--border);
      padding: 10px 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11.5px;
      line-height: 1.5;
      color: #bae6fd;
      max-height: 200px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }
    /* Assistant Response Message */
    .assistant-msg {
      color: var(--text-main);
      font-size: 13.5px;
      line-height: 1.55;
    }
    .assistant-msg p {
      margin-bottom: 8px;
    }
    .assistant-msg table {
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0;
      font-size: 12px;
    }
    .assistant-msg th, .assistant-msg td {
      border: 1px solid var(--border);
      padding: 6px 10px;
      text-align: left;
    }
    .assistant-msg th {
      background: var(--bg-card);
      color: var(--accent);
    }
    /* Footer Input */
    .input-bar {
      padding: 14px 16px;
      background: var(--bg-panel);
      border-top: 1px solid var(--border);
      display: flex;
      gap: 10px;
      align-items: center;
      flex-shrink: 0;
    }
    .task-entry {
      flex: 1;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 11px 14px;
      font-family: inherit;
      font-size: 13.5px;
      color: #fff;
      outline: none;
      transition: all 0.15s ease;
    }
    .task-entry:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
    }
    .send-button {
      background: #0284c7;
      border: none;
      border-radius: 8px;
      color: #fff;
      padding: 11px 18px;
      font-weight: 600;
      font-size: 13.5px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: background 0.15s ease;
    }
    .send-button:hover {
      background: #0369a1;
    }
    .send-button:disabled {
      background: #334155;
      cursor: not-allowed;
    }
    /* Right Screen Stream */
    .stream-pane {
      flex: 1;
      background: #000;
      display: flex;
      flex-direction: column;
    }
    .stream-bar {
      background: var(--bg-panel);
      border-bottom: 1px solid var(--border);
      padding: 10px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 12.5px;
      color: var(--text-muted);
      font-weight: 500;
    }
    .stream-frame {
      flex: 1;
      width: 100%;
      height: 100%;
      border: none;
      background: #000;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-logo">⚡</div>
      <div class="brand-title">Swades Copilot Studio</div>
    </div>
    <div style="display:flex; align-items:center; gap:12px;">
      <div class="status-badge" id="statusBadge">
        <span class="status-dot"></span>
        <span id="statusLabel">Ready</span>
      </div>
      <button onclick="clearSession()" style="background:transparent; border:1px solid var(--border); color:var(--text-muted); border-radius:6px; padding:4px 8px; font-size:12px; cursor:pointer;" title="Clear session">🗑️ Clear</button>
    </div>
  </header>

  <div class="layout-root">
    <!-- Chat Pane -->
    <div class="chat-pane">
      <div class="chips-bar">
        <button class="chip-item" onclick="triggerChip('Open Chromium and search for latest AI news')">🌐 Browse Web</button>
        <button class="chip-item" onclick="triggerChip('List open user windows')">🔍 Scan Windows</button>
        <button class="chip-item" onclick="triggerChip('Close all open windows')">❌ Close All</button>
      </div>

      <div class="messages-scroll" id="messagesScroll">
        <!-- Messages rendered here -->
      </div>

      <div class="input-bar">
        <input type="text" id="taskInput" class="task-entry" placeholder="Ask Swades to do anything on your desktop..." autofocus onkeydown="if(event.key==='Enter') sendTask()">
        <button class="send-button" id="sendBtn" onclick="sendTask()">
          <span>Run</span>
          <span>⚡</span>
        </button>
      </div>
    </div>

    <!-- Live Desktop Stream Pane -->
    <div class="stream-pane">
      <div class="stream-bar">
        <span>🖥️ Live Virtual Desktop (1920x1080)</span>
        <a id="extLink" href="#" target="_blank" style="color:var(--accent); text-decoration:none; font-weight:600; font-size:12px;">Open Fullscreen ↗</a>
      </div>
      <iframe id="streamIframe" class="stream-frame" src=""></iframe>
    </div>
  </div>

  <script>
    const streamUrl = "http://" + window.location.hostname + ":6080/vnc.html?autoconnect=true&resize=scale";
    document.getElementById("streamIframe").src = streamUrl;
    document.getElementById("extLink").href = streamUrl;

    let lastLogStr = "";
    let isWorking = false;

    async function poll() {
      try {
        // 1. Poll logs
        const res = await fetch('/api/logs');
        if (res.ok) {
          const logs = await res.json();
          const str = JSON.stringify(logs);
          if (str !== lastLogStr) {
            lastLogStr = str;
            renderConversation(logs);
          }
        }

        // 2. Poll server process status
        const statusRes = await fetch('/api/status');
        if (statusRes.ok) {
          const data = await statusRes.json();
          if (data.busy !== isWorking) {
            setWorking(data.busy);
          }
        }
      } catch (err) {}
      setTimeout(poll, 400);
    }

    function renderConversation(logs) {
      const container = document.getElementById("messagesScroll");
      if (!logs || logs.length === 0) {
        container.innerHTML = `
          <div style="color:var(--text-dim); text-align:center; padding-top:40px; font-size:13px;">
            <div style="font-size:24px; margin-bottom:8px;">⚡</div>
            <div>Swades Autonomous Desktop Copilot</div>
            <div style="margin-top:4px; font-size:12px;">Type any task below or click a suggestion chip to begin.</div>
          </div>
        `;
        return;
      }

      let html = "";
      let currentTurn = { user: null, steps: [], thoughts: [], actions: [], done: null, message: null };
      let lastMsgType = "";

      function flushTurn(isLastTurn) {
        if (!currentTurn.user && currentTurn.steps.length === 0 && !currentTurn.message && !currentTurn.done) return;

        let turnHtml = "";
        if (currentTurn.user) {
          turnHtml += `<div class="user-msg">${escapeHtml(currentTurn.user.text)}</div>`;
        }

        const hasWork = currentTurn.thoughts.length > 0 || currentTurn.actions.length > 0 || currentTurn.steps.length > 0;
        if (hasWork) {
          const count = currentTurn.steps.length || 1;
          const openClass = (isLastTurn && isWorking) ? "open" : "";
          turnHtml += `
            <div class="turn-group" style="margin-top:4px;">
              <div class="accordion-header ${openClass}" onclick="toggleAccordion(this)">
                <span class="accordion-icon">▶</span>
                <span>Worked for ${count * 2}s</span>
              </div>
              <div class="accordion-body ${openClass}">
          `;

          for (let item of currentTurn.thoughts) {
            turnHtml += `<div style="color:var(--text-muted); font-size:12px; margin-bottom:6px; font-style:italic;">💭 ${escapeHtml(item.text)}</div>`;
          }

          for (let act of currentTurn.actions) {
            turnHtml += `
              <div class="tool-card">
                <div class="tool-header" onclick="toggleToolCard(this)">
                  <div class="tool-title-grp">
                    <span class="tool-badge">Tool</span>
                    <span>${escapeHtml(act.toolName)}</span>
                  </div>
                  <span style="font-size:10px;">▼</span>
                </div>
                <div class="tool-body">${escapeHtml(act.output || "Completed")}</div>
              </div>
            `;
          }

          turnHtml += `</div></div>`;
        }

        const finalMsg = currentTurn.done?.text || currentTurn.message?.text;
        if (finalMsg) {
          turnHtml += `<div class="assistant-msg">${formatMarkdown(finalMsg)}</div>`;
        }

        html += `<div style="display:flex; flex-direction:column; gap:10px;">${turnHtml}</div>`;
        currentTurn = { user: null, steps: [], thoughts: [], actions: [], done: null, message: null };
      }

      let currentAction = null;
      for (let i = 0; i < logs.length; i++) {
        const msg = logs[i];
        const sender = msg.sender || "";
        const text = msg.text || "";
        lastMsgType = sender;

        if (sender === "User") {
          flushTurn(false);
          currentTurn.user = msg;
        } else if (sender === "AI Step") {
          currentTurn.steps.push(msg);
        } else if (sender === "AI Thought") {
          currentTurn.thoughts.push(msg);
        } else if (sender === "AI Action") {
          currentAction = { toolName: text.replace(/^🔧\s*Tool:\s*/, ""), output: "" };
          currentTurn.actions.push(currentAction);
        } else if (sender === "Observation") {
          if (currentAction) {
            currentAction.output = text;
          } else {
            currentTurn.actions.push({ toolName: "Observation", output: text });
          }
        } else if (sender === "AI Message") {
          currentTurn.message = msg;
        } else if (sender === "AI Done") {
          currentTurn.done = msg;
        }
      }
      flushTurn(true);

      // Auto clear working state if last log message is AI Done / AI Message
      if (lastMsgType === "AI Done" || lastMsgType === "AI Message") {
        if (isWorking) {
          setWorking(false);
        }
      }

      container.innerHTML = html;
      container.scrollTop = container.scrollHeight;
    }

    function toggleAccordion(el) {
      el.classList.toggle("open");
      const body = el.nextElementSibling;
      if (body) body.classList.toggle("open");
    }

    function toggleToolCard(el) {
      const body = el.nextElementSibling;
      if (body) {
        body.style.display = (body.style.display === "none") ? "block" : "none";
      }
    }

    function formatMarkdown(text) {
      if (!text) return "";
      let t = escapeHtml(text);
      t = t.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      t = t.replace(/\*(.*?)\*/g, '<em>$1</em>');
      t = t.replace(/`([^`]+)`/g, '<code style="background:#0b1120; padding:2px 5px; border-radius:4px; font-family:monospace; color:#38bdf8;">$1</code>');
      
      if (t.includes('|')) {
        const lines = t.split('\\n');
        let inTable = false;
        let tableHtml = '<table>';
        let res = [];
        for (let line of lines) {
          if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
            if (!inTable) {
              inTable = true;
              tableHtml = '<table>';
            }
            if (line.includes('---')) continue;
            const cells = line.split('|').filter((_, i, arr) => i > 0 && i < arr.length - 1);
            const tag = (tableHtml === '<table>') ? 'th' : 'td';
            tableHtml += '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>';
          } else {
            if (inTable) {
              inTable = false;
              tableHtml += '</table>';
              res.push(tableHtml);
            }
            res.push(line);
          }
        }
        if (inTable) {
          tableHtml += '</table>';
          res.push(tableHtml);
        }
        t = res.join('<br>');
      } else {
        t = t.replace(/\\n/g, '<br>');
      }

      return t;
    }

    function escapeHtml(text) {
      const div = document.createElement("div");
      div.innerText = text;
      return div.innerHTML;
    }

    async function sendTask() {
      const input = document.getElementById("taskInput");
      const text = input.value.trim();
      if (!text || isWorking) return;

      input.value = "";
      setWorking(true);

      try {
        await fetch("/api/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ task: text })
        });
      } catch (err) {
        console.error(err);
      }
    }

    function triggerChip(prompt) {
      const input = document.getElementById("taskInput");
      input.value = prompt;
      sendTask();
    }

    async function clearSession() {
      await fetch("/api/clear", { method: "POST" });
      lastLogStr = "";
      renderConversation([]);
      setWorking(false);
    }

    function setWorking(working) {
      isWorking = working;
      const badge = document.getElementById("statusBadge");
      const label = document.getElementById("statusLabel");
      const btn = document.getElementById("sendBtn");

      if (working) {
        badge.className = "status-badge busy";
        label.innerText = "Working...";
        btn.disabled = true;
        btn.innerHTML = "<span>...</span>";
      } else {
        badge.className = "status-badge";
        label.innerText = "Ready";
        btn.disabled = false;
        btn.innerHTML = "<span>Run</span><span>⚡</span>";
      }
    }

    window.onload = () => {
      poll();
    };
  </script>
</body>
</html>
"""

class CopilotHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        global current_worker, is_task_running
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ["/", "/index.html"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        elif parsed.path == "/api/status":
            busy = is_task_running or (current_worker is not None and current_worker.poll() is None)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"busy": busy}).encode("utf-8"))
        elif parsed.path == "/api/logs":
            logs = []
            if os.path.exists(LOGS_FILE):
                try:
                    with open(LOGS_FILE, "r") as f:
                        logs = json.load(f)
                except Exception:
                    logs = []
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(logs).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global current_worker, is_task_running
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/task":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
            task = data.get("task", "").strip()

            if task:
                now = time.strftime("%H:%M:%S")
                logs = []
                if os.path.exists(LOGS_FILE):
                    try:
                        with open(LOGS_FILE, "r") as f:
                            logs = json.load(f)
                    except Exception:
                        logs = []
                logs.append({"sender": "User", "text": task, "time": now})
                try:
                    with open(LOGS_FILE, "w") as f:
                        json.dump(logs[-300:], f, indent=2)
                except Exception:
                    pass

                def _run():
                    global current_worker, is_task_running
                    is_task_running = True
                    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    env = os.environ.copy()
                    env["DISPLAY"] = ":99"
                    env["SWADES_CUA_MODE"] = "true"
                    p = subprocess.Popen(
                        ["node", "src/index.js", "cua", task],
                        cwd=proj_root,
                        env=env,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    current_worker = p
                    p.wait()
                    is_task_running = False

                threading.Thread(target=_run, daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

        elif parsed.path == "/api/clear":
            global is_task_running, current_worker
            if current_worker and current_worker.poll() is None:
                try:
                    current_worker.terminate()
                except Exception:
                    pass
            is_task_running = False
            try:
                with open(LOGS_FILE, "w") as f:
                    json.dump([], f)
            except Exception:
                pass
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": True}).encode("utf-8"))

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), CopilotHandler)
    print(f"🚀 Swades Copilot Studio running at http://0.0.0.0:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
