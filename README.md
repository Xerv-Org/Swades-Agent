<p align="center">
  <img src="logos/swades-clean-removebg-preview.png" width="120" alt="Swades Agent logo — autonomous AI coding agent"/>
</p>

<h1 align="center">Swades Agent</h1>

<p align="center">
  Autonomous AI software engineering agent for your terminal.<br/>
  ReAct loop · OpenAI-compatible · Token streaming · Self-correcting · 24/7 Director mode
</p>

<p align="center">
  <a href="#setup--installation">Setup</a> ·
  <a href="#how-to-run">How to Run</a> ·
  <a href="#tools">Tools</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#safety--guardrails">Safety</a>
</p>

---

## What is Swades Agent?

Swades Agent is an open-source, terminal-native autonomous AI coding agent built on the **ReAct (Reasoning + Acting)** loop pattern. You give it a coding task in plain text. It reads your codebase, edits files with surgical precision, runs shell commands, searches code, and iterates until the task is done — all without leaving your terminal.

It works with any **OpenAI-compatible API** (OpenAI, OpenRouter, Groq, Ollama, etc.), streams tokens to the terminal in real-time as the model thinks, and runs automatic syntax validation on every file it writes.

No GUI. No cloud lock-in. No build step. ~800 lines of plain Node.js.

---

## Key Capabilities

- **ReAct agentic loop** — Thought → Tool Call → Observation → repeat until task is solved
- **Real-time token streaming** — see the model's reasoning and tool arguments token-by-token as they arrive
- **Partial file patching** — edits only the exact block that needs changing, not the entire file (saves tokens, preserves indentation)
- **Automatic codebase indexing** — maps your repo structure (imports, exports, classes, functions) before starting, so the model never re-scans blindly
- **Built-in syntax checker** — validates bracket matching, indentation consistency, and runs `node --check` on every JS save
- **24/7 Director mode** — a second "Director" model instance reviews progress after each run and writes the next subtask on behalf of the user, iterating autonomously
- **Session memory** — persists a summary of each run to `.agent_memory.json` and injects recent context into the next session
- **Workspace isolation** — when installed inside a project subdirectory, the agent hides its own files from the model so it only sees your code

---

## Setup & Installation

### Step 1: Install Node.js

You need **Node.js v18 or later** (v22 recommended).

```bash
node -v
```

