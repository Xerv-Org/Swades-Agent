// ============================================================
// orchestrator.js — Task complexity evaluation + subagent
// spawning + simulation integration
// ============================================================

import chalk from "chalk";
import { exec } from "node:child_process";
import { resolve } from "node:path";
import { writeFile, readFile, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { callLLM } from "./llm.js";
import { runSubagent, runSubagentsParallel } from "./subagent.js";
import { runSimulated } from "./simulator.js";
import { runOrchestratorLoop } from "./orchestratorLoop.js";

// ---- Shell helper ----

function shell(cmd, cwd) {
  return new Promise((resolve, reject) => {
    exec(cmd, { cwd, maxBuffer: 10 * 1024 * 1024, timeout: 120000 }, (err, stdout, stderr) => {
      if (err) return reject(new Error(stderr || stdout || err.message));
      resolve(stdout || "");
    });
  });
}

// ---- Complexity Evaluation ----

const CLASSIFIER_PROMPT = `You are a task complexity classifier for an AI coding agent. Given a coding task, classify it into one of 4 tiers:

TINY — 1 solo agent, no orchestration:
  Single file edit, explanation, quick command, docs update, config tweak

NORMAL — planner + 2-4 agents:
  Multi-file feature, moderate refactor, add tests, bug fix across files

BIG — planner + 4-6 agents:
  Cross-module feature, large refactor, new subsystem, migration

HUGE — planner + 6-8 agents:
  Full architecture overhaul, massive migration, rewrite

RULES:
- Keep the plan concise. Max 6-8 agents even for BIG/HUGE.
- Return ONLY valid JSON matching this structure exactly (no trailing commas):
{
  "tier": "tiny" | "normal" | "big" | "huge",
  "reason": "explanation of why",
  "agents": [{ "id": "string", "role": "string", "task": "string", "dependsOn": ["agent_id"] }],
  "debateEnabled": boolean,
  "approvals": { "destructiveEdits": boolean, "dependencyInstall": boolean, "architectureChanges": boolean }
}
- For TINY: agents = [{"id": "solo", "role": "implementer", "task": "<original_task>", "dependsOn": []}]
- For NORMAL/BIG/HUGE: Include planner, architect (if needed), implementers, test, review. Each with a concise task description and dependency chain.`;

/**
 * Evaluate task complexity using LLM classification.
 *
 * @param {string} task - The coding task
 * @returns {Promise<Object>}
 */
export async function evaluateComplexity(task) {
  console.log(chalk.dim("   🧠 Evaluating task complexity..."));

  const messages = [
    { role: "system", content: CLASSIFIER_PROMPT },
    { role: "user", content: `Task: ${task}` },
  ];

  try {
    const response = await callLLM(messages);
    const text = (response.content || "").trim();

    const jsonMatch = text.match(/\{[\s\S]*\}/);
    if (jsonMatch) {
      let rawJson = jsonMatch[0];
      let result = null;
      try {
        result = JSON.parse(rawJson);
      } catch (_) {
        // Strip trailing commas before } or ]
        rawJson = rawJson.replace(/,\s*([}\]])/g, "$1");
        try {
          result = JSON.parse(rawJson);
        } catch (_) {
          // If JSON was cut off near the end, attempt to close open brackets/braces
          let patched = rawJson;
          const openBrackets = (patched.match(/\[/g) || []).length - (patched.match(/\]/g) || []).length;
          const openBraces = (patched.match(/\{/g) || []).length - (patched.match(/\}/g) || []).length;
          for (let b = 0; b < openBrackets; b++) patched += "]";
          for (let b = 0; b < openBraces; b++) patched += "}";
          result = JSON.parse(patched.replace(/,\s*([}\]])/g, "$1"));
        }
      }
      if (result && result.tier) {
        console.log(chalk.cyan(`   🧠 Complexity: ${result.tier.toUpperCase()} (${result.agents?.length || 0} agents)`));
        return result;
      }
    }
  } catch (e) {
    console.log(chalk.dim(`   ⚠ Complexity eval failed: ${e.message}, defaulting to TINY`));
  }

  return {
    tier: "tiny",
    reason: "Fallback due to eval failure",
    agents: [{ id: "solo", role: "implementer", task, dependsOn: [] }],
    debateEnabled: false,
    approvals: { destructiveEdits: false, dependencyInstall: false, architectureChanges: false }
  };
}

// ---- Diff Merge Engine ----

/**
 * Merge multiple subagent diffs into the real workspace.
 * Uses git apply with 3-way merge fallback.
 * For conflicts, spawns a merge-resolution subagent.
 */
