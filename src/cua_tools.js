// cua_tools.js — 1:1 SWE to CUA Tool Equivalents for Swades ReAct Agent
import { exec } from "node:child_process";

function runPy(cmd) {
  return new Promise((resolve) => {
    exec(`python3 /root/swades-cua-sandbox/src/semantic_desktop.py ${cmd}`, {
      env: { ...process.env, DISPLAY: ":99" }
    }, (err, stdout, stderr) => {
      if (err) resolve(`Error: ${stderr || err.message}`);
      else resolve(stdout.trim());
    });
  });
}

function runXdo(cmd) {
  return new Promise((resolve) => {
    exec(`xdotool ${cmd}`, {
      env: { ...process.env, DISPLAY: ":99" }
    }, (err, stdout, stderr) => {
      if (err) resolve(`Error: ${stderr || err.message}`);
      else resolve(stdout.trim() || "OK");
    });
  });
}

export const CUA_TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "read_screen_tree",
      description: "Read the active desktop accessibility tree (dump active windows, UI widgets, buttons, editable fields, text contents, states, and available actions). Equivalent to read_file.",
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
      description: "List all open application windows and widgets on the desktop. Equivalent to list_dir.",
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
      name: "set_field_value",
      description: "Set text directly inside any input field, text editor, or entry box by element name or role without moving mouse. Equivalent to write_file.",
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
      description: "Invoke a widget action directly (e.g. 'click', 'activate', 'press') on buttons, menus, items. Equivalent to patch_file.",
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
      name: "run_os_command",
      description: "Execute a shell command on the host desktop environment. Equivalent to run_command.",
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
      name: "type_keys",
      description: "Send keyboard keys or shortcuts (e.g. 'ctrl+s', 'Return', or text strings) to the focused desktop window.",
      parameters: {
        type: "object",
        properties: {
          keys: { type: "string", description: "Keys to press or type" },
          is_shortcut: { type: "boolean", description: "True if key combination like ctrl+c, Return, etc." }
        },
        required: ["keys"]
      }
    }
  }
];

export async function executeCuaTool(name, args) {
  switch (name) {
    case "read_screen_tree":
      return await runPy("dump");
    case "list_open_windows":
      return await runPy("list_windows");
    case "set_field_value":
      return await runPy(`set_text "${args.target}" "${(args.text || '').replace(/"/g, '\\"')}"`);
    case "interact_element":
      return await runPy(`interact "${args.target}" "${args.action || 'click'}"`);
    case "type_keys":
      if (args.is_shortcut) {
        return await runXdo(`key ${args.keys}`);
      } else {
        return await runXdo(`type --delay 30 "${(args.keys || '').replace(/"/g, '\\"')}"`);
      }
    case "run_os_command":
      return new Promise((resolve) => {
        exec(args.command, { env: { ...process.env, DISPLAY: ":99" } }, (err, stdout, stderr) => {
          resolve((stdout || "") + (stderr || ""));
        });
      });
    default:
      return `Unknown tool: ${name}`;
  }
}
