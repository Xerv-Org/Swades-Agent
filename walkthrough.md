# Swades Agent v3.0 — The Complete Operational Manual

Welcome to the **Swades Agent v3.0** developer manual. This guide documents every architecture decision, configuration option, new capability, and operational workflow in the current build.

v3.0 is a foundational re-architecture: modes are gone, limits are gone, and the agent runs as a persistent conversational loop with a unified, borderless execution engine.

---

## ⚡ Quick Start

```bash
git clone https://github.com/Electroiscoding/Swades-Agent.git
cd Swades-Agent
npm install
cp .env.example .env   # add your API_KEY
node src/index.js      # start the persistent chat loop
```

**Node.js v18+** and **Git 2.30+** are required.

---

## Chapter 1: Architecture — The Unified Execution Engine

### 1.1 The Old Architecture (v2.x and Earlier)

In previous versions, the agent required you to pick a mode before it started:
- The entry point ran `detectModeWithAI()` as the very first step.
- It then hard-routed to one of three isolated runtimes: `runAgent`, `runDirector`, or `runCUA`.
- Flags like `--subagents`, `--sim`, `--autonomous` were the only way to unlock advanced capabilities.
- When a task was complete, the process exited — requiring the user to re-run the command for the next task.

**Problems this caused:**
- Artificial ceilings: the agent couldn't spontaneously spawn a simulation it hadn't been pre-authorized to run.
- No context continuity: every re-run started with zero history.
- User overhead: choosing the right mode required predicting task complexity upfront.

### 1.2 The New Architecture (v3.0)

```
┌──────────────────────────────────────────────────────────────────┐
│                    Persistent Chat Loop                          │
│  (runs continuously, retains full message history per session)  │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                ┌──────────────▼──────────────┐
                │    Unified ReAct Agent      │
                │  (single entry point for    │
                │   ALL task types)           │
                └──────────────┬──────────────┘
                               │
    ┌──────────────────────────┼────────────────────────────┐
    │                          │                            │
    ▼                          ▼                            ▼
┌──────────────┐    ┌──────────────────────┐    ┌──────────────────┐
│ File Tools   │    │ Workflow Tools       │    │ Verify Tools     │
│ read_file    │    │ run_simulation       │    │ verify_dom_state │
│ write_file   │    │ spawn_subagents      │    │ rewind_to_       │
│ patch_file   │    │ delegate_to_director │    │ checkpoint       │
│ run_command  │    │                      │    │                  │
│ grep_search  │    │ (called mid-flight,  │    │ (text-only DOM   │
│ peek_terminal│    │  no CLI flag needed) │    │  assertions, no  │
│ extend_dead  │    │                      │    │  screenshots)    │
└──────────────┘    └──────────────────────┘    └──────────────────┘

                            ┌──────────────────┐
                            │  CUA (LOCKED OUT) │
                            │  Only via --cua   │
                            │  CLI flag. Never  │
                            │  auto-invoked.    │
                            └──────────────────┘
```

**Key principles:**
1. **Start once, work forever** — the agent never exits between tasks.
2. **Tools, not modes** — advanced capabilities (`simulation`, `subagents`, `director`) are LLM-callable tools, not CLI modes.
3. **Safety by depth** — a recursive depth guard prevents subagents from spawning their own subagents.
4. **Text-first verification** — UI/browser verification is always text-based DOM assertions. No screenshots by default.
5. **CUA is strictly isolated** — desktop automation is never auto-invoked.

---

## Chapter 2: Environment Configuration

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `API_KEY` | **Yes** | — | API key for your LLM provider |
| `BASE_URL` | No | `https://openrouter.ai/api/v1` | API endpoint |
| `MODEL` | No | `openrouter/free` | Primary model |
| `FALLBACK_MODELS` | No | — | Comma-separated fallback chain (e.g. `gpt-4o,claude-3-haiku`) |
| `CUA_MODEL` | No | `openrouter/free` | Vision model for `--cua` mode only |
| `MAX_STEPS` | No | `Infinity` | Step cap per agent run |
| `MAX_OUTPUT_LENGTH` | No | `10000` | Max chars returned from shell commands |
| `WORKDIR` | No | `process.cwd()` | Target workspace directory |
| `SIM_CONCURRENCY` | No | `2` | Max parallel sandbox scenarios (see §5) |

