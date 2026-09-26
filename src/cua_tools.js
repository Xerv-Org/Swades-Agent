// cua_tools.js — Low-Level Structural Perception & Execution Tools for Swades ReAct CUA
import { exec, spawn } from "node:child_process";
import { resolve } from "node:path";
import net from "node:net";
import { existsSync } from "node:fs";

const SCRIPT_DIR = resolve(process.cwd(), "src");
const SEMANTIC_DESKTOP_PY = resolve(SCRIPT_DIR, "semantic_desktop.py");
const BROWSER_CDP_PY = resolve(SCRIPT_DIR, "browser_cdp.py");
const DAEMON_SOCK = "/tmp/swades_cua.sock";

let daemonProcess = null;

function ensureDaemonRunning() {
  if (!existsSync(DAEMON_SOCK) && !daemonProcess) {
    daemonProcess = spawn("python3", [SEMANTIC_DESKTOP_PY, "--daemon"], {
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || (existsSync("/tmp/.X11-unix/X99") ? ":99" : ":0"),
        PYTHONPATH: "/usr/lib/python3/dist-packages:" + (process.env.PYTHONPATH || "")
      },
      detached: true,
      stdio: "ignore"
    });
    daemonProcess.unref();
  }
}

function runCommand(cmd, envExtra = {}) {
  let cleanCmd = cmd;
  if (cleanCmd.includes("chromium") && !cleanCmd.includes("--no-sandbox")) {
    cleanCmd = cleanCmd.replace(/chromium-browser|chromium/g, "$& --no-sandbox");
  }
  return new Promise((resolve) => {
    exec(cmd, {
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || (existsSync("/tmp/.X11-unix/X99") ? ":99" : ":0"),
        PYTHONPATH: "/usr/lib/python3/dist-packages:" + (process.env.PYTHONPATH || ""),
        ...envExtra
      },
      timeout: 10000,
      killSignal: "SIGKILL",
      maxBuffer: 10 * 1024 * 1024
    }, (err, stdout, stderr) => {
      if (err) {
        if (err.killed || err.signal === "SIGKILL") {
          resolve("⚠️ [10s TIMEOUT TERMINATED] Operation exceeded 10s limit and was terminated.");
        } else {
          resolve(stdout ? `${stdout}\nError: ${stderr || err.message}` : `Error: ${stderr || err.message}`);
        }
      } else {
        resolve(stdout.trim() || stderr.trim() || "OK");
      }
    });
  });
}

function sendToDaemon(cmd, args = []) {
  ensureDaemonRunning();
  return new Promise((resolvePromise) => {
    const client = net.createConnection({ path: DAEMON_SOCK }, () => {
      client.write(JSON.stringify({ cmd, args }));
    });

    let data = "";
    client.on("data", (chunk) => {
      data += chunk.toString();
    });

    client.on("end", () => {
      resolvePromise(data.trim() || "OK");
    });

    client.on("error", () => {
      // Fallback to direct subprocess if socket fails
      const argsStr = args.map(a => `"${String(a).replace(/"/g, '\\"')}"`).join(" ");
      resolvePromise(runCommand(`python3 "${SEMANTIC_DESKTOP_PY}" ${cmd} ${argsStr}`));
    });

    client.setTimeout(8000, () => {
      client.destroy();
      const argsStr = args.map(a => `"${String(a).replace(/"/g, '\\"')}"`).join(" ");
      resolvePromise(runCommand(`python3 "${SEMANTIC_DESKTOP_PY}" ${cmd} ${argsStr}`));
    });
  });
}

