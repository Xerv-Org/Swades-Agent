// ============================================================
// tools.js — Tool implementations (the agent's "hands")
// ============================================================

import { readFile, writeFile, mkdir, readdir, stat, appendFile } from "node:fs/promises";
import { exec, spawn } from "node:child_process";
import { resolve, relative, dirname } from "node:path";
import { createInterface } from "node:readline";
import { existsSync } from "node:fs";

// Dangerous command patterns that require user confirmation
const DANGEROUS_PATTERNS = [
  "rm -rf",
  "rm -r",
  "sudo ",
  "kill ",
  "mkfs",
  "> /dev/",
  "dd if=",
  "chmod 777",
  ":(){",
  "format ",
];

let activeBgProcess = null;
let activeBgPid = null;
let activeBgLogPath = null;

export let activeDeadline = {
  estimatedSeconds: 180,
  startTime: Date.now()
};

function isProcessAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return false;
  }
}

// ---- Helpers ----

function getWorkdir() {
  const dir = process.env.WORKDIR || process.cwd();
  return existsSync(dir) ? dir : process.cwd();
}

function resolvePath(p) {
  if (!p) return getWorkdir();
  return resolve(getWorkdir(), p);
}

function truncate(str, maxLen) {
  const max = maxLen || parseInt(process.env.MAX_OUTPUT_LENGTH) || 10000;
  if (str.length <= max) return str;
  const half = Math.floor(max / 2);
  return (
    str.slice(0, half) +
    `\n\n... [truncated ${str.length - max} characters] ...\n\n` +
    str.slice(-half)
  );
}

async function confirm(message) {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => {
    rl.question(`${message} (y/N): `, (answer) => {
      rl.close();
      res(answer.toLowerCase() === "y");
    });
  });
}

// ---- Heuristic Syntax & Indentation Checker ----

function fixUnclosedBrackets(content) {
  const lines = content.split("\n");
  const brackets = { "{": "}", "(": ")", "[": "]" };
  const stack = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let inString = false;
    let stringChar = "";
    for (let col = 0; col < line.length; col++) {
      const char = line[col];
      if ((char === '"' || char === "'" || char === "`") && line[col - 1] !== "\\") {
        if (!inString) {
          inString = true;
          stringChar = char;
        } else if (stringChar === char) {
          inString = false;
        }
      }
      if (!inString) {
        if (char === "{" || char === "(" || char === "[") {
          stack.push(char);
        } else if (char === "}" || char === ")" || char === "]") {
          stack.pop();
        }
      }
    }
  }
  if (stack.length > 0) {
    let appendStr = "";
    while (stack.length > 0) {
      const open = stack.pop();
      appendStr += brackets[open];
    }
    return content + (content.endsWith("\n") ? "" : "\n") + appendStr;
  }
  return content;
}

function fixJson(content) {
  let fixed = content;
  // 1. Remove trailing commas
  fixed = fixed.replace(/,(\s*[\]}])/g, "$1");
  // 2. Wrap unquoted keys in double quotes
  fixed = fixed.replace(/(?<={|,)\s*([a-zA-Z0-9_$]+)\s*:/g, '"$1":');
  // 3. Replace single quotes around keys/values with double quotes
  try {
    JSON.parse(fixed);
    return fixed;
  } catch (e) {
    let fixed2 = fixed.replace(/'([^']*)'/g, '"$1"');
    try {
      JSON.parse(fixed2);
      return fixed2;
    } catch (e2) {
      return fixed;
    }
  }
}

