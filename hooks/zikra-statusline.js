#!/usr/bin/env node
// zikra-statusline.js — Claude Code status line renderer
// Reads local cache only. Zero network calls. Silent fail on any error.
//
// Output format:
//   Zikra (8m ago) │ 17 runs · 847 memories │ veltisai │ Opus 4.6 │ 💀 650K/1M ████░░░░ 65%

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
    if (!raw) return { runs: 0, memories: 0, lastSaved: null, project: 'global' };
    const d = JSON.parse(raw);
    return {
      runs:      typeof d.runs_today   === 'number' ? d.runs_today   : 0,
      memories:  typeof d.memory_count === 'number' ? d.memory_count :
                 typeof d.memories_approx === 'number' ? d.memories_approx : 0,
      lastSaved: d.last_saved || null,
      project:   d.project    || 'global',
    };
  } catch {
    return { runs: 0, memories: 0, lastSaved: null, project: 'global' };
  }
}

function formatAge(isoString) {
  if (!isoString) return 'never';
  try {
    const diffMs  = Date.now() - new Date(isoString).getTime();
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 1)  return 'just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr  < 24) return `${diffHr}h ago`;
    return `${Math.floor(diffHr / 24)}d ago`;
  } catch { return '?'; }
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
  try {
    if (!payload || !payload.usage) return '';
    const used = payload.usage.input_tokens || 0;
    const max  = payload.usage.context_window || 200000;
    if (!used || !max) return '';
    const pct         = used / max;
    const TOTAL_BLOCKS = 8;
    const filled      = Math.round(pct * TOTAL_BLOCKS);
    const empty       = TOTAL_BLOCKS - filled;

    let fillColor;
    let showSkull = false;
    if      (pct < 0.65) { fillColor = GREEN; }
    else if (pct < 0.85) { fillColor = YELLOW; showSkull = true; }
    else                 { fillColor = RED;    showSkull = true; }

    const bar        = fillColor + '█'.repeat(Math.max(0, filled)) + DIM + '░'.repeat(Math.max(0, empty)) + RESET;
    const skull      = showSkull ? '💀 ' : '';
    const pctDisplay = Math.round(pct * 100);
    const pctColor   = pct >= 0.85 ? RED : pct >= 0.65 ? YELLOW : GREEN;

    return ` ${W}${skull}${formatTokens(used)}/${formatTokens(max)}${RESET} ${bar} ${pctColor}${pctDisplay}%${RESET}`;
  } catch { return ''; }
}

// ── Main ──────────────────────────────────────────────────────────────────────

try {
  let payload = null;
  try {
    if (!process.stdin.isTTY) {
      const raw = fs.readFileSync(process.stdin.fd, 'utf8').trim();
      if (raw) payload = JSON.parse(raw);
    }
  } catch { /* no stdin or not JSON — fine */ }

  const { runs, memories, lastSaved, project } = getStats();
  const age   = formatAge(lastSaved);
  const model = getModelLabel(payload && (payload.model || payload.model_id));
  const bar   = tokenBar(payload);

  const line =
    `${R}Zikra${RESET} ${D}(${age})${RESET} ${G}│${RESET} ` +
    `${R}${runs}${RESET}${G} runs · ${RESET}${R}${memories}${RESET}${G} memories${RESET} ${G}│${RESET} ` +
    `${W}${project}${RESET} ${G}│${RESET} ` +
    `${W}${model}${RESET}` +
    (bar ? ` ${G}│${RESET}` + bar : '');

  process.stdout.write(line + '\n');
} catch {
  // Silent fail — never break the Claude Code prompt
}
