#!/usr/bin/env node
// zikra-statusline.js — Claude Code status line renderer
// Reads local cache + walks cwd for CLAUDE.md. Zero network calls. Silent fail on any error.
//
// Output format:
//   Zikra (v1.0.8) │ 17 runs · 847 memories │ veltisai │ Opus 4.7 │ 💀 130K/1M ████░░░░ 13%
//
// Project resolution:
//   1. CLAUDE.md `project:` / `ZIKRA_PROJECT=` walking up from cwd (skips "global")
//   2. Falls back to project in ~/.claude/cache/zikra-stats.json
//
// Context window:
//   Uses whatever size Claude Code reports for the session — never hardcoded.
//   Falls back to 200K only when the payload contains no size at all.

'use strict';

const fs   = require('fs');
const path = require('path');
const os   = require('os');

// ── Colour palette ────────────────────────────────────────────────────────────
const GREEN  = '\x1b[38;5;82m';   // bright green  (< 65%)
const YELLOW = '\x1b[38;5;226m';  // yellow        (65–85%)
const RED    = '\x1b[38;5;196m';  // red           (85%+)
const DIM    = '\x1b[38;5;238m';  // dark grey for empty blocks
const W      = '\x1b[37m';        // white
const R      = '\x1b[38;5;208m';  // orange (Zikra brand)
const D      = '\x1b[38;5;172m';  // dim orange (timestamps)
const G      = '\x1b[38;5;240m';  // grey dim (separators, labels)
const RESET  = '\x1b[0m';

// ── Helpers ───────────────────────────────────────────────────────────────────

function silentRead(filePath) {
  try { return fs.readFileSync(filePath, 'utf8'); } catch { return null; }
}

