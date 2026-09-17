import chalk from 'chalk';
import { exec } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

import { DependencyGraph } from './dependencyGraph.js';
import { PatchSafety, parseDiffStats } from './patchSafety.js';
import { runGates } from './qualityGates.js';
import { synthesizeReport, printReport, identifyRisks, suggestNextSteps } from './synthesis.js';
import { runSubagent, Semaphore } from './subagent.js';
import { requestApproval } from './approvalFlow.js';
import { recordAgentPerformance, recordTierUsage } from './memory.js';
import { callLLM } from './llm.js';
import { getSwadesCacheDir } from './cleanup.js';

/**
 * Returns the maximum concurrency (semaphore limit) for a given tier.
 */
export function getMaxConcurrency(tier) {
  switch (tier) {
    case 'huge': return 25;
    case 'big': return 10;
    case 'normal': return 5;
    case 'tiny': return 1;
    default: return 5;
  }
}

/**
 * Returns true if debate should be enabled based on tier and riskScore.
 */
export function shouldDebate(tier, riskScore) {
  const isHighTier = ['normal', 'big', 'huge'].includes(tier);
  return isHighTier && riskScore > 60;
}

/**
 * Main entry for the Orchestrator Loop.
 * 
 * @param {Object} plan - Output from evaluateComplexity
 * @param {string} workdir - The working directory
 */
