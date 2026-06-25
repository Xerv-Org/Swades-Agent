// ============================================================
// prompts.js — System prompt (JSONL format) & Tool schemas
// ============================================================

// Rewritten system prompt in highly structured JSONL format.
// This allows modern reasoning models to parse instructions with extreme precision.
export const SYSTEM_PROMPT = `{"role": "system_rules", "content": "You are a production-grade autonomous AI software engineer. You solve coding tasks by executing plan, implementation, and verification steps."}
{"rule": "Codebase Knowledge", "action": "Before starting or doing heavy searches, run the 'index_codebase' tool to load the repository structure. Use the local '.agent_index.json' to immediately locate relevant files."}
{"rule": "Token Optimization", "action": "DO NOT rewrite entire files. ALWAYS prefer the 'patch_file' tool over 'write_file' for editing existing files. Only use 'write_file' to create brand new files."}
{"rule": "Space & Indentation Sensitivity", "action": "When calling 'patch_file', ensure the 'target' block matches the file's leading spaces exactly. Preserve the project's indentation style."}
{"rule": "Self-Correction", "action": "If a file edit returns syntax warnings or errors from the compiler checker, read the error message carefully and immediately call 'patch_file' to fix it before executing other commands."}
{"rule": "Command Safety", "action": "Verify files and run tests using 'run_command'. Avoid dangerous command sequences."}
{"workflow_step": "1. Run 'index_codebase' to map the codebase."}
{"workflow_step": "2. Locate files and read relevant lines with 'read_file'."}
{"workflow_step": "3. Edit precisely using 'patch_file' with exact indentation."}
{"workflow_step": "4. Verify syntax output, run tests with 'run_command'."}
{"workflow_step": "5. Iterate if tests or compiler checks fail."}
{"note": "Think out loud in your responses. You can output normally in markdown format; the system parses your thoughts and tool calls natively."}`;

// OpenAI function-calling tool schemas (including patch_file and index_codebase)
export const TOOL_SCHEMAS = [
  {
    type: "function",
    function: {
      name: "read_file",
      description:
        "Read the contents of a file. Shows line numbers. Optionally specify a line range.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Relative path to the file to read",
          },
          start_line: {
            type: "integer",
            description: "Optional 1-indexed start line",
          },
          end_line: {
            type: "integer",
            description: "Optional 1-indexed end line (inclusive)",
          },
        },
        required: ["path"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "write_file",
      description:
        "Create a brand new file with complete content. Generates parent directories automatically. Only use for writing new files.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Relative path to the file to create",
          },
          content: {
            type: "string",
            description: "The complete content to write",
          },
        },
        required: ["path", "content"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "patch_file",
      description:
        "Partially edit an existing file by replacing a specific unique block of lines. Space-sensitive, preserves indentation. Extremely token-efficient. Use this instead of write_file for modifying files.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Relative path to the file to modify",
          },
          target: {
            type: "string",
            description:
              "The exact block of code to be replaced. Must match the file contents exactly, including leading spaces and indentation.",
          },
          replacement: {
            type: "string",
            description:
              "The new code block to replace the target block. Maintain correct indentation.",
          },
        },
        required: ["path", "target", "replacement"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "list_dir",
      description:
        "List the contents of a directory. Skips node_modules and agent files automatically.",
      parameters: {
        type: "object",
        properties: {
          path: {
            type: "string",
            description: "Path to list (defaults to workspace root)",
          },
          recursive: {
            type: "boolean",
            description: "If true, list contents recursively",
          },
        },
        required: ["path"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "run_command",
      description:
        "Execute a shell command in the workspace. Automatically times out after 30 seconds. Used to run tests or compilers.",
      parameters: {
        type: "object",
        properties: {
          command: {
            type: "string",
            description: "The shell command to execute",
          },
          cwd: {
            type: "string",
            description: "Working directory relative to workspace root",
          },
        },
        required: ["command"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "grep_search",
      description:
        "Search for a regex pattern across files. Excludes the agent directory automatically.",
      parameters: {
        type: "object",
        properties: {
          pattern: {
            type: "string",
            description: "The search pattern (regex)",
          },
          path: {
            type: "string",
            description: "Directory or file to search in",
          },
          include: {
            type: "string",
            description: "Glob filter (e.g. '*.js')",
          },
        },
        required: ["pattern", "path"],
      },
    },
  },
  {
    type: "function",
    function: {
      name: "index_codebase",
      description:
        "Scan the entire repository and generate/update the local '.agent_index.json' containing file lists, sizes, exports, imports, and structures. Run this tool at the very beginning of a task to get immediate, deep knowledge of the codebase.",
      parameters: {
        type: "object",
        properties: {},
      },
    },
  },
];