function fixMixedIndentation(content) {
  const lines = content.split("\n");
  let spaceLines = 0;
  let tabLines = 0;
  for (const line of lines) {
    const leading = line.match(/^([ \t]+)/);
    if (leading) {
      if (leading[1].includes(" ")) spaceLines++;
      if (leading[1].includes("\t")) tabLines++;
    }
  }
  if (spaceLines > 0 && tabLines > 0) {
    if (spaceLines >= tabLines) {
      return lines.map(line => {
        const leading = line.match(/^([ \t]+)/);
        if (leading) {
          const cleanLeading = leading[1].replace(/\t/g, "    ");
          return cleanLeading + line.slice(leading[0].length);
        }
        return line;
      }).join("\n");
    } else {
      return lines.map(line => {
        const leading = line.match(/^([ \t]+)/);
        if (leading) {
          const cleanLeading = leading[1].replace(/    /g, "\t").replace(/  /g, "\t");
          return cleanLeading + line.slice(leading[0].length);
        }
        return line;
      }).join("\n");
    }
  }
  return content;
}

function checkSyntaxAndIndentation(filePath, content) {
  const ext = filePath.split(".").pop().toLowerCase();
  const errors = [];
  const warnings = [];
  const lines = content.split("\n");

  const isIndentationSensitive = ["py", "yml", "yaml", "gd", "nim", "hs"].includes(ext);

  if (isIndentationSensitive) {
    // 1. Indentation mix check (spaces vs tabs) & Indentation jump check
    let hasSpaces = false;
    let hasTabs = false;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const leading = line.match(/^([ \t]+)/);
      if (leading) {
        if (leading[1].includes(" ")) hasSpaces = true;
        if (leading[1].includes("\t")) hasTabs = true;

        // Indentation jump checks (spaces only for simplicity)
        if (hasSpaces && !hasTabs) {
          const spaceCount = leading[1].length;
          if (i > 0) {
            const prevLine = lines[i - 1];
            const prevLeading = prevLine.match(/^([ ]+)/);
            if (prevLeading) {
              const prevCount = prevLeading[1].length;
              const diff = spaceCount - prevCount;
              // Alert on sudden jumps greater than 4 spaces without brace/colon opening
              if (
                diff > 4 &&
                !prevLine.trim().endsWith("{") &&
                !prevLine.trim().endsWith(":") &&
                !prevLine.trim().endsWith("(") &&
                !prevLine.trim().endsWith("[")
              ) {
                warnings.push(`Line ${i + 1}: Indentation jumped suddenly by ${diff} spaces without a block opening character ({, :, (, [).`);
              }
            }
          }
        }
      }
    }

    if (hasSpaces && hasTabs) {
      warnings.push("Mixed spaces and tabs detected in file indentation. Use either spaces or tabs consistently.");
    }
  }

  // 2. Bracket matching checks (curly braces, parentheses, square brackets)
  const brackets = {
    "{": "}",
    "(": ")",
    "[": "]",
  };
  const stack = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let inString = false;
    let stringChar = "";
    
    for (let col = 0; col < line.length; col++) {
      const char = line[col];
      // Skip strings to avoid matching quotes/braces inside literals
      if ((char === '"' || char === "'" || char === "`") && line[col - 1] !== "\\") {
        if (!inString) {
          inString = true;
          stringChar = char;
        } else if (stringChar === char) {
          inString = false;
        }
      }

      if (!inString) {
        if (char === "{" || char === "(" || char === "[") {
          stack.push({ char, line: i + 1, col: col + 1 });
        } else if (char === "}" || char === ")" || char === "]") {
          const last = stack.pop();
          if (!last) {
            errors.push(`Unmatched closing bracket '${char}' at line ${i + 1}:${col + 1}`);
          } else if (brackets[last.char] !== char) {
            errors.push(`Mismatched bracket: expected '${brackets[last.char]}' for '${last.char}' from line ${last.line}:${last.col}, but found '${char}' at line ${i + 1}:${col + 1}`);
          }
        }
      }
    }
  }

  while (stack.length > 0) {
    const unclosed = stack.pop();
    errors.push(`Unclosed bracket '${unclosed.char}' opened at line ${unclosed.line}:${unclosed.col}`);
  }

  return { errors, warnings };
}

