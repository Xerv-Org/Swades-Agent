// ============================================================
// llm.js — LLM client with streaming + multi-model fallback cascade
// Supports: OpenRouter, Groq, OpenAI, Ollama, and any OpenAI-compatible API
// ============================================================

import OpenAI from "openai";
import chalk from "chalk";

// ---- Provider detection ----

function detectProvider(url) {
  if (url && url.includes("groq.com")) return "groq";
  if (!process.env.BASE_URL && process.env.GROQ_API_KEY) return "groq";
  if (url && url.includes("openrouter.ai")) return "openrouter";
  if (!process.env.BASE_URL && process.env.OPENAI_API_KEY) return "openai";
  if (url && url.includes("api.openai.com")) return "openai";
  if (url && (url.includes("localhost") || url.includes("127.0.0.1"))) return "ollama";
  return "generic";
}

export const PROVIDER = detectProvider(process.env.BASE_URL);

const DEFAULT_BASE_URLS = {
  groq:       "https://api.groq.com/openai/v1",
  openrouter: "https://openrouter.ai/api/v1",
  openai:     "https://api.openai.com/v1",
  ollama:     "http://localhost:11434/v1",
  generic:    "https://openrouter.ai/api/v1",
};

export const BASE_URL = process.env.BASE_URL || DEFAULT_BASE_URLS[PROVIDER];

// ---- API key resolution (supports provider-specific env vars) ----

export const API_KEY = process.env.API_KEY
  || (PROVIDER === "groq"   ? process.env.GROQ_API_KEY   : null)
  || (PROVIDER === "openai" ? process.env.OPENAI_API_KEY  : null)
  || process.env.GROQ_API_KEY
  || process.env.OPENAI_API_KEY;

// ---- Default model per provider ----

const DEFAULT_MODELS = {
  openrouter: "openrouter/free",
  groq:       "openai/gpt-oss-20b",
  openai:     "gpt-4o",
  ollama:     "qwen2.5-coder:7b",
  generic:    "gpt-4o",
};

export const MODEL = process.env.MODEL || DEFAULT_MODELS[PROVIDER] || "openrouter/free";

// Fallback cascade: comma-separated list of models to try if primary fails
const FALLBACK_MODELS = (process.env.FALLBACK_MODELS || "")
  .split(",")
  .map(m => m.trim())
  .filter(Boolean);

let _client = null;

/** Build provider-specific headers — only send what each provider expects. */
function getProviderHeaders() {
  switch (PROVIDER) {
    case "openrouter":
      return {
        "HTTP-Referer": "https://xerv.netlify.app/swades.html",
        "X-Title": "Swades Agent",
        "X-OpenRouter-Title": "Swades Agent",
        "X-OpenRouter-Categories": "cli-agent",
      };
    case "groq":
      return {}; // Groq needs no custom headers — just the API key
    case "openai":
      return {};
    default:
      return {};
  }
}

function getClient() {
  if (!_client) {
    if (!API_KEY) {
      const hint = PROVIDER === "groq"
        ? "Set API_KEY or GROQ_API_KEY in .env"
        : PROVIDER === "openai"
        ? "Set API_KEY or OPENAI_API_KEY in .env"
        : "Set API_KEY in .env";
      throw new Error(`Missing API key. ${hint}. Copy .env.example → .env and add your key.`);
    }
    _client = new OpenAI({
      apiKey: API_KEY,
      baseURL: BASE_URL,
      defaultHeaders: getProviderHeaders(),
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

  // HTTP 429 = Rate Limit, HTTP 413 TPM Overflow (Groq/OpenAI TPM limit)
  if (status === 429 || status === 413 || msg.includes("429") || msg.includes("413") || msg.includes("rate limit") || msg.includes("rate_limit") || msg.includes("tokens per minute") || msg.includes("tpm")) {
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

// ---- Message sanitizer ----

/**
 * Strip all non-standard properties from message objects before sending to any provider.
 *
 * The OpenAI Chat Completions spec only allows these fields per message:
 *   role, content, tool_calls, tool_call_id, name
 *
 * Any extra property (e.g. `_originalContent`, internal SDK fields) causes providers
 * like Groq to return HTTP 400 "property '...' is unsupported".
 */
const ALLOWED_MSG_KEYS = new Set(["role", "content", "tool_calls", "tool_call_id", "name"]);

function sanitizeMessages(messages) {
  return messages.map((msg) => {
    const clean = {};
    for (const key of ALLOWED_MSG_KEYS) {
      if (key in msg) clean[key] = msg[key];
    }
    return clean;
  });
}

// ---- Internal streaming call ----

/**
 * Internal LLM call implementation (single model, no fallback).
 */
async function _callLLMInternal(messages, tools, onChunk, model) {
  const params = {
    model,
    messages: sanitizeMessages(messages), // always sanitize before sending
    temperature: 0,
    stream: true,
  };

  if (BASE_URL && BASE_URL.includes("openrouter")) {
    params.plugins = [{ id: "context-compression" }];
  }

  // Groq's qwen3.8-27b has a strict 1000 OTPM limit; default 2048 causes immediate 429
  if (PROVIDER === "groq" && model.includes("qwen3.8-27b")) {
    params.max_tokens = 950;
  }

  if (tools && tools.length > 0) {
    params.tools = tools;
    params.tool_choice = "auto";
  }

  const stream = await getClient().chat.completions.create(params);

  // ---- Reconstruct full message from streaming chunks ----
  let contentBuf = "";
  let reasoningBuf = "";
  // tool_calls accumulator: index → { id, type, function: { name, arguments } }
  const toolCallMap = {};

  for await (const chunk of stream) {
    const delta = chunk.choices?.[0]?.delta;
    if (!delta) continue;

    // --- Reasoning chunks (for reasoning models: gpt-oss-20b, deepseek-r1, etc.) ---
    const reasoningText = delta.reasoning || delta.reasoning_content;
    if (reasoningText) {
      reasoningBuf += reasoningText;
      if (onChunk) onChunk({ type: "reasoning", text: reasoningText });
    }

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
    content: contentBuf || (toolCalls.length === 0 && reasoningBuf ? reasoningBuf : null),
  };
  if (reasoningBuf) {
    message.reasoning = reasoningBuf;
  }
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
