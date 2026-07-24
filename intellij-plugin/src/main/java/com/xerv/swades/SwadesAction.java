package com.xerv.swades;

import com.intellij.openapi.actionSystem.AnAction;
import com.intellij.openapi.actionSystem.AnActionEvent;
import com.intellij.openapi.project.Project;
import com.intellij.openapi.ui.Messages;
import org.jetbrains.plugins.terminal.TerminalView;
import org.jetbrains.plugins.terminal.ShellTerminalWidget;

public class SwadesAction extends AnAction {
    @Override
    public void actionPerformed(AnActionEvent e) {
        Project project = e.getProject();
        if (project == null) return;

        // 1. Prompt for Task
        String task = Messages.showInputDialog(
            project,
            "Enter your task/goal for Swades Agent:",
            "Swades Agent",
            Messages.getQuestionIcon()
        );
        if (task == null || task.trim().isEmpty()) return;

        // 2. Prompt for Options
        String options = Messages.showInputDialog(
            project,
            "Enter optional flags (e.g., --autonomous, --cua, --image arch.png):",
            "Swades Agent Options",
            Messages.getQuestionIcon(),
            "",
            null
        );
        if (options == null) options = "";

        // 3. Formulate the execution command
        String escapedTask = task.replace("\"", "\\\"");
        String command = "npx @xerv/swades-agent \"" + escapedTask + "\" " + options;

        // 4. Spawn a terminal widget inside the IntelliJ Terminal view and execute
        try {
            TerminalView terminalView = TerminalView.getInstance(project);
            ShellTerminalWidget terminalWidget = terminalView.createLocalShellWidget(project.getBasePath(), "Swades Agent");
            terminalWidget.executeCommand(command);
        } catch (Exception ex) {
            Messages.showErrorDialog(project, "Failed to launch terminal: " + ex.getMessage(), "Error");
        }
    }
}
