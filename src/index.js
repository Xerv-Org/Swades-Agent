// ============================================================
// index.js — Entry point & CLI interface
// ============================================================

import "dotenv/config";
import { createInterface } from "node:readline";
import chalk from "chalk";
import { runAgent } from "./agent.js";
import { runDirector } from "./director.js";
import { executeTool } from "./tools.js";

// ---- Get the task and mode from CLI args or interactive prompt ----

async function getTaskAndMode() {
  const args = process.argv.slice(2);
  const isAutonomous = args.includes("--autonomous") || args.includes("-a");

  // Filter out flags to get the raw task description
  const taskArgs = args.filter((arg) => arg !== "--autonomous" && arg !== "-a");
  const task = taskArgs.join(" ").trim();

  if (task) {
    return { task, isAutonomous };
  }

  // Interactive prompt
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    console.log(chalk.cyan.bold("\n╔══════════════════════════════════════╗"));
    console.log(chalk.cyan.bold("║    🧠 ReAct SWE Agent               ║"));
    console.log(chalk.cyan.bold("╚══════════════════════════════════════╝\n"));
    
    rl.question(chalk.white.bold("What should I do? → "), (taskAnswer) => {
      rl.question(chalk.white.bold("Run in 24/7 Autonomous Mode? (y/N) → "), (modeAnswer) => {
        rl.close();
        res({
          task: taskAnswer.trim(),
          isAutonomous: modeAnswer.toLowerCase() === "y" || modeAnswer.toLowerCase() === "yes",
        });
      });
    });
  });
}

// ---- Main ----

async function main() {
  const { task, isAutonomous } = await getTaskAndMode();

  if (!task) {
    console.log(chalk.red("No task provided. Exiting."));
    process.exit(1);
  }

  if (!process.env.API_KEY) {
    console.log(chalk.red("Missing API_KEY in your env/command line. Copy .env.example to .env and add your key."));
    process.exit(1);
  }

  // 1. Auto-index the codebase at startup (gives the AI instant, deep knowledge)
  console.log(chalk.dim("⚡ Auto-indexing codebase..."));
  const indexResult = await executeTool("index_codebase", {});
  console.log(chalk.dim(`   ${indexResult}\n`));

  try {
    if (isAutonomous) {
      // Run in 24/7 Director-supervised Autonomous Mode
      await runDirector(task);
    } else {
      // Run standard single-run Worker Mode
      await runAgent(task);
    }
  } catch (err) {
    console.error(chalk.red(`\nFatal error: ${err.message}`));
    process.exit(1);
  }
}

main();
