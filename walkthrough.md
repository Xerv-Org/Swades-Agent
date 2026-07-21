# Swades Agent v3.1: The Ultimate Operational Developer Manual & Tutorial

---

## Chapter 1: Introduction & Operational Philosophy

Swades Agent is a terminal-native, autonomous software engineering agent designed to run directly within your codebase. Unlike web-based coding assistants that operate in isolated clouds or require copying and pasting code, Swades Agent executes commands directly in your local environment, making surgical file edits, running shell tasks, and managing background services.

### 1.1 Developer Experience (DX) Philosophy
Swades Agent is built to behave like a human engineer working inside a terminal:
- **Think-Before-Write**: Before making code edits, the agent analyzes file imports, functions, and layout structures to avoid syntax corruption.
- **Strict Verification Gates**: Modified files are validated at write-time. The linter automatically repairs unclosed brackets, formatting, or JSON syntax issues before the compiler executes.
- **Asynchronous Execution**: Long-running tests, server builds, or package installs run in detached background terminals, keeping the main CLI loop responsive.
- **Time and Cost Safety**: The agent estimates a time budget at startup. It monitors a visual countdown timer and can request deadline extensions to prevent infinite execution loops.

---

## Chapter 2: System Installation & Configuration

Follow this checklist to configure Swades Agent inside your workspace.

### 2.1 Runtime Prerequisites
- **Node.js**: Version 18.0.0 or later is required (v22.x or later is recommended).
- **Git**: Version 2.30 or later is required to run subagents and sandbox simulations.
- **System Check**:
  ```bash
  node -v
  npm -v
  git --version
  ```

### 2.2 Project Setup
Clone or copy the Swades Agent directory into your target workspace, then execute:
```bash
npm install
```
This command installs the three core NPM modules locally:
- `openai`: Manages communication with OpenAI-compatible API endpoints and parses SSE token streams.
- `dotenv`: Loads environment configurations from your local `.env` file into `process.env`.
- `chalk`: Formats and color-codes terminal logs (e.g. countdown bars, tool indicators, errors).

---

### 2.3 Comprehensive `.env` Variable Reference

Create your environment configuration file:
```bash
cp .env.example .env
```

Open `.env` in a text editor to configure the parameters below.

| Variable Name | Required | Default Value | Description |
|---|---|---|---|
| `API_KEY` | **Yes** | `(None)` | Your LLM provider API key (e.g. OpenRouter, OpenAI, Groq, local gateways). |
| `BASE_URL` | No | `https://openrouter.ai/api/v1` | The HTTP endpoint for API requests. |
| `MODEL` | No | `openrouter/free` | The primary model used to handle task planning and code editing. |
| `CUA_MODEL` | No | `openrouter/free` | The vision-capable model used to analyze desktop screenshots in CUA mode. |
| `MAX_STEPS` | No | `Infinity` | Max steps allowed per ReAct worker run. |
| `MAX_OUTPUT_LENGTH`| No | `10000` | Character limit on stdout/stderr outputs returned to the LLM. |
| `WORKDIR` | No | `process.cwd()` | Target directory for file operations. Set to `../` if the agent is installed as a subfolder in your project. |
| `GOOGLE_MAPS_API_KEY`| No | `(None)` | Optional key for Google Maps Platform Directions API. |

---

### 2.4 LLM Provider Setup Profiles

#### Profile A: OpenRouter Setup (Cloud Model API)
```env
API_KEY=sk-or-v1-your-openrouter-key-here
BASE_URL=https://openrouter.ai/api/v1
MODEL=meta-llama/llama-3.3-70b-instruct
```

#### Profile B: OpenAI Setup
```env
API_KEY=sk-proj-your-openai-key-here
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o
```

#### Profile C: Groq Setup
```env
API_KEY=gsk_your-groq-key-here
BASE_URL=https://api.groq.com/openai/v1
MODEL=llama-3.3-70b-versatile
```

#### Profile D: Local Ollama Setup (Offline/Private)
Ensure Ollama is running (`ollama serve`) and the model is pulled (`ollama pull qwen2.5-coder:7b`):
```env
API_KEY=ollama
BASE_URL=http://localhost:11434/v1
MODEL=qwen2.5-coder:7b
```

---

## Chapter 3: The Command Interface (Modes & Syntax)

You can launch tasks interactively or pass prompts directly as command-line arguments.

### 3.1 Interactive Dashboard Mode
Run the command:
```bash
npm start
```
The terminal will display the configuration menu:
1. **Task →**: Enter your prompt (e.g. *"create a basic express app in src/server.js"*).
2. **Image path/URL (optional) →**: Provide a path or web URL to a layout image/mockup if you are using a vision-capable model.
3. **Mode? →**: Select your execution mode:
   - `c` (or `cua`): Desktop GUI automation.
   - `a` (or `autonomous`): Director-supervised multi-cycle development loops.
   - `s` (or `subagents`): Runs task decomposition in parallel workspaces.
   - `n` (or `normal`): Single-run worker loop.
   - Press **Enter** to let the AI auto-classify task complexity.

