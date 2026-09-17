import chalk from 'chalk';

export function formatDuration(ms) {
  if (ms == null || isNaN(ms) || ms < 0) return '0s';
  if (ms < 1000) return `${ms}ms`;
  
  const seconds = Math.floor((ms / 1000) % 60);
  const minutes = Math.floor((ms / (1000 * 60)) % 60);
  const hours = Math.floor(ms / (1000 * 60 * 60));
  
  const parts = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (seconds > 0 || parts.length === 0) parts.push(`${seconds}s`);
  
  return parts.join(' ');
}

export function identifyRisks(data) {
  if (Array.isArray(data)) {
    data = { agents: data };
  }
  data = data || {};
  const risks = [];
  
  if (data.agents && data.agents.some(a => a.status === 'failed')) {
    risks.push('One or more agents failed during execution');
  }
  
  if (data.mergeResult && data.mergeResult.conflicts && data.mergeResult.conflicts.length > 0) {
    risks.push(`Merge conflicts in files: ${data.mergeResult.conflicts.join(', ')}`);
  }
  
  if (data.qualityGates && data.qualityGates.passed === false) {
    risks.push('One or more quality gates failed');
  }
  
  if (data.changedFiles && data.changedFiles.length > 20) {
    risks.push('Large number of changed files');
  }
  
  if (data.changedFiles && data.changedFiles.some(f => f.match(/\.config\.|package\.json/i))) {
    risks.push('Configuration files were modified');
  }
  
  return risks;
}

export function suggestNextSteps(data) {
  if (Array.isArray(data)) {
    data = { agents: data };
  }
  data = data || {};
  const steps = [];
  const hasTests = data.agents && data.agents.some(a => a.role === 'test' || (a.task && a.task.toLowerCase().includes('test')));
  
  if (!hasTests) {
    steps.push('Add test coverage');
  }
  
  if (data.qualityGates && data.qualityGates.results) {
    const lintFailed = data.qualityGates.results.some(r => r.name && r.name.toLowerCase().includes('lint') && !r.passed);
    if (lintFailed) {
      steps.push('Fix linting issues');
    }
  }
  
  if (data.tier === 'big' || data.tier === 'huge' || (data.changedFiles && data.changedFiles.length > 10)) {
    steps.push('Manual code review recommended');
  }
  
  return steps;
}

export function synthesizeReport(data, secondary = null) {
  let normalizedData = data;
  if (Array.isArray(data)) {
    normalizedData = {
      task: 'Orchestrated Task',
      tier: 'normal',
      agents: data,
      qualityGates: secondary,
    };
  }
  normalizedData = normalizedData || {};

  const risks = identifyRisks(normalizedData);
  const nextSteps = suggestNextSteps(normalizedData);
  
  const durationMs = (normalizedData.endTime || Date.now()) - (normalizedData.startTime || Date.now());
  const formattedDuration = formatDuration(durationMs);
  
  const agents = normalizedData.agents || [];
  const successAgents = agents.filter(a => a.status === 'completed').length;
  const totalAgents = agents.length;
  const successRate = totalAgents > 0 ? `${Math.round((successAgents / totalAgents) * 100)}%` : '0%';
  
  const passedTests = 0;
  const failedTests = 0;
  const skippedTests = 0;
  
  let summary = `Task "${normalizedData.task || 'Task'}" completed in ${formattedDuration} using ${normalizedData.tier || 'adaptive'} tier.`;
  if (risks.length > 0) summary += ` Completed with ${risks.length} potential risk(s).`;
  
  return {
    summary,
    changedFiles: data.changedFiles || [],
    testsRun: { passed: passedTests, failed: failedTests, skipped: skippedTests },
    risks,
    nextSteps,
    agentPerformance: {
      totalAgents,
      tier: data.tier || 'unknown',
      duration: formattedDuration,
      successRate
    }
  };
}

export function printReport(report) {
  console.log(chalk.green.bold('\n=== EXECUTION REPORT ==='));
  console.log(chalk.green(report.summary));
  
  console.log(chalk.bold('\nChanged Files:'));
  if (report.changedFiles && report.changedFiles.length === 0) {
    console.log('  None');
  } else {
    report.changedFiles.forEach(f => console.log(`  - ${f}`));
  }
  
  console.log(chalk.bold('\nTest Results:'));
  console.log(`  Passed: ${chalk.green(report.testsRun.passed)}`);
  console.log(`  Failed: ${chalk.red(report.testsRun.failed)}`);
  console.log(`  Skipped: ${chalk.gray(report.testsRun.skipped)}`);
  
  if (report.risks && report.risks.length > 0) {
    console.log(chalk.yellow.bold('\nRisks Identified:'));
    report.risks.forEach(r => console.log(chalk.yellow(`  ! ${r}`)));
  }
  
  if (report.nextSteps && report.nextSteps.length > 0) {
    console.log(chalk.cyan.bold('\nSuggested Next Steps:'));
    report.nextSteps.forEach(s => console.log(chalk.cyan(`  → ${s}`)));
  }
  
  console.log(chalk.dim('\n--- Agent Performance ---'));
  console.log(chalk.dim(`Total Agents: ${report.agentPerformance.totalAgents}`));
  console.log(chalk.dim(`Tier: ${report.agentPerformance.tier}`));
  console.log(chalk.dim(`Duration: ${report.agentPerformance.duration}`));
  console.log(chalk.dim(`Success Rate: ${report.agentPerformance.successRate}`));
  console.log('');
}
