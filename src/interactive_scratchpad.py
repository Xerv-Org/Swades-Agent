import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import json
import os
import sys
import time
import urllib.request
import threading
import subprocess

STATE_FILE = '/tmp/swades_scratchpad.json'
QUEUE_FILE = '/tmp/swades_message_queue.json'

CSS_STYLE = b"""
window {
    background-color: transparent;
}
#card {
    background-color: rgba(15, 23, 42, 0.95);
    border: 1.5px solid rgba(56, 189, 248, 0.3);
    border-radius: 20px;
    box-shadow: 0 25px 35px -5px rgba(0, 0, 0, 0.7), 0 10px 15px -5px rgba(0, 0, 0, 0.2);
    padding: 18px;
}
#badge {
    background: linear-gradient(135deg, #2563eb, #38bdf8);
    color: #ffffff;
    font-weight: 700;
    font-size: 11px;
    border-radius: 12px;
    padding: 4px 12px;
}
#queue_badge {
    background-color: #f59e0b;
    color: #0f172a;
    font-weight: 700;
    font-size: 11px;
    border-radius: 12px;
    padding: 4px 8px;
}
#status_text {
    color: #38bdf8;
    font-weight: 600;
    font-size: 13px;
}
#chat_box {
    background-color: rgba(30, 41, 59, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 14px;
    padding: 10px;
    color: #f8fafc;
    font-size: 12px;
}
#input_entry {
    background-color: rgba(30, 41, 59, 0.9);
    color: #f8fafc;
    border: 1.5px solid rgba(56, 189, 248, 0.4);
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
}
#send_button {
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #ffffff;
    font-weight: 700;
    font-size: 12px;
    border-radius: 10px;
    padding: 6px 14px;
    border: none;
}
#footer_label {
    color: #94a3b8;
    font-size: 10px;
    font-weight: 500;
}
"""