### LLM Provider Profiles

**OpenRouter (recommended):**
```env
API_KEY=sk-or-v1-xxxx
BASE_URL=https://openrouter.ai/api/v1
MODEL=anthropic/claude-sonnet-4-5
FALLBACK_MODELS=meta-llama/llama-3.3-70b-instruct,openrouter/free
WORKDIR=../
```

**OpenAI:**
```env
API_KEY=sk-proj-xxxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o
```

**Groq:**
```env
API_KEY=gsk_xxxx
BASE_URL=https://api.groq.com/openai/v1
MODEL=llama-3.3-70b-versatile
```

**Ollama (local):**
```env
API_KEY=ollama
BASE_URL=http://localhost:11434/v1
MODEL=qwen2.5-coder:7b
```

### OpenRouter Context Compression

When `BASE_URL` contains `openrouter`, the agent automatically attaches the server-side context compression plugin to every LLM call:

```js
// llm.js — always active on OpenRouter
params.plugins = [{ id: "context-compression" }];
```

This means OpenRouter compresses older messages server-side before forwarding to the model — reducing token costs significantly on long sessions. The local context pruner (see §8.2) handles the Node.js process memory side.

---

## Chapter 3: The Persistent Chat Loop

This is the most significant UX change in v3.0.

### 3.1 Starting the Loop

```bash
node src/index.js
```

Output:
```
  🚀 Swades Agent v3.0
  Workspace: /your/project
  Type 'exit' to quit | 'clear' to reset context | '/help' for commands

────────────────────────────────────────────────────────────

💬 What do you need? → _
```

The agent waits for input. Each task you type is executed by the full ReAct loop. When the task completes, **it returns to the prompt** — no re-run needed.

### 3.2 Chat Loop Commands

| Input | Behavior |
|---|---|
| Any task text | Runs the task through the full agent loop |
| `exit` / `quit` | Gracefully exits the process |
| `clear` | Resets the session message context to blank |
| `/help` | Prints the help menu |
| `task text --image path.png` | Attaches an image inline with the task |

### 3.3 Session Context Continuity

Messages from previous tasks in the same session are preserved in `sessionMessages`. This means the agent remembers what it did in step 1 when you give it a follow-up in step 2:

```
💬 → Add a dark mode toggle to the dashboard
  ✅ Done. Dark mode added via CSS variables.

💬 → Now write a test to verify the toggle works
  (agent already knows about the dashboard from the previous task)
```

Use `clear` to wipe context when you switch to an unrelated project.

### 3.4 CLI Task Shortcut

You can still pass a task on the command line. It runs first, then drops into the loop:

```bash
node src/index.js "Fix the login bug in auth.js"
# → runs the task
# → drops into chat loop for follow-up work
```

---

## Chapter 4: CLI Flags — Now Capability Hints, Not Mode Gates

Flags no longer hard-route the agent into a separate runtime. Instead they set environment variable hints that bias the agent's tool calling behavior.

| Flag | Old Behavior | New Behavior |
|---|---|---|
| `--autonomous`, `-a` | Hard-route to `runDirector()` | Sets `PREFER_DIRECTOR=true`; agent starts in Director loop, then enters chat |
| `--sim` | Force `FORCE_ORCHESTRATED=true` | Sets `PREFER_SIMULATION=true`; biases agent toward `run_simulation` tool |
| `--subagents`, `-s`, `--no-sim` | Force `SUBAGENTS_ONLY=true` | Sets `PREFER_SUBAGENTS=true`; biases agent toward `spawn_subagents` tool |
| `--cua`, `-c` | Hard-route to `runCUA()` | **Still a hard gate** — the ONLY way to enable CUA. Agent process does not enter chat loop. |
| `--image path` | Pass image to first task | Same behavior |
| `--rewind` | (new) | Lists available git checkpoints from the current session |
| `--help`, `-h` | Print help and exit | Same behavior |

