#!/usr/bin/env node
// zikra-statusline.js — Claude Code status line renderer
// Reads local cache only. Zero network calls. Silent fail on any error.
// Keep in sync with zikra-lite/hooks/zikra-statusline.js
//
// Output format:
//   Zikra (v0.1.0) │ 17 runs · 847 memories │ veltisai │ Opus 4.6 │ 💀 650K/1M ████░░░░ 65%

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

  // Determine max tokens — context_window may be a number or an object
  let maxTokens = null;
  if (typeof payload.context_window === 'number') {
    maxTokens = payload.context_window;
  } else if (payload.context_window && typeof payload.context_window === 'object') {
    maxTokens = payload.context_window.size || null;
  } else if (typeof payload.context_window_size === 'number') {
    maxTokens = payload.context_window_size;
  }
  if (!maxTokens) return '';

  // Determine tokens used and percentage
  let tokensUsed = null;
  let pct = 0;
  if (typeof payload.context_tokens_used === 'number') {
    tokensUsed = payload.context_tokens_used;
    pct = tokensUsed / maxTokens;
  } else if (typeof payload.tokens_used === 'number') {
    tokensUsed = payload.tokens_used;
    pct = tokensUsed / maxTokens;
  } else if (payload.context_window && typeof payload.context_window === 'object' &&
             typeof payload.context_window.used_percentage === 'number') {
    pct = payload.context_window.used_percentage / 100;
    tokensUsed = Math.round(pct * maxTokens);
  }

  if (pct === 0 && tokensUsed === null) return '';

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

  // Left label: tokensUsedK / maxTokensDisplay
  const usedStr = tokensUsed !== null ? Math.round(tokensUsed / 1000) + 'K' : '?';
  let maxStr;
  if      (maxTokens >= 1900000) maxStr = '2M';
  else if (maxTokens >= 900000)  maxStr = '1M';
  else                           maxStr = Math.round(maxTokens / 1000) + 'K';

  return ` ${W}${icon}${usedStr}/${maxStr}${RESET} ${bar} ${pctColor}${Math.round(pct * 100)}%${RESET}`;
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
    const version = process.env.ZIKRA_VERSION || 'v0.1.0';
    const model   = getModelLabel(payload && (payload.model || payload.model_id));
    const bar     = tokenBar(payload);

    const line =
      `${G}Zikra (${version})${RESET} ${G}│${RESET} ` +
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
