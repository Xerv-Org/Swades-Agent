// ============================================================
// memory.js — Persistent memory across sessions (isolated in cache dir)
// ============================================================

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import chalk from "chalk";
import { getSwadesCacheDir } from "./cleanup.js";

const DEFAULT_MEMORY = {
  project: {
    stack: '',
    conventions: [],
    knownIssues: [],
    architecture: ''
  },
  preferences: {
    approvalMode: 'auto',
    testCommand: '',
    lintCommand: '',
    buildCommand: '',
    preferredPatterns: []
  },
  tasks: [],
  performance: {
    agents: {},
    models: {},
    tiers: { tiny: 0, normal: 0, big: 0, huge: 0 }
  }
};

/**
 * Get the memory file path, isolated in ~/.cache/swades/<project-hash>/
 * instead of polluting the project root.
 */
function getMemoryFilePath() {
  const workdir = process.env.WORKDIR || process.cwd();
  const cacheDir = getSwadesCacheDir(workdir);
  return resolve(cacheDir, "agent_memory.json");
}

/**
 * Load memory from disk. Returns the 4-layer structure.
 * Handles backward compatibility with old agent_memory.json format.
 */
export async function loadMemory() {
  try {
    const memoryFile = getMemoryFilePath();
    const raw = await readFile(memoryFile, "utf-8");
    const data = JSON.parse(raw);

    // Migration from old { sessions, summary } to { tasks, ... }
    if (data.sessions && !data.tasks) {
      data.tasks = data.sessions;
      delete data.sessions;
      delete data.summary;
    }

    // Ensure all layers and defaults exist
    const memory = {
      project: { ...DEFAULT_MEMORY.project, ...data.project },
      preferences: { ...DEFAULT_MEMORY.preferences, ...data.preferences },
      tasks: data.tasks || [],
      performance: {
        agents: data.performance?.agents || {},
        models: data.performance?.models || {},
        tiers: { ...DEFAULT_MEMORY.performance.tiers, ...data.performance?.tiers }
      }
    };
    
    return memory;
  } catch (err) {
    if (err.code !== "ENOENT") {
      console.log(chalk.dim(`   ⚠ Memory load warning: ${err.message}`));
    }
    return JSON.parse(JSON.stringify(DEFAULT_MEMORY));
  }
}

/**
 * Save memory to disk (in cache directory).
 */
export async function saveMemory(memory) {
  const memoryFile = getMemoryFilePath();
  await mkdir(dirname(memoryFile), { recursive: true });
  await writeFile(memoryFile, JSON.stringify(memory, null, 2), "utf-8");
}

/**
 * Record a completed session into memory.
 * Keeps the last 10 sessions to avoid unbounded growth.
 */
export async function recordSession(task, result, toolsUsed, meta = {}) {
  const memory = await loadMemory();

  memory.tasks.push({
    timestamp: new Date().toISOString(),
    task,
    result: result.slice(0, 500), // keep summaries short
    toolsUsed,
    meta
  });

  // Keep only last 10 tasks
  if (memory.tasks.length > 10) {
    memory.tasks = memory.tasks.slice(-10);
  }

  await saveMemory(memory);
  return memory;
}

/**
 * Merge updates into the project layer.
 */
export async function updateProjectMemory(updates) {
  const memory = await loadMemory();
  memory.project = { ...memory.project, ...updates };
  await saveMemory(memory);
  return memory;
}

/**
 * Merge updates into the preferences layer.
 */
export async function updatePreferences(updates) {
  const memory = await loadMemory();
  memory.preferences = { ...memory.preferences, ...updates };
  await saveMemory(memory);
  return memory;
}