---

### 3.2 CLI Mode Flags
Pass your task as a string and add the appropriate flags:

#### Normal Mode
Used for quick, single-step tasks:
```bash
node src/index.js "Check for syntax errors in src/database.js" --normal
```

#### Autonomous Director Mode
Used for complex features requiring multiple test/implementation cycles:
```bash
node src/index.js "Write unit tests for auth.js, run them, and fix any failures" --autonomous
```

#### CUA Mode (Computer Use Agent)
Spawns Wayland GUI mode to open a web browser or desktop app:
```bash
node src/index.js "Open Chrome and search for Node.js docs" --cua
```

#### Subagents Mode
Bypasses the simulation engine to run task decomposition in parallel workspaces:
```bash
node src/index.js "Refactor src/api/ and src/utils/ folders to ES modules" --subagents
```

#### Passing Images
Pass local or web image URLs directly to the agent:
```bash
node src/index.js "Analyze this layout and implement it in index.html" --image mockups/design.png
```

---

## Chapter 4: Dynamic Timer & Urgency Pressure System

The countdown timer manager prevents the agent from getting stuck in infinite loops.

### 4.1 Understanding the Visual Progress Bar
At each step of the ReAct loop, a countdown timer is rendered to the terminal. Watch the bar colors to monitor progress:

* **[CALM]** (Green Bar, `remaining > 60%`): Safe workspace, focus on clean and complete code.
  ```
  ⏰ TIMER: 120s remaining / 120s [████████████████████] URGENCY: CALM
  ```
* **[MEDIUM]** (Yellow Bar, `remaining 30%-60%`): Ticking timer, keep edits structured.
  ```
  ⏰ TIMER: 58s remaining / 120s [██████████░░░░░░░░░░] URGENCY: MEDIUM
  ```
* **[URGENT]** (Red Bar, `remaining 10%-30%`): Time is low, skip non-essential steps.
  ```
  ⏰ TIMER: 22s remaining / 120s [████░░░░░░░░░░░░░░░░] URGENCY: URGENT
  ```
* **[PANIC]** (Bold Red Bar, `remaining < 10%`): Finish immediately, skip cleanup.
  ```
  ⏰ TIMER: 8s remaining / 120s [█░░░░░░░░░░░░░░░░░░░] URGENCY: PANIC
  ```
* **[OVERTIME]** (Inverted Red Bar, `remaining <= 0`): System is running overdue.
  ```
  ⏰ TIMER: OVERTIME (12s overdue) / 120s [░░░░░░░░░░░░░░░░░░░░] URGENCY: OVERTIME
  ```

---

### 4.2 Overtime Grace Ticks & Forced Termination
If the agent enters **OVERTIME**, a warning is injected into its prompt:
`🚨 DEADLINE EXPIRED: You are running in OVERTIME! Wrap up or request an extension.`
- The agent gets a strict **limit of 3 steps** in overtime.
- If it doesn't finish or request an extension, the system triggers a **forced loop-prevention termination** to save token costs.

### 4.3 How to Instruct the Agent to Extend the Timer
If you anticipate that a task is complex or requires installing software, you can prompt the agent to manage its time budget directly:
> *"Implement feature X and run the build tests. If you run low on time, make sure to call the extend_deadline tool to add 120 seconds."*

The agent will invoke the tool:
```json
{
  "name": "extend_deadline",
  "arguments": {
    "additional_seconds": 120,
    "reason": "Compiling libraries is taking longer than expected"
  }
}
```
This resets the timers and returns the agent to a CALM state.

---

## Chapter 5: The Self-Healing Linter & Indentation Rules

When the agent writes files, syntax guardrails prevent code corruption.

### 5.1 Reading Linter Reports
On every save or patch, the linter prints validation outputs to the console:
- **`✅ File written successfully`**: Indicates zero syntax or indentation errors.
- **`❌ WARNING: SYNTAX ERRORS DETECTED`**: Lists JavaScript compile errors (`node --check`), bracket mismatch lines, or JSON parser errors.
- **`⚠️ INDENTATION WARNINGS`**: Informs the agent of inconsistent tab/space patterns or sudden indentation jumps (jumps > 4 spaces without a block opening character like `{`, `(`, `[`, or `:`).

### 5.2 Self-Healing Logic
You do not need to intervene if the agent makes a bracket error. The linter's auto-fixer will:
1. Parse bracket structures and append missing closing brackets at EOF.
2. Format mixed spaces/tabs automatically.
3. Clean JSON trailing commas and wrap unquoted keys in double quotes.

If successful, the linter writes the corrected content and prints:
`✅ File written and automatically auto-fixed syntax errors.`