**The agent can now call `run_simulation`, `spawn_subagents`, and `delegate_to_director` autonomously** — without any CLI flag. The flags only provide an upfront nudge.

---

## Chapter 5: Parallel Sandbox Simulation (run_simulation)

### 5.1 What Changed

**Before (v2.x):** Sandbox scenarios ran sequentially in a `for...of` loop — Scenario A, then B, then C. Three scenarios = 3× the wait time.

**After (v3.0):** Scenarios run concurrently using `Promise.allSettled()` + a `Semaphore`:

```js
// simulator.js
const concurrencyLimit = parseInt(process.env.SIM_CONCURRENCY) || 2;
const simSemaphore = new Semaphore(concurrencyLimit);

const settled = await Promise.allSettled(
  scenarios.map(scenario =>
    simSemaphore.acquire().then(async () => {
      try { return await runSandbox(scenario, task, baseDir); }
      finally { simSemaphore.release(); }
    })
  )
);
```

**Impact:** 3-scenario simulations drop from ~5 minutes to ~90 seconds with `SIM_CONCURRENCY=3`.

### 5.2 Simulation as a Tool (Mid-Flight)

The agent can now call simulation **at any point** during a task — not just at startup:

```js
// Tool: run_simulation
{
  "name": "run_simulation",
  "arguments": {
    "task": "Implement the caching layer using either Redis or in-memory LRU — test both",
    "reason": "Two valid approaches exist; simulation will pick the one with cleaner test results"
  }
}
```

What happens:
1. The agent calls `run_simulation` as a normal tool call
2. `simulator.js` generates 2–4 scenarios, runs them in parallel git worktrees
3. The best scenario is promoted back to the live workspace
4. The tool returns a summary to the agent, who continues the task

### 5.3 Recursion Guard

Simulation agents (running inside a worktree) **cannot** call `run_simulation` again:

```
❌ [RECURSION GUARD] Cannot call 'run_simulation' from within a subagent
   or simulation context (depth=2). Complete this subtask directly.
```

Depth is tracked via `process.env._SWADES_TOOL_DEPTH`.

### 5.4 Configuring Concurrency

```env
# .env
SIM_CONCURRENCY=3   # run 3 sandboxes at once (more CPU, faster results)
SIM_CONCURRENCY=1   # sequential (original behavior, lowest resource use)
```

### 5.5 Simulation Pipeline (unchanged, now faster)

```
Generate Scenarios (2–4)
        │
        ▼ (parallel, capped at SIM_CONCURRENCY)
┌──────────┬──────────┬──────────┐
│ Sandbox A│ Sandbox B│ Sandbox C│   ← concurrent git worktrees
│ agent run│ agent run│ agent run│
│ compile  │ compile  │ compile  │
│ test     │ test     │ test     │
└──────────┴──────────┴──────────┘
        │
        ▼
  LLM Verdict Selection
        │
        ▼
  Shadow Verification (separate worktree)
        │
        ▼
  git apply → Live Workspace
        │
        ▼
  Post-Promotion Build + Test
```

---

## Chapter 6: Parallel Subagents (spawn_subagents)

### 6.1 How it Works Now

**Before:** `--subagents` or `--sim` CLI flag triggered `runOrchestrated()` which called `evaluateComplexity()` and then spawned workers.

**After:** The agent calls `spawn_subagents` as a mid-flight tool call whenever it decides decomposition is appropriate:

```js
{
  "name": "spawn_subagents",
  "arguments": {
    "subtasks": [
      { "label": "auth-module", "description": "Create JWT auth middleware in src/middleware/auth.js" },
      { "label": "user-routes", "description": "Implement CRUD routes for users in src/routes/users.js" },
      { "label": "test-suite",  "description": "Write integration tests for both modules in tests/" }
    ],
    "reason": "Three independent workstreams that can be built in parallel without conflicts"
  }
}
```

