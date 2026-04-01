#!/usr/bin/env node
// zikra-statusline.js — Claude Code status line renderer
// Reads local cache only. Zero network calls. Silent fail on any error.
//
// Output format:
//   zikra 17 runs · 847 memories │ user@host │ Sonnet 4.6 │ ~/dir (branch) │ 387K/200K ████░░░░░░ 45%

'use strict';

const fs            = require('fs');
const path          = require('path');
const os            = require('os');
const { execSync }  = require('child_process');

// ── Helpers ──────────────────────────────────────────────────────────────────

function silentRead(filePath) {
  try {
    return fs.readFileSync(filePath, 'utf8');
  } catch {
    return null;
  }
}

function getStats() {
  const cachePath = path.join(os.homedir(), '.claude', 'cache', 'zikra-stats.json');
  try {
    const raw = silentRead(cachePath);
    if (!raw) return { runs: 0, memories: 0 };
    const d = JSON.parse(raw);
    return {
      runs:     typeof d.runs_today   === 'number' ? d.runs_today   : 0,
      memories: typeof d.memory_count === 'number' ? d.memory_count : 0,
    };
  } catch {
    return { runs: 0, memories: 0 };
  }
}

function getGitBranch(dir) {
  try {
    const branch = execSync('git rev-parse --abbrev-ref HEAD', {
      cwd: dir,
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 1000,
    }).toString().trim();
    return branch === 'HEAD' ? '' : branch;
  } catch {
    return '';
  }
}

function getModelLabel(model) {
  if (!model) return 'Claude';
  // claude-sonnet-4-6 → Sonnet 4.6
  // claude-opus-4-6   → Opus 4.6
  // claude-haiku-4-5  → Haiku 4.5
  const m = model.match(/claude-([a-z]+)-(\d+)-?(\d*)/i);
  if (m) {
    const name    = m[1].charAt(0).toUpperCase() + m[1].slice(1);
    const version = m[3] ? `${m[2]}.${m[3]}` : m[2];
    return `${name} ${version}`;
  }
  return model;
}

function getContextBar(payload) {
  try {
    const used  = payload && (payload.tokens_used  || payload.context_tokens_used);
    const limit = payload && (payload.context_window || payload.context_window_size);
    if (!used || !limit || limit === 0) return '';

    const pct      = Math.min(100, Math.round((used / limit) * 100));
    const barWidth = 10;
    const filled   = Math.min(barWidth, Math.round((pct / 100) * barWidth));
    const empty    = barWidth - filled;
    const bar      = '█'.repeat(filled) + '░'.repeat(empty);

    const kUsed  = Math.round(used  / 1000);
    const kLimit = Math.round(limit / 1000);

    // Color thresholds
    let prefix = '';
    let suffix = '';
    const isTerminal = process.stdout.isTTY;
    if (isTerminal) {
      if      (pct >= 95) { prefix = '\x1b[31m'; suffix = '\x1b[0m'; } // red
      else if (pct >= 81) { prefix = '\x1b[33m'; suffix = '\x1b[0m'; } // orange/yellow
      else if (pct >= 63) { prefix = '\x1b[33m'; suffix = '\x1b[0m'; } // yellow
      else                { prefix = '\x1b[32m'; suffix = '\x1b[0m'; } // green
    }

    const skull = pct >= 95 ? '💀 ' : '';
    return ` │ ${skull}${kUsed}K/${kLimit}K ${prefix}${bar}${suffix} ${pct}%`;
  } catch {
    return '';
  }
}

function getActiveTodo() {
  try {
    const todosDir = path.join(os.homedir(), '.claude', 'todos');
    if (!fs.existsSync(todosDir)) return '';

    const files = fs.readdirSync(todosDir)
      .filter(f => f.endsWith('.json'))
      .sort()
      .reverse();

    for (const file of files) {
      const raw = silentRead(path.join(todosDir, file));
      if (!raw) continue;
      const todos = JSON.parse(raw);
      if (!Array.isArray(todos)) continue;
      const active = todos.find(t => t && t.status === 'in_progress');
      if (active && active.content) {
        const text = String(active.content).replace(/\n/g, ' ').slice(0, 40);
        return ` ▶ ${text}`;
      }
    }
    return '';
  } catch {
    return '';
  }
}

// ── Main ─────────────────────────────────────────────────────────────────────

try {
  // Read stdin payload (may be empty or absent)
  // Avoid /dev/stdin — not available on Windows; use process.stdin fd directly.
  let payload = null;
  try {
    if (!process.stdin.isTTY) {
      const raw = fs.readFileSync(process.stdin.fd, 'utf8').trim();
      if (raw) payload = JSON.parse(raw);
    }
  } catch { /* no stdin or not JSON — fine */ }

  const { runs, memories } = getStats();

  // Identity
  const username = (() => { try { return os.userInfo().username; } catch { return 'user'; } })();
  const hostname = os.hostname().split('.')[0];

  // Working directory
  const cwd    = process.cwd();
  const cwdRel = cwd.startsWith(os.homedir())
    ? '~' + cwd.slice(os.homedir().length)
    : cwd;

  // Git branch
  const branch  = getGitBranch(cwd);
  const dirPart = branch ? `${cwdRel} (${branch})` : cwdRel;

  // Model
  const model = getModelLabel(payload && (payload.model || payload.model_id));

  // Context bar
  const ctxBar = getContextBar(payload);

  // Active todo
  const todo = getActiveTodo();

  // Build line
  const line = `zikra ${runs} runs · ${memories} memories │ ${username}@${hostname} │ ${model} │ ${dirPart}${ctxBar}${todo}`;

  process.stdout.write(line + '\n');
} catch {
  // Silent fail — never break the Claude Code prompt
}
