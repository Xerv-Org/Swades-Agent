import fs from 'node:fs/promises';
import path from 'node:path';
import cp from 'node:child_process';
import crypto from 'node:crypto';
import chalk from 'chalk';
import { getSwadesCacheDir } from './cleanup.js';

export function parseDiffStats(diff) {
  let linesAdded = 0;
  let linesRemoved = 0;
  let filesAdded = 0;
  let filesModified = 0;
  let filesDeleted = 0;
  const files = new Set();
  
  const lines = diff.split('\n');
  let currentFile = null;
  let isNew = false;
  let isDeleted = false;
  
  for (const line of lines) {
    if (line.startsWith('diff --git ')) {
      if (currentFile) {
        if (isNew) filesAdded++;
        else if (isDeleted) filesDeleted++;
        else filesModified++;
        isNew = false;
        isDeleted = false;
      }
      const parts = line.split(' ');
      const bPath = parts[parts.length - 1];
      currentFile = bPath.replace(/^b\//, '');
      files.add(currentFile);
    } else if (line.startsWith('new file mode')) {
      isNew = true;
    } else if (line.startsWith('deleted file mode')) {
      isDeleted = true;
    } else if (line.startsWith('--- ') || line.startsWith('+++ ')) {
      // ignore
    } else if (line.startsWith('+') && !line.startsWith('+++')) {
      linesAdded++;
    } else if (line.startsWith('-') && !line.startsWith('---')) {
      linesRemoved++;
    }
  }
  
  if (currentFile) {
    if (isNew) filesAdded++;
    else if (isDeleted) filesDeleted++;
    else filesModified++;
  }
  
  return {
    filesAdded,
    filesModified,
    filesDeleted,
    linesAdded,
    linesRemoved,
    files: Array.from(files)
  };
}

const execAsync = (cmd, options = {}) => new Promise((resolve, reject) => {
  cp.exec(cmd, options, (error, stdout, stderr) => {
    if (error) reject({ error, stdout, stderr });
    else resolve({ stdout, stderr });
  });
});

export class PatchSafety {
  constructor(workdir = process.env.WORKDIR || process.cwd()) {
    this.workdir = workdir;
    this.staged = new Map();
    this.rollbackStack = [];
  }

  async _getPatchDir() {
    const cacheDir = getSwadesCacheDir(this.workdir);
    const patchDir = path.join(cacheDir, 'staged_patches');
    await fs.mkdir(patchDir, { recursive: true });
    return patchDir;
  }

  async stage(agentId, diff, label) {
    const patchId = crypto.randomUUID().slice(0, 8);
    const patchDir = await this._getPatchDir();
    const patchPath = path.join(patchDir, `${patchId}.patch`);
    
    await fs.writeFile(patchPath, diff, 'utf-8');
    
    this.staged.set(patchId, {
      patchId,
      agentId,
      label,
      diff,
      timestamp: Date.now(),
      status: 'staged',
      patchPath
    });
    
    return patchId;
  }

  reviewDiff(patchId) {
    const patch = this.staged.get(patchId);
    if (!patch) throw new Error(`Patch ${patchId} not found`);
    
    const stats = parseDiffStats(patch.diff);
    const touchesConfig = stats.files.some(f => 
      f.match(/package\.json|package-lock\.json|yarn\.lock|tsconfig.*\.json|\.env|Dockerfile/)
    );
    
    return {
      filesTouched: stats.files,
      linesAdded: stats.linesAdded,
      linesRemoved: stats.linesRemoved,
      filesAdded: stats.filesAdded,
      filesDeleted: stats.filesDeleted,
      touchesConfig
    };
  }

  scoreRisk(patchIdOrDiff, codebaseIndex = null) {
    let diff = "";
    let patch = null;
    if (typeof patchIdOrDiff === "string" && this.staged.has(patchIdOrDiff)) {
      patch = this.staged.get(patchIdOrDiff);
      diff = patch.diff;
    } else if (typeof patchIdOrDiff === "string") {
      diff = patchIdOrDiff;
    } else {
      throw new Error(`Invalid patch or patchId: ${patchIdOrDiff}`);
    }

    const stats = parseDiffStats(diff);
    let score = 10;
    const reasons = ['Base risk: 10'];
    
    const isConfig = (f) => f.match(/package\.json|tsconfig.*\.json|\.env|Dockerfile/);
    const isDependency = (f) => f.match(/package-lock\.json|yarn\.lock/);
    
    if (stats.files.some(isConfig)) {
      score += 15;
      reasons.push('+15 for touching config files');
    }
    
    if (stats.filesDeleted > 0) {
      score += 10;
      reasons.push('+10 for deleting files');
    }
    
    const linesChanged = stats.linesAdded + stats.linesRemoved;
    if (linesChanged > 0) {
      const lineScore = Math.floor(linesChanged / 100) * 5;
      if (lineScore > 0) {
        score += lineScore;
        reasons.push(`+${lineScore} for ${linesChanged} lines changed`);
      }
    }
    
    if (stats.files.some(isDependency)) {
      score += 20;
      reasons.push('+20 for touching dependency files');
    }
    
    if (stats.files.length > 5) {
      score += 15;
      reasons.push('+15 for modifying more than 5 files');
    }
    
    if (diff.includes('<<<<<<< ') || diff.includes('=======\n') || diff.includes('>>>>>>> ')) {
      score += 10;
      reasons.push('+10 for merge conflict markers');
    }
    
    if (score > 100) score = 100;
    
    if (patch) patch.riskScore = score;
    return { score, reasons };
  }

  async apply(patchId) {
    const patch = this.staged.get(patchId);
    if (!patch) throw new Error(`Patch ${patchId} not found`);
    
    const opts = { cwd: this.workdir };
    
    try {
      let stashHash = '';
      try {
        const { stdout: stashOut } = await execAsync('git stash create', opts);
        stashHash = (stashOut || '').trim();
      } catch (_) {
        // Clean working tree prior to apply — no dirty changes to stash
      }
      
      try {
        await execAsync(`git apply --check "${patch.patchPath}"`, opts);
        await execAsync(`git apply "${patch.patchPath}"`, opts);
      } catch (err) {
        await execAsync(`git apply --3way "${patch.patchPath}"`, opts);
      }
      
      if (stashHash) {
        this.rollbackStack.push({ patchId, stashHash });
      }
      
      patch.status = 'applied';
      return { ok: true, stashHash };
    } catch (error) {
      return { ok: false, error: error.error ? error.error.message : error.toString() };
    }
  }

  async applyPatch(diff, workdir) {
    if (workdir) this.workdir = workdir;
    const patchId = await this.stage('orchestrator', diff, 'patch');
    const res = await this.apply(patchId);
    if (!res.ok) throw new Error(res.error || 'Failed to apply patch');
    return res;
  }

  async rollback(patchId = null) {
    let target = patchId;
    if (!target && this.rollbackStack.length > 0) {
      target = this.rollbackStack[this.rollbackStack.length - 1].patchId;
    }
    const patch = target ? this.staged.get(target) : null;
    const opts = { cwd: this.workdir };
    
    try {
      if (patch && patch.patchPath) {
        try {
          await execAsync(`git apply --reverse "${patch.patchPath}"`, opts);
          patch.status = 'rolledBack';
          return { ok: true };
        } catch (_) {
          // fallback to stash or checkout below
        }
      }

      const rollbackEntry = this.rollbackStack.find(r => r.patchId === target) || this.rollbackStack[this.rollbackStack.length - 1];
      if (rollbackEntry && rollbackEntry.stashHash) {
        await execAsync(`git stash apply ${rollbackEntry.stashHash}`, opts);
      } else {
        await execAsync(`git checkout -- .`, opts);
      }
      
      if (patch) patch.status = 'rolledBack';
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error.error ? error.error.message : error.toString() };
    }
  }

  async autoRollbackOnFailure(patchId, testCmd) {
    const applyRes = await this.apply(patchId);
    if (!applyRes.ok) {
      return { applied: false, testPassed: false, rolledBack: false };
    }
    
    try {
      await execAsync(testCmd, { cwd: this.workdir });
      return { applied: true, testPassed: true, rolledBack: false };
    } catch (error) {
      await this.rollback(patchId);
      return { applied: true, testPassed: false, rolledBack: true };
    }
  }

  listStaged() {
    return Array.from(this.staged.values()).map(p => ({
      patchId: p.patchId,
      agentId: p.agentId,
      label: p.label,
      timestamp: p.timestamp,
      status: p.status,
      riskScore: p.riskScore
    }));
  }

  async cleanup() {
    const patchDir = await this._getPatchDir();
    try {
      await fs.rm(patchDir, { recursive: true, force: true });
    } catch (err) {
      // ignore
    }
    this.staged.clear();
  }
}