export async function mergeDiffs(results, baseDir) {
  console.log(chalk.cyan.bold("\n🔗 Merging subagent artifacts into real workspace..."));

  const successfulResults = results.filter(r => r.success && r.diff.length > 0);
  if (successfulResults.length === 0) {
    console.log(chalk.yellow("   ⚠ No diffs to merge"));
    return { merged: 0, failed: 0, conflicts: [] };
  }

  let merged = 0;
  let failed = 0;
  const conflicts = [];

  for (const result of successfulResults) {
    const diffFile = resolve(baseDir, `.tmp_merge_${result.label}.patch`);
    await writeFile(diffFile, result.diff, "utf-8");

    try {
      // Try clean apply first
      try {
        await shell(`git apply --check "${diffFile}" 2>&1`, baseDir);
        await shell(`git apply "${diffFile}" 2>&1`, baseDir);
        console.log(chalk.green(`   ✅ [${result.label}] merged cleanly`));
        merged++;
      } catch (applyErr) {
        console.log(chalk.dim(`   ⚠ Clean apply failed for [${result.label}]: ${applyErr.message}`));
        // Fallback to 3-way merge
        try {
          await shell(`git apply --3way "${diffFile}" 2>&1`, baseDir);
          console.log(chalk.yellow(`   ⚠ [${result.label}] merged with 3-way (may need review)`));
          merged++;
        } catch (mergeErr) {
          console.log(chalk.red(`   ❌ [${result.label}] conflict — queuing resolution`));
          conflicts.push({ label: result.label, diff: result.diff, error: mergeErr.message });
          failed++;
        }
      }
    } finally {
      try { await rm(diffFile, { force: true }); } catch (rmErr) { console.log(chalk.dim(`   ⚠ Patch file cleanup failed: ${rmErr.message}`)); }
    }
  }

  // Handle conflicts with a merge-resolution subagent
  if (conflicts.length > 0) {
    console.log(chalk.yellow(`\n   🔧 Spawning merge-resolution subagent for ${conflicts.length} conflict(s)...`));
    for (const conflict of conflicts) {
      const mergeTask = `A git merge conflict occurred while applying changes from subagent "${conflict.label}".

The diff that failed to apply:
\`\`\`diff
${conflict.diff.slice(0, 5000)}
\`\`\`

Error: ${conflict.error}

Your job: Manually apply the intended changes from this diff to the current codebase. Read the relevant files, understand the intent of the diff, and use patch_file to apply the changes correctly. Resolve any conflicts.`;

      try {
        await runSubagent(`merge-${conflict.label}`, mergeTask, baseDir);
        merged++;
        failed--;
      } catch (mergeResErr) {
        console.log(chalk.red(`   ❌ Merge resolution for [${conflict.label}] also failed: ${mergeResErr.message}`));
      }
    }
  }

  console.log(chalk.cyan(`   🔗 Merge complete: ${merged} applied, ${failed} failed`));
  return { merged, failed, conflicts };
}

// ---- Main Orchestrated Execution ----

/**
 * Run the full orchestrated pipeline:
 *
 * @param {string} task    - The coding task
 * @param {string} baseDir - Real workspace root
 * @returns {string|null}  - Result string, or null if TINY complexity
 */
export async function runOrchestrated(task, baseDir) {
  let plan = await evaluateComplexity(task);

  // --sim flag: force full pipeline even if classifier says TINY
  const forceOrchestrated = process.env.FORCE_ORCHESTRATED === "true";

  if (plan.tier === "tiny" && !forceOrchestrated) {
    return null; // Signal to caller: run normal single-agent
  }

  if (plan.tier === "tiny" && forceOrchestrated) {
    console.log(chalk.yellow("   ⚡ Complexity: TINY but --sim flag forces orchestrated pipeline"));
    plan.tier = "normal";
    plan.agents = [
      { id: "planner", role: "planner", task: "Plan the implementation", dependsOn: [] },
      { id: "implementer-1", role: "implementer", task, dependsOn: ["planner"] }
    ];
  }

  console.log(chalk.green.bold("\n🔷 Orchestrated Execution Activated"));
  console.log(chalk.dim(`   Task: "${task.slice(0, 100)}"`));
  console.log(chalk.dim(`   Tier: ${plan.tier.toUpperCase()}`));
  console.log(chalk.dim("═".repeat(60)));

  // Ensure we are inside a git repository so git worktree works
  try {
    await shell("git rev-parse --is-inside-work-tree", baseDir);
  } catch (err) {
    console.log(chalk.yellow("   ⚠ Not a git repository. Initializing git to support subagents and sandboxes..."));
    try {
      await shell("git init", baseDir);
      await shell("git config user.email \"xerv.org@gmail.com\"", baseDir);
      await shell("git config user.name \"Swades Agent\"", baseDir);
      await shell("git add -A", baseDir);
      await shell("git commit --allow-empty -m \"Initial commit by Swades Agent\"", baseDir);
      console.log(chalk.green("   ✅ Git repository initialized successfully."));
    } catch (gitErr) {
      console.log(chalk.red(`   ❌ Failed to initialize git: ${gitErr.message}. Falling back to single-agent mode.`));
      return null;
    }
  }

  // Call the new orchestrator loop
  return await runOrchestratorLoop(plan, baseDir);
}