export async function runOrchestratorLoop(plan, workdir) {
  console.log(chalk.blue('=== SWADES AGENT ORCHESTRATOR LOOP ==='));

  // Phase 1: ANALYSE
  console.log(chalk.cyan('\n[Phase 1: ANALYSE]'));
  const cacheDir = getSwadesCacheDir(workdir);
  let agentIndex = {};
  try {
    const indexData = await readFile(join(cacheDir, 'agent_index.json'), 'utf8');
    agentIndex = JSON.parse(indexData);
  } catch (err) {
    console.log(chalk.yellow('No agent_index.json found. Creating empty graph.'));
  }

  const depGraph = new DependencyGraph(agentIndex);
  
  // Simulate predictConflicts if available on DependencyGraph
  if (typeof depGraph.predictConflicts === 'function') {
    const conflicts = depGraph.predictConflicts(plan.agents);
    if (conflicts && conflicts.length > 0) {
      console.log(chalk.yellow('Warning: Potential file conflicts detected:', conflicts.join(', ')));
    }
  } else {
    console.log(chalk.gray('predictConflicts not available on DependencyGraph. Proceeding.'));
  }

  // Phase 2: PLAN
  console.log(chalk.cyan('\n[Phase 2: PLAN]'));
  console.log(chalk.white(`Execution Tier: ${plan.tier}`));
  console.log(chalk.white(`Debate Enabled: ${plan.debateEnabled}`));
  plan.agents.forEach(a => {
    console.log(chalk.gray(`- Agent [${a.id}]: ${a.role} -> ${a.task}`));
  });

  // Phase 3: APPROVE
  console.log(chalk.cyan('\n[Phase 3: APPROVE]'));
  const approvedAgents = [];
  for (const agent of plan.agents) {
    let requiresApproval = false;
    let reason = '';
    const taskLower = agent.task.toLowerCase();
    
    if (taskLower.includes('delete') || taskLower.includes('remove') || taskLower.includes('drop')) {
      requiresApproval = plan.approvals?.destructiveEdits ?? true;
      reason = 'Destructive edits detected';
    }
    if (taskLower.includes('npm install') || taskLower.includes('yarn add') || taskLower.includes('install')) {
      requiresApproval = plan.approvals?.dependencyInstall ?? true;
      reason = 'Dependency installation detected';
    }
    if (taskLower.includes('architecture') || taskLower.includes('refactor')) {
      requiresApproval = plan.approvals?.architectureChanges ?? true;
      reason = 'Architecture changes detected';
    }
    
    if (requiresApproval) {
      console.log(chalk.yellow(`Approval needed for Agent ${agent.id}: ${reason}`));
      const approved = await requestApproval(`Agent ${agent.id} requires approval for: ${reason}`);
      if (!approved) {
        console.log(chalk.red(`Approval denied for Agent ${agent.id}. Removing from plan.`));
        continue;
      }
      console.log(chalk.green(`Approval granted for Agent ${agent.id}.`));
    }
    approvedAgents.push(agent);
  }
  plan.agents = approvedAgents;

  // Phase 4: ASSIGN
  // Phase 5: MONITOR
  console.log(chalk.cyan('\n[Phase 4 & 5: ASSIGN & MONITOR]'));
  const concurrency = getMaxConcurrency(plan.tier);
  const semaphore = new Semaphore(concurrency);
  
  // Dependency graph setup
  const inDegree = new Map();
  const graph = new Map();
  
  for (const a of plan.agents) {
    inDegree.set(a.id, 0);
    graph.set(a.id, []);
  }
  
  for (const a of plan.agents) {
    if (a.dependsOn) {
      for (const dep of a.dependsOn) {
        if (graph.has(dep)) {
          graph.get(dep).push(a.id);
          inDegree.set(a.id, inDegree.get(a.id) + 1);
        }
      }
    }
  }
  
  const statusMap = new Map();
  for (const a of plan.agents) {
    statusMap.set(a.id, {
      status: 'pending',
      startTime: null,
      promise: null,
      result: null,
      agentInfo: a
    });
  }

  const completedAgents = [];
  const readyQueue = [];
  for (const [id, degree] of inDegree.entries()) {
    if (degree === 0) readyQueue.push(id);
  }

  const runAgent = async (agentId) => {
    const statusInfo = statusMap.get(agentId);
    statusInfo.status = 'running';
    statusInfo.startTime = Date.now();
    await semaphore.acquire();
    try {
      const result = await runSubagent(statusInfo.agentInfo, workdir);
      statusInfo.result = result;
      statusInfo.status = 'completed';
    } catch (err) {
      statusInfo.status = 'failed';
      statusInfo.result = { error: err.message };
    } finally {
      semaphore.release();
    }
  };

  while (completedAgents.length < plan.agents.length) {
    // Phase 4: Start ready agents
    while (readyQueue.length > 0) {
      const nextId = readyQueue.shift();
      statusMap.get(nextId).promise = runAgent(nextId);
      console.log(chalk.gray(`Started Agent ${nextId}`));
    }
    
    // Phase 5: Monitor
    const runningAgents = Array.from(statusMap.entries()).filter(([id, info]) => info.status === 'running');
    
    const now = Date.now();
    for (const [id, info] of runningAgents) {
      if (now - info.startTime > 120000) {
        console.log(chalk.yellow(`Agent ${id} has been running for over 120s. Marking as stuck.`));
        info.status = 'stuck';
      }
    }

    const promises = Array.from(statusMap.values())
      .filter(info => info.status === 'running' || info.status === 'stuck')
      .map(info => info.promise);
      
    if (promises.length === 0) {
      const pending = Array.from(statusMap.values()).filter(info => info.status === 'pending');
      if (pending.length > 0) {
        console.log(chalk.red('Deadlock detected! Pending agents cannot start due to missing dependencies.'));
        break;
      }
    } else {
      // 2 second monitoring tick
      const timeoutPromise = new Promise(resolve => setTimeout(() => resolve('timeout'), 2000));
      await Promise.race([...promises, timeoutPromise]);
    }
    
    // Process completions
    for (const [id, info] of statusMap.entries()) {
      if ((info.status === 'completed' || info.status === 'failed') && !completedAgents.includes(id)) {
        completedAgents.push(id);
        
        if (info.status === 'completed') {
           console.log(chalk.green(`Agent ${id} completed successfully.`));
           const dependents = graph.get(id) || [];
           for (const dep of dependents) {
             const currentInDegree = inDegree.get(dep);
             inDegree.set(dep, currentInDegree - 1);
             if (inDegree.get(dep) === 0) {
               readyQueue.push(dep);
             }
           }
        } else {
          console.log(chalk.red(`Agent ${id} failed. Dependent agents will remain blocked.`));
        }
      }
    }
  }

  // Phase 6: DEBATE
  console.log(chalk.cyan('\n[Phase 6: DEBATE]'));
  if (plan.debateEnabled) {
    for (const [id, info] of statusMap.entries()) {
      if (info.status === 'completed' && info.result && info.result.diff) {
        const safety = new PatchSafety();
        const riskScore = await safety.scoreRisk(info.result.diff);
        
        if (shouldDebate(plan.tier, riskScore)) {
           console.log(chalk.yellow(`Risk score ${riskScore} for agent ${id} exceeds threshold. Initiating debate.`));
           const critique = await callLLM('review', `Review this diff for critical issues:\n${info.result.diff}`);
           console.log(chalk.gray(`Critique received for Agent ${id}. Generating fix...`));
           const fix = await callLLM('fixer', `Fix these issues in the diff:\n${critique}\nOriginal Diff:\n${info.result.diff}`);
           info.result.diff = fix;
           console.log(chalk.green(`Fix applied to diff for Agent ${id}.`));
        }
      }
    }
  } else {
    console.log(chalk.gray('Debate phase skipped (not enabled in plan).'));
  }

  // Phase 7: MERGE
  console.log(chalk.cyan('\n[Phase 7: MERGE]'));
  // Merge in dependency completion order
  const appliedPatches = [];
  const patchSafety = new PatchSafety();
  
  for (const id of completedAgents) {
    const info = statusMap.get(id);
    if (info.status === 'completed' && info.result && info.result.diff) {
      try {
        await patchSafety.applyPatch(info.result.diff, workdir);
        appliedPatches.push(id);
        console.log(chalk.green(`Successfully applied patch from agent ${id}`));
      } catch (err) {
        console.log(chalk.red(`Failed to apply patch from agent ${id}: ${err.message}. Auto-rollback triggered.`));
        await patchSafety.rollback();
      }
    }
  }

  // Phase 8: VERIFY
  console.log(chalk.cyan('\n[Phase 8: VERIFY]'));
  const gatesResult = await runGates(workdir);
  if (!gatesResult.passed) {
    console.log(chalk.red('Quality gates failed. Automatically rolling back most recent patch.'));
    const patchSafety = new PatchSafety();
    await patchSafety.rollback();
  } else {
    console.log(chalk.green('Quality gates passed!'));
  }

  // Phase 9: SUMMARIZE
  console.log(chalk.cyan('\n[Phase 9: SUMMARIZE]'));
  const allResults = Array.from(statusMap.entries()).map(([id, info]) => ({
    id,
    status: info.status,
    result: info.result
  }));
  
  const report = await synthesizeReport(allResults, gatesResult);
  await printReport(report);
  
  const risks = identifyRisks(allResults);
  if (risks && risks.length > 0) {
    console.log(chalk.yellow('Identified Risks:'));
    risks.forEach(r => console.log(chalk.gray(`- ${r}`)));
  }
  
  const nextSteps = suggestNextSteps(allResults);
  
  await recordAgentPerformance(allResults);
  await recordTierUsage(plan.tier);
  
  console.log(chalk.blue('=== ORCHESTRATOR LOOP COMPLETE ==='));
  
  return { report, nextSteps };
}
