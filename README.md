# 🧠 ReAct SWE Agent

A production-grade, highly optimized autonomous AI software engineering agent (~800 lines of code) that uses the **ReAct (Thought → Action → Observation)** loop to solve complex coding tasks directly inside your terminal.

It features **24/7 Autonomous Supervision**, **Local Codebase Indexing**, **Space-Sensitive Partial Patching**, **Built-in Syntax & Indentation Checkers**, and **Real-time Live Streaming** of thoughts and tool calls.

---

## 🚀 Key Features

*   **🎬 24/7 Autonomous Mode (Director AI)**: A high-level Director AI supervises the Worker Agent, breaking complex goals into multi-step sub-tasks, reviewing git status and test logs, and iterating autonomously until the entire project is verified and complete.
*   **⚡ Next-Gen Codebase Indexing**: The agent automatically scans and maps your codebase on startup, indexing imports, exports, functions, and classes to `.agent_index.json`. The AI starts with deep codebase knowledge, bypassing the need to list directories.
*   **🔧 Space-Sensitive Partial Patching (`patch_file`)**: Edits existing files by replacing precise blocks of code instead of rewriting entire files. Space-sensitive, preserves indentation, and saves up to 90% in token usage!
*   **🔒 Heuristic Syntax & Indentation Checker**: Runs automatic, zero-dependency static analysis before saving code. It flags unclosed brackets, mixed tabs/spaces, unexpected indentation jumps, and runs built-in compiler checks (`node --check` for JS, `JSON.parse` for JSON) to self-correct code before execution.
*   **📺 Real-Time Live Streaming**: Watch the AI's reasoning, thought process, and tool calls stream live in your terminal token-by-token with color-coded previews.
*   **📝 Structured JSONL Prompts**: System instructions and conversation history are formatted as structured JSON Lines (JSONL), ensuring hyper-predictable behavior and instruction-following.

---

## 🚀 Setup & Installation

### Step 1: Install Node.js
You need **Node.js** (v18+ or v22+) installed on your computer.
```bash
node -v
```
If not installed, get it from [nodejs.org](https://nodejs.org/).

### Step 2: Clone & Install Dependencies
```bash
git clone https://github.com/Electroiscoding/reactsystemlearning1.git
cd reactsystemlearning1
npm install
```

### Step 3: Configure your Environment
1. Create a `.env` file from the template:
   * **Mac/Linux:** `cp .env.example .env`
   * **Windows:** `copy .env.example .env`
2. Open `.env` and add your OpenRouter key:
   ```env
   API_KEY=sk-or-v1-your-key-here
   BASE_URL=https://openrouter.ai/api/v1
   MODEL=openrouter/free
   ```
3. **Important (Nesting in other projects)**: If you clone this agent folder inside your own repository to edit it, add this line to your `.env` so the agent targets your project and not its own folder:
   ```env
   WORKDIR=../
   ```

---

## 🎮 How to Run

You can run the agent in two modes:

### 1. Standard Mode (Worker Only)
The agent executes the task in a single session and stops when finished.
*   **Interactive**: `npm start` (choose `N` when asked about 24/7 mode)
*   **Direct Task**: `node src/index.js "Write a hello world script in JS"`

### 2. 🎬 24/7 Autonomous Mode (Director Supervised)
The Director AI will supervise, evaluate, write sub-tasks, run tests, and guide the worker autonomously until the goal is fully achieved.
*   **Interactive**: `npm start` (choose `Y` when asked about 24/7 mode)
*   **Direct Task**: `node src/index.js "Create a fully functional calculator app with tests and run it" --autonomous`

---

## 🛠 Tools in the Toolbox

| Tool | Mode | Description |
|------|------|-------------|
| `index_codebase` | Read | Generates/updates `.agent_index.json` with class, function, and file structures. |
| `read_file` | Read | Reads file contents with precise line numbers. |
| `write_file` | Write | Writes complete content to new files (auto-creates directories). |
| `patch_file` | Write | Space-sensitive partial block edits to existing files. **Extremely token-efficient.** |
| `list_dir` | Read | Lists files in workspace (ignores `node_modules`, `.git`, and self-hides). |
| `grep_search` | Read | Searches for regex patterns across files. |
| `run_command` | Execute | Executes shell commands with a 30s timeout (dangerous commands require confirmation). |

---

## 🔒 Safety & Guardrails

*   **Workspace Isolation & Self-Hiding**: If cloned as a subdirectory (like `/agent`), the agent programmatically filters out its own directory from `list_dir` and `grep_search`. The AI cannot see, read, or alter its own code, preventing folder-trap loops.
*   **Dangerous Command Blocking**: Shell commands containing `rm -rf`, `sudo`, `kill`, etc. require manual interactive approval.
*   **Timeout & Step Caps**: Terminal commands automatically time out after 30 seconds. Worker agents are hard-capped at 30 steps per sub-task.
