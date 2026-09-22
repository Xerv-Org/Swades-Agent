#!/usr/bin/env node
// index.js — Entry point, CLI parser & persistent chat loop

import "dotenv/config";
import { createInterface } from "node:readline";
import chalk from "chalk";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { spawn } from "node:child_process";
import { runAgent } from "./agent.js";
import { runDirector } from "./director.js";
import { runCUA } from "./cua.js";
import { runCuaAgent } from "./cua_agent.js";
import { executeTool } from "./tools.js";
import { callLLM, API_KEY } from "./llm.js";
import { migrateAndCleanup } from "./cleanup.js";
import { recordSession } from "./memory.js";
import { initApprovalFlow } from "./approvalFlow.js";

export { runAgent, runDirector, runCUA, executeTool };

// ============================================================
// CLI flag helpers
// ============================================================

function printHelp() {
  console.log(chalk.cyan.bold("\n  🚀 Swades Agent v4.0\n"));
  console.log(chalk.white("  Usage: swades-agent [task] [flags]\n"));
  console.log(chalk.dim("  If no task is given, enters the persistent chat loop.\n"));

  console.log(chalk.white.bold("  Execution Flags & Commands:\n"));
  console.log(chalk.green("  cua [task]          ") + "Computer Use Agent with low-level structural perception (CDP, AT-SPI2, /proc)");
  console.log(chalk.green("  cua --hud           ") + "Launch interactive local Web HUD overlay (http://localhost:6081)");
  console.log(chalk.green("  --cua, -c           ") + "Flag equivalent for CUA mode");
  console.log(chalk.green("  --orchestrated, -o  ") + "Multi-agent orchestrated pipeline with dependency graphs & debate");
  console.log(chalk.green("  --autonomous, -a    ") + "Hint: start in Director loop (agent can escalate on its own anyway)");
  console.log(chalk.green("  --sim               ") + "Hint: bias toward run_simulation tool (agent can also call it autonomously)");
  console.log(chalk.green("  --subagents, -s     ") + "Hint: bias toward spawn_subagents tool");
  console.log(chalk.green("  --no-sim            ") + "Disable run_simulation even if agent wants to use it");
  console.log();
  console.log(chalk.white.bold("  Other Flags:\n"));
  console.log(chalk.blue("  --image, -i <path>  ") + "Attach a local image or URL to the task");
  console.log(chalk.blue("  --rewind            ") + "List available checkpoints from last session");
  console.log(chalk.blue("  --help, -h          ") + "Show this help message");
  console.log();
  console.log(chalk.white.bold("  Chat Loop Commands (while running):\n"));
  console.log(chalk.yellow("  exit / quit         ") + "Exit the agent");
  console.log(chalk.yellow("  clear               ") + "Reset the message context (start fresh)");
  console.log(chalk.yellow("  /help               ") + "Show this help inside the loop");
  console.log();
  console.log(chalk.dim("  Examples:"));
  console.log(chalk.dim('    swades cua "Inspect browser console errors and list open windows"'));
  console.log(chalk.dim('    swades cua --hud'));
  console.log(chalk.dim('    swades "Add login tests"'));
  console.log(chalk.dim('    swades "Refactor to TypeScript" --autonomous'));
  console.log(chalk.dim('    swades "Build REST API" --sim'));
  console.log();
}

function parseCLI() {
  const args = process.argv.slice(2);

  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    process.exit(0);
  }

  const isCuaSubcommand    = args[0] === "cua";
  const hasCuaFlag         = isCuaSubcommand || args.includes("--cua") || args.includes("-c");
  const hasHudFlag         = args.includes("--hud");
  const hasOrchestratedFlag = args.includes("--orchestrated") || args.includes("-o");
  const hasAutonomousFlag  = args.includes("--autonomous")   || args.includes("-a");
  const hasSimFlag         = args.includes("--sim");
  const hasNoSimFlag       = args.includes("--no-sim");
  const hasSubagentsFlag   = args.includes("--subagents")    || args.includes("-s");
  const hasRewindFlag      = args.includes("--rewind");

  let image = null;
  const imgIdx = args.findIndex(a => a === "--image" || a === "-i");
  if (imgIdx !== -1 && imgIdx + 1 < args.length) {
    image = args[imgIdx + 1];
  }

  const FLAG_TOKENS = new Set([
    "cua", "--cua", "-c", "--hud", "--orchestrated", "-o", "--autonomous", "-a", "--sim", "--no-sim",
    "--subagents", "-s", "--rewind", "--help", "-h",
  ]);
  const taskArgs = [];
  for (let i = 0; i < args.length; i++) {
    if (FLAG_TOKENS.has(args[i])) continue;
    if (args[i] === "--image" || args[i] === "-i") { i++; continue; }
    taskArgs.push(args[i]);
  }
  const task = taskArgs.join(" ").trim();

  // Apply env hints from flags — capability tool calling is biased by these
  if (hasOrchestratedFlag) {
    process.env.FORCE_ORCHESTRATED = "true";
    process.env.PREFER_ORCHESTRATED = "true";
  }
  if (hasSimFlag)        process.env.PREFER_SIMULATION = "true";
  if (hasNoSimFlag)      process.env.DISABLE_SIMULATION = "true";
  if (hasSubagentsFlag)  process.env.PREFER_SUBAGENTS = "true";
  if (hasAutonomousFlag) process.env.PREFER_DIRECTOR = "true";

  return { task, image, isCUA: hasCuaFlag, hasHudFlag, hasRewindFlag, isOrchestrated: hasOrchestratedFlag };
}

