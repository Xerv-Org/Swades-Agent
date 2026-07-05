// index.js — Entry point & CLI

import "dotenv/config";
import { createInterface } from "node:readline";
import chalk from "chalk";
import { runAgent } from "./agent.js";
import { runDirector } from "./director.js";
import { runCUA } from "./cua.js";
import { executeTool } from "./tools.js";

// CUA-related keywords for auto-detection
const CUA_HINTS = ["click", "open app", "browser", "screen", "desktop", "gui", "window", "mouse", "type in", "navigate to", "fill form", "screenshot"];

async function getTaskAndMode() {
  const args = process.argv.slice(2);
  const isAutonomous = args.includes("--autonomous") || args.includes("-a");
  const forceCUA = args.includes("--cua") || args.includes("-c");

  const taskArgs = args.filter(a => !a.startsWith("-"));
  const task = taskArgs.join(" ").trim();

  if (task) {
    // Auto-detect CUA from task text if not explicitly set
    const isCUA = forceCUA || CUA_HINTS.some(h => task.toLowerCase().includes(h));
    if (isCUA && !forceCUA) {
      console.log(chalk.dim("   (Auto-detected CUA mode from task keywords)"));
    }
    return { task, isAutonomous, isCUA };
  }

  // Interactive prompt
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    console.log(chalk.cyan.bold("\n  Swades Agent\n"));
    rl.question(chalk.white.bold("Task → "), (taskAnswer) => {
      rl.question(chalk.white.bold("Mode? [c]ua / [a]utonomous / [enter] normal → "), (modeAnswer) => {
        rl.close();
        const m = modeAnswer.trim().toLowerCase();
        res({
          task: taskAnswer.trim(),
          isAutonomous: m === "a" || m === "autonomous",
          isCUA: m === "c" || m === "cua",
        });
      });
    });
  });
}

async function main() {
  const { task, isAutonomous, isCUA } = await getTaskAndMode();

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
      await runDirector(task);
    } else {
      await runAgent(task);
    }
  } catch (err) {
    console.error(chalk.red(`Fatal: ${err.message}`));
    process.exit(1);
  }
}

main();