What happens:
1. `runSubagentsParallel()` creates one isolated git worktree per subtask (in `/tmp/swades_worktrees/`)
2. Each subagent runs the full ReAct loop in its worktree, completely isolated
3. All diffs are captured with `git diff --cached HEAD`
4. `mergeDiffs()` applies each diff to the live workspace with `git apply --3way`
5. Conflicts spawn a dedicated merge-resolution subagent
6. The tool returns a merge summary to the calling agent

### 6.2 Subagent Semaphore

Parallel subagents are capped at 5 concurrent workers by the global `Semaphore` in `subagent.js`. This is separate from the simulation semaphore.

### 6.3 Worktree Location

Subagent worktrees live in OS temp dir, not your project:
```
/tmp/swades_worktrees/<project-hash>/<label>-<uuid>/
```

They are automatically cleaned up after `runSubagentsParallel` completes.

---

## Chapter 7: Director Escalation (delegate_to_director)

### 7.1 Mid-Flight Escalation

Previously, Director mode had to be started with `--autonomous`. Now the agent can escalate itself:

```js
{
  "name": "delegate_to_director",
  "arguments": {
    "goal": "Migrate the entire backend from Express to Fastify, update all tests, and verify no regressions",
    "reason": "Task scope has grown beyond the current step budget and requires multi-cycle planning"
  }
}
```

The Director AI then:
1. Reviews the current conversation history
2. Plans the next action on behalf of the user
3. Runs the worker agent for one cycle
4. Reviews progress and decides the next prompt
5. Repeats until `STATUS: COMPLETE`

### 7.2 Autonomous Mode via Flag

`--autonomous` still works as before but is now a chat-loop bootstrap:

```bash
node src/index.js "Build a full REST API" --autonomous
# → starts Director loop for the first task
# → drops into chat loop when Director finishes
```

---

## Chapter 8: State Checkpointing & Rewind

### 8.1 How Checkpoints Work

Before every state-mutating tool call (`write_file`, `patch_file`, `run_command`), the agent creates a lightweight git stash snapshot:

```js
// agent.js — before executing any mutating tool
const stashHash = await shell("git stash create", resolvedWorkdir);
if (stashHash) {
  checkpointStore.push({ step, stashHash, messagesSnapshot: deepClone(messages) });
}
```

- `git stash create` creates a stash object **without touching the working tree** — it's a pure snapshot, zero-cost for clean checkouts.
- Up to 10 checkpoints are kept in memory per session (FIFO).
- Both the **workspace files** and the **LLM message context** are snapshotted.

### 8.2 Rewinding

The agent can call the `rewind_to_checkpoint` tool to undo a bad change:

```js
{
  "name": "rewind_to_checkpoint",
  "arguments": { "step": 7 }
}
```

What happens:
1. `git read-tree --reset -u <stashHash>` restores all workspace files to the step 7 state
2. `process.env._SWADES_REWIND_STEP` is set to signal `agent.js`
3. `agent.js` detects the signal and splices the `messages` array back to the step 7 snapshot
4. The agent continues from a clean state as if step 7 just completed

**Manual rewind** (outside the agent):
```bash
# List available stash snapshots
git stash list

# Restore manually
git read-tree --reset -u <stash-hash>
```

---

## Chapter 9: Context Window Management

### 9.1 Two-Layer Compression

**Layer 1 — Server-side (OpenRouter):**
When using OpenRouter, the `context-compression` plugin automatically compresses older messages before they reach the model. This is transparent and free.

**Layer 2 — Local pruning (agent.js):**
After each step, if `messages.length > 40`, the agent compresses the middle of the conversation:

```js
function pruneContext(msgs) {
  if (msgs.length <= 40) return msgs;
  const systemMsgs = msgs.filter(m => m.role === "system");
  const recent = msgs.slice(-15);           // keep last 15
  const middle = msgs.slice(systemMsgs.length, msgs.length - 15);
  const summary = `[CONTEXT PRUNED: ${middle.length} older messages compressed...]`;
  return [...systemMsgs, { role: "user", content: summary }, ...recent];
}
```

