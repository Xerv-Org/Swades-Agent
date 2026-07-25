// ============================================================
// llm.js — LLM client with streaming + multi-model fallback cascade
// ============================================================

import OpenAI from "openai";
import chalk from "chalk";

const API_KEY  = process.env.API_KEY;
const BASE_URL = process.env.BASE_URL || "https://openrouter.ai/api/v1";
export const MODEL = process.env.MODEL || "openrouter/free";

// Fallback cascade: comma-separated list of models to try if primary fails
const FALLBACK_MODELS = (process.env.FALLBACK_MODELS || "")
  .split(",")
  .map(m => m.trim())
  .filter(Boolean);

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

// ---- Error classification ----

/**
 * Determine if an error is retryable (rate limit, payment, auth on specific model).
 * These errors indicate we should try a different model, not crash.
 */
function isRetryableError(err) {
  const msg = (err.message || "").toLowerCase();
  const status = err.status || err.statusCode || 0;

  // HTTP 429 = Rate Limit
  if (status === 429 || msg.includes("429") || msg.includes("rate limit") || msg.includes("rate_limit")) {
    return true;
  }
  // HTTP 402 = Payment Required (key limit exceeded)
  if (status === 402 || msg.includes("402") || msg.includes("payment required") || msg.includes("key limit") || msg.includes("insufficient")) {
    return true;
  }
  // HTTP 403 = Forbidden (model access denied for this key)
  if (status === 403 || msg.includes("403") || msg.includes("forbidden")) {
    return true;
  }
  // HTTP 503 = Service Unavailable / model overloaded
  if (status === 503 || msg.includes("503") || msg.includes("service unavailable") || msg.includes("overloaded")) {
    return true;
  }
  // OpenRouter-specific: "No endpoints found" (model temporarily unavailable)
  if (msg.includes("no endpoints found") || msg.includes("no available model")) {
    return true;
  }

  return false;
}

/**
 * Build a human-readable error context string for structured error reporting.
 */
function formatLLMError(err, modelName) {
  const status = err.status || err.statusCode || "unknown";
  const retryable = isRetryableError(err);
  return `[LLM Error] Model: ${modelName} | Status: ${status} | Retryable: ${retryable} | ${err.message}`;
}

// ---- Internal streaming call ----

/**
 * Internal LLM call implementation (single model, no fallback).
 */
async function _callLLMInternal(messages, tools, onChunk, model) {
  const params = {
    model,
    messages,
    temperature: 0,
    stream: true,
  };

  if (BASE_URL && BASE_URL.includes("openrouter")) {
    params.plugins = [{ id: "context-compression" }];
  }

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

// ---- Public API with fallback cascade ----

/**
 * Call the LLM with automatic fallback cascade on retryable errors.
 *
 * On 429/402/403/503 errors, automatically tries the next model in the
 * FALLBACK_MODELS chain. Max 3 total attempts before throwing.
 *
 * @param {Array}    messages     - OpenAI message array
 * @param {Array}    tools        - Optional tool schemas
 * @param {Function} onChunk      - Optional streaming callback
 * @param {string}   modelOverride - Optional model override (bypasses default)
 * @returns {Object} - Reconstructed assistant message
 */
export async function callLLM(messages, tools, onChunk, modelOverride) {
  const primaryModel = modelOverride || MODEL;
  const cascade = [primaryModel, ...FALLBACK_MODELS.filter(m => m !== primaryModel)];

  // Cap at 4 total attempts to prevent infinite retry loops
  const maxAttempts = Math.min(cascade.length, 4);

  for (let i = 0; i < maxAttempts; i++) {
    const currentModel = cascade[i];

    try {
      if (i > 0) {
        console.log(chalk.yellow(`   ⚡ Fallback attempt ${i + 1}/${maxAttempts}: trying ${currentModel}...`));
      }

      return await _callLLMInternal(messages, tools, onChunk, currentModel);
    } catch (err) {
      const errorInfo = formatLLMError(err, currentModel);

      if (isRetryableError(err) && i < maxAttempts - 1) {
        console.log(chalk.yellow(`   ⚠ ${errorInfo}`));
        console.log(chalk.yellow(`   ↻ Failing over to next model in cascade...`));

        // Brief delay before retry to be respectful to rate limits
        await new Promise(r => setTimeout(r, 1000 * (i + 1)));
        continue;
      }

      // Non-retryable error or exhausted all fallbacks
      const wrappedError = new Error(errorInfo);
      wrappedError.originalError = err;
      wrappedError.model = currentModel;
      wrappedError.status = err.status || err.statusCode;
      throw wrappedError;
    }
  }

  // Should not reach here, but safety net
  throw new Error(`All ${maxAttempts} models in fallback cascade exhausted. No response received.`);
}
