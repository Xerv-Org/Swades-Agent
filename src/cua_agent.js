// cua_agent.js — Swades ReAct Autonomous CUA Loop with Low-Level Structural Perception
import chalk from "chalk";
import { CUA_TOOL_SCHEMAS, executeCuaTool } from "./cua_tools.js";
import { callLLM } from "./llm.js";

const CUA_SYSTEM_PROMPT = `You are Swades Autonomous Computer Use Agent (CUA) operating directly on the local host Linux environment.
You operate on structural runtime perception — NOT screenshots. You see what normal users cannot see:
- Browser internal state via Chrome DevTools Protocol (CDP): live console.error, JS exceptions, stack traces, network 4xx/5xx failures, and DOM nodes with bounding boxes.
- Desktop UI accessibility tree via AT-SPI2 D-Bus IPC: widget hierarchy, active focus, button actions, and editable fields.
- Kernel & OS telemetry: process tables (/proc), open ports, memory, and geometry.

You run in an autonomous ReAct loop:
THINK -> ACT -> OBSERVE.

Available Tools:
1. read_screen_tree: Dumps the active AT-SPI2 accessibility widget tree.
2. list_open_windows: Lists open application windows, child counts, and geometry.
3. get_focused_element: Inspects currently focused UI element, role, states, and text.
4. get_element_coordinates: Computes exact bounding box (x, y, width, height, center_x, center_y) for any widget.
5. set_field_value: Sets text inside an input field or editor directly without moving mouse.
6. interact_element: Triggers widget action ('click', 'press', 'activate') directly via accessibility bridge.
7. mouse_click: Clicks at exact coordinates (x, y) dynamically calculated from get_element_coordinates or browser_query_dom.
8. mouse_scroll: Scrolls up or down by a given amount.
9. type_keys: Sends keyboard keys, hotkeys (e.g. 'ctrl+s', 'Return'), or text.
10. browser_launch: Launches Chromium with CDP enabled on an ephemeral port.
11. browser_console_errors: Streams live browser console errors, warnings, uncaught exceptions & stack traces.
12. browser_network_events: Streams failed HTTP network requests (4xx, 5xx, CORS).
13. browser_eval_js: Evaluates arbitrary JavaScript inside the active browser tab.
14. browser_query_dom: Queries DOM elements and returns their attributes, text, and exact bounding boxes.
15. inspect_desktop_state: Comprehensive system telemetry (active windows, mouse pos, memory, top processes, listening ports).
16. run_os_command: Executes any bash command on the host.

Rules:
- NEVER assume or hardcode coordinates. Calculate them dynamically using get_element_coordinates or browser_query_dom.
- When inspecting browser issues, use browser_console_errors and browser_network_events to catch runtime exceptions.
- Output a JSON tool call block in your response:
{"name": "tool_name", "arguments": {"arg1": "val1"}}
or use native tool calling. You may only execute ONE tool call per step. Explain your reasoning first.
- When the objective is achieved, provide your final detailed summary without any tool calls.`;

function parseToolCallFromText(content) {
  if (!content) return null;
  const jsonMatch = content.match(/\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"arguments"\s*:\s*(\{[^}]*\})\s*\}/);
  if (jsonMatch) {
    try {
      return {
        name: jsonMatch[1],
        arguments: JSON.parse(jsonMatch[2])
      };
    } catch (e) {}
  }
  return null;
}

export async function runCuaAgent(task, logCallback = console.log, maxSteps = 15) {
  const messages = [
    { role: "system", content: CUA_SYSTEM_PROMPT },
    { role: "user", content: `Objective: ${task}` }
  ];

  logCallback("System", `🚀 Starting Swades Native CUA ReAct Loop for: "${task}"`);
  console.log(chalk.cyan.bold(`\n  🚀 Swades CUA ReAct Loop: "${task}"\n`));

  for (let step = 1; step <= maxSteps; step++) {
    logCallback("AI Step", `⚡ Step ${step}: Reasoning...`);
    console.log(chalk.dim(`\n── Step ${step} ──────────────────────────────────────────`));

    let assistantMsg;
    try {
      assistantMsg = await callLLM(messages, CUA_TOOL_SCHEMAS, (chunk) => {
        if (chunk.type === "content") process.stdout.write(chalk.gray(chunk.text));
      });
    } catch (err) {
      logCallback("Error", `LLM Inference failure: ${err.message}`);
      console.error(chalk.red(`\n❌ LLM Error: ${err.message}`));
      return `Failed at step ${step}: ${err.message}`;
    }

    const content = assistantMsg.content || "";
    messages.push(assistantMsg);

    // Check for native tool_calls first, then fallback to text-parsed tool call
    let toolCall = null;
    if (assistantMsg.tool_calls && assistantMsg.tool_calls.length > 0) {
      const tc = assistantMsg.tool_calls[0];
      try {
        toolCall = {
          id: tc.id,
          name: tc.function.name,
          arguments: typeof tc.function.arguments === "string" ? JSON.parse(tc.function.arguments) : tc.function.arguments
        };
      } catch (e) {
        toolCall = { id: tc.id, name: tc.function.name, arguments: {} };
      }
    } else {
      toolCall = parseToolCallFromText(content);
    }

    if (toolCall && toolCall.name) {
      const thought = content.replace(/\{[\s\S]*\}/, "").trim() || "Analyzing and dispatching action...";
      logCallback("AI Thought", thought);
      logCallback("AI Action", `🔧 ${toolCall.name} | Args: ${JSON.stringify(toolCall.arguments)}`);
      console.log(chalk.cyan(`\n🔧 Tool: ${toolCall.name}`));
      console.log(chalk.dim(`   Args: ${JSON.stringify(toolCall.arguments)}`));

      let observation = "";
      try {
        observation = await executeCuaTool(toolCall.name, toolCall.arguments || {});
      } catch (err) {
        observation = `Tool Execution Error: ${err.message}`;
      }

      const obsText = typeof observation === "string" ? observation : JSON.stringify(observation, null, 2);
      logCallback("Observation", obsText.slice(0, 1000));
      console.log(chalk.green(`👁 Observation:\n${obsText.slice(0, 500)}${obsText.length > 500 ? "\n...[truncated]" : ""}`));

      if (toolCall.id) {
        messages.push({
          role: "tool",
          tool_call_id: toolCall.id,
          name: toolCall.name,
          content: obsText
        });
      } else {
        messages.push({
          role: "user",
          content: `Observation for ${toolCall.name}:\n${obsText}\n\nContinue with your next step or conclude if task is complete.`
        });
      }
    } else {
      logCallback("AI Done", content || "Task finished successfully.");
      console.log(chalk.yellow.bold(`\n✅ Conclusion:\n${content}\n`));
      return content;
    }
  }

  logCallback("System", `Max steps (${maxSteps}) reached.`);
  console.log(chalk.yellow(`\n⚠️ Max steps (${maxSteps}) reached.`));
  return "Max steps reached in CUA loop.";
}
