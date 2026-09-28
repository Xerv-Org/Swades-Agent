import { exec } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SCRIPT_DIR = __dirname;
const NATIVE_CUA_ENGINE_PY = resolve(SCRIPT_DIR, "native_cua_engine.py");

export function runCommand(cmd, envExtra = {}) {
  return new Promise((resolvePromise) => {
    exec(cmd, {
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || (existsSync("/tmp/.X11-unix/X99") ? ":99" : ":0"),
        PYTHONPATH: "/usr/lib/python3/dist-packages:" + (process.env.PYTHONPATH || ""),
        ...envExtra
      },
      timeout: 25000,
      killSignal: "SIGKILL",
      maxBuffer: 10 * 1024 * 1024
    }, (err, stdout, stderr) => {
      if (err) {
        if (err.killed || err.signal === "SIGKILL") {
          resolvePromise("⚠️ [TIMEOUT TERMINATED] Command exceeded time limit.");
        } else {
          resolvePromise(stdout ? `${stdout}\nError: ${stderr || err.message}` : `Error: ${stderr || err.message}`);
        }
      } else {
        resolvePromise(stdout.trim() || stderr.trim() || "OK");
      }
    });
  });
}

function runNativeCua(args = []) {
  const sanitizedArgs = args.map(a => `"${String(a).replace(/"/g, '\\"')}"`).join(" ");
  return runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" ${sanitizedArgs}`);
}

export const CUA_TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "browser_navigate",
      description: "Navigate the web browser directly to a URL using Playwright. Launches browser on desktop display automatically if not already running.",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL or search query URL (e.g. 'https://www.google.com/search?q=AMD+MI300X+specs')" }
        },
        required: ["url"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_snapshot",
      description: "Inspect the live webpage using Playwright. Returns page title, URL, structured search result cards, main content text summary, and clickable interactive elements.",
      parameters: {
        type: "object",
        properties: {},
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_click",
      description: "Click a button, link, or element on the current webpage by text name, role, or selector using Playwright.",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Visible text, role, or CSS selector of the button/link to click" }
        },
        required: ["target"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_type",
      description: "Type text into an input field or search bar on the webpage using Playwright.",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Placeholder, label, role, or selector of the input field" },
          text: { type: "string", description: "Text content to type" },
          press_enter: { type: "boolean", description: "Whether to hit Enter after typing (default false)" }
        },
        required: ["target", "text"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_scroll",
      description: "Scroll the webpage smoothly up or down using Playwright.",
      parameters: {
        type: "object",
        properties: {
          direction: { type: "string", enum: ["up", "down"], description: "Scroll direction (default 'down')" },
          amount: { type: "integer", description: "Pixels to scroll (default 500)" }
        },
        required: ["direction"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "desktop_window_control",
      description: "Manage native desktop application windows: 'list' (list open windows), 'focus' (bring window to front), 'close' (close window or 'all').",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["list", "focus", "close"], description: "Window operation" },
          target: { type: "string", description: "Window title substring or 'all' for close" }
        },
        required: ["action"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "desktop_interact",
      description: "Interact with native desktop windows outside the browser (click coordinates, type keys, or press shortcuts).",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["click", "type", "key"], description: "Interaction type" },
          x: { type: "integer", description: "Screen X coordinate for click" },
          y: { type: "integer", description: "Screen Y coordinate for click" },
          keys: { type: "string", description: "Keys to type or shortcut (e.g. 'ctrl+s', 'Return', or text)" }
        },
        required: ["action"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "run_command",
      description: "Execute a bash shell command on the host environment.",
      parameters: {
        type: "object",
        properties: {
          command: { type: "string", description: "Shell command to run" }
        },
        required: ["command"]
      }
    }
  },
  // Legacy aliases for seamless backwards compatibility
  {
    type: "function",
    function: {
      name: "read_screen_tree",
      description: "Inspect the screen content and elements (alias for browser_snapshot).",
      parameters: { type: "object", properties: {}, required: [] }
    }
  },
  {
    type: "function",
    function: {
      name: "mouse_scroll",
      description: "Scroll page (alias for browser_scroll).",
      parameters: {
        type: "object",
        properties: {
          direction: { type: "string", enum: ["up", "down"] },
          amount: { type: "integer" }
        },
        required: ["direction"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "list_open_windows",
      description: "List open windows (alias for desktop_window_control list).",
      parameters: { type: "object", properties: {}, required: [] }
    }
  },
  {
    type: "function",
    function: {
      name: "window_control",
      description: "Control window (alias for desktop_window_control).",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string" },
          action: { type: "string", enum: ["close", "maximize", "minimize"] }
        },
        required: ["title", "action"]
      }
    }
  }
];

export const CUA_MINIMAL_TOOL_SCHEMAS = [
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_navigate"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_snapshot"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_click"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_type"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_scroll"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "desktop_window_control"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "desktop_interact"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "run_command")
];

export async function executeCuaTool(name, args = {}) {
  switch (name) {
    case "browser_navigate":
    case "open_browser_url": {
      const url = args.url || "https://google.com";
      return await runNativeCua(["navigate", url]);
    }

    case "browser_snapshot":
    case "read_screen_tree": {
      return await runNativeCua(["snapshot"]);
    }

    case "browser_click": {
      const target = args.target || "";
      return await runNativeCua(["click", target]);
    }

    case "browser_type": {
      const target = args.target || "";
      const text = args.text || "";
      const enterFlag = args.press_enter ? ["--enter"] : [];
      return await runNativeCua(["type", target, text, ...enterFlag]);
    }

    case "browser_scroll":
    case "mouse_scroll": {
      const dir = args.direction || "down";
      const amt = String(args.amount || 500);
      return await runNativeCua(["scroll", dir, amt]);
    }

    case "desktop_window_control": {
      const act = args.action || "list";
      const target = args.target || "";
      return await runNativeCua(["windows", act, target]);
    }

    case "list_open_windows": {
      return await runNativeCua(["windows", "list"]);
    }

    case "window_control": {
      const act = args.action || "close";
      const target = args.title || "";
      return await runNativeCua(["windows", act, target]);
    }

    case "desktop_interact": {
      const act = args.action || "click";
      if (act === "click") {
        return await runNativeCua(["interact", "click", String(args.x || 0), String(args.y || 0)]);
      }
      return await runNativeCua(["interact", act, String(args.keys || "")]);
    }

    case "mouse_click": {
      return await runNativeCua(["interact", "click", String(args.x || 0), String(args.y || 0)]);
    }

    case "type_keys": {
      const act = args.is_shortcut ? "key" : "type";
      return await runNativeCua(["interact", act, String(args.keys || "")]);
    }

    case "run_command":
    case "run_os_command": {
      return await runCommand(args.command || "");
    }

    default:
      return JSON.stringify({ error: `Unknown tool: ${name}` });
  }
}
