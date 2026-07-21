// prompts.js — System prompt & tool schemas for the coding agent

export const SYSTEM_PROMPT = `You are an autonomous AI software engineer. You solve coding tasks by planning, implementing, and verifying changes.

DYNAMIC ARTIFACT DECISION:
For every task, you must dynamically evaluate whether you need to utilize the Google Antigravity Core Artifacts.
- SIMPLE TASKS: If the task is simple (single file edits, explanations, quick CLI runs, queries), do NOT create these artifacts.
- COMPLEX TASKS: If the task is complex, involves multiple files, or requires structured execution tracking, you should choose to use them:
  1. Implementation Plan (implementation_plan.md): Create this first in the workspace root to document context, proposed file changes, and verification plans.
  2. Task List (tasks.md): Create this to log checklist items ([ ] Todo, [/] In Progress, [x] Done) and update it dynamically as you execute.
  3. Walkthrough (walkthrough.md): Create this upon completion, summarizing the final edits, copy-pasteable verification commands, and results.

WORKFLOW:
1. Run index_codebase first to map the repo structure.
2. Evaluate if Core Artifacts are needed. If yes, generate implementation_plan.md and tasks.md in the workspace.
3. Read relevant files with read_file to understand the code.
4. Edit using patch_file (CRITICAL: Always use patch_file for existing files to ensure high token-efficiency. Never rewrite entire files with write_file).
5. Verify with run_command — run tests, check syntax, confirm behavior.
6. If errors appear, fix immediately and re-verify.
7. Update tasks.md as progress is made, and create walkthrough.md at the end if you opted to use the Core Artifacts.

RULES:
- YOU MUST ALWAYS prefer patch_file over write_file for editing existing files. Rewriting entire files is extremely token-inefficient and strictly prohibited.
- Match exact indentation in patch_file targets. Leading spaces must be precise.
- If a file edit returns syntax errors, read the error and fix it immediately.
- Think step-by-step. Explain your reasoning before acting.`;

export const TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "read_file",
      description: "Read file contents with line numbers. Optionally specify a line range.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path to file" },
          start_line: { type: "integer", description: "Start line (1-indexed)" },
          end_line: { type: "integer", description: "End line (inclusive)" }
        },
        required: ["path"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "write_file",
      description: "Create a NEW file with complete content. Auto-creates parent dirs. Use only for new files.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path" },
          content: { type: "string", description: "Complete file content" }
        },
        required: ["path", "content"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "patch_file",
      description: "Edit an existing file by replacing a unique block of text. Space-sensitive. Preferred over write_file.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Relative path" },
          target: { type: "string", description: "Exact text block to replace (must match including indentation)" },
          replacement: { type: "string", description: "Replacement text with correct indentation" }
        },
        required: ["path", "target", "replacement"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "list_dir",
      description: "List directory contents. Skips node_modules and .git.",
      parameters: {
        type: "object",
        properties: {
          path: { type: "string", description: "Directory path" },
          recursive: { type: "boolean", description: "List recursively" }
        },
        required: ["path"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "run_command",
      description: "Execute a shell command. 30s timeout.",
      parameters: {
        type: "object",
        properties: {
          command: { type: "string", description: "Shell command" },
          cwd: { type: "string", description: "Working directory (relative)" }
        },
        required: ["command"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "grep_search",
      description: "Search for a pattern across files.",
      parameters: {
        type: "object",
        properties: {
          pattern: { type: "string", description: "Search pattern (regex)" },
          path: { type: "string", description: "Search directory" },
          include: { type: "string", description: "File glob filter (e.g. '*.js')" }
        },
        required: ["pattern", "path"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "index_codebase",
      description: "Scan the repo and generate .agent_index.json with file structure, exports, and imports. Run at task start.",
      parameters: { type: "object", properties: {} }
    }
  },
  {
    type: "function",
    function: {
      name: "peek_terminal",
      description: "Peek at the active background terminal process output buffer, check its status (running, completed), or terminate it.",
      parameters: {
        type: "object",
        properties: {
          action: { type: "string", enum: ["peek", "kill"], description: "Action to perform (default: 'peek')" }
        }
      }
    }
  },
  {
    type: "function",
    function: {
      name: "extend_deadline",
      description: "Extend the estimated task completion time limit. Use this if the task is taking longer than expected or needs additional complex phases.",
      parameters: {
        type: "object",
        properties: {
          additional_seconds: { type: "number", description: "Number of seconds to add to the deadline (e.g., 60, 120)" },
          reason: { type: "string", description: "Reason explaining why the deadline extension is required" }
        },
        required: ["additional_seconds", "reason"]
      }
    }
  }
];