### 5.3 Strict vs Cosmetic Indentation Languages
Indentation warnings are only enabled for indentation-sensitive files:
- **Strict Indentation**: Python (`.py`) and YAML (`.yml`, `.yaml`).
- **Cosmetic Indentation**: JavaScript, CSS, HTML, Markdown, and configuration files skip indentation warnings.

---

## Chapter 6: Background Process Management (`peek_terminal`)

If a command takes longer than 30 seconds (e.g. running a compile step or dev server), the agent detaches the task to run in the background.

### 6.1 Checking Background Process Logs
If a task detaches, you can instruct the agent to poll the output using `peek_terminal`:
> *"Run npm run build. If it detaches, wait 10 seconds and peek at the terminal log to confirm it compiled successfully."*

The agent calls `peek_terminal` with the default `peek` action:
- **`[STATUS: RUNNING]`**: The background task is still executing. The agent reads the tail of `.agent_terminal.log` to view recent output.
- **`[STATUS: COMPLETED]`**: The background process finished. The agent reads the final logs and handles success/error codes.

### 6.2 Terminating Stuck Processes
If a background server or test loop gets stuck:
1. Prompt the agent: *"Kill the background process immediately using peek_terminal with the kill action."*
2. The agent executes `peek_terminal` with `action: "kill"`.
3. This sends `SIGTERM` to the process group, releasing system resources.

---

## Chapter 7: Wayland Native GUI (CUA Mode) Setup

CUA mode allows the agent to control your desktop. For safety under modern Linux installations, set up the following:

### Step 1: Install Introspector Packages
Wayland CUA requires system GObject libraries to communicate over the Mutter remote desktop bus:

* **Ubuntu / Debian**:
  ```bash
  sudo apt update && sudo apt install -y python3-gi python3-gi-cairo
  ```
* **Fedora**:
  ```bash
  sudo dnf install -y python3-gobject python3-gobject-base
  ```
* **Arch Linux**:
  ```bash
  sudo pacman -S --noconfirm python-gobject
  ```

### Step 2: Enable Remote Sharing
In your GNOME desktop settings, navigate to:
**Settings** -> **Sharing** -> **Remote Desktop**
Turn on **Remote Desktop** and **Screen Sharing**.

### Step 3: Run the Portals Check Command
Ensure the Mutter desktop interfaces are available on the active D-Bus session:
```bash
dbus-send --session --dest=org.freedesktop.DBus --type=method_call --print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames | grep Mutter
```
You should see:
- `org.gnome.Mutter.RemoteDesktop`
- `org.gnome.Mutter.ScreenCast`

### Step 4: Spatial Click Protection Limits
To prevent click loops:
- **Proximity Bounding Box**: If the agent clicks inside a **25px horizontally and 15px vertically** bounding box of the previous click consecutively, the system blocks the action.
- **Click Limit**: The agent is blocked if it clicks the same coordinate area more than **2 times overall** in a single run.
- **Agent Response**: The tool returns a declined message, forcing the model to scroll, type, or navigate elsewhere.

---

## Chapter 8: Subagents & Sandbox Simulations

For complex refactoring, Swades Agent orchestrates multiple tasks in isolated workspaces.

### 8.1 Monitoring Parallel Subagents
When a task is classified as high-complexity:
1. The parent orchestrator breaks down the main prompt into subtasks.
2. It sets up git worktrees under `.swades_worktrees/`.
3. Subagents run parallel modifications. You can watch progress outputs from all subagents concurrently.
4. Git merge conflicts are resolved dynamically by a merge-resolution agent.

### 8.2 Sandbox Simulation Engine
Before applying modifications to your live workspace files, the engine generates alternative scenarios:
1. It copies project code to scenario sandboxes under `.swades_sandboxes/`.
2. It compiles the code and runs test suites inside each sandbox.
3. The LLM evaluates the results, selects the winner, and promotes the winning diff to your workspace.
4. Telemetry logs containing comparisons are saved to `.swades_simulation_report.json`.

---

## Chapter 9: Troubleshooting & FAQ

#### Q: The agent gets stuck in a loop trying to patch a file.
* **Solution**: Ensure your target block matches the file content exactly. You can read the target file using `read_file` with a line range to confirm its indentation.

#### Q: I hit a timeout when installing packages.
* **Solution**: Detached package installations run in the background. Prompt the agent: *"Call peek_terminal to verify the package installation completed."*

#### Q: How do I change the default time limit?
* **Solution**: Set `MAX_STEPS` in your `.env` file to limit the steps, or use `extend_deadline` to adjust timing.

#### Q: The agent fails to connect to the model.
* **Solution**: Double-check your `API_KEY` and `BASE_URL` settings in `.env`. If using local models, ensure Ollama is running (`ollama run qwen2.5-coder:7b`).
