#!/usr/bin/env node
// index.js — Entry point & CLI

import "dotenv/config";
import { createInterface } from "node:readline";
import chalk from "chalk";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { runAgent } from "./agent.js";
import { runDirector } from "./director.js";
import { runCUA } from "./cua.js";
import { executeTool } from "./tools.js";
import { callLLM } from "./llm.js";
import { migrateAndCleanup } from "./cleanup.js";

export { runAgent, runDirector, runCUA, executeTool };

async function detectModeWithAI(task) {
  if (!process.env.API_KEY) {
    return { isAutonomous: false, isCUA: false };
  }

  console.log(chalk.dim("🤖 Auto-detecting optimal execution mode..."));

  const systemPrompt = `You are the execution mode classifier for Swades Agent.
Your job is to classify the user's task into one of the following execution modes:
1. "cua" (Computer Use Agent): Use this if the task requires GUI automation, desktop interaction, web browsing, clicking, screenshots, mouse/keyboard inputs, or opening applications (e.g. Chrome, Settings, VSCode UI, file manager).
2. "autonomous" (Director Mode): Use this if the task is complex, multi-file, requires planning, self-correction, multiple steps of execution, or building a feature/debugging code (e.g. "implement feature X", "debug the test failures in this directory", "refactor the database helper").
3. "normal": Use this for simple, single-step tasks that can be done in a single run (e.g. "explain how function X works", "format this JSON", "what is the date", "run git status").

Response MUST be a single word, one of: "cua", "autonomous", "normal". Do not write anything else.`;

  try {
    const response = await callLLM([
      { role: "system", content: systemPrompt },
      { role: "user", content: `Task: ${task}` }
    ]);
    
    const decision = response.content?.trim().toLowerCase() || "normal";
    
    if (decision.includes("cua")) {
      console.log(chalk.cyan("   → CUA mode (desktop automation)"));
      return { isAutonomous: false, isCUA: true };
    } else if (decision.includes("autonomous")) {
      console.log(chalk.cyan("   → Autonomous mode (Director-supervised)"));
      return { isAutonomous: true, isCUA: false };
    } else {
      console.log(chalk.cyan("   → Normal mode (single-run)"));
      return { isAutonomous: false, isCUA: false };
    }
  } catch (err) {
    console.log(chalk.dim(`   (Auto-detect failed: ${err.message}. Using normal mode.)`));
    return { isAutonomous: false, isCUA: false };
  }
}

function printHelp() {
  console.log(chalk.cyan.bold("\n  🚀 Swades Agent v2.0.0\n"));
  console.log(chalk.white("  Usage: swades-agent [task] [flags]\n"));
  console.log(chalk.dim("  If no task is given, drops into interactive mode.\n"));
  console.log(chalk.white.bold("  Execution Strategy Flags:\n"));
  console.log(chalk.green("  (default)          ") + "AI auto-detects the best strategy for your task");
  console.log(chalk.green("  --autonomous, -a   ") + "Force Director-supervised loop (multi-cycle autonomous)");
  console.log(chalk.green("  --normal, -n       ") + "Force single-run agent (no Director loop)");
  console.log(chalk.green("  --cua, -c          ") + "Force Computer Use Agent (desktop/GUI automation)");
  console.log();
  console.log(chalk.white.bold("  Subagent & Simulation Flags:\n"));
  console.log(chalk.yellow("  (default)          ") + "Subagents + simulation auto-triggered on HIGH complexity tasks");
  console.log(chalk.yellow("  --subagents, -s    ") + "Force subagent decomposition, SKIP post-merge simulation (faster)");
  console.log(chalk.yellow("  --no-sim           ") + "Same as --subagents: subagents enabled, simulation disabled");
  console.log(chalk.yellow("  --sim              ") + "Force subagent decomposition WITH simulation (even on low-complexity)");
  console.log();
  console.log(chalk.white.bold("  Other Flags:\n"));
  console.log(chalk.blue("  --image, -i <path> ") + "Attach a local image or URL to the task");
  console.log(chalk.blue("  --help, -h         ") + "Show this help message");
  console.log();
  console.log(chalk.dim("  Examples:"));
  console.log(chalk.dim('    swades-agent "Add login tests"'));
  console.log(chalk.dim('    swades-agent "Refactor to TypeScript" --autonomous'));
  console.log(chalk.dim('    swades-agent "Build REST API" --subagents        # fast, no simulation'));
  console.log(chalk.dim('    swades-agent "Build REST API" --sim               # subagents + full simulation'));
  console.log(chalk.dim('    swades-agent "Implement UI" --image mockup.png'));
  console.log();
}