// ============================================================
// System-level startup (runs once)
// ============================================================

async function startup(isCUA) {
  if (!API_KEY) {
    console.log(chalk.red("❌ Missing API_KEY / GROQ_API_KEY in .env. Copy .env.example → .env and add your key."));
    process.exit(1);
  }

  if (!isCUA) {
    const workdir = process.env.WORKDIR || process.cwd();
    console.log(chalk.dim("🧹 Checking for legacy files to migrate..."));
    await migrateAndCleanup(resolve(workdir));

    console.log(chalk.dim("⚡ Indexing codebase..."));
    const r = await executeTool("index_codebase", {});
    console.log(chalk.dim(`   ${r}\n`));

    // Initialize approval flow (asks user once, saves preference)
    try {
      const mode = await initApprovalFlow();
      console.log(chalk.dim(`   🔒 Approval mode: ${mode}\n`));
    } catch (approvalErr) {
      console.log(chalk.dim(`   ⚠ Approval flow init skipped: ${approvalErr.message}`));
    }
  }
}

// ============================================================
// Inline --image parser for chat loop
// ============================================================

function parseInlineTask(input) {
  // Support: "some task --image path/to/img.png" inside the chat loop
  const parts = input.split(/\s+/);
  let image = null;
  const imgIdx = parts.findIndex(p => p === "--image" || p === "-i");
  if (imgIdx !== -1 && imgIdx + 1 < parts.length) {
    image = parts[imgIdx + 1];
    parts.splice(imgIdx, 2);
  }
  return { task: parts.join(" ").trim(), image };
}

// ============================================================
// Persistent Chat Loop
// ============================================================

/**
 * Run the agent in a persistent chat loop.
 * Messages (context) are preserved across tasks within a session.
 * Users can reset context with 'clear', exit with 'exit'/'quit'.
 *
 * @param {string|null} initialTask  - Task from CLI args (if any)
 * @param {string|null} initialImage - Image from CLI args (if any)
 */
async function chatLoop(initialTask, initialImage) {
  const workdir = process.env.WORKDIR || process.cwd();
  const resolvedWorkdir = resolve(workdir);

  // Session-persistent message history
  let sessionMessages = null;

  console.log(chalk.cyan.bold("\n  🚀 Swades Agent v4.0"));
  console.log(chalk.dim(`  Workspace: ${resolvedWorkdir}`));
  console.log(chalk.dim("  Type 'exit' to quit | 'clear' to reset context | '/help' for commands\n"));
  console.log(chalk.dim("─".repeat(60)));

  // If a task was passed on the CLI, execute it first
  if (initialTask) {
    console.log(chalk.dim(`\n  Running initial task: "${initialTask}"\n`));
    try {
      const result = await runAgent(initialTask, null, sessionMessages, initialImage);
      sessionMessages = runAgent.lastMessages || sessionMessages;
    } catch (err) {
      console.error(chalk.red(`Fatal: ${err.message}`));
    }
    console.log(chalk.dim("\n─".repeat(60)));
  }

  // ---- Interactive Chat Loop ----
  const rl = createInterface({ input: process.stdin, output: process.stdout });

  const prompt = () => new Promise((res) => {
    rl.question(chalk.cyan.bold("\n💬 What do you need? → "), res);
  });

  while (true) {
    let input;
    try {
      input = await prompt();
    } catch {
      // stdin closed (piped input finished)
      console.log(chalk.dim("\n  [stdin closed — exiting]"));
      break;
    }

    const trimmed = input.trim();
    if (!trimmed) continue;

    // ---- Chat Commands ----
    if (trimmed.toLowerCase() === "exit" || trimmed.toLowerCase() === "quit") {
      console.log(chalk.cyan("\n  👋 Goodbye!\n"));
      rl.close();
      break;
    }

    if (trimmed.toLowerCase() === "clear") {
      sessionMessages = null;
      if (runAgent.lastMessages) runAgent.lastMessages = null;
      console.log(chalk.yellow("  🧹 Context cleared — starting fresh.\n"));
      continue;
    }

    if (trimmed === "/help") {
      printHelp();
      continue;
    }

    // ---- Parse inline --image flag ----
    const { task, image } = parseInlineTask(trimmed);
    if (!task) continue;

    // ---- Run the agent (messages persist across tasks) ----
    console.log(chalk.dim("\n" + "─".repeat(60)));
    try {
      const result = await runAgent(task, null, sessionMessages, image);
      sessionMessages = runAgent.lastMessages || sessionMessages;
      // Note: tier info is displayed by the orchestrator itself when it activates
      // Record completed session
      await recordSession(task, typeof result === "string" ? result : String(result), []);
      console.log(chalk.dim("\n─".repeat(60)));
      console.log(chalk.green("  ✅ Task complete. Next task? (type 'clear' to reset context, 'exit' to quit)"));
    } catch (err) {
      console.error(chalk.red(`\n  ❌ Agent error: ${err.message}`));
      console.log(chalk.yellow("  Context preserved. You can continue with the next task."));
    }
  }

  process.exit(0);
}

