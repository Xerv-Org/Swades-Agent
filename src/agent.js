// agent.js — ReAct loop orchestrator (THINK → ACT → OBSERVE)

import chalk from "chalk";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { resolve, extname } from "node:path";
import { callLLM, MODEL } from "./llm.js";
import { executeTool, activeDeadline } from "./tools.js";
import { SYSTEM_PROMPT, TOOL_SCHEMAS } from "./prompts.js";
import { getMemoryContext, recordSession } from "./memory.js";
import { runOrchestrated } from "./orchestrator.js";
import { runSimulated } from "./simulator.js";

/**
 * Prepare an image URL for OpenAI multimodal schema.
 * Supports web URLs and local file paths (converting local files to base64 data URIs).
 *
 * @param {string} imagePathOrUrl
 * @returns {Promise<string>}
 */
export async function prepareImageUrl(imagePathOrUrl) {
  if (!imagePathOrUrl) return null;

  if (imagePathOrUrl.startsWith("http://") || imagePathOrUrl.startsWith("https://") || imagePathOrUrl.startsWith("data:")) {
    return imagePathOrUrl;
  }

  const workdir = process.env.WORKDIR || process.cwd();
  let filePath = resolve(imagePathOrUrl);
  if (!existsSync(filePath)) {
    filePath = resolve(workdir, imagePathOrUrl);
  }

  if (!existsSync(filePath)) {
    throw new Error(`Image file not found: ${imagePathOrUrl}`);
  }

  const buffer = await readFile(filePath);
  const base64Data = buffer.toString("base64");

  const ext = extname(filePath).toLowerCase();
  let mimeType = "image/png";
  if (ext === ".jpg" || ext === ".jpeg") {
    mimeType = "image/jpeg";
  } else if (ext === ".gif") {
    mimeType = "image/gif";
  } else if (ext === ".webp") {
    mimeType = "image/webp";
  }

  return `data:${mimeType};base64,${base64Data}`;
}

/**
 * Run the ReAct agentic loop.
 * @param {string} task - User's task
 * @param {number} maxSteps - Safety cap (default Infinity)
 * @param {Array} existingMessages - Continue from existing conversation
 * @param {string} image - Optional image path or URL
 * @returns {string} - Final answer
 */