If not installed, download from [nodejs.org](https://nodejs.org/) or use a version manager like [nvm](https://github.com/nvm-sh/nvm).

### Step 2: Clone & Install Dependencies

```bash
git clone https://github.com/Electroiscoding/reactsystemlearning1.git
cd reactsystemlearning1
npm install
```

This installs three packages: `openai` (API client), `dotenv` (env loading), and `chalk` (terminal colors).

### Step 3: Configure your Environment

**Mac / Linux:**
```bash
cp .env.example .env
```

**Windows:**
```cmd
copy .env.example .env
```

Open `.env` and fill in your values:

```env
API_KEY=sk-or-v1-your-key-here
BASE_URL=https://openrouter.ai/api/v1
MODEL=openrouter/free
```

**All supported environment variables:**

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | Yes | — | Your LLM provider API key |
| `BASE_URL` | No | `https://openrouter.ai/api/v1` | Provider base URL (change for OpenAI, Groq, Ollama, etc.) |
| `MODEL` | No | `openrouter/free` | Model identifier string |
| `MAX_STEPS` | No | `30` | Max tool-call iterations per agent run before hard stop |
| `MAX_OUTPUT_LENGTH` | No | `10000` | Character cap on tool output returned to the model |
| `WORKDIR` | No | `process.cwd()` | Absolute or relative path the agent operates on |

**Using a different provider:**

```env
# OpenAI
API_KEY=sk-...
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o

# Groq
API_KEY=gsk_...
BASE_URL=https://api.groq.com/openai/v1
MODEL=llama-3.3-70b-versatile

# Local Ollama
API_KEY=ollama
BASE_URL=http://localhost:11434/v1
MODEL=qwen2.5-coder:7b
```

**Important — running inside another project:**

If you clone this repo as a subfolder inside your own codebase (e.g. `myproject/swades-agent/`), add this to `.env` so the agent targets your project root and not its own folder:

```env
WORKDIR=../
```

---

## How to Run

### Standard Mode (single task, one run)

The agent executes the task from start to finish in a single session and exits when done.

**Interactive prompt:**
```bash
npm start
# Answer the task question, then answer N to the autonomous mode question
```

**Direct task via argument:**
```bash
node src/index.js "Write a hello world script in Python"
node src/index.js "Add input validation to the login form in src/auth.js"
node src/index.js "Find all TODO comments in the codebase and open a summary file"
```

### 24/7 Autonomous Mode (Director-supervised, multi-cycle)

In autonomous mode, a second "Director" model instance supervises the worker. After each worker run, the Director reviews the full conversation history and writes the next subtask prompt on behalf of the user. This repeats until the Director determines the goal is fully achieved.

**Interactive prompt:**
```bash
npm start
# Answer the task question, then answer Y to the autonomous mode question
```

**Direct task via argument:**
```bash
node src/index.js "Create a fully functional REST API with tests, run them, and fix any failures" --autonomous
node src/index.js "Refactor the entire codebase to TypeScript and verify it compiles" --autonomous
```

The `--autonomous` flag (or `-a`) activates the Director loop. The Director runs for up to 5 cycles by default.

---

## Tools

The agent has access to 7 tools it can call during a run:

| Tool | Arguments | Description |
|---|---|---|
| `index_codebase` | _(none)_ | Scans workspace, writes `.agent_index.json` with file paths, sizes, imports, exports, classes, functions |
| `read_file` | `path`, `start_line?`, `end_line?` | Returns file contents with line numbers. Supports partial reads by line range. |
| `write_file` | `path`, `content` | Writes a complete new file. Runs syntax + indentation checks on save. |
| `patch_file` | `path`, `target`, `replacement` | Replaces a unique block within an existing file. Space-sensitive. Fails with a clear error if target is ambiguous or not found. |
| `list_dir` | `path`, `recursive?` | Lists directory tree. Skips `node_modules`, `.git`, and the agent's own folder. |
| `grep_search` | `pattern`, `path`, `include?` | Runs `grep -rnI` across the workspace. Excludes the agent directory automatically. |
| `run_command` | `command`, `cwd?` | Executes a shell command with 30s timeout. Prompts for user confirmation on destructive patterns. |

**Automatic validation on every write:**

Both `write_file` and `patch_file` run these checks immediately after writing and return the results to the model so it can self-correct:

- Bracket matching: detects unclosed `{`, `(`, `[` and mismatched pairs
- Indentation consistency: flags mixed tabs + spaces; flags sudden indentation jumps
- JS/MJS/CJS: runs `node --check <file>` for compiler-level syntax errors
- JSON: runs `JSON.parse()` on the written content

---

## Architecture

```
src/
  index.js      CLI entry point — reads task from args or stdin, runs auto-index, dispatches to agent or director
  agent.js      ReAct loop — message history, streaming LLM call, tool dispatch, observation injection
  director.js   Director loop — runs worker across cycles, reviews history, writes next subtask prompt
  llm.js        OpenAI SDK wrapper — stream=true, reconstructs full message from SSE delta chunks
  tools.js      7 tool implementations + heuristic syntax checker + codebase indexer
  prompts.js    System prompt (JSONL-structured) + OpenAI function-calling tool schemas
  memory.js     Appends session summaries to .agent_memory.json, injects recent context at startup
```

**Single-run message flow:**
```
index.js → index_codebase() → agent.js loop:
  [system + memory + task] → LLM (streaming SSE)
    → text delta    → printed live to terminal
    → tool_call delta → executeTool() → observation → appended to messages
  repeat until LLM returns no tool calls → print final answer → exit
```

**24/7 autonomous message flow:**
```
director.js → cycle 1..N:
  runAgent(messages)         ← worker resolves a subtask
  callLLM(directorMessages)  ← director reviews history, writes next prompt
  messages.push(nextPrompt)  ← appended as user turn, fed into next cycle
  repeat until director outputs "STATUS: COMPLETE"
```

---

## Safety & Guardrails

- **Workspace isolation & self-hiding** — when installed as a subdirectory of the target project, the agent filters out its own folder from `list_dir` and `grep_search`. The model cannot see, read, or modify its own source files, which prevents it from getting confused about which codebase it is working on.
- **Dangerous command blocking** — shell commands matching `rm -rf`, `sudo`, `kill`, `dd if=`, `chmod 777`, `:(){`, and others pause execution and require an explicit `y` typed in the terminal before running.
- **Step cap** — the worker agent stops after `MAX_STEPS` iterations (default 30) to prevent infinite loops. This is configurable via `.env`.
- **Director cycle cap** — the Director loop stops after 5 cycles by default.
- **Timeout** — `run_command` automatically times out after 30 seconds.
- **Workspace scoping** — all file paths passed to tools are resolved relative to `WORKDIR`. The agent cannot access paths outside of it.

---

## Session Memory

After each completed run, the agent appends a session record to `.agent_memory.json`:

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "task": "Add input validation to the login form",
  "summary": "Added email format check and password length validation in src/auth.js. Updated tests.",
  "toolsUsed": ["read_file", "patch_file", "run_command"]
}
```

On the next run, the three most recent sessions are injected into the system prompt, giving the agent continuity between invocations without needing a long-running server.

---

## What's New in v2.0

- **24/7 Director Loop** — autonomous multi-cycle execution with a supervising Director model. Pass `--autonomous` to any task.
- **Codebase Indexing** — automatic `index_codebase` run at startup generates `.agent_index.json` with the full repository structure so the model starts with deep context.
- **Partial File Patching** — `patch_file` tool for surgical block-level edits. Preserves exact indentation. Saves significant tokens vs. full-file rewrites.
- **Static Syntax Guardrails** — automatic bracket matching, indentation checks, `node --check`, and JSON parse validation on every file save, with errors returned to the model for self-correction.
- **Real-time Token Streaming** — LLM reasoning, tool names, and arguments stream to the terminal token-by-token using OpenAI SDK SSE.
- **JSONL System Prompt** — system instructions structured as JSON Lines for high-precision instruction following by reasoning models.
- **Session Memory** — cross-run context via `.agent_memory.json`.
- **Referer attribution** — all API calls include `HTTP-Referer: https://xerv.netlify.app/swades.html` for OpenRouter analytics tracking.
