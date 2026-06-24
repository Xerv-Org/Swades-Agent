// ============================================================
// llm.js — Thin LLM client wrapper (OpenAI-compatible)
// ============================================================

import OpenAI from "openai";

// Read config from process.env — secure for public repos
const API_KEY = process.env.API_KEY;
const BASE_URL = process.env.BASE_URL || "https://openrouter.ai/api/v1";
const MODEL = process.env.MODEL || "openrouter/free";

let client = null;

function getClient() {
  if (!client) {
    if (!API_KEY) {
      throw new Error("Missing API_KEY environment variable. Please define it in your .env file.");
    }
    client = new OpenAI({
      apiKey: API_KEY,
      baseURL: BASE_URL,
      defaultHeaders: {
        "HTTP-Referer": "https://github.com/Electroiscoding/reactsystemlearning1",
        "X-Title": "ReAct SWE Agent",
      },
    });
  }
  return client;
}

/**
 * Call the LLM with messages and optional tool schemas.
 * Returns the assistant message object.
 */
export async function callLLM(messages, tools) {
  const params = {
    model: MODEL,
    messages,
    temperature: 0,
  };

  // Only include tools if provided
  if (tools && tools.length > 0) {
    params.tools = tools;
    params.tool_choice = "auto";
  }

  const response = await getClient().chat.completions.create(params);
  return response.choices[0].message;
}

export { MODEL };