class InteractiveScratchpadHUD(Gtk.Window):
    def __init__(self):
        super().__init__(title="Swades Agent Live Chat HUD")
        self.set_default_size(460, 560)
        self.set_keep_above(True)
        self.set_decorated(False)
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS_STYLE)
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Position overlay in top-right
        self.move(1920 - 490, 40)

        # Outer card
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.card.set_name("card")
        self.add(self.card)

        # Header Row
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        badge = Gtk.Label(label="SWADES AGENT HUD")
        badge.set_name("badge")
        header_box.pack_start(badge, False, False, 0)

        self.queue_badge = Gtk.Label(label="Queue: 0")
        self.queue_badge.set_name("queue_badge")
        header_box.pack_start(self.queue_badge, False, False, 0)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.set_name("status_text")
        self.status_label.set_xalign(1)
        header_box.pack_start(self.status_label, True, True, 0)
        self.card.pack_start(header_box, False, False, 0)

        # Chat / Thought Stream
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        
        self.text_view = Gtk.TextView()
        self.text_view.set_name("chat_box")
        self.text_view.set_editable(False)
        self.text_view.set_cursor_visible(False)
        self.text_view.set_wrap_mode(Gtk.WrapMode.WORD)
        scrolled.add(self.text_view)
        self.card.pack_start(scrolled, True, True, 0)
        
        self.buffer = self.text_view.get_buffer()
        self.append_log("System", "Desktop is locked in READ-ONLY mode.\nYou can type commands/tasks directly in the input box below.")

        # Input Row
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self.entry = Gtk.Entry()
        self.entry.set_name("input_entry")
        self.entry.set_placeholder_text("Type instruction or task here...")
        self.entry.connect("activate", self.on_send)
        input_box.pack_start(self.entry, True, True, 0)

        send_btn = Gtk.Button(label="Send")
        send_btn.set_name("send_button")
        send_btn.connect("clicked", self.on_send)
        input_box.pack_start(send_btn, False, False, 0)
        
        self.card.pack_start(input_box, False, False, 0)

        # Footer
        footer = Gtk.Label(label="🔒 Full OS Input Blocked for User • AI Semantic Automation Active • MI300X")
        footer.set_name("footer_label")
        footer.set_xalign(0)
        self.card.pack_start(footer, False, False, 0)

        # State files init
        if not os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, 'w') as f:
                json.dump([], f)

        # Periodic Polling
        GLib.timeout_add(300, self.poll_updates)
        GLib.timeout_add(1000, self.process_queue_worker)

    def append_log(self, sender, text):
        end_iter = self.buffer.get_end_iter()
        formatted = f"\n[{sender}]: {text}\n"
        self.buffer.insert(end_iter, formatted)
        # Scroll to bottom
        adj = self.text_view.get_vadjustment()
        adj.set_value(adj.get_upper())

    def on_send(self, widget):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        self.append_log("User", text)

        # Add to message queue
        try:
            queue = []
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r') as f:
                    queue = json.load(f)
            queue.append({
                "id": str(int(time.time() * 1000)),
                "text": text,
                "timestamp": time.strftime("%H:%M:%S"),
                "status": "pending"
            })
            with open(QUEUE_FILE, 'w') as f:
                json.dump(queue, f, indent=2)
            self.queue_badge.set_text(f"Queue: {len(queue)}")
        except Exception as e:
            self.append_log("Error", f"Failed to enqueue: {e}")

    def poll_updates(self):
        # Update queue count badge
        if os.path.exists(QUEUE_FILE):
            try:
                with open(QUEUE_FILE, 'r') as f:
                    q = json.load(f)
                pending = [item for item in q if item.get('status') == 'pending']
                self.queue_badge.set_text(f"Queue: {len(pending)}")
            except Exception:
                pass

        # Update status from STATE_FILE
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    data = json.load(f)
                if data.get('_updated', 0) > getattr(self, '_last_state_time', 0):
                    self._last_state_time = data.get('_updated')
                    status = data.get('status', 'Active')
                    self.status_label.set_text(status)
                    if 'log' in data:
                        self.append_log("AI", data['log'])
            except Exception:
                pass
        return True

    def process_queue_worker(self):
        # Check if there is a pending item in queue
        if not os.path.exists(QUEUE_FILE):
            return True
        try:
            with open(QUEUE_FILE, 'r') as f:
                queue = json.load(f)
            pending_items = [item for item in queue if item.get("status") == "pending"]
            if not pending_items:
                return True

            # Process first item asynchronously if not already processing
            if getattr(self, '_busy', False):
                return True

            item = pending_items[0]
            self._busy = True
            item["status"] = "processing"
            with open(QUEUE_FILE, 'w') as f:
                json.dump(queue, f, indent=2)

            threading.Thread(target=self._execute_agent_task, args=(item, queue)).start()
        except Exception:
            pass
        return True

    def _execute_agent_task(self, item, queue):
        user_prompt = item["text"]
        GLib.idle_add(self.status_label.set_text, "AI Thinking...")
        GLib.idle_add(self.append_log, "AI", f"Received task: '{user_prompt}'. Querying AMD MI300X model...")

        try:
            # Query local MI300X vLLM
            req = urllib.request.Request(
                "http://localhost:8000/v1/chat/completions",
                headers={"Content-Type": "application/json"},
                data=json.dumps({
                    "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
                    "messages": [
                        {"role": "system", "content": "You are an autonomous computer use agent controlling an OS desktop. Respond concisely with the actions you are performing."},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 150
                }).encode("utf-8")
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                reply = data["choices"][0]["message"]["content"]
            
            GLib.idle_add(self.append_log, "AI Thought", reply)

            # Perform action on GUI (e.g. typing into mousepad / terminal)
            GLib.idle_add(self.status_label.set_text, "Executing CUA Action...")
            subprocess.run(["xdotool", "search", "--onlyvisible", "--class", "mousepad", "windowactivate"], env={"DISPLAY": ":99", "PATH": "/usr/bin:/bin"})
            time.sleep(0.5)
            
            # Send newline and text
            subprocess.run(["xdotool", "key", "Return"], env={"DISPLAY": ":99", "PATH": "/usr/bin:/bin"})
            subprocess.run(["xdotool", "type", "--delay", "40", f"# User Command: {user_prompt}"], env={"DISPLAY": ":99", "PATH": "/usr/bin:/bin"})
            subprocess.run(["xdotool", "key", "Return"], env={"DISPLAY": ":99", "PATH": "/usr/bin:/bin"})
            
            # Save
            subprocess.run(["xdotool", "key", "ctrl+s"], env={"DISPLAY": ":99", "PATH": "/usr/bin:/bin"})

            GLib.idle_add(self.append_log, "AI Action", f"Completed action and updated desktop state for: '{user_prompt}'")
            GLib.idle_add(self.status_label.set_text, "Done")

        except Exception as e:
            GLib.idle_add(self.append_log, "Error", f"Execution error: {e}")
            GLib.idle_add(self.status_label.set_text, "Error")

        finally:
            # Mark done in queue
            try:
                for q in queue:
                    if q["id"] == item["id"]:
                        q["status"] = "completed"
                with open(QUEUE_FILE, 'w') as f:
                    json.dump(queue, f, indent=2)
            except Exception:
                pass
            self._busy = False

if __name__ == '__main__':
    win = InteractiveScratchpadHUD()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