The system prompt and last 15 messages are always preserved. The middle is collapsed to a single summary line.

**Console output:**
```
   🧹 Context pruned: 47 → 18 messages
```

### 9.2 Use `clear` in the Chat Loop

For completely unrelated follow-up work, type `clear` in the chat loop to wipe the session context entirely:

```
💬 → clear
  🧹 Context cleared — starting fresh.
```

---

## Chapter 10: Incremental Codebase Re-Indexing

### 10.1 What Changed

**Before:** `index_codebase` ran once at startup. If the agent wrote 10 files during the session, the index became stale — function names, exports, and imports were outdated.

**After:** Every `write_file` and `patch_file` call triggers a non-blocking incremental update for only the modified file:

```js
// tools.js — called after every write/patch
async function _updateIndexForFile(fullPath, content) {
  const index = JSON.parse(await readFile(indexPath, "utf-8"));
  const relPath = relative(workdir, fullPath);
  index.files[relPath] = { size: content.length, structure: parseFileStructure(...) };
  index.lastUpdated = new Date().toISOString();
  await writeFile(indexPath, JSON.stringify(index, null, 2), "utf-8");
}

// Called non-blocking so it never delays the tool response:
_updateIndexForFile(fullPath, content).catch(() => {});
```

The index stays 100% accurate throughout multi-file runs without the overhead of a full rescan.

---

## Chapter 11: Text-Only DOM Verification (verify_dom_state)

### 11.1 Why No Screenshots

Even when using a vision-capable model, screenshots are slow, token-heavy, and non-deterministic. A text assertion on the HTML is instant and 100% deterministic.

`verify_dom_state` fetches any URL over `node:http` or `node:https` (zero external dependencies) and runs structured text assertions against the raw HTML.

### 11.2 Assertion Syntax

| Assertion | Checks |
|---|---|
| `text:Submit` | Raw HTML contains the string `Submit` |
| `not-text:Error` | Raw HTML does NOT contain `Error` |
| `class:dark` | Any element has `class="...dark..."` |
| `element:#login-btn` | `id="login-btn"` is present |
| `element:.nav-item` | Element with class `nav-item` exists |
| `element:header` | `<header` tag is present |
| `attr:data-theme=dark` | Attribute `data-theme="dark"` is present |

### 11.3 Example Tool Call

```js
{
  "name": "verify_dom_state",
  "arguments": {
    "url": "http://localhost:3000",
    "assertions": [
      "class:dark",
      "element:#theme-toggle",
      "text:Dashboard",
      "not-text:Uncaught Error"
    ]
  }
}
```

Output:
```
✅ ALL ASSERTIONS PASSED
DOM Verification (http://localhost:3000): 4 passed, 0 failed

  ✅ PASS [class:dark] — Class 'dark' found
  ✅ PASS [element:#theme-toggle] — Element id='theme-toggle' found
  ✅ PASS [text:Dashboard] — Found 'Dashboard' in HTML
  ✅ PASS [not-text:Uncaught Error] — Confirmed 'Uncaught Error' absent from HTML
```

### 11.4 Single-Level Redirect Support

If the URL redirects (HTTP 3xx), the tool automatically follows one redirect. This handles common dev server setups that redirect `/` to `/app`.

---

## Chapter 12: CUA Mode — Strict Isolation

### 12.1 The Lockout

Desktop automation (CUA) is **completely invisible** to the agent unless the user explicitly passes `--cua`:

- No `gui_interact` tool appears in `TOOL_SCHEMAS`.
- The system prompt contains an explicit CUA lockout notice.
- `runCUA` is never imported or called in the chat loop path.
- Subagents and simulation agents are also CUA-blind.

```
CUA LOCKOUT (from system prompt):
- You do NOT have access to any GUI interaction, screenshot, mouse-click,
  or desktop automation tools.
- Desktop automation requires explicit --cua CLI flag from the user.
- Browser and UI verification MUST use the verify_dom_state tool.
```

### 12.2 Enabling CUA

