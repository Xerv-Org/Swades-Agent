#!/usr/bin/env python3
"""
desktop_hud_overlay.py — Nir Eyal 'Hooked' UX Native Floating HUD Panel for Swades CUA
- Trigger: Single clear prompt & zero-friction quick suggestion chips.
- Action: Effortless single-input submission with Enter or ⚡ Run Task button.
- Variable Reward: Live animated status pulse, real-time ReAct thought & sensory observation stream.
- Investment: Fluid draggable anywhere, persistent session logs, instant context memory.
"""

import sys
import os
import json
import time
import subprocess
import threading
import signal
import tkinter as tk

try:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
except Exception:
    pass

LOGS_FILE = "/tmp/swades_chat_logs.json"

class SwadesDesktopHUD:
    def __init__(self, root):
        self.root = root
        self.root.title("Swades AI Copilot")
        
        # Dimensions & positioning
        self.width = 460
        self.height = 680
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # Position at bottom-right with 24px padding
        x = max(0, self.screen_width - self.width - 24)
        y = max(0, self.screen_height - self.height - 56)
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        self.root.configure(bg="#0b0f19")
        
        # Keep floating on top
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass

        self.last_log_hash = ""
        self._offset_x = 0
        self._offset_y = 0
        self.is_working = False

        self._setup_ui()
        self._poll_logs()

    def _setup_ui(self):
        # 1. Sleek Header Bar (Draggable)
        header = tk.Frame(self.root, bg="#0f172a", height=50, padx=14, pady=10)
        header.pack(side="top", fill="x")
        
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._on_drag)

        left_hdr = tk.Frame(header, bg="#0f172a")
        left_hdr.pack(side="left")
        left_hdr.bind("<ButtonPress-1>", self._start_drag)
        left_hdr.bind("<B1-Motion>", self._on_drag)

        drag_icon = tk.Label(left_hdr, text="⠿", fg="#94a3b8", bg="#0f172a", font=("DejaVu Sans", 13, "bold"), cursor="fleur")
        drag_icon.pack(side="left", padx=(0, 6))
        drag_icon.bind("<ButtonPress-1>", self._start_drag)
        drag_icon.bind("<B1-Motion>", self._on_drag)

        title_lbl = tk.Label(left_hdr, text="⚡ Swades Copilot", fg="#f8fafc", bg="#0f172a", font=("DejaVu Sans", 11, "bold"))
        title_lbl.pack(side="left")
        title_lbl.bind("<ButtonPress-1>", self._start_drag)
        title_lbl.bind("<B1-Motion>", self._on_drag)

        right_hdr = tk.Frame(header, bg="#0f172a")
        right_hdr.pack(side="right")

        close_btn = tk.Label(right_hdr, text="✕", fg="#94a3b8", bg="#0f172a", font=("DejaVu Sans", 10, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=(8, 0))
        close_btn.bind("<ButtonPress-1>", lambda e: self.root.destroy())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg="#f87171"))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg="#94a3b8"))

        clear_btn = tk.Label(right_hdr, text="🗑️", fg="#94a3b8", bg="#0f172a", font=("DejaVu Sans", 10), cursor="hand2")
        clear_btn.pack(side="right", padx=(6, 0))
        clear_btn.bind("<ButtonPress-1>", lambda e: self._clear_logs())

        self.status_badge = tk.Label(
            right_hdr,
            text="● Ready",
            fg="#4ade80",
            bg="#064e3b",
            font=("DejaVu Sans", 8, "bold"),
            padx=8,
            pady=3,
            relief="flat"
        )
        self.status_badge.pack(side="right")

        # 2. Quick Trigger Chips (Zero friction, no choice paralysis)
        chips_frame = tk.Frame(self.root, bg="#0b0f19", padx=10, pady=6)
        chips_frame.pack(side="top", fill="x")

        chips = [
            ("🌐 Browse Web", "Open Chromium and search for latest AI news"),
            ("📝 Open Notes", "Open text editor and take notes"),
            ("🔍 Check Windows", "List open applications and inspect layout")
        ]

        for label, prompt in chips:
            chip_btn = tk.Label(
                chips_frame,
                text=label,
                fg="#cbd5e1",
                bg="#1e293b",
                font=("DejaVu Sans", 8, "bold"),
                padx=8,
                pady=4,
                cursor="hand2",
                relief="flat"
            )
            chip_btn.pack(side="left", padx=(0, 6))
            chip_btn.bind("<ButtonPress-1>", lambda e, p=prompt: self._on_chip_click(p))
            chip_btn.bind("<Enter>", lambda e, w=chip_btn: w.configure(bg="#334155", fg="#ffffff"))
            chip_btn.bind("<Leave>", lambda e, w=chip_btn: w.configure(bg="#1e293b", fg="#cbd5e1"))

        # 3. Live Feed / Stream Area
        chat_container = tk.Frame(self.root, bg="#0b0f19")
        chat_container.pack(side="top", fill="both", expand=True, padx=8, pady=(2, 4))

        self.text_area = tk.Text(
            chat_container,
            bg="#0f172a",
            fg="#f1f5f9",
            wrap="word",
            font=("DejaVu Sans", 9),
            padx=10,
            pady=10,
            relief="flat",
            highlightthickness=1,
            highlightcolor="#1e293b",
            highlightbackground="#1e293b",
            cursor="arrow"
        )
        self.text_area.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(chat_container, command=self.text_area.yview, bg="#0f172a", width=8, relief="flat")
        scrollbar.pack(side="right", fill="y")
        self.text_area.configure(yscrollcommand=scrollbar.set)

        # Style tags
        self.text_area.tag_configure("user_header", foreground="#38bdf8", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("user_body", foreground="#ffffff", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("step_tag", foreground="#facc15", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("thought_header", foreground="#c084fc", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("thought_body", foreground="#cbd5e1", font=("DejaVu Sans", 9))
        self.text_area.tag_configure("message_header", foreground="#94a3b8", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("message_body", foreground="#f8fafc", font=("DejaVu Sans", 9))
        self.text_area.tag_configure("action_header", foreground="#38bdf8", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("action_body", foreground="#bae6fd", font=("DejaVu Sans Mono", 8))
        self.text_area.tag_configure("obs_header", foreground="#34d399", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("obs_body", foreground="#a7f3d0", font=("DejaVu Sans Mono", 8))
        self.text_area.tag_configure("done_tag", foreground="#4ade80", font=("DejaVu Sans", 10, "bold"))
        self.text_area.tag_configure("error_tag", foreground="#f87171", font=("DejaVu Sans", 9, "bold"))
        self.text_area.tag_configure("time_tag", foreground="#64748b", font=("DejaVu Sans", 8))

        self._render_welcome()

        # 4. Zero-Friction Input Footer Bar
        input_bar = tk.Frame(self.root, bg="#0f172a", padx=10, pady=10)
        input_bar.pack(side="bottom", fill="x")

        self.input_entry = tk.Entry(
            input_bar,
            bg="#1e293b",
            fg="#ffffff",
            insertbackground="#38bdf8",
            relief="flat",
            font=("DejaVu Sans", 10),
            highlightthickness=1,
            highlightcolor="#38bdf8",
            highlightbackground="#334155"
        )
        self.input_entry.pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self._on_execute())

        self.exec_btn = tk.Button(
            input_bar,
            text="Run ⚡",
            command=self._on_execute,
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief="flat",
            font=("DejaVu Sans", 9, "bold"),
            padx=14,
            pady=5,
            cursor="hand2"
        )
        self.exec_btn.pack(side="right")

    def _render_welcome(self):
        if not os.path.exists(LOGS_FILE) or os.path.getsize(LOGS_FILE) == 0:
            self.text_area.configure(state="normal")
            self.text_area.insert(tk.END, "⚡ Swades Autonomous Copilot\n", "step_tag")
            self.text_area.insert(tk.END, "Type any task below or click a quick suggestion to begin.\n\n", "message_body")
            self.text_area.configure(state="disabled")

    def _start_drag(self, event):
        self._offset_x = event.x_root - self.root.winfo_x()
        self._offset_y = event.y_root - self.root.winfo_y()

    def _on_drag(self, event):
        x = event.x_root - self._offset_x
        y = event.y_root - self._offset_y
        self.root.geometry(f"+{x}+{y}")

    def _on_chip_click(self, prompt):
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, prompt)
        self._on_execute()

    def _set_status(self, working, text=None):
        self.is_working = working
        if working:
            self.status_badge.configure(text=text or "● Working...", fg="#38bdf8", bg="#082f49")
            self.exec_btn.configure(text="...", state="disabled", bg="#334155")
        else:
            self.status_badge.configure(text="● Ready", fg="#4ade80", bg="#064e3b")
            self.exec_btn.configure(text="Run ⚡", state="normal", bg="#0284c7")

    def _clear_logs(self):
        try:
            with open(LOGS_FILE, "w") as f:
                json.dump([], f)
            self.last_log_hash = ""
            self.text_area.configure(state="normal")
            self.text_area.delete("1.0", tk.END)
            self._render_welcome()
            self.text_area.configure(state="disabled")
            self._set_status(False)
        except Exception:
            pass

    def _on_execute(self):
        text = self.input_entry.get().strip()
        if not text:
            return
        self.input_entry.delete(0, tk.END)
        self._set_status(True, "● Working...")

        now = time.strftime("%H:%M:%S")
        logs = []
        if os.path.exists(LOGS_FILE):
            try:
                with open(LOGS_FILE, "r") as f:
                    logs = json.load(f)
            except Exception:
                logs = []
        logs.append({"sender": "User", "text": text, "time": now})
        try:
            with open(LOGS_FILE, "w") as f:
                json.dump(logs[-300:], f, indent=2)
        except Exception:
            pass

        def _run():
            proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            p = subprocess.Popen(
                ["node", "src/index.js", "cua", text],
                cwd=proj_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            p.wait()
            self.root.after(100, lambda: self._set_status(False))

        threading.Thread(target=_run, daemon=True).start()

    def _poll_logs(self):
        try:
            if os.path.exists(LOGS_FILE):
                with open(LOGS_FILE, "r") as f:
                    raw = f.read()
                    if raw != self.last_log_hash:
                        self.last_log_hash = raw
                        logs = json.loads(raw)
                        self._render_logs(logs)
        except Exception:
            pass
        self.root.after(400, self._poll_logs)

    def _render_logs(self, logs):
        self.text_area.configure(state="normal")
        self.text_area.delete("1.0", tk.END)

        for msg in logs:
            sender = msg.get("sender", "System")
            text = msg.get("text", "")
            msg_time = msg.get("time", "")

            if sender == "User":
                self.text_area.insert(tk.END, f"👤 Task: {text}\n", "user_body")
                self.text_area.insert(tk.END, f"  {msg_time}\n\n", "time_tag")
            elif sender == "AI Step":
                self.text_area.insert(tk.END, f"⚡ {text}  ", "step_tag")
                self.text_area.insert(tk.END, f"{msg_time}\n", "time_tag")
            elif sender == "AI Thought":
                self.text_area.insert(tk.END, f"💭 Reasoning: ", "thought_header")
                self.text_area.insert(tk.END, f"{msg_time}\n", "time_tag")
                self.text_area.insert(tk.END, f"{text}\n\n", "thought_body")
            elif sender == "AI Message":
                self.text_area.insert(tk.END, f"🤖 Swades: ", "message_header")
                self.text_area.insert(tk.END, f"{msg_time}\n", "time_tag")
                self.text_area.insert(tk.END, f"{text}\n\n", "message_body")
            elif sender == "AI Action":
                self.text_area.insert(tk.END, f"🔧 Tool: ", "action_header")
                self.text_area.insert(tk.END, f"{msg_time}\n", "time_tag")
                self.text_area.insert(tk.END, f"{text}\n\n", "action_body")
            elif sender == "Observation":
                self.text_area.insert(tk.END, f"👁️ Observation: ", "obs_header")
                self.text_area.insert(tk.END, f"{msg_time}\n", "time_tag")
                self.text_area.insert(tk.END, f"{text}\n\n", "obs_body")
            elif sender == "AI Done":
                self.text_area.insert(tk.END, f"✅ Complete: {text}\n", "done_tag")
                self.text_area.insert(tk.END, f"  {msg_time}\n\n", "time_tag")
            else:
                self.text_area.insert(tk.END, f"ℹ️ {sender}: {text}\n\n", "message_body")

        self.text_area.see(tk.END)
        self.text_area.configure(state="disabled")

def main():
    if "--test" in sys.argv:
        root = tk.Tk()
        app = SwadesDesktopHUD(root)
        root.update()
        print("Desktop HUD initialized successfully in test mode.")
        root.destroy()
        sys.exit(0)

    # Prevent multiple HUD instances
    lock_file = "/tmp/swades_desktop_hud.pid"
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"Swades Desktop HUD is already running (PID {old_pid}).")
            sys.exit(0)
        except Exception:
            pass

    with open(lock_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        root = tk.Tk()
        app = SwadesDesktopHUD(root)
        root.mainloop()
    finally:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except Exception:
            pass

if __name__ == "__main__":
    main()
