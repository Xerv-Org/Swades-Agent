import 'dotenv/config';
import test from 'node:test';
import assert from 'node:assert/strict';
import { DependencyGraph } from '../src/dependencyGraph.js';
import { PatchSafety, parseDiffStats } from '../src/patchSafety.js';
import { getMaxConcurrency, shouldDebate, runOrchestratorLoop } from '../src/orchestratorLoop.js';
import { evaluateComplexity } from '../src/orchestrator.js';
import { callLLM } from '../src/llm.js';
import { getRolePrompt } from '../src/prompts.js';
import { synthesizeReport, identifyRisks, suggestNextSteps } from '../src/synthesis.js';

test('1. Dependency Graph & Conflict Prediction', async (t) => {
  const indexData = {
    files: {
      'src/db.js': { imports: [], exports: ['query', 'connect'] },
      'src/models/user.js': { imports: ['../db.js'], exports: ['User'] },
      'src/routes/auth.js': { imports: ['../models/user.js', '../db.js'], exports: ['authRouter'] },
      'src/server.js': { imports: ['./routes/auth.js', './db.js'], exports: ['app'] }
    }
  };

  const graph = new DependencyGraph(indexData);

  await t.test('tracks dependencies and dependents', () => {
    const userDeps = graph.getDependencies('src/models/user.js');
    assert.ok(userDeps.has('src/db.js'), 'User model should depend on db.js');

    const dbDependents = graph.getDependents('src/db.js');
    assert.ok(dbDependents.has('src/models/user.js'), 'db.js should have models/user.js as dependent');
    assert.ok(dbDependents.has('src/routes/auth.js'), 'db.js should have routes/auth.js as dependent');
  });

  await t.test('calculates topological order for execution', () => {
    const files = ['src/server.js', 'src/models/user.js', 'src/db.js', 'src/routes/auth.js'];
    const order = graph.getTopologicalOrder(files);
    
    // db.js must precede models/user.js and routes/auth.js
    assert.ok(order.indexOf('src/db.js') < order.indexOf('src/models/user.js'));
    assert.ok(order.indexOf('src/models/user.js') < order.indexOf('src/routes/auth.js'));
    assert.ok(order.indexOf('src/routes/auth.js') < order.indexOf('src/server.js'));
  });

  await t.test('predicts file conflicts across competing agents', () => {
    const tasks = [
      { agentId: 'agent-auth', files: ['src/routes/auth.js', 'src/db.js'] },
      { agentId: 'agent-billing', files: ['src/routes/billing.js', 'src/db.js'] }
    ];

    const conflicts = graph.predictConflicts(tasks);
    assert.equal(conflicts.length, 1);
    assert.equal(conflicts[0].file, 'src/db.js');
    assert.deepEqual(conflicts[0].agents.sort(), ['agent-auth', 'agent-billing']);
  });

  await t.test('file claiming prevents concurrent conflicting edits', () => {
    const claim1 = graph.claimFile('agent-1', 'src/config.js');
    assert.equal(claim1.ok, true);

    const claim2 = graph.claimFile('agent-2', 'src/config.js');
    assert.equal(claim2.ok, false);
    assert.equal(claim2.claimedBy, 'agent-1');

    graph.releaseFile('agent-1', 'src/config.js');
    const claim3 = graph.claimFile('agent-2', 'src/config.js');
    assert.equal(claim3.ok, true);
    graph.releaseFile('agent-2', 'src/config.js');
  });

  await t.test('calculates impacted files blast radius', () => {
    const impacted = graph.getImpactedFiles(['src/db.js']);
    assert.ok(impacted.has('src/models/user.js'));
    assert.ok(impacted.has('src/routes/auth.js'));
    assert.ok(impacted.has('src/server.js'));
  });
});

test('2. Patch Safety, Diff Stats & Risk Scoring', async (t) => {
  const lowRiskDiff = `diff --git a/src/utils.js b/src/utils.js
--- a/src/utils.js
+++ b/src/utils.js
@@ -1,2 +1,3 @@
 function add(a, b) {
+  // addition helper
   return a + b;
 }`;

  const highRiskDiff = `diff --git a/package-lock.json b/package-lock.json
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,5 +1,150 @@
+dependency changes
diff --git a/package.json b/package.json
deleted file mode 100644
--- a/package.json
+++ /dev/null
diff --git a/src/config.json b/src/config.json
--- a/src/config.json
+++ b/src/config.json
@@ -1,5 +1,600 @@
+// replaced config
+<<<<<<< HEAD
+=======
+>>>>>>> incoming
`;

  const safety = new PatchSafety();

  await t.test('parses diff statistics accurately', () => {
    const stats = parseDiffStats(lowRiskDiff);
    assert.equal(stats.linesAdded, 1);
    assert.equal(stats.linesRemoved, 0);
    assert.equal(stats.filesModified, 1);
  });

  await t.test('scores low risk diff correctly', () => {
    const risk = safety.scoreRisk(lowRiskDiff);
    assert.equal(typeof risk, 'object');
    assert.ok(risk.score <= 20, `Expected low risk score <= 20, got ${risk.score}`);
    assert.ok(Array.isArray(risk.reasons));
  });

  await t.test('scores high risk diff for config touches and deletions', () => {
    const risk = safety.scoreRisk(highRiskDiff);
    assert.equal(typeof risk, 'object');
    assert.ok(risk.score >= 60, `Expected high risk score >= 60, got ${risk.score}`);
    assert.ok(risk.reasons.some(r => r.includes('config') || r.includes('deleting')));
  });
});