// Walk up from the current directory looking for a CLAUDE.md containing a
// `project: <name>` line (or `ZIKRA_PROJECT=<name>`). First match wins.
// Returns null when nothing is found so the caller can fall back to the cache.
// "global" is skipped so a top-level CLAUDE.md defaulting to global does not
// override a more-specific project deeper in the tree.
function getProjectFromCwd(payload) {
  try {
    const cwd = (payload && payload.workspace && (payload.workspace.current_dir || payload.workspace.cwd))
             || (payload && payload.cwd)
             || process.env.CLAUDE_PROJECT_DIR
             || process.env.PWD
             || process.cwd();

    const projectRe = /^\s*(?:-\s*)?project\s*[:=]\s*["']?([a-zA-Z0-9_\-]+)["']?/im;
    const envRe     = /ZIKRA_PROJECT\s*=\s*["']?([a-zA-Z0-9_\-]+)["']?/i;

    const seen = new Set();
    let dir = path.resolve(cwd);
    const home = os.homedir();

    while (dir && !seen.has(dir)) {
      seen.add(dir);
      const raw = silentRead(path.join(dir, 'CLAUDE.md'));
      if (raw) {
        const m = raw.match(projectRe) || raw.match(envRe);
        if (m) {
          const name = m[1].toLowerCase();
          if (name && name !== 'global') return name;
        }
      }
      const parent = path.dirname(dir);
      if (parent === dir || dir === home || dir === '/') break;
      dir = parent;
    }
  } catch { /* silent */ }
  return null;
}

function getStats() {
  const cachePath = path.join(os.homedir(), '.claude', 'cache', 'zikra-stats.json');
  try {
    const raw = silentRead(cachePath);
    if (!raw) return { runs: 0, memories: 0, project: 'global', orphans: 0 };
    const d = JSON.parse(raw);
    return {
      runs:     typeof d.runs_today   === 'number' ? d.runs_today   : 0,
      memories: typeof d.memory_count === 'number' ? d.memory_count :
                typeof d.memories_approx === 'number' ? d.memories_approx : 0,
      project:  d.project || 'global',
      orphans:  typeof d.orphan_count === 'number' ? d.orphan_count : 0,
    };
  } catch {
    return { runs: 0, memories: 0, project: 'global', orphans: 0 };
  }
}

function formatTokens(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(0) + 'M';
  if (n >= 1000)    return Math.round(n / 1000) + 'K';
  return String(n);
}

function getModelLabel(model) {
  if (!model) return 'Claude';
  if (typeof model === 'object') model = model.id || '';
  if (!model) return 'Claude';
  const m = model.match(/claude-([a-z]+)-([\d-]+)/);
  if (!m) return 'Claude';
  const name = m[1].charAt(0).toUpperCase() + m[1].slice(1);
  const ver  = m[2].replace(/-/g, '.');
  return `${name} ${ver}`;
}

function tokenBar(payload) {
  if (!payload) return '';
  const ctx = payload.context_window;
  if (!ctx || typeof ctx !== 'object') return '';

  // Get max tokens from context_window_size (Claude Code provides this)
  const maxTokens = ctx.context_window_size || ctx.size || null;

  // Get actual tokens used from current_usage breakdown
  let tokensUsed = null;
  if (ctx.current_usage && typeof ctx.current_usage === 'object') {
    const u = ctx.current_usage;
    tokensUsed = (u.input_tokens || 0)
               + (u.cache_creation_input_tokens || 0)
               + (u.cache_read_input_tokens || 0);
  }

  // Fallback to cumulative input tokens
  if (tokensUsed === null && typeof ctx.total_input_tokens === 'number') {
    tokensUsed = ctx.total_input_tokens;
  }

  // Use whatever size Claude Code reports for this session. Never hardcode
  // 200K or 1M — the reported value is authoritative. 200K is only a last-
  // ditch fallback for payloads that omit the field entirely.
  const sessionMax = maxTokens || 200000;

  // Back-calculate actual tokens from used_percentage when no breakdown
  if (tokensUsed === null && typeof ctx.used_percentage === 'number') {
    tokensUsed = Math.round((ctx.used_percentage / 100) * sessionMax);
  }

  if (tokensUsed === null || tokensUsed === 0) return '';

  const pct = tokensUsed / sessionMax;

  const BLOCKS = 8;
  const filled = Math.round(pct * BLOCKS);
  const empty  = BLOCKS - filled;

  let color, skull = false;
  if      (pct < 0.65) { color = GREEN; }
  else if (pct < 0.85) { color = YELLOW; skull = true; }
  else                 { color = RED;    skull = true; }

  const bar      = color + '█'.repeat(Math.max(0, filled)) + DIM + '░'.repeat(Math.max(0, empty)) + RESET;
  const pctColor = pct >= 0.85 ? RED : pct >= 0.65 ? YELLOW : GREEN;
  const icon     = skull ? '💀 ' : '   ';

  const usedStr = formatTokens(tokensUsed);
  const maxStr  = formatTokens(sessionMax);

  return ` ${W}${icon}${usedStr}/${maxStr}${RESET} ${bar} ${pctColor}${Math.round(pct * 100)}%${RESET}`;
}

function formatVersion(local, latest) {
  const parse = (v) => (v || '').replace(/^v/, '').split('.').map(Number);
  const lv = parse(local);
  const rv = parse(latest);

  if (!latest || rv.length < 3 || lv.length < 3) {
    return `${G}(${local})${RESET}`;
  }

  if (rv[0] > lv[0]) {
    // Major update: highlight all three
    return `${G}(v${R}${lv[0]}${G}.${R}${lv[1]}${G}.${R}${lv[2]}${G})${RESET}`;
  } else if (rv[1] > lv[1]) {
    // Minor update: highlight minor and patch
    return `${G}(v${lv[0]}.${R}${lv[1]}${G}.${R}${lv[2]}${G})${RESET}`;
  } else if (rv[2] > lv[2]) {
    // Patch update: highlight patch only
    return `${G}(v${lv[0]}.${lv[1]}.${R}${lv[2]}${G})${RESET}`;
  }

  return `${G}(${local})${RESET}`;
}

function getVersions() {
  const cachePath = path.join(os.homedir(), '.claude', 'cache', 'zikra-stats.json');
  try {
    const raw = silentRead(cachePath);
    if (!raw) return { server: null, latest: null };
    const d = JSON.parse(raw);
    return {
      server: d.server_version || null,
      latest: d.latest_version || null,
    };
  } catch { return { server: null, latest: null }; }
}

// ── Main ──────────────────────────────────────────────────────────────────────

// Read stdin asynchronously with a 200ms deadline.
// fs.readFileSync(process.stdin.fd) blocks when Claude Code keeps the pipe open,
// preventing the status bar from ever rendering.
const chunks = [];
let rendered  = false;

function render(payload) {
  if (rendered) return;
  rendered = true;
  try {
    const { runs, memories, project: cacheProject, orphans } = getStats();
    const project = getProjectFromCwd(payload) || cacheProject;
    const { server, latest } = getVersions();
    const version = server || 'zikra';
    const model   = getModelLabel(payload && (payload.model || payload.model_id));
    const bar     = tokenBar(payload);
    const vLabel  = server ? formatVersion(server, latest) : `${G}(update if ${R}●${G})${RESET}`;
    const stale   = orphans > 0 ? ` ${G}│${RESET} ${YELLOW}⚠ ${orphans} stale${RESET}` : '';

    const line =
      `${R}Zikra${RESET} ${vLabel} ${G}│${RESET} ` +
      `${R}${runs}${RESET}${G} runs · ${RESET}${R}${memories}${RESET}${G} memories${RESET} ${G}│${RESET} ` +
      `${W}${project}${RESET} ${G}│${RESET} ` +
      `${W}${model}${RESET}` +
      (bar ? ` ${G}│${RESET}` + bar : '') +
      stale;

    process.stdout.write(line + '\n');
  } catch { /* silent fail */ }
}

try {
  const timer = setTimeout(() => { process.stdin.destroy(); render(null); }, 200);

  process.stdin.setEncoding('utf8');
  process.stdin.on('data', chunk => chunks.push(chunk));
  process.stdin.on('end', () => {
    clearTimeout(timer);
    let p = null;
    try { p = JSON.parse(chunks.join('').trim()); } catch {}
    render(p);
  });
  process.stdin.on('error', () => { clearTimeout(timer); render(null); });
  process.stdin.resume();
} catch {
  render(null);
}
