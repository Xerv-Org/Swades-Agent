// ============================================================
// llm.js — LLM client with true token-by-token streaming
// ============================================================

import OpenAI from "openai";

const API_KEY  = process.env.API_KEY;
const BASE_URL = process.env.BASE_URL || "https://openrouter.ai/api/v1";
export const MODEL = process.env.MODEL || "openrouter/free";

let _client = null;

function getClient() {
  if (!_client) {
    if (!API_KEY) throw new Error("Missing API_KEY in environment. Copy .env.example → .env and add your key.");
    _client = new OpenAI({
      apiKey: API_KEY,
      baseURL: BASE_URL,
      defaultHeaders: {
        "HTTP-Referer": "https://xerv.netlify.app/swades.html",
        "X-Title": "Swades Agent",
        "X-OpenRouter-Title": "Swades Agent",
        "X-OpenRouter-Categories": "cli-agent",
      },
    });
  }
  return _client;
}

/**
 * Call the LLM with optional streaming.
 *
 * @param {Array}    messages   - OpenAI message array
 * @param {Array}    tools      - Optional tool schemas
 * @param {Function} onChunk    - Optional callback({ type, text?, name?, args? })
 *                               Called per token while streaming.
 * @returns {Object} - Reconstructed assistant message (same shape as non-streaming response)
 */
export async function callLLM(messages, tools, onChunk, modelOverride) {
  const params = {
    model: modelOverride || MODEL,
    messages,
    temperature: 0,
    stream: true,
    plugins: [{ id: "context-compression" }],
  };

  if (tools && tools.length > 0) {
    params.tools = tools;
    params.tool_choice = "auto";
  }

  const stream = await getClient().chat.completions.create(params);

  // ---- Reconstruct full message from streaming chunks ----
  let contentBuf = "";
  // tool_calls accumulator: index → { id, type, function: { name, arguments } }
  const toolCallMap = {};

  for await (const chunk of stream) {
    const delta = chunk.choices?.[0]?.delta;
    if (!delta) continue;

    // --- Text content chunks ---
    if (delta.content) {
      contentBuf += delta.content;
      if (onChunk) onChunk({ type: "content", text: delta.content });
    }

    // --- Tool call chunks ---
    if (delta.tool_calls) {
      for (const tc of delta.tool_calls) {
        const idx = tc.index ?? 0;
        if (!toolCallMap[idx]) {
          toolCallMap[idx] = {
            id: tc.id || `call_${idx}`,
            type: "function",
            function: { name: "", arguments: "" },
          };
        }
        const entry = toolCallMap[idx];

        if (tc.id) entry.id = tc.id;
        if (tc.function?.name) {
          entry.function.name += tc.function.name;
          if (onChunk) onChunk({ type: "tool_name", name: tc.function.name });
        }
        if (tc.function?.arguments) {
          entry.function.arguments += tc.function.arguments;
          if (onChunk) onChunk({ type: "tool_args", args: tc.function.arguments });
        }
      }
    }
  }

  // Build the assistant message object
  const toolCalls = Object.values(toolCallMap);

  const message = {
    role: "assistant",
    content: contentBuf || null,
  };
  if (toolCalls.length > 0) {
    message.tool_calls = toolCalls;
  }
  return message;
}
