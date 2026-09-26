import { createInterface } from 'node:readline';
import chalk from 'chalk';
import { loadMemory, updatePreferences, getPreferences } from './memory.js';

function askQuestion(query) {
  return new Promise(resolve => {
    const rl = createInterface({
      input: process.stdin,
      output: process.stdout
    });
    rl.question(query, answer => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

export async function initApprovalFlow() {
  // If NON_INTERACTIVE or non-TTY — always auto, save and return immediately
  if (!process.stdin.isTTY || process.env.NON_INTERACTIVE || process.env.SWADES_AUTO_APPROVE === "true") {
    await updatePreferences({ approvalMode: 'auto' });
    return 'auto';
  }

  await loadMemory();
  const prefs = getPreferences();

  if (prefs && prefs.approvalMode) {
    console.log(chalk.green(`✓ Using saved approval mode: ${prefs.approvalMode}`));
    return prefs.approvalMode;
  }

  console.log(chalk.cyan('\n🔒 Approval Mode (saved for future sessions):'));
  console.log('  [1] Auto-approve everything — trust AI fully, no interruptions');
  console.log('  [2] Approve critical only — pause for destructive edits, dependency installs, architecture changes');
  console.log('  [3] Manual review — approve every patch before applying');
  
  const choice = await askQuestion('\nChoice (1/2/3, default=2): ');
  
  let mode = 'critical';
  if (choice === '1') mode = 'auto';
  else if (choice === '3') mode = 'manual';
  
  await updatePreferences({ approvalMode: mode });
  console.log(chalk.green(`✓ Approval mode set to: ${mode}\n`));
  
  return mode;
}

export async function requestApproval(action, details, mode = null) {
  if (!mode) {
    await loadMemory();
    const prefs = getPreferences();
    mode = prefs?.approvalMode || 'critical';
  }

  if (mode === 'auto') {
    return true;
  }

  if (!process.stdin.isTTY || process.env.NON_INTERACTIVE) {
    return true; // Auto approve in non-interactive environments
  }

  const isActionCritical = isDestructive(action);

  if (mode === 'critical' && !isActionCritical) {
    return true;
  }

  console.log(chalk.yellow(`\n⚠️  Approval required for: ${action}`));
  console.log(chalk.gray(`Details: ${details}`));
  
  const answer = await askQuestion(chalk.yellow('Allow this action? [y/N]: '));
  return answer.toLowerCase() === 'y';
}

export function classifyAction(toolName, args) {
  if (toolName === 'run_command') {
    const cmd = args.command || args.CommandLine || '';
    if (/(npm|pip|cargo|yarn|pnpm)\s+(install|add)/.test(cmd)) {
      return 'dependency_install';
    }
    if (/\b(rm|delete|rmdir)\b/.test(cmd)) {
      return 'destructive_edit';
    }
  }
  
  if (['write_file', 'patch_file', 'write_to_file', 'replace_file_content'].includes(toolName)) {
    const file = args.file || args.TargetFile || args.path || '';
    if (/\.(json|yaml|yml|config\.[a-z]+|toml)$/.test(file)) {
      return 'architecture_change';
    }
    // Example heuristic for new directory (often ends with / or contains new subdirs)
    // Could also just be part of normal unless we check fs, but we keep it static here.
  }

  return 'normal';
}

export function isDestructive(action) {
  const criticalActions = ['dependency_install', 'destructive_edit', 'architecture_change', 'file_delete'];
  return criticalActions.includes(action);
}
