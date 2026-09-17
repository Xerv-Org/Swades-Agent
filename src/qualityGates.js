import chalk from 'chalk';
import { exec } from 'node:child_process';
import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { existsSync } from 'node:fs';

async function shell(cmd, cwd, timeoutMs = 60000) {
  return new Promise((resolve) => {
    const start = Date.now();
    const child = exec(cmd, { cwd, timeout: timeoutMs }, (error, stdout, stderr) => {
      const durationMs = Date.now() - start;
      if (error) {
        resolve({ stdout, stderr, exitCode: error.code || 1, durationMs, error });
      } else {
        resolve({ stdout, stderr, exitCode: 0, durationMs });
      }
    });
  });
}

export async function detectGates(workdir) {
  const gates = [];
  
  let pkg = {};
  const pkgPath = join(workdir, 'package.json');
  if (existsSync(pkgPath)) {
    try {
      pkg = JSON.parse(await readFile(pkgPath, 'utf8'));
    } catch (e) {}
  }
  const scripts = pkg.scripts || {};
  
  // 1. lint
  let lintCmd = null;
  if (scripts.lint) {
    lintCmd = 'npm run lint';
  } else {
    let hasEslint = false;
    try {
      const files = await readdir(workdir);
      hasEslint = files.some(f => f.startsWith('.eslintrc') || f.startsWith('eslint.config.'));
    } catch (e) {}
    if (hasEslint) {
      lintCmd = 'npx eslint .';
    } else if (existsSync(join(workdir, 'ruff.toml'))) {
      lintCmd = 'ruff check .';
    } else if (existsSync(join(workdir, 'pyproject.toml'))) {
      try {
        const pyproject = await readFile(join(workdir, 'pyproject.toml'), 'utf8');
        if (pyproject.includes('[tool.ruff]')) {
          lintCmd = 'ruff check .';
        }
      } catch (e) {}
    }
  }
  gates.push({ name: 'lint', cmd: lintCmd, available: !!lintCmd });
  
  // 2. typecheck
  let tcCmd = null;
  if (scripts.typecheck) {
    tcCmd = 'npm run typecheck';
  } else if (scripts['type-check']) {
    tcCmd = 'npm run type-check';
  } else if (existsSync(join(workdir, 'tsconfig.json'))) {
    tcCmd = 'npx tsc --noEmit';
  } else if (existsSync(join(workdir, 'mypy.ini'))) {
    tcCmd = 'mypy .';
  } else if (existsSync(join(workdir, 'pyrightconfig.json'))) {
    tcCmd = 'pyright';
  }
  gates.push({ name: 'typecheck', cmd: tcCmd, available: !!tcCmd });
  
  // 3. unit-test
  let testCmd = null;
  if (scripts.test && !scripts.test.includes('no test specified')) {
    testCmd = 'npm test';
  } else if (existsSync(join(workdir, 'pytest.ini'))) {
    testCmd = 'pytest';
  } else if (existsSync(join(workdir, 'Cargo.toml'))) {
    testCmd = 'cargo test';
  }
  gates.push({ name: 'unit-test', cmd: testCmd, available: !!testCmd });
  
  // 4. build
  let buildCmd = null;
  if (scripts.build) {
    buildCmd = 'npm run build';
  } else if (existsSync(join(workdir, 'Cargo.toml'))) {
    buildCmd = 'cargo build';
  } else if (existsSync(join(workdir, 'Makefile'))) {
    buildCmd = 'make';
  }
  gates.push({ name: 'build', cmd: buildCmd, available: !!buildCmd });
  
  // 5. security
  let secCmd = null;
  if (existsSync(join(workdir, 'package-lock.json'))) {
    secCmd = 'npm audit';
  } else if (existsSync(join(workdir, 'requirements.txt'))) {
    secCmd = 'pip-audit';
  }
  gates.push({ name: 'security', cmd: secCmd, available: !!secCmd });
  
  return gates;
}

export async function runSingleGate(workdir, name, cmd) {
  const result = await shell(cmd, workdir, 60000);
  const passed = result.exitCode === 0;
  return {
    name,
    passed,
    output: passed ? result.stdout : (result.stderr || result.stdout || String(result.error)),
    durationMs: result.durationMs
  };
}

export async function runGates(workdir, gates = null) {
  if (!gates) {
    gates = await detectGates(workdir);
  }
  
  const results = [];
  const availableGates = gates.filter(g => g.available);
  
  for (const gate of availableGates) {
    const res = await runSingleGate(workdir, gate.name, gate.cmd);
    results.push(res);
  }
  
  const passed = results.every(r => r.passed);
  const passedCount = results.filter(r => r.passed).length;
  const summary = `Passed ${passedCount}/${availableGates.length} quality gates.`;
  
  return {
    passed,
    results,
    summary
  };
}
