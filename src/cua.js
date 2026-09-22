// cua.js — Computer Use Agent (CUA) — Unified with Swades Core ReAct Loop
import chalk from "chalk";
import { runAgent } from "./agent.js";

export async function runCUA(globalGoal, maxSteps = 40) {
  process.env.SWADES_CUA_MODE = "true";
  console.log(chalk.cyan.bold("\n🖥️  Swades CUA (Unified ReAct Engine)"));
  console.log(chalk.dim(`   Goal: "${globalGoal}"\n`));
  return await runAgent(globalGoal);
}
