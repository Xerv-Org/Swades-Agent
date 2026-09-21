// cua_agent.js — Swades ReAct Loop for Semantic Computer Use Agent (CUA)
// Powered by local AMD MI300X vLLM (Qwen2.5-Coder-32B)
import { CUA_TOOL_SCHEMAS, executeCuaTool } from "./cua_tools.js";

const MI300X_URL = "http://localhost:8000/v1/chat/completions";
const MODEL_NAME = "Qwen/Qwen2.5-Coder-32B-Instruct";

const CUA_SYSTEM_PROMPT = `You are Swades Semantic Computer Use Agent (CUA) operating on a Linux desktop system.
You run in a classic autonomous ReAct loop:
THINK -> ACT -> OBSERVE.

You have access to the following semantic CUA tools:
- read_screen_tree: Inspect active UI hierarchy, accessibility tree, and widget states.
- list_open_windows: List open application windows and processes.
- set_field_value: Modify text fields and inputs directly (args: {"target": "name", "text": "value"}).
- interact_element: Click buttons or activate UI elements (args: {"target": "name", "action": "click"}).
- type_keys: Send keystrokes or hotkeys (args: {"keys": "Return" or "ctrl+s", "is_shortcut": true}).
- run_os_command: Execute shell commands on the host OS (args: {"command": "sh cmd"}).

To invoke a tool, write a JSON tool call block in your response:
{"name": "tool_name", "arguments": {"arg1": "val1"}}
You may only call ONE tool per step. Explain your thinking first, then output the JSON tool call. When your task is finished, state your conclusion clearly without any tool calls.`;

async function callLocalLLM(messages) {
  const payload = {
    model: MODEL_NAME,
    messages: messages,
    max_tokens: 512,
    temperature: 0.1
  };

  const res = await fetch(MI300X_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`LLM Error ${res.status}: ${errText}`);
  }
  const data = await res.json();
  return data.choices[0].message;
}

function parseToolCall(content) {
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

export async function runCuaAgent(task, logCallback = console.log) {
  const messages = [
    { role: "system", content: CUA_SYSTEM_PROMPT },
    { role: "user", content: `Goal / Task: ${task}` }
  ];

  logCallback("System", `Starting Swades ReAct CUA Loop on MI300X for task: "${task}"`);

  const maxSteps = 12;
  for (let step = 1; step <= maxSteps; step++) {
    logCallback("AI Step", `⚡ Step ${step}: Reasoning...`);

    let response;
    try {
      response = await callLocalLLM(messages);
    } catch (err) {
      logCallback("Error", `Inference failure: ${err.message}`);
      return `Failed at step ${step}: ${err.message}`;
    }

    const content = response.content || "";
    messages.push({ role: "assistant", content });

    const toolCall = parseToolCall(content);
    if (toolCall && toolCall.name) {
      logCallback("AI Thought", content.replace(/\{[\s\S]*\}/, "").trim() || "Executing tool...");
      logCallback("AI Action", `🔧 Calling Tool: ${toolCall.name} | Args: ${JSON.stringify(toolCall.arguments)}`);

      let observation = "";
      try {
        observation = await executeCuaTool(toolCall.name, toolCall.arguments || {});
      } catch (err) {
        observation = `Error executing tool: ${err.message}`;
      }

      const obsPreview = typeof observation === "string" ? observation : JSON.stringify(observation);
      logCallback("Observation", obsPreview.slice(0, 500));

      messages.push({
        role: "user",
        content: `Observation for ${toolCall.name}:\n${obsPreview}\n\nContinue with next step or conclude.`
      });
    } else {
      logCallback("AI Thought", content);
      logCallback("AI Done", "ReAct loop concluded successfully.");
      return content;
    }
  }

  logCallback("System", "Max steps reached in ReAct loop.");
  return "Max steps reached.";
}