The only way to enable CUA:
```bash
node src/index.js --cua "Open Chrome and navigate to the app"
```

This starts a separate CUA session. It does NOT drop into the chat loop afterward.

### 12.3 CUA Wayland Setup (Linux)

```bash
# Ubuntu/Debian
sudo apt install -y python3-gi python3-gi-cairo

# Fedora
sudo dnf install -y python3-gobject

# Arch
sudo pacman -S python-gobject
```

Enable in GNOME: **Settings → Sharing → Remote Desktop → On**

Verify D-Bus portals:
```bash
dbus-send --session --dest=org.freedesktop.DBus --type=method_call \
  --print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames \
  | grep Mutter
```

---

## Chapter 13: Timer, Urgency & Deadline System

The AI-estimated countdown timer is unchanged from v2.x and prevents infinite loops.

### 13.1 Visual Progress Bar

```
⏰ TIMER: 120s remaining / 180s [█████████████░░░░░░░] URGENCY: CALM
⏰ TIMER: 54s remaining / 180s  [██████░░░░░░░░░░░░░░] URGENCY: MEDIUM
⏰ TIMER: 18s remaining / 180s  [██░░░░░░░░░░░░░░░░░░] URGENCY: URGENT
⏰ TIMER: OVERTIME (5s overdue) / 180s [░░░░░░░░░░░░░░░░░░░░] URGENCY: OVERTIME
```

| Urgency | Threshold | Color |
|---|---|---|
| CALM | > 60% remaining | Green |
| MEDIUM | 30–60% remaining | Yellow |
| URGENT | 10–30% remaining | Red |
| PANIC | < 10% remaining | Bold red |
| OVERTIME | Expired | Inverted red |

### 13.2 Extending the Deadline

```js
{
  "name": "extend_deadline",
  "arguments": {
    "additional_seconds": 120,
    "reason": "npm install is taking longer than estimated"
  }
}
```

The agent gets 3 grace steps after entering OVERTIME before forced termination.

---

## Chapter 14: Self-Healing Linter & Syntax Validation

Every `write_file` and `patch_file` call triggers post-write validation:

1. **Bracket matching**: Detects and auto-appends missing `}`, `)`, `]` at EOF.
2. **JSON repair**: Removes trailing commas, wraps unquoted keys, normalizes single quotes.
3. **Indentation fix**: Converts mixed tab/space files to consistent indentation.
4. **Node.js check**: Runs `node --check` on every `.js`/`.mjs`/`.cjs` file.
5. **Python compile**: Runs `python3 -m py_compile` on `.py` files.

Output on success:
```
✅ File patched successfully: src/auth.js
```

Output with auto-fix:
```
✅ File written successfully: src/utils.js (1243 bytes)
⚠️ INDENTATION WARNINGS:
- Mixed spaces and tabs detected. Auto-fixed.
```

---

## Chapter 15: Background Process Management

When a shell command runs past 30 seconds, it detaches to the background.

### Checking output:
```
peek_terminal → action: "peek"
[STATUS: RUNNING] Process is still executing (PID 12345).
Recent output:
> Building... 45%
```

### Killing a stuck process:
```
peek_terminal → action: "kill"
✅ Sent SIGTERM to the active background process.
```

Logs are stored in `~/.cache/swades/<project-hash>/agent_terminal.log`.

---

## Chapter 16: Memory & Session Persistence

The agent writes a memory file after each completed task:

- **Location**: `~/.cache/swades/<project-hash>/agent_memory.json`
- **Content**: Last 10 sessions with task summary, result, and tools used
- **Injected as**: `## MEMORY — Previous Sessions` block in the system prompt

This means the agent remembers what it built in your project across **different sessions** — not just within the current chat loop.

---

## Chapter 17: Fallback Model Cascade

If the primary model returns a retryable error (429, 402, 403, 503, "No endpoints found"), the agent automatically tries the next model in `FALLBACK_MODELS`:

```env
FALLBACK_MODELS=claude-3-haiku,gpt-4o-mini,openrouter/free
```