async function getTaskAndMode() {
  const args = process.argv.slice(2);

  // --help / -h
  if (args.includes("--help") || args.includes("-h")) {
    printHelp();
    process.exit(0);
  }

  const hasAutonomousFlag = args.includes("--autonomous") || args.includes("-a");
  const hasCuaFlag        = args.includes("--cua")        || args.includes("-c");
  const hasNormalFlag     = args.includes("--normal")     || args.includes("-n");
  // --subagents / -s / --no-sim → subagents WITHOUT simulation (faster)
  const hasNoSimFlag      = args.includes("--subagents")  || args.includes("-s") || args.includes("--no-sim");
  // --sim → force subagents WITH simulation (even on auto-detected low-complexity)
  const hasSimFlag        = args.includes("--sim");

  let image = null;
  const imgIdx = args.findIndex(a => a === "--image" || a === "-i");
  if (imgIdx !== -1 && imgIdx + 1 < args.length) {
    image = args[imgIdx + 1];
  }

  // Filter out flags and their parameters to build clean task string
  const FLAG_TOKENS = new Set([
    "--autonomous", "-a", "--cua", "-c", "--normal", "-n",
    "--subagents", "-s", "--no-sim", "--sim", "--help", "-h",
  ]);
  const taskArgs = [];
  for (let i = 0; i < args.length; i++) {
    if (FLAG_TOKENS.has(args[i])) continue;
    if (args[i] === "--image" || args[i] === "-i") {
      i++; // Skip the next arg (its value)
      continue;
    }
    taskArgs.push(args[i]);
  }
  const task = taskArgs.join(" ").trim();

  if (task) {
    // CLI flags are power-user overrides — they skip auto-detection
    if (hasAutonomousFlag) {
      return { task, image, isAutonomous: true, isCUA: false };
    }
    if (hasCuaFlag) {
      return { task, image, isAutonomous: false, isCUA: true };
    }
    if (hasNoSimFlag) {
      // Subagents enabled, simulation SKIPPED
      process.env.SUBAGENTS_ONLY = "true";
      console.log(chalk.yellow("   ⚡ Mode: Subagents (simulation skipped)"));
      return { task, image, isAutonomous: false, isCUA: false };
    }
    if (hasSimFlag) {
      // Force full pipeline: subagents + simulation
      process.env.FORCE_ORCHESTRATED = "true";
      console.log(chalk.yellow("   🧪 Mode: Subagents + Simulation (forced)"));
      return { task, image, isAutonomous: false, isCUA: false };
    }
    if (hasNormalFlag) {
      return { task, image, isAutonomous: false, isCUA: false };
    }
    // No flag → AI auto-detects the best mode
    const aiMode = await detectModeWithAI(task);
    return { task, image, ...aiMode };
  }

  // ---- Zero-friction interactive prompt ----
  // Only asks for the task. Mode is auto-detected. No choices, no paralysis.
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    console.log(chalk.cyan.bold("\n  🚀 Swades Agent\n"));
    console.log(chalk.dim("  Just describe what you want done. Mode is auto-detected.\n"));
    rl.question(chalk.white.bold("  What do you need? → "), async (taskAnswer) => {
      rl.close();
      const taskStr = taskAnswer.trim();
      if (!taskStr) {
        res({ task: "", image: null, isAutonomous: false, isCUA: false });
        return;
      }
      // Auto-detect mode from task description — zero user decisions
      const aiMode = await detectModeWithAI(taskStr);
      res({ task: taskStr, image: null, ...aiMode });
    });
  });
}

async function main() {
  const { task, image, isAutonomous, isCUA } = await getTaskAndMode();

  if (!task) {
    console.log(chalk.red("No task. Exiting."));
    process.exit(1);
  }

  if (!process.env.API_KEY) {
    console.log(chalk.red("Missing API_KEY in .env"));
    process.exit(1);
  }

  // Migrate legacy files from project root to cache directory
  if (!isCUA) {
    const workdir = process.env.WORKDIR || process.cwd();
    console.log(chalk.dim("🧹 Checking for legacy files to migrate..."));
    await migrateAndCleanup(resolve(workdir));
  }

  // Index codebase only for coding tasks
  if (!isCUA) {
    console.log(chalk.dim("⚡ Indexing codebase..."));
    const r = await executeTool("index_codebase", {});
    console.log(chalk.dim(`   ${r}\n`));
  }

  try {
    if (isCUA) {
      await runCUA(task);
    } else if (isAutonomous) {
      await runDirector(task, Infinity, image);
    } else {
      await runAgent(task, null, null, image);
    }
  } catch (err) {
    console.error(chalk.red(`Fatal: ${err.message}`));
    process.exit(1);
  }
}

// Check if run directly (CLI mode)
const isMain = process.argv[1] && (
  fileURLToPath(import.meta.url) === resolve(process.argv[1]) ||
  resolve(process.argv[1]).endsWith("bin/swades-agent") ||
  resolve(process.argv[1]).endsWith("bin\\swades-agent")
);

if (isMain) {
  main();
}