export async function runAgent(task, maxSteps, existingMessages, image) {
  const max = maxSteps || parseInt(process.env.MAX_STEPS) || Infinity;
  let messages = existingMessages;

  // ---- Orchestrator gate (only for fresh top-level tasks) ----
  if (!existingMessages && task && !task.startsWith("[SUBAGENT:") && !task.startsWith("[SIMULATION") && !image) {
    const workdir = process.env.WORKDIR || process.cwd();
    const resolvedWorkdir = resolve(workdir);

    try {
      const orchestratorResult = await runOrchestrated(task, resolvedWorkdir);
      if (orchestratorResult !== null) {
        // HIGH complexity — orchestrator handled everything
        await recordSession(task, orchestratorResult, ["orchestrator", "subagents", "simulator"]);
        return orchestratorResult;
      }
    } catch (err) {
      console.log(chalk.yellow(`   ⚠ Orchestrator eval error: ${err.message}, proceeding with single agent`));
    }

    // LOW complexity — falls through to normal ReAct loop below
  }

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

    let userContent = task;
    if (image) {
      try {
        const imageUrl = await prepareImageUrl(image);
        userContent = [
          { type: "text", text: task },
          { type: "image_url", image_url: { url: imageUrl } }
        ];
      } catch (err) {
        console.log(chalk.red(`❌ Image prepare failed: ${err.message}`));
        throw err;
      }
    }

    messages = [
      { role: "system", content: SYSTEM_PROMPT + workspaceContext + indexContext + memoryContext },
      { role: "user", content: userContent },
    ];
  }

  const toolsUsed = new Set();

  let estimatedDurationSeconds = 180;
  if (!existingMessages && task) {
    console.log(chalk.dim("⏰ AI is estimating the optimal task deadline..."));
    try {
      const estimationPrompt = [
        {
          role: "system",
          content: "You are the time estimator for Swades Agent. Estimate how many seconds this task should take to execute under ordinary circumstances. Be realistic and consider code writing, file searches, testing, and debugging. Respond with ONLY a single integer representing seconds (e.g. 120). Minimum: 30 seconds, Maximum: 600 seconds. Do not write any other text."
        },
        {
          role: "user",
          content: `Task: ${task}`
        }
      ];
      const res = await callLLM(estimationPrompt);
      const seconds = parseInt(res.content?.trim());
      if (!isNaN(seconds) && seconds >= 30 && seconds <= 600) {
        estimatedDurationSeconds = seconds;
      }
    } catch (err) {
      console.log(chalk.dim(`   (AI time estimation failed: ${err.message}. Defaulting to 180s.)`));
    }
    console.log(chalk.cyan(`   (AI allocated task time: ${estimatedDurationSeconds} seconds)`));
    
    activeDeadline.estimatedSeconds = estimatedDurationSeconds;
    activeDeadline.startTime = Date.now();
  } else {
    if (!activeDeadline.startTime) {
      activeDeadline.startTime = Date.now();
      activeDeadline.estimatedSeconds = 180;
    }
  }

  console.log(chalk.cyan.bold("\n🤖 Agent started"));
  console.log(chalk.dim(`   Model: ${MODEL} | Steps: ${max === Infinity ? "∞" : max} | Task: ${task || "continuing"}\n`));

  let graceStepsLeft = 3;

  for (let step = 1; step <= max; step++) {
    console.log(chalk.yellow(`⚡ Step ${step}${max === Infinity ? "" : `/${max}`}`));

    const elapsed = Math.round((Date.now() - activeDeadline.startTime) / 1000);
    const remaining = activeDeadline.estimatedSeconds - elapsed;

    let urgencyLevel = "CALM";
    let pressureGuideline = "Plenty of time left. Focus on clean code, validation, and complete solutions.";
    let timerColor = chalk.green;
    
    const pct = remaining / activeDeadline.estimatedSeconds;
    if (remaining <= 0) {
      urgencyLevel = "OVERTIME";
      pressureGuideline = "🚨 DEADLINE EXPIRED: You are running in OVERTIME! You MUST wrap up immediately. If you need more time to finish cleanly, explain why and call the 'extend_deadline' tool now to prevent forced shutdown.";
      timerColor = chalk.bgRed.white.bold;
    } else if (pct < 0.1) {
      urgencyLevel = "PANIC";
      pressureGuideline = "⚠️ CRITICAL TIME PRESSURE: Time is almost up! Omit extra steps, focus purely on resolving the core task and finishing immediately.";
      timerColor = chalk.red.bold;
    } else if (pct < 0.3) {
      urgencyLevel = "URGENT";
      pressureGuideline = "Time is running low. Avoid round-trips, run tests quickly, and resolve the final steps.";
      timerColor = chalk.red;
    } else if (pct < 0.6) {
      urgencyLevel = "MEDIUM";
      pressureGuideline = "Time is ticking. Work efficiently and avoid repeating commands.";
      timerColor = chalk.yellow;
    }

    if (remaining <= 0) {
      graceStepsLeft--;
      if (graceStepsLeft < 0) {
        const errorMsg = `🚨 [LOOP PREVENTION] Task terminated: Deadline exceeded and grace step limit reached without extension.`;
        console.log(chalk.red.bold(`\n${errorMsg}\n`));
        await recordSession(task, errorMsg, [...toolsUsed]);
        return errorMsg;
      }
    }

    const barWidth = 20;
    const filledWidth = Math.max(0, Math.min(barWidth, Math.round(pct * barWidth)));
    const emptyWidth = barWidth - filledWidth;
    const barStr = "█".repeat(filledWidth) + "░".repeat(emptyWidth);
    
    const remainingText = remaining <= 0 ? `OVERTIME (${Math.abs(remaining)}s overdue)` : `${remaining}s remaining`;
    console.log(timerColor(`⏰ TIMER: ${remainingText} / ${activeDeadline.estimatedSeconds}s [${barStr}] URGENCY: ${urgencyLevel}`));
    if (remaining <= 0) {
      console.log(chalk.red(`   ⚠️ Grace steps left: ${graceStepsLeft + 1} steps`));
    }

    const timePressureContext = `\n\n## URGENT TIMING AND DEADLINE SYSTEM
- Task Start Time: ${new Date(activeDeadline.startTime).toISOString()}
- Current Time: ${new Date().toISOString()}
- Total Allocated Duration: ${activeDeadline.estimatedSeconds}s
- Elapsed Time: ${elapsed}s
- Remaining Time: ${remainingText}
- Urgency Level: ${urgencyLevel}
- Critical Instruction: ${pressureGuideline}
${remaining <= 0 ? `- GRACE WARNING: You will be forcibly terminated in ${graceStepsLeft + 1} steps if you do not complete the task or use 'extend_deadline'.` : ""}`;

    if (!messages[0]._originalContent) {
      messages[0]._originalContent = messages[0].content;
    }
    messages[0].content = messages[0]._originalContent + timePressureContext;

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
