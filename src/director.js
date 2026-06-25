// ============================================================
// director.js — Director AI loop orchestrator (24/7 Autonomy)
// ============================================================

import chalk from "chalk";
import { runAgent } from "./agent.js";
import { callLLM } from "./llm.js";
import { executeTool } from "./tools.js";

const DIRECTOR_SYSTEM_PROMPT = `{"role": "director", "content": "You are the Director AI supervising an autonomous software engineering agent."}
{"rule": "Responsibilities", "action": "Your job is to take a high-level user goal, break it down, and direct the worker agent to execute it step-by-step. After each worker run, analyze the result and decide if the overall goal is fully achieved, tested, and stable."}
{"rule": "Status Check", "action": "If everything is 100% complete, tested, and stable, respond with: 'STATUS: COMPLETE' followed by a concise summary of what was accomplished. Otherwise, respond with the next highly focused sub-task for the worker agent to execute."}
{"rule": "Guidance", "action": "Give precise, step-by-step tasks. Do not try to make the worker do everything in one go if the task is complex. Guide them iteratively."}
{"note": "Output 'STATUS: COMPLETE' ONLY when the entire goal is fully achieved and verified."}`;

/**
 * Run the Director AI loop for autonomous multi-step execution (24/7 Autonomy).
 *
 * @param {string} globalGoal - The overall high-level goal
 * @param {number} maxCycles - Safety cap on Director loops
 * @returns {string} - Final completion status
 */
export async function runDirector(globalGoal, maxCycles = 5) {
  console.log(chalk.green.bold("\n🎬 Director AI Activated (24/7 Autonomous Mode)"));
  console.log(chalk.dim(`   Global Goal: ${globalGoal}`));
  console.log(chalk.dim(`   Max cycles: ${maxCycles}\n`));
  console.log(chalk.dim("═".repeat(60)) + "\n");

  const history = [
    { role: "system", content: DIRECTOR_SYSTEM_PROMPT },
    {
      role: "user",
      content: `Global Goal: "${globalGoal}"\n\nAnalyze this goal and provide the first highly specific sub-task for the worker agent to execute.`,
    },
  ];

  for (let cycle = 1; cycle <= maxCycles; cycle++) {
    console.log(chalk.green.bold(`\n🎬 [Director Cycle ${cycle}/${maxCycles}]`));

    // 1. Ask the Director AI for the next instruction (streamed or synchronous)
    // We run the Director synchronously to get a clean instruction
    const directorResponse = await callLLM(history);
    const instruction = directorResponse.content.trim();

    // Check if Director declares task complete
    if (instruction.includes("STATUS: COMPLETE")) {
      console.log(chalk.green.bold("\n🎉 Director AI declares the global goal FULLY COMPLETE!"));
      console.log(chalk.green(instruction));
      console.log(chalk.dim("\n" + "═".repeat(60) + "\n"));
      return instruction;
    }

    console.log(chalk.green(`   Director Instruction: `) + chalk.white(instruction));
    history.push(directorResponse);

    // 2. Execute the Worker Agent on the sub-task
    console.log(chalk.cyan(`\n👷 Worker Agent starting sub-task...`));
    const workerResult = await runAgent(instruction);

    // 3. Gather workspace state for the Director to evaluate
    const gitStatus = await executeTool("run_command", { command: "git status --short" });

    // 4. Construct feedback for the Director
    const feedback = `[Cycle ${cycle} complete]
Worker Agent finished the sub-task.

Worker Output Summary:
${workerResult}

Current Git Status:
${gitStatus || "(no changes / clean)"}

What is the next sub-task? If everything is complete, tested, and correct, respond with 'STATUS: COMPLETE' and a final summary.`;

    history.push({
      role: "user",
      content: feedback,
    });
  }

  const msg = `⚠️ Director AI hit the safety cycle limit (${maxCycles}). Stopping to prevent infinite execution.`;
  console.log(chalk.red.bold(`\n${msg}\n`));
  return msg;
}
