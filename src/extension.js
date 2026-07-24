import * as vscode from 'vscode';
import * as path from 'path';

export function activate(context) {
  console.log('Swades Agent terminal extension is active!');

  // Register the general run command
  context.subscriptions.push(
    vscode.commands.registerCommand('swades-agent.run', () => {
      runSwadesTerminal(context, null);
    })
  );

  // Register direct mode shortcuts
  context.subscriptions.push(
    vscode.commands.registerCommand('swades-agent.runAutonomous', () => {
      runSwadesTerminal(context, 'autonomous');
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('swades-agent.runCua', () => {
      runSwadesTerminal(context, 'cua');
    })
  );
}

export function deactivate() {}

async function runSwadesTerminal(context, mode) {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showErrorMessage('Please open a workspace folder before running Swades Agent.');
    return;
  }

  const workspacePath = workspaceFolders[0].uri.fsPath;
  const indexJsPath = path.join(context.extensionPath, 'src', 'index.js');

  // 1. Prompt for Task
  const task = await vscode.window.showInputBox({
    prompt: "Enter your task/goal for Swades Agent",
    placeHolder: "e.g., Add email verification to auth.js and run tests",
    ignoreFocusOut: true,
    validateInput: (value) => {
      return value.trim() ? null : "Task cannot be empty.";
    }
  });

  if (!task) return;

  // 2. Resolve Mode
  let selectedMode = mode;
  if (!selectedMode) {
    const modeChoice = await vscode.window.showQuickPick([
      { label: "Normal Mode", detail: "Executes the task from start to finish in a single worker session" },
      { label: "Autonomous Mode", detail: "Runs worker directed by a supervising supervisor loop (Director Mode)" },
      { label: "CUA Mode", detail: "Executes graphical desktop automation tasks (Computer Use)" }
    ], {
      placeHolder: "Select execution mode for Swades Agent",
      ignoreFocusOut: true
    });

    if (!modeChoice) return;

    if (modeChoice.label.includes("Autonomous")) {
      selectedMode = "autonomous";
    } else if (modeChoice.label.includes("CUA")) {
      selectedMode = "cua";
    } else {
      selectedMode = "normal";
    }
  }

  // 3. Prompt for Image (Optional)
  const image = await vscode.window.showInputBox({
    prompt: "Specify local image path or URL (Optional)",
    placeHolder: "e.g., arch.png (press Enter to skip)",
    ignoreFocusOut: true
  });

  // 4. Formulate command and escape parameters safely for shell execution
  const escapedTask = task.replace(/"/g, '\\"');
  let cmd = `node "${indexJsPath}" "${escapedTask}"`;

  if (selectedMode === 'autonomous') {
    cmd += ' --autonomous';
  } else if (selectedMode === 'cua') {
    cmd += ' --cua';
  }

  if (image && image.trim()) {
    const escapedImage = image.trim().replace(/"/g, '\\"');
    cmd += ` --image "${escapedImage}"`;
  }

  // 5. Retrieve or Create VS Code Terminal
  let terminal = vscode.window.terminals.find(t => t.name === "Swades Agent");
  if (!terminal) {
    terminal = vscode.window.createTerminal({
      name: "Swades Agent",
      cwd: workspacePath
    });
  }

  // Show the terminal and send execution command
  terminal.show(true);
  terminal.sendText(cmd);
}