// ============================================================
// Main Entry Point
// ============================================================

async function main() {
  const { task, image, isCUA, hasHudFlag, hasRewindFlag, isOrchestrated } = parseCLI();

  // --rewind: list available checkpoints (informational)
  if (hasRewindFlag) {
    const { checkpointStore } = await import("./tools.js");
    if (checkpointStore.length === 0) {
      console.log(chalk.yellow("No checkpoints available in this session. Checkpoints are created during a running task."));
    } else {
      console.log(chalk.cyan.bold("\nAvailable checkpoints:"));
      for (const cp of checkpointStore) {
        console.log(chalk.green(`  Step ${cp.step}: stash ${cp.stashHash?.slice(0, 8) || "N/A"}`));
      }
    }
    process.exit(0);
  }

  // ---- CUA mode: swades cua / swades --cua / swades cua --hud ----
  if (isCUA) {
    if (hasHudFlag) {
      console.log(chalk.cyan.bold("\n  🚀 Launching Swades CUA Interactive Web HUD..."));
      console.log(chalk.dim("  Desktop Stream: 100% read-only locked (pointer-events: none)"));
      console.log(chalk.green("  Access URL: http://localhost:6081\n"));
      const overlayPath = resolve(fileURLToPath(import.meta.url), "../web_chat_overlay.py");
      const hudProc = spawn("python3", [overlayPath], { stdio: "inherit" });
      hudProc.on("close", (code) => process.exit(code || 0));
      return;
    }

    if (!task) {
      console.log(chalk.yellow("\n  🚀 Swades CUA (Computer Use Agent) — Native Low-Level OS Perception"));
      console.log(chalk.white("  Usage:"));
      console.log(chalk.green('    swades cua "<task>"') + chalk.dim("     Autonomous ReAct loop (CDP, AT-SPI2, /proc)"));
      console.log(chalk.green('    swades cua --hud') + chalk.dim("        Launch local Web HUD overlay (http://localhost:6081)"));
      console.log(chalk.dim('  Example: swades cua "Inspect browser console errors and list open windows"\n'));
      process.exit(0);
    }

    if (!API_KEY) {
      console.log(chalk.red("❌ Missing API_KEY / GROQ_API_KEY in .env"));
      process.exit(1);
    }

    try {
      await runCuaAgent(task);
    } catch (err) {
      console.error(chalk.red(`Fatal CUA Error: ${err.message}`));
      process.exit(1);
    }
    return;
  }

  // ---- Normal & Autonomous modes: startup + chat loop ----
  await startup(false);

  // ---- Orchestrator mode: --orchestrated / -o flag ----
  if (isOrchestrated && task) {
    console.log(chalk.blue.bold("\n🔷 Orchestrator mode (--orchestrated flag): delegating to Multi-Agent Orchestrator"));
    try {
      const { runOrchestrated } = await import("./orchestrator.js");
      const workdir = process.env.WORKDIR || process.cwd();
      const result = await runOrchestrated(task, resolve(workdir));
      if (result) {
        console.log(chalk.green("\n  ✅ Orchestrated execution completed successfully."));
      }
    } catch (err) {
      console.error(chalk.red(`Fatal: ${err.message}`));
      process.exit(1);
    }
    process.exit(0);
  }

  // PREFER_DIRECTOR hint: start with Director for long-horizon autonomous mode
  if (process.env.PREFER_DIRECTOR === "true" && task) {
    console.log(chalk.green.bold("\n🎬 Director mode (--autonomous flag): delegating to Director AI"));
    try {
      await runDirector(task, Infinity, image);
    } catch (err) {
      console.error(chalk.red(`Fatal: ${err.message}`));
      process.exit(1);
    }
    // After director finishes, drop into chat loop
    await chatLoop(null, null);
    return;
  }

  // Default: enter chat loop (task from CLI is the first message, if any)
  await chatLoop(task || null, image || null);
}

// ---- CLI guard ----
const isMain = process.argv[1] && (
  fileURLToPath(import.meta.url) === resolve(process.argv[1]) ||
  resolve(process.argv[1]).endsWith("swades") ||
  resolve(process.argv[1]).endsWith("swades-agent") ||
  resolve(process.argv[1]).endsWith("index.js")
);

if (isMain) {
  main();
}
