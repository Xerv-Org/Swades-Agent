// cua_tools.js — Low-Level Structural Perception & Execution Tools for Swades ReAct CUA
import { exec } from "node:child_process";
import { resolve } from "node:path";

const SCRIPT_DIR = resolve(process.cwd(), "src");
const SEMANTIC_DESKTOP_PY = resolve(SCRIPT_DIR, "semantic_desktop.py");
const BROWSER_CDP_PY = resolve(SCRIPT_DIR, "browser_cdp.py");

function runCommand(cmd, envExtra = {}) {
  return new Promise((resolve) => {
    exec(cmd, {
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || ":0",
        ...envExtra
      },
      maxBuffer: 10 * 1024 * 1024
    }, (err, stdout, stderr) => {
      if (err) {
        resolve(stdout ? `${stdout}\nError: ${stderr || err.message}` : `Error: ${stderr || err.message}`);
      } else {
        resolve(stdout.trim() || stderr.trim() || "OK");
      }
    });
  });
}

function runSemantic(args) {
  return runCommand(`python3 "${SEMANTIC_DESKTOP_PY}" ${args}`);
}

function runBrowserCdp(args) {
  return runCommand(`python3 "${BROWSER_CDP_PY}" ${args}`);
}

export const CUA_TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "read_screen_tree",
      description: "Read the full desktop accessibility widget tree via Linux AT-SPI2 D-Bus IPC (dump active windows, UI widgets, buttons, editable fields, text contents, states, and available actions). Zero-screenshot structural perception.",
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
      description: "Set text directly inside any input field, text editor, or entry box by element name or role without moving the mouse pointer.",
      parameters: {
        type: "object",
        properties: {
          target: { type: "string", description: "Name or role of the target text/entry element" },
          text: { type: "string", description: "Text content to set" }
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
      description: "Open any URL in the user's default system browser (Firefox, Chrome, Brave, Edge, etc.) or a specified browser executable. Works universally on any existing browser without requiring debug flags.",
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
  }
];

export async function executeCuaTool(name, args = {}) {
  switch (name) {
    case "read_screen_tree":
      return await runSemantic("dump");

    case "list_open_windows":
      return await runSemantic("list_windows");

    case "get_focused_element":
      return await runSemantic("focused");

    case "get_element_coordinates":
      return await runSemantic(`extents "${(args.target || "").replace(/"/g, '\\"')}"`);

    case "set_field_value":
      return await runSemantic(`set_text "${(args.target || "").replace(/"/g, '\\"')}" "${(args.text || "").replace(/"/g, '\\"')}"`);

    case "interact_element":
      return await runSemantic(`interact "${(args.target || "").replace(/"/g, '\\"')}" "${args.action || 'click'}"`);

    case "mouse_click":
      return await runSemantic(`click ${args.x} ${args.y} "${args.button || 'left'}" ${args.clicks || 1}`);

    case "mouse_scroll":
      return await runSemantic(`scroll ${args.amount || 5} "${args.direction || 'down'}"`);

    case "type_keys":
      return await runSemantic(`type "${(args.keys || "").replace(/"/g, '\\"')}" ${args.is_shortcut ? 'true' : 'false'}`);

    case "open_browser_url": {
      let targetUrl = (args.url || "about:blank").trim();
      if (!targetUrl.startsWith("http://") && !targetUrl.startsWith("https://") && !targetUrl.startsWith("file://")) {
        targetUrl = `https://${targetUrl}`;
      }
      const b = args.browser ? args.browser.trim() : null;
      let cmd;
      if (b) {
        cmd = `${b} "${targetUrl.replace(/"/g, '\\"')}" &`;
      } else {
        cmd = `xdg-open "${targetUrl.replace(/"/g, '\\"')}" 2>/dev/null || sensible-browser "${targetUrl.replace(/"/g, '\\"')}" 2>/dev/null || open "${targetUrl.replace(/"/g, '\\"')}" 2>/dev/null &`;
      }
      await runCommand(cmd);
      return `Opened '${targetUrl}' in ${b || "default system browser"}.`;
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
