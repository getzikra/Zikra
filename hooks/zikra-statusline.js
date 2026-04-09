#!/usr/bin/env node
// zikra-statusline.js — Claude Code status line renderer
// Reads local cache only. Zero network calls. Silent fail on any error.
// Keep in sync with zikra-lite/hooks/zikra-statusline.js
//
// Output format:
//   Zikra (v1.0.1) │ 17 runs · 847 memories │ veltisai │ Opus 4.6 │ 💀 650K/1M ████░░░░ 65%

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

function getStats() {
  const cachePath = path.join(os.homedir(), '.claude', 'cache', 'zikra-stats.json');
  try {
    const raw = silentRead(cachePath);
    if (!raw) return { runs: 0, memories: 0, project: 'global' };
    const d = JSON.parse(raw);
    return {
      runs:     typeof d.runs_today   === 'number' ? d.runs_today   : 0,
      memories: typeof d.memory_count === 'number' ? d.memory_count :
                typeof d.memories_approx === 'number' ? d.memories_approx : 0,
      project:  d.project || 'global',
    };
  } catch {
    return { runs: 0, memories: 0, project: 'global' };
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

  // Hardcoded to 1M — Claude Code CLI session limit.
  // Claude Code reports context_window_size: 200K (per-call window) which is misleading.
  const sessionMax = 1000000;
  const callMax = maxTokens || 200000;

  // Back-calculate actual tokens from used_percentage * per-call window
  if (tokensUsed === null && typeof ctx.used_percentage === 'number') {
    tokensUsed = Math.round((ctx.used_percentage / 100) * callMax);
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

  return ` ${W}${icon}${usedStr}/1M${RESET} ${bar} ${pctColor}${Math.round(pct * 100)}%${RESET}`;
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
    const { runs, memories, project } = getStats();
    const { server, latest } = getVersions();
    const version = server || 'zikra';
    const model   = getModelLabel(payload && (payload.model || payload.model_id));
    const bar     = tokenBar(payload);
    const vLabel  = server ? formatVersion(server, latest) : `${G}(update if ${R}●${G})${RESET}`;

    const line =
      `${R}Zikra${RESET} ${vLabel} ${G}│${RESET} ` +
      `${R}${runs}${RESET}${G} runs · ${RESET}${R}${memories}${RESET}${G} memories${RESET} ${G}│${RESET} ` +
      `${W}${project}${RESET} ${G}│${RESET} ` +
      `${W}${model}${RESET}` +
      (bar ? ` ${G}│${RESET}` + bar : '');

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