function runSemantic(cmdOrArgs) {
  if (typeof cmdOrArgs === "string" && !cmdOrArgs.includes(" ")) {
    return sendToDaemon(cmdOrArgs, []);
  }
  // If passed as command string like 'focus_window "Firefox"'
  const parts = cmdOrArgs.match(/(?:[^\s"]+|"[^"]*")+/g) || [cmdOrArgs];
  const cmd = parts[0];
  const args = parts.slice(1).map(p => p.replace(/^"|"$/g, ""));
  return sendToDaemon(cmd, args);
}

function runBrowserCdp(args) {
  return runCommand(`python3 "${BROWSER_CDP_PY}" ${args}`);
}

export const CUA_TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "read_screen_tree",
      description: "Read the desktop accessibility widget tree via Linux AT-SPI2 D-Bus IPC (buttons, editable fields, text contents, states, and available actions). Defaults to focused window or specify target app name (e.g. 'Text Editor').",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Optional window title or application name to inspect (e.g. 'Text Editor')" }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "list_open_windows",
      description: "List all open application windows and widgets on the desktop with their PIDs, child counts, geometry, and RSS memory via hybrid AT-SPI2 and X11/EWMH discovery (discovers all applications, including sandboxed Snap, Flatpak, Spotify, Chrome, Electron).",
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
      name: "get_focused_element",
      description: "Inspect the currently focused UI element, its role, name, states, bounding box geometry, and current text content across all applications.",
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
      name: "get_element_coordinates",
      description: "Dynamically calculate the exact screen bounding box (x, y, width, height, center_x, center_y) for any UI element by its accessibility name or role. Never guess pixel coordinates.",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Name or role of the target UI element" }
        },
        required: ["target"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "set_field_value",
      description: "Set text directly inside any input field, text editor, or entry box by element name or role without moving the mouse pointer. Use save:true to atomically save after injection (eliminates a separate ctrl+s turn).",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Name or role of the target text/entry element" },
          text: { type: "string", description: "Text content to set" },
          save: { type: "boolean", description: "If true, automatically saves the document after injecting text (equivalent to ctrl+s). Default false." }
        },
        required: ["target", "text"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "interact_element",
      description: "Invoke a widget action directly (e.g. 'click', 'activate', 'press') on buttons, menus, items via native AT-SPI2 accessibility bridge.",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Name of the button, menu item, or widget" },
          action: { type: "string", description: "Action to trigger (default 'click')", default: "click" }
        },
        required: ["target"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "open_browser_url",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "The URL to open" },
          browser: { type: "string", description: "Optional browser command name (e.g. 'firefox', 'google-chrome', 'brave-browser'). Defaults to system default." }
        },
        required: ["url"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_launch",
      description: "Launch a browser instance with Chrome DevTools Protocol (CDP) enabled on an automatically allocated ephemeral debugging port. Returns port and WebSocket debugger URL.",
      parameters: {
        type: "object",
        properties: {
          url: { type: "string", description: "URL to navigate to (default 'about:blank')" },
          headless: { type: "boolean", description: "Run in headless mode (default false)" }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_console_errors",
      description: "Inspect live browser console errors, warnings, unhandled Promise rejections, and JavaScript exception stack traces via CDP without opening developer tools.",
      parameters: {
        type: "object",
        properties: {
          port: { type: "integer", description: "Optional CDP port (auto-detected if omitted)" }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_network_events",
      description: "Inspect failed HTTP network requests (4xx, 5xx, CORS, net::ERR_*), URLs, and response statuses via CDP.",
      parameters: {
        type: "object",
        properties: {
          port: { type: "integer", description: "Optional CDP port (auto-detected if omitted)" }
        },
        required: []
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_eval_js",
      description: "Execute arbitrary JavaScript directly inside the active browser tab context to inspect global variables, local storage, cookies, or page state.",
      parameters: {
        type: "object",
        properties: {
          expression: { type: "string", description: "JavaScript expression to evaluate" },
          port: { type: "integer", description: "Optional CDP port (auto-detected if omitted)" }
        },
        required: ["expression"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "browser_query_dom",
      description: "Query DOM elements matching a CSS selector and return their tags, IDs, classes, text, and exact bounding box geometries (x, y, w, h) without screenshots.",
      parameters: {
        type: "object",
        properties: {
          selector: { type: "string", description: "CSS selector (e.g. 'button', '.submit-btn', 'input[name=q]')" },
          port: { type: "integer", description: "Optional CDP port (auto-detected if omitted)" }
        },
        required: ["selector"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "inspect_desktop_state",
      description: "Lowest-level system telemetry: returns active windows with PIDs and geometry, mouse coordinates, top CPU/RAM processes, listening ports, and system load.",
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
      name: "mouse_click",
      description: "Click at specific screen pixel coordinates (x, y). Calculate x, y dynamically from get_element_coordinates or browser_query_dom.",
      parameters: {
        type: "object",
        properties: {
          x: { type: "integer", description: "Target X screen coordinate" },
          y: { type: "integer", description: "Target Y screen coordinate" },
          button: { type: "string", enum: ["left", "right", "middle"], description: "Mouse button (default 'left')" },
          clicks: { type: "integer", description: "Number of clicks (default 1)" }
        },
        required: ["x", "y"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "mouse_scroll",
      description: "Scroll the mouse wheel up or down by a given amount.",
      parameters: {
        type: "object",
        properties: {
          direction: { type: "string", enum: ["up", "down"], description: "Scroll direction (default 'down')" },
          amount: { type: "integer", description: "Number of scroll ticks (default 5)" }
        },
        required: ["direction"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "type_keys",
      description: "Send keyboard keys, text strings, or shortcuts (e.g. 'ctrl+s', 'Return', 'ctrl+w') to the focused desktop window.",
      parameters: {
        type: "object",
        properties: {
          keys: { type: "string", description: "Keys to press or text to type" },
          is_shortcut: { type: "boolean", description: "True if key combination like ctrl+c, Return, etc." }
        },
        required: ["keys"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "run_os_command",
      description: "Execute any bash shell command on the host environment with full stdout, stderr, and exit code capture.",
      parameters: {
        type: "object",
        properties: {
          command: { type: "string", description: "Bash command to run" }
        },
        required: ["command"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "focus_window",
      description: "Bring an application window to focus and foreground by window title or application name substring.",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string", description: "Window title or application name substring" }
        },
        required: ["title"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "window_control",
      description: "Perform window operations (close, maximize, minimize) on a window by title substring.",
      parameters: {
        type: "object",
        properties: {
          title: { type: "string", description: "Window title or application name substring" },
          action: { type: "string", enum: ["close", "maximize", "minimize"], description: "Action to perform" }
        },
        required: ["title", "action"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "system_info",
      description: "Retrieve comprehensive host hardware and OS telemetry: CPU cores, load averages, RAM usage, disk usage, and top active processes.",
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
      name: "manage_process",
      description: "Inspect running processes, search by name or cmdline, or safely terminate a PID/process.",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["list", "search", "kill"], description: "Action to perform" },
          target: { type: "string", description: "Process name or PID (required for search and kill)" }
        },
        required: ["action"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "get_clipboard",
      description: "Read the current text content from the desktop system clipboard.",
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
      name: "set_clipboard",
      description: "Set text content directly into the desktop system clipboard.",
      parameters: {
        type: "object",
        properties: {
          text: { type: "string", description: "Text content to copy to clipboard" }
        },
        required: ["text"]
      }
    }
  }
];

// ── Minimal CUA schema ── Essential tools for AT-SPI-native OS navigation.
// Model uses read_screen_tree to see full app widget hierarchy (like a DOM for the whole OS),
// then set_field_value to inject text by element name/role, interact_element to click/activate.
// NO mouse coordinates needed — pure accessibility tree navigation.
export const CUA_MINIMAL_TOOL_SCHEMAS = [
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "read_screen_tree"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "set_field_value"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "interact_element"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "get_element_coordinates"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "mouse_click"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "mouse_scroll"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "type_keys"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "focus_window"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "window_control"),
  CUA_TOOL_SCHEMAS.find(t => t.function.name === "list_open_windows"),
  {
    type: "function",
    function: {
      name: "read_file",
      description: "Read a file's contents to verify it was written correctly.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Absolute or relative path to the file" }
        },
        required: ["path"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "run_command",
      description: "Run a shell command to launch apps or perform system operations.",
      parameters: {
        type: "object",
        properties: {
          command: { type: "string", description: "Shell command to execute" }
        },
        required: ["command"]
      }
    }
  }
];

function tryParse(s) {
  try { return JSON.parse(s); } catch { return s; }
}

async function withEnvironmentFeedback(actionPromise) {
  const actionRaw = await actionPromise;
  try {
    const focusedRaw = await runSemantic("focused");
    return JSON.stringify({
      action_result: tryParse(actionRaw),
      current_focused_element: tryParse(focusedRaw)
    }, null, 2);
  } catch {
    return actionRaw;
  }
}

export async function executeCuaTool(name, args = {}) {
  switch (name) {
    case "read_screen_tree":
      return await runSemantic(args.target ? `dump "${args.target.replace(/"/g, '\\"')}"` : "dump");

    case "list_open_windows":
      return await runSemantic("list_windows");

    case "get_focused_element":
      return await runSemantic("focused");

    case "get_element_coordinates":
      return await runSemantic(`extents "${(args.target || "").replace(/"/g, '\\"')}"`);

    case "set_field_value":
      return await withEnvironmentFeedback(runSemantic(`set_text "${(args.target || "").replace(/"/g, '\\"')}" "${(args.text || "").replace(/"/g, '\\"')}" ${args.save ? 'true' : 'false'}`));

    case "interact_element":
      return await withEnvironmentFeedback(runSemantic(`interact "${(args.target || "").replace(/"/g, '\\"')}" "${args.action || 'click'}"`));

    case "mouse_click":
      return await withEnvironmentFeedback(runSemantic(`click ${args.x} ${args.y} "${args.button || 'left'}" ${args.clicks || 1}`));

    case "mouse_scroll":
      return await withEnvironmentFeedback(runSemantic(`scroll ${args.amount || 5} "${args.direction || 'down'}"`));

    case "type_keys":
      return await withEnvironmentFeedback(runSemantic(`type "${(args.keys || "").replace(/"/g, '\\"')}" ${args.is_shortcut ? 'true' : 'false'}`));

    case "focus_window":
      return await withEnvironmentFeedback(runSemantic(`focus_window "${(args.title || "").replace(/"/g, '\\"')}"`));

    case "window_control":
      return await withEnvironmentFeedback(runSemantic(`window_control "${(args.title || "").replace(/"/g, '\\"')}" "${args.action || 'close'}"`));

    case "system_info":
      return await runSemantic("system_info");

    case "manage_process":
      return await runSemantic(`manage_process "${args.action || 'list'}" "${(args.target || "").replace(/"/g, '\\"')}"`);

    case "get_clipboard":
      return await runSemantic("get_clipboard");

    case "set_clipboard":
      return await runSemantic(`set_clipboard "${(args.text || "").replace(/"/g, '\\"')}"`);

    case "open_browser_url": {
      let targetUrl = (args.url || "https://google.com").trim();
      if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://") && !targetUrl.startsWith("file://")) {
        targetUrl = `https://${targetUrl}`;
      }
      const cmd = `chromium-browser --no-sandbox "${targetUrl.replace(/"/g, '\"')}" >/dev/null 2>&1 &`;
      await runCommand(cmd);
      return `Opened '${targetUrl}' in Chromium.`;
    }

    case "browser_launch": {
      const url = args.url ? `"${args.url.replace(/"/g, '\\"')}"` : '"about:blank"';
      const headlessFlag = args.headless ? "--headless" : "";
      return await runBrowserCdp(`launch ${url} ${headlessFlag}`);
    }

    case "browser_console_errors": {
      const portFlag = args.port ? `--port=${args.port}` : "";
      return await runBrowserCdp(`console ${portFlag}`);
    }

    case "browser_network_events": {
      const portFlag = args.port ? `--port=${args.port}` : "";
      return await runBrowserCdp(`network ${portFlag}`);
    }

    case "browser_eval_js": {
      const portFlag = args.port ? `--port=${args.port}` : "";
      const expr = (args.expression || "window.location.href").replace(/"/g, '\\"');
      return await runBrowserCdp(`eval "${expr}" ${portFlag}`);
    }

    case "browser_query_dom": {
      const portFlag = args.port ? `--port=${args.port}` : "";
      const sel = (args.selector || "*").replace(/"/g, '\\"');
      return await runBrowserCdp(`query "${sel}" ${portFlag}`);
    }

    case "inspect_desktop_state": {
      const windows = await runSemantic("list_windows");
      const mouse = await runSemantic("mouse_pos");
      const sys = await runCommand(`
        echo "=== MEMORY ==="; free -h
        echo "=== TOP PROCESSES ==="; ps aux --sort=-%cpu | head -n 8
        echo "=== LISTENING PORTS ==="; ss -tuln | head -n 10
      `);
      return `=== AT-SPI2 WINDOWS ===\n${windows}\n\n=== MOUSE POSITION ===\n${mouse}\n\n${sys}`;
    }

    case "run_os_command": {
      return await runCommand(args.command);
    }

    default:
      return `Unknown tool: ${name}`;
  }
}
