// agent.js — ReAct loop orchestrator (THINK → ACT → OBSERVE)

import chalk from "chalk";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { callLLM, MODEL } from "./llm.js";
import { executeTool } from "./tools.js";
import { SYSTEM_PROMPT, TOOL_SCHEMAS } from "./prompts.js";
import { getMemoryContext, recordSession } from "./memory.js";

/**
 * Run the ReAct agentic loop.
 * @param {string} task - User's task
 * @param {number} maxSteps - Safety cap
 * @param {Array} existingMessages - Continue from existing conversation
 * @returns {string} - Final answer
 */
export async function runAgent(task, maxSteps, existingMessages) {
  const max = maxSteps || parseInt(process.env.MAX_STEPS) || 30;
  let messages = existingMessages;

  if (!messages) {
    const workdir = process.env.WORKDIR || process.cwd();
    const resolvedWorkdir = resolve(workdir);

    // Load codebase index if available
    let indexContext = "";
    const indexFile = resolve(resolvedWorkdir, ".agent_index.json");
    if (existsSync(indexFile)) {
      try {
        const index = JSON.parse(await readFile(indexFile, "utf-8"));
        const files = Object.keys(index.files);
        if (files.length > 0) {
          indexContext = `\n\n## CODEBASE STRUCTURE\n${files.map(f => {
            const s = index.files[f].structure || { functions: [], classes: [] };
            const d = [];
            if (s.classes?.length) d.push(`classes: [${s.classes.join(", ")}]`);
            if (s.functions?.length) d.push(`funcs: [${s.functions.join(", ")}]`);
            return `- ${f} (${d.join("; ") || "file"})`;
          }).join("\n")}`;
        }
      } catch (e) {
        console.log(chalk.dim(`⚠ Index load failed: ${e.message}`));
      }
    }

    const memoryContext = await getMemoryContext();

    const workspaceContext = `\n\n## WORKSPACE\nActive directory: ${resolvedWorkdir}\nAll tool operations run relative to this folder.`;

    messages = [
      { role: "system", content: SYSTEM_PROMPT + workspaceContext + indexContext + memoryContext },
      { role: "user", content: task },
    ];
  }

  const toolsUsed = new Set();

  console.log(chalk.cyan.bold("\n🤖 Agent started"));
  console.log(chalk.dim(`   Model: ${MODEL} | Steps: ${max} | Task: ${task || "continuing"}\n`));

  for (let step = 1; step <= max; step++) {
    console.log(chalk.yellow(`⚡ Step ${step}/${max}`));

    let response;
    let header = false;

    try {
      response = await callLLM(messages, TOOL_SCHEMAS, (chunk) => {
        if (chunk.type === "content") {
          if (!header) { process.stdout.write(chalk.blue("💭 ")); header = true; }
          process.stdout.write(chalk.blue(chunk.text));
        } else if (chunk.type === "tool_name" && chunk.name) {
          process.stdout.write(chalk.magenta(`\n   🔧 ${chunk.name}`));
        } else if (chunk.type === "tool_args" && chunk.args) {
          process.stdout.write(chalk.gray(chunk.args));
        }
      });
      console.log();
    } catch (err) {
      console.log(chalk.red(`\n   ❌ ${err.message}`));
      if (step < max) { console.log(chalk.yellow("   Retrying...\n")); continue; }
      return `Agent error: ${err.message}`;
    }

    messages.push(response);

    // No tool calls → final answer
    if (!response.tool_calls?.length) {
      const answer = response.content || "(no response)";
      console.log(chalk.green("\n💬 Answer:\n"));
      console.log(answer);
      console.log(chalk.green.bold("\n✅ Done\n"));
      await recordSession(task, answer, [...toolsUsed]);
      return answer;
    }

    // Execute tools
    for (const toolCall of response.tool_calls) {
      const { name, arguments: args } = toolCall.function;
      toolsUsed.add(name);
      console.log(chalk.magenta(`   → ${name}`));

      const result = await executeTool(name, args);
      const preview = result.length > 200 ? result.slice(0, 200) + chalk.dim(`... (${result.length} chars)`) : result;
      console.log(chalk.gray(`   ${preview.split("\n").join("\n   ")}\n`));

      messages.push({ role: "tool", tool_call_id: toolCall.id, content: result });
    }

    console.log(chalk.dim("─".repeat(50)));
  }

  const msg = `⚠ Hit ${max}-step limit.`;
  console.log(chalk.red.bold(`\n${msg}\n`));
  await recordSession(task, msg, [...toolsUsed]);
  return msg;
}
