import path from 'node:path';
import chalk from 'chalk';

export function resolveImportPath(importStr, fromFile, indexFiles = []) {
  if (!importStr.startsWith('.')) return null;

  const dir = path.dirname(fromFile);
  const resolvedBase = path.normalize(path.join(dir, importStr));
  
  const extensions = ['', '.js', '.ts', '.mjs', '.cjs', '/index.js', '/index.ts', '/index.mjs'];

  for (const ext of extensions) {
    const candidate = resolvedBase + ext;
    if (indexFiles.includes(candidate)) {
      return candidate;
    }
  }

  return resolvedBase;
}

export class DependencyGraph {
  constructor(indexData = null) {
    this.nodes = new Map();
    this.agentClaims = new Map();
    this.editHistory = new Map();
    if (indexData && indexData.files) {
      this.loadIndex(indexData);
    }
  }

  loadIndex(indexData) {
    if (!indexData || !indexData.files) return;

    let fileEntries = [];
    if (Array.isArray(indexData.files)) {
      fileEntries = indexData.files;
    } else if (typeof indexData.files === "object") {
      fileEntries = Object.entries(indexData.files).map(([p, info]) => ({
        path: p,
        imports: info?.structure?.imports || info?.imports || [],
        exports: info?.structure?.exports || info?.exports || [],
      }));
    }

    const allFiles = fileEntries.map(f => f.path);
    
    for (const fileObj of fileEntries) {
      this.addFile(fileObj.path, fileObj.imports || [], fileObj.exports || [], allFiles);
    }
  }

  static fromIndex(indexData) {
    const graph = new DependencyGraph();
    graph.loadIndex(indexData);
    return graph;
  }

  addFile(filePath, imports = [], exports = [], allFiles = []) {
    if (!this.nodes.has(filePath)) {
      this.nodes.set(filePath, {
        imports: new Set(),
        exports: new Set(),
        importedBy: new Set()
      });
    }

    const node = this.nodes.get(filePath);
    for (const exp of exports) {
      node.exports.add(exp);
    }

    for (const imp of imports) {
      let resolved = imp;
      if (imp.startsWith('.')) {
        resolved = resolveImportPath(imp, filePath, allFiles) || imp;
      }
      
      node.imports.add(resolved);
      
      if (!this.nodes.has(resolved)) {
        this.nodes.set(resolved, {
          imports: new Set(),
          exports: new Set(),
          importedBy: new Set()
        });
      }
      this.nodes.get(resolved).importedBy.add(filePath);
    }
  }

  getDependencies(filePath) {
    const node = this.nodes.get(filePath);
    return node ? node.imports : new Set();
  }

  getDependents(filePath) {
    const node = this.nodes.get(filePath);
    return node ? node.importedBy : new Set();
  }

  getTopologicalOrder(taskFiles) {
    const inDegree = new Map();
    const adjList = new Map();
    const result = [];
    const queue = [];

    for (const file of taskFiles) {
      inDegree.set(file, 0);
      adjList.set(file, []);
    }

    for (const file of taskFiles) {
      const deps = this.getDependencies(file);
      for (const dep of deps) {
        if (taskFiles.includes(dep)) {
          adjList.get(dep).push(file);
          inDegree.set(file, inDegree.get(file) + 1);
        }
      }
    }

    for (const [file, degree] of inDegree.entries()) {
      if (degree === 0) queue.push(file);
    }

    while (queue.length > 0) {
      const u = queue.shift();
      result.push(u);

      for (const v of adjList.get(u) || []) {
        inDegree.set(v, inDegree.get(v) - 1);
        if (inDegree.get(v) === 0) {
          queue.push(v);
        }
      }
    }

    for (const file of taskFiles) {
      if (!result.includes(file)) {
        result.push(file);
      }
    }

    return result;
  }

  predictConflicts(agentTasks) {
    const conflicts = [];
    const fileToAgents = new Map();

    for (const task of agentTasks) {
      for (const file of task.files || []) {
        if (!fileToAgents.has(file)) {
          fileToAgents.set(file, new Set());
        }
        fileToAgents.get(file).add(task.agentId);
      }
    }

    for (const [file, agents] of fileToAgents.entries()) {
      if (agents.size > 1) {
        conflicts.push({ file, agents: Array.from(agents) });
      }
    }

    return conflicts;
  }

  claimFile(agentId, filePath) {
    if (!this.agentClaims.has(filePath)) {
      this.agentClaims.set(filePath, new Set());
    }

    const claims = this.agentClaims.get(filePath);
    if (claims.size > 0 && !claims.has(agentId)) {
      const otherAgentId = Array.from(claims)[0];
      return { ok: false, claimedBy: otherAgentId };
    }

    claims.add(agentId);
    
    if (!this.editHistory.has(filePath)) {
      this.editHistory.set(filePath, []);
    }
    this.editHistory.get(filePath).push(agentId);
    
    return { ok: true };
  }

  releaseFile(agentId, filePath) {
    if (this.agentClaims.has(filePath)) {
      const claims = this.agentClaims.get(filePath);
      claims.delete(agentId);
      if (claims.size === 0) {
        this.agentClaims.delete(filePath);
      }
    }
  }

  getImpactedFiles(changedFiles) {
    const impacted = new Set();
    const queue = [...changedFiles];

    while (queue.length > 0) {
      const file = queue.shift();
      const dependents = this.getDependents(file);
      for (const dep of dependents) {
        if (!impacted.has(dep) && !changedFiles.includes(dep)) {
          impacted.add(dep);
          queue.push(dep);
        }
      }
    }

    return impacted;
  }
}
