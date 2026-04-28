// Minimal VS Code extension (CommonJS) — no build step.
// Tracks focused time while this repository is opened as a workspace folder.
//
// Notes:
// - This is best-effort engineering telemetry, not legal-grade time tracking.
// - It writes periodic checkpoints while focused to reduce data loss on crashes.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

/**
 * @typedef {{
 *   workspaceRoot: string;
 *   sessionSeq: number;
 *   startedAtMs: number;
 *   lastCheckpointAtMs: number;
 * }} FocusSession
 */

/**
 * @param {import('vscode').ExtensionContext} context
 */
function activate(context) {
  const sessionId = vscode.env.sessionId;
  const machineId = vscode.env.machineId;
  const appName = vscode.env.appName;

  const extensionPath = context.extensionUri.fsPath;

  const resolveRepoRoot = () => {
    const folders = vscode.workspace.workspaceFolders ?? [];
    if (folders.length === 0) return null;

    // Prefer the workspace folder that actually contains this extension on disk.
    const marker = path.join("devtools", "cursor-open-time-tracker");
    for (const f of folders) {
      const p = path.join(f.uri.fsPath, marker);
      try {
        if (fs.existsSync(p)) return f.uri.fsPath;
      } catch {
        // ignore
      }
    }

    // Fallback: first workspace root
    return folders[0].uri.fsPath;
  };

  const repoRoot = resolveRepoRoot();
  const logFileAbs = repoRoot ? path.join(repoRoot, "logs", "cursor-open-time.jsonl") : null;
  const logDirAbs = logFileAbs ? path.dirname(logFileAbs) : null;

  /** @type {Map<string, FocusSession>} */
  const sessions = new Map();

  let seq = 0;
  /** @type {NodeJS.Timeout | undefined} */
  let checkpointTimer;

  const ensureLogDir = () => {
    if (!logDirAbs) return;
    fs.mkdirSync(logDirAbs, { recursive: true });
  };

  const appendJsonl = (obj) => {
    if (!logFileAbs) return;
    ensureLogDir();
    fs.appendFileSync(logFileAbs, JSON.stringify(obj) + "\n", { encoding: "utf8" });
  };

  const nowIso = () => new Date().toISOString();

  const workspaceRoots = () => (vscode.workspace.workspaceFolders ?? []).map((f) => f.uri.fsPath);

  const emit = (type, extra) => {
    appendJsonl({
      ts: nowIso(),
      type,
      appName,
      sessionId,
      machineId,
      repoRoot,
      roots: workspaceRoots(),
      extensionPath,
      ...extra,
    });
  };

  const stopCheckpointTimer = () => {
    if (checkpointTimer) clearInterval(checkpointTimer);
    checkpointTimer = undefined;
  };

  const startCheckpointTimer = () => {
    stopCheckpointTimer();
    // Checkpoint every 5 minutes while focused.
    checkpointTimer = setInterval(() => checkpoint("timer"), 5 * 60 * 1000);
  };

  const endSession = (workspaceRoot, reason, kind) => {
    const s = sessions.get(workspaceRoot);
    if (!s) return;

    const endedAtMs = Date.now();
    const durationMs = Math.max(0, endedAtMs - s.startedAtMs);

    sessions.delete(workspaceRoot);

    appendJsonl({
      ts: nowIso(),
      type: kind,
      appName,
      sessionId,
      machineId,
      repoRoot,
      roots: workspaceRoots(),
      extensionPath,
      workspaceRoot,
      reason,
      sessionSeq: s.sessionSeq,
      startedAtMs: s.startedAtMs,
      endedAtMs,
      durationMs,
    });
  };

  const endAllSessions = (reason, kind) => {
    for (const root of [...sessions.keys()]) endSession(root, reason, kind);
  };

  const checkpoint = (reason) => {
    // Convert elapsed time since last checkpoint into a closed interval, but keep working.
    const endedAtMs = Date.now();
    for (const [workspaceRoot, s] of sessions.entries()) {
      const durationMs = Math.max(0, endedAtMs - s.startedAtMs);
      if (durationMs <= 0) continue;

      appendJsonl({
        ts: nowIso(),
        type: "focus_interval_checkpoint",
        appName,
        sessionId,
        machineId,
        repoRoot,
        roots: workspaceRoots(),
        extensionPath,
        workspaceRoot,
        reason,
        sessionSeq: s.sessionSeq,
        startedAtMs: s.startedAtMs,
        endedAtMs,
        durationMs,
      });

      // Roll the window forward without changing sessionSeq.
      s.startedAtMs = endedAtMs;
      s.lastCheckpointAtMs = endedAtMs;
    }
  };

  const syncFocusState = (reason) => {
    if (!logFileAbs || !repoRoot) {
      emit("disabled_no_workspace", { reason });
      stopCheckpointTimer();
      endAllSessions(reason, "focus_interval");
      return;
    }

    const focused = vscode.window.state.focused;
    const roots = workspaceRoots();

    if (!focused || roots.length === 0) {
      stopCheckpointTimer();
      endAllSessions(reason, "focus_interval");
      return;
    }

    // Start sessions for any roots not already running
    for (const root of roots) {
      if (sessions.has(root)) continue;
      seq += 1;
      const s = {
        workspaceRoot: root,
        sessionSeq: seq,
        startedAtMs: Date.now(),
        lastCheckpointAtMs: Date.now(),
      };
      sessions.set(root, s);
      emit("focus_start", { workspaceRoot: root, reason, sessionSeq: s.sessionSeq });
    }

    // Stop sessions for roots no longer present
    for (const existing of [...sessions.keys()]) {
      if (!roots.includes(existing)) endSession(existing, "workspace_folder_removed", "focus_interval");
    }

    startCheckpointTimer();
  };

  emit("activate", { logFile: logFileAbs, repoRoot });
  syncFocusState("activate");

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((e) => syncFocusState(e.focused ? "window_focused" : "window_blurred")),
  );

  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => syncFocusState("workspace_folders_changed")));

  context.subscriptions.push(
    vscode.commands.registerCommand("cursorOpenTime.flush", () => {
      checkpoint("manual_flush");
      emit("manual_flush", {});
      void vscode.window.showInformationMessage(`Cursor Open Time: checkpoint written to ${logFileAbs ?? "(no log path)"}`);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("cursorOpenTime.showToday", async () => {
      const channel = vscode.window.createOutputChannel("Cursor Open Time");
      channel.clear();

      if (!logFileAbs || !fs.existsSync(logFileAbs)) {
        channel.appendLine(`No log file yet: ${logFileAbs ?? "(no log path)"}`);
        channel.show(true);
        return;
      }

      const text = fs.readFileSync(logFileAbs, "utf8");
      const lines = text.split("\n").filter(Boolean);

      /** @type {Map<string, number>} */
      const totalsMs = new Map();

      const today = new Date();
      const y = today.getFullYear();
      const m = String(today.getMonth() + 1).padStart(2, "0");
      const d = String(today.getDate()).padStart(2, "0");
      const dayPrefix = `${y}-${m}-${d}`;

      for (const line of lines) {
        let obj;
        try {
          obj = JSON.parse(line);
        } catch {
          continue;
        }
        if (!obj || typeof obj !== "object") continue;
        if (obj.type !== "focus_interval" && obj.type !== "focus_interval_checkpoint") continue;
        if (typeof obj.ts !== "string" || !obj.ts.startsWith(dayPrefix)) continue;
        if (typeof obj.workspaceRoot !== "string") continue;
        if (typeof obj.durationMs !== "number") continue;

        totalsMs.set(obj.workspaceRoot, (totalsMs.get(obj.workspaceRoot) ?? 0) + obj.durationMs);
      }

      channel.appendLine(`Totals for ${dayPrefix} (focused time, checkpoints included):`);
      if (totalsMs.size === 0) {
        channel.appendLine("- (no interval events for today yet)");
      } else {
        for (const [root, ms] of [...totalsMs.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
          const minutes = (ms / 60000).toFixed(1);
          channel.appendLine(`- ${root}: ${minutes} min (${ms} ms)`);
        }
      }

      channel.appendLine("");
      channel.appendLine(`Log file: ${logFileAbs}`);
      channel.show(true);
    }),
  );

  context.subscriptions.push({
    dispose: () => {
      stopCheckpointTimer();
      endAllSessions("extension_deactivate", "focus_interval");
    },
  });
}

function deactivate() {
  // primary cleanup happens via subscription dispose
}

module.exports = { activate, deactivate };