// Perform active checks (Node check for JS, JSON.parse for JSON) and auto-fix if needed
async function performPostWriteValidation(fullPath, content) {
  const ext = fullPath.split(".").pop().toLowerCase();
  
  // 1. Run initial checks
  let heuristics = checkSyntaxAndIndentation(fullPath, content);
  let isJsonValid = true;
  if (ext === "json") {
    try {
      JSON.parse(content);
    } catch (err) {
      isJsonValid = false;
      heuristics.errors.push(`JSON Parsing Error: ${err.message}`);
    }
  }

  // 2. If errors/warnings detected, try to auto-fix
  if (heuristics.errors.length > 0 || heuristics.warnings.length > 0) {
    let fixedContent = content;
    let didChange = false;

    // Apply JSON fixes if needed
    if (ext === "json" && !isJsonValid) {
      const maybeFixed = fixJson(content);
      if (maybeFixed !== content) {
        fixedContent = maybeFixed;
        didChange = true;
      }
    }

    // Apply bracket fixes for JS/JSON etc if unclosed brackets exist
    const hasUnclosedBracket = heuristics.errors.some(e => e.includes("Unclosed bracket"));
    if (hasUnclosedBracket && ["js", "json", "ts", "jsx", "tsx", "css", "html"].includes(ext)) {
      const maybeFixed = fixUnclosedBrackets(fixedContent);
      if (maybeFixed !== fixedContent) {
        fixedContent = maybeFixed;
        didChange = true;
      }
    }

    // Apply indentation fixes for mixed indentation
    const hasMixedIndentation = heuristics.warnings.some(w => w.includes("Mixed spaces and tabs"));
    if (hasMixedIndentation) {
      const maybeFixed = fixMixedIndentation(fixedContent);
      if (maybeFixed !== fixedContent) {
        fixedContent = maybeFixed;
        didChange = true;
      }
    }

    // 3. If we updated the content, write it back and re-run checks
    if (didChange) {
      try {
        await writeFile(fullPath, fixedContent, "utf-8");
        // Recheck
        heuristics = checkSyntaxAndIndentation(fullPath, fixedContent);
        if (ext === "json") {
          try {
            JSON.parse(fixedContent);
          } catch (err) {
            heuristics.errors.push(`JSON Parsing Error (post-fix): ${err.message}`);
          }
        }
        heuristics.autoFixed = true;
      } catch (err) {
        heuristics.errors.push(`Auto-fix write error: ${err.message}`);
      }
    }
  }

  // Node check for JS files
  if (ext === "js" || ext === "mjs" || ext === "cjs") {
    // Read the current file on disk (it might have been auto-fixed)
    let currentContent = content;
    try {
      currentContent = await readFile(fullPath, "utf-8");
    } catch (e) {}

    const errorMsg = await new Promise((res) => {
      exec(`node --check "${fullPath}"`, (err, stdout, stderr) => {
        if (err) res(stderr.trim() || err.message);
        else res(null);
      });
    });
    if (errorMsg) {
      // If we haven't tried fixing unclosed brackets yet, let's try it
      const hasUnclosedBracket = errorMsg.includes("missing }") || errorMsg.includes("unexpected end of input") || errorMsg.includes("missing )") || errorMsg.includes("missing ]");
      if (hasUnclosedBracket && !heuristics.autoFixed) {
        const maybeFixed = fixUnclosedBrackets(currentContent);
        if (maybeFixed !== currentContent) {
          try {
            await writeFile(fullPath, maybeFixed, "utf-8");
            const secondCheckError = await new Promise((res) => {
              exec(`node --check "${fullPath}"`, (err, stdout, stderr) => {
                if (err) res(stderr.trim() || err.message);
                else res(null);
              });
            });
            if (!secondCheckError) {
              heuristics.autoFixed = true;
              // Clear previous JS/Node syntax errors
              heuristics.errors = heuristics.errors.filter(e => !e.includes("Node.js Syntax Error"));
            } else {
              heuristics.errors.push(`Node.js Syntax Error (post-fix):\n${secondCheckError}`);
            }
          } catch (e) {}
        } else {
          heuristics.errors.push(`Node.js Syntax Error:\n${errorMsg}`);
        }
      } else {
        heuristics.errors.push(`Node.js Syntax Error:\n${errorMsg}`);
      }
    }
  }

  return heuristics;
}