test('3. Orchestrator Concurrency & Debate Policies', async (t) => {
  await t.test('returns appropriate concurrency limit per tier', () => {
    assert.equal(getMaxConcurrency('tiny'), 1);
    assert.equal(getMaxConcurrency('normal'), 5);
    assert.equal(getMaxConcurrency('big'), 10);
    assert.equal(getMaxConcurrency('huge'), 25);
  });

  await t.test('shouldDebate triggers only on high-tier and high-risk diffs', () => {
    assert.equal(shouldDebate('tiny', 70), false); // Tiny tier does not debate
    assert.equal(shouldDebate('normal', 30), false); // Low risk does not debate
    assert.equal(shouldDebate('normal', 65), true); // High risk in normal tier debates
    assert.equal(shouldDebate('big', 85), true); // High risk in big tier debates
  });
});

test('4. Live Multi-Agent Debate Cycle (Critic vs Fixer on Groq)', async (t) => {
  // Vulnerable diff with SQL injection and missing null checks
  const buggyDiff = `diff --git a/src/auth.js b/src/auth.js
--- a/src/auth.js
+++ b/src/auth.js
@@ -10,4 +10,10 @@
+function findUser(username, password) {
+  // Vulnerable to SQL injection!
+  const query = "SELECT * FROM users WHERE user = '" + username + "' AND pass = '" + password + "'";
+  return db.execute(query);
+}`;

  console.log('\n--- Round 1: Critic attacks the implementation ---');
  const criticRes = await callLLM('critic', `Attack this diff. Find security holes, vulnerabilities, and missing sanitization:\n\n${buggyDiff}`);
  const critique = criticRes?.content || "";
  
  console.log(`Critic findings snippet: ${critique.slice(0, 180)}...`);
  assert.ok(critique.length > 50, 'Critic must produce substantial adversarial critique');
  assert.match(critique.toLowerCase(), /sql|inject|parameter|secur/i, 'Critic must identify SQL injection vulnerability');

  console.log('\n--- Round 2: Fixer defends and produces corrected implementation ---');
  const fixerRes = await callLLM('fixer', `Address all issues raised by the critic. Produce a secure, corrected implementation:\n\nCRITIQUE:\n${critique}\n\nORIGINAL DIFF:\n${buggyDiff}`);
  const fix = fixerRes?.content || "";

  console.log(`Fixer response snippet: ${fix.slice(0, 180)}...`);
  assert.ok(fix.length > 50, 'Fixer must produce corrected code');
  assert.match(fix.toLowerCase(), /parameter|prepare|\?|\$|bind/i, 'Fixer must parameterize or prepare the query to fix SQL injection');
});

test('5. Orchestrator Synthesis & Quality Gates', async (t) => {
  const mockAgentResults = [
    { id: 'agent-db', status: 'completed', result: { diff: 'diff --git a/db.js b/db.js\n+console.log("db");' } },
    { id: 'agent-api', status: 'completed', result: { diff: 'diff --git a/api.js b/api.js\n+console.log("api");' } }
  ];

  const mockGatesResult = { passed: true, gatesRun: [{ name: 'test', passed: true, exitCode: 0 }] };

  const report = await synthesizeReport(mockAgentResults, mockGatesResult);
  assert.ok(report.summary.includes('Task'));
  assert.equal(report.agentPerformance.totalAgents, 2);
  assert.equal(report.agentPerformance.successRate, '100%');

  const risks = identifyRisks(mockAgentResults);
  assert.ok(Array.isArray(risks));

  const nextSteps = suggestNextSteps(mockAgentResults);
  assert.ok(Array.isArray(nextSteps));
});

test('6. Orchestrator Task Complexity Classification via LLM', async (t) => {
  const tinyTask = "Fix a typo in README.md";
  const planTiny = await evaluateComplexity(tinyTask);
  assert.equal(planTiny.tier, 'tiny');
  assert.equal(planTiny.debateEnabled, false);
  assert.equal(planTiny.agents.length, 1);

  const bigTask = "Overhaul user authentication, migrate database schemas, rewrite auth controllers, and implement multi-factor login";
  const planBig = await evaluateComplexity(bigTask);
  assert.ok(['normal', 'big', 'huge'].includes(planBig.tier));
  assert.ok(planBig.agents.length >= 2, 'Should spawn 2 or more specialized agents');
  assert.ok(planBig.agents.some(a => a.role === 'planner' || a.role === 'architect' || a.role === 'implementer'));
});
