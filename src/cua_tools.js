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
      description: "Navigate the web browser directly to a URL using Playwright. Automatically returns the updated compact indexed DOM snapshot ([@0], [@1], ...).",
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
      description: "Inspect the live webpage using Playwright. Returns compact indexed DOM ([@0], [@1], ...), page title, URL, search result cards, main content text summary, and element attributes.",
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
      description: "Click a button, link, or interactive element on the current webpage by its closed-world index from the compact DOM (e.g. 0 for [@0]). Executes multi-tier dispatch (DOM click -> synthetic events -> CDP coordinate click) and automatically returns the updated observation.",
      parameters: {
        type: "object",
        properties: {
          index: { type: "integer", description: "The integer index of the element to click (e.g. 0 for [@0], 1 for [@1])" }
        },
        required: ["index"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_type",
      description: "Type text into an input field or textarea by its closed-world index from the compact DOM (e.g. 1 for [@1]). Supports clearing previous text and pressing Enter to submit.",
      parameters: {
        type: "object",
        properties: {
          index: { type: "integer", description: "The integer index of the input element (e.g. 1 for [@1])" },
          text: { type: "string", description: "Text content to type" },
          clear: { type: "boolean", description: "Whether to clear existing text before typing (default true)" },
          submit: { type: "boolean", description: "Whether to submit the form or press Enter after typing (default false)" }
        },
        required: ["index", "text"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_select",
      description: "Select an option from a dropdown (<select>) element by its closed-world index from the compact DOM (e.g. 2 for [@2]). Automatically returns updated observation.",
      parameters: {
        type: "object",
        properties: {
          index: { type: "integer", description: "The integer index of the select element (e.g. 2 for [@2])" },
          value: { type: "string", description: "The option text or value to select" }
        },
        required: ["index", "value"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_scroll",
      description: "Scroll the webpage smoothly up or down. Automatically returns the newly visible compact indexed DOM snapshot.",
      parameters: {
        type: "object",
        properties: {
          direction: { type: "string", enum: ["up", "down", "left", "right"], description: "Scroll direction (default 'down')" },
          amount: { type: "integer", description: "Pixels to scroll (default 500)" }
        },
        required: ["direction"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_wait",
      description: "Wait for a specified number of seconds to let dynamic page content or SPA animations settle, and return a fresh compact indexed snapshot.",
      parameters: {
        type: "object",
        properties: {
          seconds: { type: "number", description: "Number of seconds to wait (default 1.0)" }
        },
        required: ["seconds"]
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
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_select"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_scroll"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "browser_wait"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "desktop_window_control"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "desktop_interact"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "run_command")
];

export async function executeCuaTool(name, args = {}) {
  switch (name) {
    case "browser_navigate":
    case "open_browser_url": {
      const url = args.url || "https://google.com";
      const payload = JSON.stringify({ action: "navigate", url });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_snapshot":
    case "read_screen_tree": {
      const payload = JSON.stringify({ action: "snapshot" });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_click": {
      const index = args.index !== undefined ? args.index : (args.target !== undefined ? args.target : 0);
      const payload = JSON.stringify({ action: "click", index });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_type": {
      const index = args.index !== undefined ? args.index : (args.target !== undefined ? args.target : 0);
      const text = args.text || "";
      const clear = args.clear !== undefined ? Boolean(args.clear) : true;
      const submit = Boolean(args.submit || args.press_enter);
      const payload = JSON.stringify({ action: "type", index, text, clear, submit });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_select": {
      const index = args.index !== undefined ? args.index : (args.target !== undefined ? args.target : 0);
      const value = args.value || "";
      const payload = JSON.stringify({ action: "select", index, value });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_scroll":
    case "mouse_scroll": {
      const direction = args.direction || "down";
      const amount = Number(args.amount || 500);
      const payload = JSON.stringify({ action: "scroll", direction, amount });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "browser_wait": {
      const seconds = Number(args.seconds || 1.0);
      const payload = JSON.stringify({ action: "wait", seconds });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "desktop_window_control": {
      const action = args.action || "list";
      const target = args.target || "";
      const payload = JSON.stringify({ action: "windows", target_action: action, action_type: action, action, target });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "list_open_windows": {
      const payload = JSON.stringify({ action: "windows", action_type: "list" });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "window_control": {
      const action = args.action || "close";
      const target = args.title || "";
      const payload = JSON.stringify({ action: "windows", action_type: action, action, target });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "desktop_interact": {
      const action = args.action || "click";
      const payload = JSON.stringify({ action: "interact", action_type: action, x: args.x, y: args.y, keys: args.keys });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "mouse_click": {
      const payload = JSON.stringify({ action: "interact", action_type: "click", x: args.x || 0, y: args.y || 0 });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "type_keys": {
      const action_type = args.is_shortcut ? "key" : "type";
      const payload = JSON.stringify({ action: "interact", action_type, keys: args.keys || "" });
      return await runCommand(`python3 "${NATIVE_CUA_ENGINE_PY}" --json '${payload.replace(/'/g, "'\\''")}'`);
    }

    case "run_command":
    case "run_os_command": {
      return await runCommand(args.command || "");
    }

    default:
      return JSON.stringify({ error: `Unknown tool: ${name}` });
  }
}