export async function recordAgentPerformance(roleOrResults, success = true, durationMs = 0) {
  const memory = await loadMemory();

  if (Array.isArray(roleOrResults)) {
    for (const item of roleOrResults) {
      const role = item.role || item.id || 'agent';
      const isSuccess = item.status === 'completed';
      const duration = item.durationMs || 1000;
      const agentPerf = memory.performance.agents[role] || { total: 0, succeeded: 0, avgDurationMs: 0 };
      agentPerf.total++;
      if (isSuccess) agentPerf.succeeded++;
      agentPerf.avgDurationMs = ((agentPerf.avgDurationMs * (agentPerf.total - 1)) + duration) / agentPerf.total;
      memory.performance.agents[role] = agentPerf;
    }
    await saveMemory(memory);
    return memory;
  }

  const role = roleOrResults || 'agent';
  const agentPerf = memory.performance.agents[role] || { total: 0, succeeded: 0, avgDurationMs: 0 };
  
  agentPerf.total++;
  if (success) agentPerf.succeeded++;
  
  // Running average
  agentPerf.avgDurationMs = ((agentPerf.avgDurationMs * (agentPerf.total - 1)) + durationMs) / agentPerf.total;
  
  memory.performance.agents[role] = agentPerf;
  await saveMemory(memory);
  return memory;
}

/**
 * Record model performance metrics.
 */
export async function recordModelPerformance(model, success, latencyMs) {
  const memory = await loadMemory();
  const modelPerf = memory.performance.models[model] || { calls: 0, failures: 0, avgLatencyMs: 0 };
  
  modelPerf.calls++;
  if (!success) modelPerf.failures++;
  
  // Running average
  modelPerf.avgLatencyMs = ((modelPerf.avgLatencyMs * (modelPerf.calls - 1)) + latencyMs) / modelPerf.calls;
  
  memory.performance.models[model] = modelPerf;
  await saveMemory(memory);
  return memory;
}

/**
 * Increment the counter for a tier usage.
 */
export async function recordTierUsage(tier) {
  const memory = await loadMemory();
  if (memory.performance.tiers[tier] !== undefined) {
    memory.performance.tiers[tier]++;
  } else {
    memory.performance.tiers[tier] = 1;
  }
  await saveMemory(memory);
  return memory;
}

/**
 * Return the preferences object.
 */
export async function getPreferences() {
  const memory = await loadMemory();
  return memory.preferences;
}

/**
 * Build a memory context string to inject into the system prompt.
 */
export async function getMemoryContext() {
  const memory = await loadMemory();

  let ctx = "\n\n## MEMORY — Context\n";
  
  const { project, preferences, tasks } = memory;
  let hasContext = false;

  if (project.stack || project.architecture || project.conventions.length > 0 || project.knownIssues.length > 0) {
    ctx += "### Project Context\n";
    if (project.stack) ctx += `- Stack: ${project.stack}\n`;
    if (project.architecture) ctx += `- Architecture: ${project.architecture}\n`;
    if (project.conventions.length) ctx += `- Conventions: ${project.conventions.join(", ")}\n`;
    if (project.knownIssues.length) ctx += `- Known Issues: ${project.knownIssues.join(", ")}\n`;
    ctx += "\n";
    hasContext = true;
  }

  if (preferences.approvalMode || preferences.testCommand || preferences.lintCommand || preferences.buildCommand || preferences.preferredPatterns.length > 0) {
    ctx += "### Preferences\n";
    ctx += `- Approval Mode: ${preferences.approvalMode}\n`;
    if (preferences.testCommand) ctx += `- Test Command: ${preferences.testCommand}\n`;
    if (preferences.lintCommand) ctx += `- Lint Command: ${preferences.lintCommand}\n`;
    if (preferences.buildCommand) ctx += `- Build Command: ${preferences.buildCommand}\n`;
    if (preferences.preferredPatterns.length) ctx += `- Preferred Patterns: ${preferences.preferredPatterns.join(", ")}\n`;
    ctx += "\n";
    hasContext = true;
  }

  if (tasks.length > 0) {
    ctx += "### Recent Tasks (Sessions)\n";
    for (const task of tasks) {
      ctx += `- **${task.timestamp}**: Task: "${task.task}"\n`;
      ctx += `  Result: ${task.result.slice(0, 200)}\n`;
      if (task.toolsUsed?.length) {
        ctx += `  Tools used: ${task.toolsUsed.join(", ")}\n`;
      }
      ctx += "\n";
    }
    hasContext = true;
  }

  return hasContext ? ctx : "";
}