Max 4 total attempts. On each retry:
```
   ⚡ Fallback attempt 2/4: trying claude-3-haiku...
```

---

## Chapter 18: Full Tool Reference

| Tool | Description |
|---|---|
| `read_file` | Read file with line numbers, optional range |
| `write_file` | Create a new file (use only for new files) |
| `patch_file` | Surgical text replacement in existing file |
| `list_dir` | List directory contents (skips node_modules, .git) |
| `run_command` | Execute shell command (30s timeout, then detaches) |
| `grep_search` | Regex search across files |
| `index_codebase` | Full codebase scan → `agent_index.json` |
| `peek_terminal` | Check/kill active background process |
| `extend_deadline` | Add seconds to the current task timer |
| `run_simulation` | Spawn parallel sandbox scenarios, promote winner |
| `spawn_subagents` | Parallel subagents in isolated worktrees, auto-merge |
| `delegate_to_director` | Escalate to Director AI for multi-cycle planning |
| `verify_dom_state` | Text-only DOM assertions via HTTP fetch |
| `rewind_to_checkpoint` | Restore workspace + context to a prior step |

---

## Chapter 19: Troubleshooting

#### The agent won't use `run_simulation` automatically
The agent decides on its own. If you want to force it, say: *"Use run_simulation to test two approaches for this."*

#### Stale git worktrees after Ctrl+C
```bash
git worktree prune
rm -rf /tmp/swades_worktrees
```

#### verify_dom_state returns 'Failed to fetch'
The dev server must be running and reachable. Start it first with `run_command`, wait for it to be ready, then verify.

#### Context is getting confused across tasks
Type `clear` in the chat loop to wipe the session history.

#### Rewind isn't available
Checkpoints require git to be initialized in the workspace. Run `git init && git add . && git commit -m "init"` first.

#### `run_simulation` fails with "not a git repository"
The simulator auto-initializes git if needed. If it still fails, commit your files: `git add . && git commit -m "WIP"`.

---

## Chapter 20: CI/CD Integration

Swades runs headlessly in GitHub Actions or any CI runner.

```yaml
# .github/workflows/swades-autofix.yml
name: Swades Auto-Fix
on: [pull_request]

jobs:
  auto-fix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with: { node-version: '22' }
      - run: npm ci
      - run: npm test || echo "TESTS_FAILED=true" >> $GITHUB_ENV
      - name: Run Swades to fix failures
        if: env.TESTS_FAILED == 'true'
        env:
          API_KEY: ${{ secrets.OPENROUTER_KEY }}
          MAX_STEPS: "20"
        run: |
          echo "Fix all test failures in the test suite. Read the failing tests, identify root cause, patch the relevant source files, and verify tests pass." \
          | node src/index.js --autonomous
      - name: Commit fixes
        run: |
          git config --global user.name "Swades Bot"
          git commit -am "chore: auto-fixed test failures" || true
          git push || true
```

> [!WARNING]
> Never use `--cua` in CI — there is no display server in standard runners.

Set `MAX_STEPS=20` in CI to cap token spend.

---

## Chapter 21: Advanced Prompting

### Forcing specific tools
> "Use `run_simulation` to compare a Redis-based cache vs an in-memory LRU. Promote whichever has cleaner test results."

### Parallel workstreams
> "Split this into three subagents: one for the API routes, one for the database models, one for the test suite. Use `spawn_subagents` to run them in parallel."

### Verification-first workflow
> "After applying the dark mode changes, call `verify_dom_state` on http://localhost:3000 and assert that `class:dark` is present on the html element."

### Rewind on bad output
> "The last patch broke the build. Use `rewind_to_checkpoint` to undo it and try a different approach."

### Multi-constraint framing
> "Refactor `src/auth.js` to use JWT. Do NOT add any new npm dependencies. After patching, run `node --check src/auth.js` to verify syntax, then run `npm test` to ensure zero regressions."

---

*Swades Agent v3.0 — Unified Execution Engine, Persistent Chat Loop, Modes-as-Tools*