// ---- Codebase Indexing Engine ----

function parseFileStructure(filename, content) {
  const ext = filename.split(".").pop().toLowerCase();
  const structure = {
    imports: [],
    exports: [],
    classes: [],
    functions: [],
  };

  const lines = content.split("\n");

  if (["js", "mjs", "cjs", "ts", "tsx", "jsx"].includes(ext)) {
    for (const line of lines) {
      // Parse imports
      const importMatches = [...line.matchAll(/import\s+.*\s+from\s+['"](.*)['"]/g)];
      for (const m of importMatches) structure.imports.push(m[1]);

      // Parse classes
      const classMatches = [...line.matchAll(/class\s+(\w+)/g)];
      for (const m of classMatches) structure.classes.push(m[1]);

      // Parse functions
      const funcMatches = [...line.matchAll(/(?:function\s+(\w+)|const\s+(\w+)\s*=\s*\([^)]*\)\s*=>)/g)];
      for (const m of funcMatches) structure.functions.push(m[1] || m[2]);

      // Parse exports
      const exportMatches = [...line.matchAll(/export\s+(?:default\s+)?(?:const|class|function|let|var)?\s*(\w+)/g)];
      for (const m of exportMatches) {
        if (m[1] && !["const", "class", "function", "let", "var", "default"].includes(m[1])) {
          structure.exports.push(m[1]);
        }
      }
    }
  } else if (ext === "py") {
    for (const line of lines) {
      const classMatch = line.match(/^class\s+(\w+)/);
      if (classMatch) structure.classes.push(classMatch[1]);

      const defMatch = line.match(/^\s*def\s+(\w+)/);
      if (defMatch) structure.functions.push(defMatch[1]);
    }
  }

  // Deduplicate and filter empty strings
  structure.imports = [...new Set(structure.imports)].filter(Boolean);
  structure.exports = [...new Set(structure.exports)].filter(Boolean);
  structure.classes = [...new Set(structure.classes)].filter(Boolean);
  structure.functions = [...new Set(structure.functions)].filter(Boolean);

  return structure;
}

async function generateCodebaseIndex() {
  const workdir = getWorkdir();
  const index = {
    generatedAt: new Date().toISOString(),
    files: {},
  };

  async function scan(dir) {
    const items = await readdir(dir, { withFileTypes: true });
    for (const item of items) {
      if (
        item.name === "node_modules" ||
        item.name === ".git" ||
        item.name === ".agent_index.json" ||
        item.name === ".agent_memory.json"
      ) {
        continue;
      }
      const fullPath = resolve(dir, item.name);
      const relPath = relative(workdir, fullPath);

      if (item.isDirectory()) {
        await scan(fullPath);
      } else {
        const info = await stat(fullPath);
        // Only index text-like source files under 1MB
        const ext = item.name.split(".").pop().toLowerCase();
        const textExtensions = ["js", "jsx", "ts", "tsx", "py", "json", "html", "css", "md", "sh", "yml", "yaml", "env"];
        
        if (info.size < 1024 * 1024 && textExtensions.includes(ext)) {
          const content = await readFile(fullPath, "utf-8");
          const structure = parseFileStructure(item.name, content);
          index.files[relPath] = {
            size: info.size,
            structure,
          };
        }
      }
    }
  }

  await scan(workdir);
  await writeFile(resolve(workdir, ".agent_index.json"), JSON.stringify(index, null, 2), "utf-8");
  return index;
}

// ---- Tool Implementations ----

async function readFileTool({ path, start_line, end_line }) {
  const fullPath = resolvePath(path);
  const content = await readFile(fullPath, "utf-8");

  if (start_line || end_line) {
    const lines = content.split("\n");
    const start = (start_line || 1) - 1;
    const end = end_line || lines.length;
    const sliced = lines.slice(start, end);
    return sliced.map((line, i) => `${start + i + 1} | ${line}`).join("\n");
  }

  // Add line numbers
  return content
    .split("\n")
    .map((line, i) => `${i + 1} | ${line}`)
    .join("\n");
}

async function writeFileTool({ path, content }) {
  const fullPath = resolvePath(path);
  await mkdir(dirname(fullPath), { recursive: true });
  
  // Write content first
  await writeFile(fullPath, content, "utf-8");

  // Validate syntax and indentation
  const validation = await performPostWriteValidation(fullPath, content);
  
  let report = `✅ File written successfully: ${path} (${content.length} bytes)`;
  if (validation.errors.length > 0) {
    report += `\n\n❌ WARNING: SYNTAX ERRORS DETECTED:\n- ` + validation.errors.join("\n- ");
  }
  if (validation.warnings.length > 0) {
    report += `\n\n⚠️ INDENTATION WARNINGS:\n- ` + validation.warnings.join("\n- ");
  }
  return report;
}

async function patchFileTool({ path, target, replacement }) {
  const fullPath = resolvePath(path);
  if (!existsSync(fullPath)) {
    return `❌ Error: File does not exist at path: ${path}. Use write_file to create new files.`;
  }

  const content = await readFile(fullPath, "utf-8");
  
  // Normalize line endings and trim trailing spaces for robust matching
  const normalize = (str) => str.replace(/\r\n/g, "\n").replace(/[ \t]+$/gm, "");
  const normalizedContent = normalize(content);
  const normalizedTarget = normalize(target);
  
  const occurrences = normalizedContent.split(normalizedTarget).length - 1;
  
  if (occurrences === 0) {
    return `❌ Error: Target block not found in the file. Ensure your 'target' content matches the file EXACTLY (including indentation and casing).`;
  }
  if (occurrences > 1) {
    return `❌ Error: Multiple matches (${occurrences}) of the target block were found. Provide more surrounding lines (context) to make the target block unique.`;
  }

  // Perform single replacement
  const newContent = normalizedContent.replace(normalizedTarget, normalize(replacement));
  
  // Write to disk
  await writeFile(fullPath, newContent, "utf-8");

  // Validate syntax and indentation
  const validation = await performPostWriteValidation(fullPath, newContent);
  
  let report = `✅ File patched successfully: ${path}`;
  if (validation.errors.length > 0) {
    report += `\n\n❌ WARNING: SYNTAX ERRORS DETECTED IN THE NEW PATCH:\n- ` + validation.errors.join("\n- ");
  }
  if (validation.warnings.length > 0) {
    report += `\n\n⚠️ INDENTATION WARNINGS DETECTED IN THE NEW PATCH:\n- ` + validation.warnings.join("\n- ");
  }
  return report;
}

async function listDirTool({ path, recursive }) {
  const fullPath = resolvePath(path);
  const entries = [];
  const agentRoot = process.cwd(); // The agent's own root folder

  async function walk(dir, depth = 0) {
    const items = await readdir(dir, { withFileTypes: true });
    for (const item of items) {
      // Skip node_modules and .git
      if (item.name === "node_modules" || item.name === ".git") continue;

      const itemPath = resolve(dir, item.name);

      // Skip the agent's own installation folder to prevent the LLM from getting trapped/distracted
      // Only apply this skip if the agent is installed in a strict subdirectory of the workspace
      const isStrictSubDir = agentRoot.startsWith(fullPath + "/") || (fullPath !== agentRoot && agentRoot.startsWith(fullPath));
      if (isStrictSubDir && (itemPath === agentRoot || itemPath.startsWith(agentRoot + "/"))) {
        continue;
      }

      const rel = relative(fullPath, itemPath);
      const prefix = "  ".repeat(depth);
      const isDir = item.isDirectory();

      if (isDir) {
        entries.push(`${prefix}📁 ${rel}/`);
        if (recursive) await walk(itemPath, depth + 1);
      } else {
        const info = await stat(itemPath);
        const size = info.size;
        const sizeStr =
          size > 1024
            ? `${(size / 1024).toFixed(1)}KB`
            : `${size}B`;
        entries.push(`${prefix}📄 ${rel} (${sizeStr})`);
      }
    }
  }

  await walk(fullPath);
  return entries.length > 0 ? entries.join("\n") : "(empty directory)";
}

async function runCommandTool({ command, cwd }) {
  let workdir = cwd ? resolvePath(cwd) : getWorkdir();
  if (!existsSync(workdir)) {
    workdir = process.cwd();
  }

  // Safety check for dangerous commands
  const isDangerous = DANGEROUS_PATTERNS.some((p) =>
    command.toLowerCase().includes(p.toLowerCase())
  );
  if (isDangerous) {
    const allowed = await confirm(
      `⚠️  Potentially dangerous command:\n   ${command}\n   Allow execution?`
    );
    if (!allowed) return "❌ Command blocked by user.";
  }

  // Check if a background command is already active
  if (activeBgPid && isProcessAlive(activeBgPid)) {
    return `⚠️ A background process is already running (PID ${activeBgPid}). Use 'peek_terminal' to check its progress, or run 'peek_terminal' with action='kill' to terminate it first.`;
  }

  activeBgLogPath = resolve(getWorkdir(), ".agent_terminal.log");

  try {
    await writeFile(activeBgLogPath, `--- Run Command: ${command} ---\n`, "utf-8");
  } catch (err) {
    return `❌ Failed to initialize log file: ${err.message}`;
  }

  const child = spawn(command, {
    shell: true,
    cwd: workdir,
    detached: true,
    stdio: ["ignore", "pipe", "pipe"]
  });

  activeBgProcess = child;
  activeBgPid = child.pid;

  child.stdout.on("data", (data) => {
    appendFile(activeBgLogPath, data).catch(() => {});
  });

  child.stderr.on("data", (data) => {
    appendFile(activeBgLogPath, data).catch(() => {});
  });

  let exitCode = null;
  let hasExited = false;

  child.on("exit", (code) => {
    exitCode = code;
    hasExited = true;
    activeBgProcess = null;
    activeBgPid = null;
  });

  child.on("error", (err) => {
    appendFile(activeBgLogPath, `\nERROR SPAWNING PROCESS: ${err.message}\n`).catch(() => {});
    hasExited = true;
    activeBgProcess = null;
    activeBgPid = null;
  });

  const timeoutMs = 30000;
  
  return new Promise((resolvePromise) => {
    const checkInterval = setInterval(async () => {
      if (hasExited) {
        clearInterval(checkInterval);
        clearTimeout(timer);
        try {
          const logContent = await readFile(activeBgLogPath, "utf-8");
          let output = logContent;
          if (exitCode !== null && exitCode !== 0) {
            output += `\nCommand exited with code ${exitCode}`;
          }
          resolvePromise(truncate(output || "(no output)"));
        } catch (e) {
          resolvePromise(`Command completed but failed to read output: ${e.message}`);
        }
      }
    }, 100);

    const timer = setTimeout(async () => {
      clearInterval(checkInterval);
      try {
        const logContent = await readFile(activeBgLogPath, "utf-8");
        resolvePromise(`⚠️ [TIMEOUT] The command is taking longer than 30s. It has been detached and is running in the background.
You can monitor the output using the 'peek_terminal' tool.
Recent output:
${truncate(logContent || "(no output)")}`);
      } catch (e) {
        resolvePromise(`⚠️ [TIMEOUT] The command is taking longer than 30s. It has been detached. Failed to read current logs: ${e.message}`);
      }
    }, timeoutMs);
  });
}

async function peekTerminalTool({ action = "peek" } = {}) {
  if (action === "kill") {
    if (!activeBgPid) {
      return "❌ No active background process to kill.";
    }
    try {
      process.kill(-activeBgPid, "SIGTERM");
    } catch (e) {
      try {
        process.kill(activeBgPid, "SIGTERM");
      } catch (e2) {
        return `❌ Failed to kill process: ${e2.message}`;
      }
    }
    activeBgProcess = null;
    activeBgPid = null;
    return "✅ Sent SIGTERM to the active background process.";
  }

  const logPath = resolve(getWorkdir(), ".agent_terminal.log");
  const logExists = existsSync(logPath);

  if (!activeBgPid) {
    if (logExists) {
      try {
        const logContent = await readFile(logPath, "utf-8");
        return `[STATUS: INACTIVE] No background process is active.
Last process output:
${truncate(logContent || "(no output)")}`;
      } catch (e) {
        return `[STATUS: INACTIVE] No background process is active. Failed to read logs: ${e.message}`;
      }
    }
    return `[STATUS: INACTIVE] No background process has been run yet.`;
  }

  const alive = isProcessAlive(activeBgPid);
  let logContent = "";
  if (logExists) {
    try {
      logContent = await readFile(logPath, "utf-8");
    } catch (e) {
      logContent = `Error reading terminal buffer: ${e.message}`;
    }
  }

  if (alive) {
    return `[STATUS: RUNNING] Process is still executing in the background (PID ${activeBgPid}).
Recent output:
${truncate(logContent || "(no output)")}`;
  } else {
    activeBgProcess = null;
    activeBgPid = null;
    return `[STATUS: COMPLETED] The process has finished running.
Final output:
${truncate(logContent || "(no output)")}`;
  }
}

async function grepSearchTool({ pattern, path, include }) {
  const fullPath = resolvePath(path);
  const agentRoot = process.cwd();

  // Build grep command
  let cmd = `grep -rnI --color=never`;
  if (include) cmd += ` --include='${include}'`;

  // Exclude the agent folder if it lies inside the search path
  if (agentRoot.startsWith(fullPath)) {
    const relAgentFolder = relative(fullPath, agentRoot);
    if (relAgentFolder && !relAgentFolder.startsWith("..")) {
      cmd += ` --exclude-dir='${relAgentFolder}'`;
    }
  }

  cmd += ` '${pattern.replace(/'/g, "'\\''")}' '${fullPath}'`;

  return new Promise((res) => {
    exec(cmd, { maxBuffer: 1024 * 1024 }, (error, stdout) => {
      if (error && !stdout) {
        return res("No matches found.");
      }
      // Make paths relative for readability
      const result = stdout.replace(new RegExp(fullPath + "/", "g"), "");
      res(truncate(result || "No matches found."));
    });
  });
}

async function indexCodebaseTool() {
  try {
    const index = await generateCodebaseIndex();
    const fileCount = Object.keys(index.files).length;
    return `✅ Codebase indexed successfully. Found and indexed ${fileCount} source files. Saving to .agent_index.json.`;
  } catch (err) {
    return `❌ Error generating codebase index: ${err.message}`;
  }
}

async function extendDeadlineTool({ additional_seconds, reason }) {
  if (typeof additional_seconds !== "number" || additional_seconds <= 0) {
    return "❌ Error: 'additional_seconds' must be a positive number.";
  }
  activeDeadline.estimatedSeconds += additional_seconds;
  return `✅ Deadline successfully extended by ${additional_seconds} seconds. New limit: ${activeDeadline.estimatedSeconds}s. Reason: ${reason}`;
}

// ---- Registry ----

const TOOL_REGISTRY = {
  read_file: readFileTool,
  write_file: writeFileTool,
  patch_file: patchFileTool,
  list_dir: listDirTool,
  run_command: runCommandTool,
  grep_search: grepSearchTool,
  index_codebase: indexCodebaseTool,
  peek_terminal: peekTerminalTool,
  extend_deadline: extendDeadlineTool,
};

/**
 * Execute a tool by name with parsed arguments.
 * Returns the tool output as a string.
 */
export async function executeTool(name, argsJson) {
  const fn = TOOL_REGISTRY[name];
  if (!fn) return `Unknown tool: ${name}`;

  try {
    const args = typeof argsJson === "string" ? JSON.parse(argsJson) : argsJson;
    return await fn(args);
  } catch (err) {
    return `Tool error (${name}): ${err.message}`;
  }
}
