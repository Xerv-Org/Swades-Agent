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

export { runAgent, runDirector, runCUA, executeTool };

async function detectModeWithAI(task) {
  if (!process.env.API_KEY) {
    return { isAutonomous: false, isCUA: false };
  }

  console.log(chalk.dim("🤖 AI is deciding the optimal execution mode..."));

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
      console.log(chalk.cyan("   (AI classified task: CUA mode)"));
      return { isAutonomous: false, isCUA: true };
    } else if (decision.includes("autonomous")) {
      console.log(chalk.cyan("   (AI classified task: Autonomous mode)"));
      return { isAutonomous: true, isCUA: false };
    } else {
      console.log(chalk.cyan("   (AI classified task: Normal mode)"));
      return { isAutonomous: false, isCUA: false };
    }
  } catch (err) {
    console.log(chalk.dim(`   (AI mode classification failed: ${err.message}. Defaulting to Normal mode.)`));
    return { isAutonomous: false, isCUA: false };
  }
}

async function getTaskAndMode() {
  const args = process.argv.slice(2);
  const hasAutonomousFlag = args.includes("--autonomous") || args.includes("-a");
  const hasCuaFlag = args.includes("--cua") || args.includes("-c");
  const hasNormalFlag = args.includes("--normal") || args.includes("-n");
  const hasSubagentsFlag = args.includes("--subagents") || args.includes("-s");

  let image = null;
  const imgIdx = args.findIndex(a => a === "--image" || a === "-i");
  if (imgIdx !== -1 && imgIdx + 1 < args.length) {
    image = args[imgIdx + 1];
  }

  // Filter out flags and their parameters to build clean task string
  const taskArgs = [];
  for (let i = 0; i < args.length; i++) {
    if (
      args[i] === "--autonomous" || args[i] === "-a" ||
      args[i] === "--cua" || args[i] === "-c" ||
      args[i] === "--normal" || args[i] === "-n" ||
      args[i] === "--subagents" || args[i] === "-s"
    ) {
      continue;
    }
    if (args[i] === "--image" || args[i] === "-i") {
      i++; // Skip the next arg (its value)
      continue;
    }
    taskArgs.push(args[i]);
  }
  const task = taskArgs.join(" ").trim();

  if (task) {
    if (hasAutonomousFlag) {
      return { task, image, isAutonomous: true, isCUA: false };
    }
    if (hasCuaFlag) {
      return { task, image, isAutonomous: false, isCUA: true };
    }
    if (hasSubagentsFlag) {
      process.env.SUBAGENTS_ONLY = "true";
      return { task, image, isAutonomous: false, isCUA: false };
    }
    if (hasNormalFlag) {
      return { task, image, isAutonomous: false, isCUA: false };
    }
    const aiMode = await detectModeWithAI(task);
    return { task, image, ...aiMode };
  }

  // Interactive prompt
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    console.log(chalk.cyan.bold("\n  Swades Agent\n"));
    rl.question(chalk.white.bold("Task → "), (taskAnswer) => {
      rl.question(chalk.white.bold("Image path/URL (optional) → "), (imageAnswer) => {
        rl.question(chalk.white.bold("Mode? [c]ua / [a]utonomous / [s]ubagents (no simulation) / [n]ormal / [enter] auto-detect → "), async (modeAnswer) => {
          rl.close();
          const m = modeAnswer.trim().toLowerCase();
          const taskStr = taskAnswer.trim();
          if (m === "c" || m === "cua") {
            res({ task: taskStr, image: imageAnswer.trim() || null, isAutonomous: false, isCUA: true });
          } else if (m === "a" || m === "autonomous") {
            res({ task: taskStr, image: imageAnswer.trim() || null, isAutonomous: true, isCUA: false });
          } else if (m === "s" || m === "subagents") {
            process.env.SUBAGENTS_ONLY = "true";
            res({ task: taskStr, image: imageAnswer.trim() || null, isAutonomous: false, isCUA: false });
          } else if (m === "n" || m === "normal") {
            res({ task: taskStr, image: imageAnswer.trim() || null, isAutonomous: false, isCUA: false });
          } else {
            const aiMode = await detectModeWithAI(taskStr);
            res({ task: taskStr, image: imageAnswer.trim() || null, ...aiMode });
          }
        });
      });
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
