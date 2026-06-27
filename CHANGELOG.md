# Changelog

## [1.0.14] — 2026-06-26

### Fixed — statusline & hook reliability

The statusline and session hooks could intermittently render `0 runs · 0
memories` or stall. Root cause was a non-atomic cache write racing the reader,
unbounded hook network calls, and a duplicated Stop hook. All four are fixed.

- **Atomic statusline cache writes** (`hooks/zikra-stats-update.sh`). The stats
  cache (`~/.claude/cache/zikra-stats.json`) is now written to a **per-process**
  temp file (`.tmp.<pid>`), `fsync`'d, then `os.replace`'d into place — atomic on
  POSIX. The statusline reader can no longer observe a half-written file, even if
  the `Stop` hook is killed mid-write by its timeout, and concurrent Stop hooks
  (multiple terminals closing at once) no longer collide on a shared temp path.

- **Bounded hook network calls** (`hooks/zikra-stats-update.sh`,
  `hooks/zikra_autolog.sh`). Every `curl` in the stats updater now uses
  `--max-time 3 --connect-timeout 2` (and the daily GitHub version check uses a
  3s timeout); the autolog diary/`log_run` POST gains `--max-time 20`. A slow or
  unreachable server can no longer hang a hook or get it killed mid-write.

- **Statusline self-heal** (`hooks/zikra-statusline.js`). The renderer now keeps
  a last-good `.bak` snapshot, refreshed atomically on every clean read. If the
  primary cache is corrupt or mid-write, it falls back to the snapshot instead of
  rendering zeros. Falls back to safe defaults only when both are unreadable.

- **Duplicate `Stop` hook removed** (installer/setup). The `Stop` event could be
  wired with the autolog handler twice (once via `~/` and once via an absolute
  path), running the diary path twice per session. Installers now de-duplicate.

### Changed — installers deliver the full statusline

- **`installer.py`** now installs `hooks/zikra-stats-update.sh` and wires the
  `statusLine`, `Stop`, and `PreCompact` hooks into `~/.claude/settings.json`
  (atomically, with de-duplication). Previously only `python` + the GitHub setup
  prompt produced a complete statusline; `installer.py` left out the live stats
  refresh. Both install paths are now equivalent.

## [1.0.13] — 2026-05-06

### Added

- **Memory-type color palette** (`ui.html`). `TYPE_COLORS` expanded from 6 to 14
  presets so every memory type that exists in the database renders with its own
  distinct color in the graph view and badges. New entries: `bug` (red),
  `diary` (rose), `investigation` (gold), `reference` (sky blue), `mockup`
  (orange), `skill` (mint), `feedback` (teal), `handoff` (lavender), and a
  differentiated coral for `error` so it no longer collides with `bug`.

- **Search pagination** (`ui.html`). The Search tab now shows `showing N of
  total` underneath the result list and a "Load more" button when more results
  are available. Replaces the silent 50-row truncation. Pagination uses a
  growing-limit re-fetch so the hybrid vector+FTS ranking stays consistent
  across pages.

- **Hooks: server log_run** (`hooks/codex-hook.sh`, `hooks/gemini-hook.sh`).
  Both hooks now POST a `log_run` to the Zikra server when `ZIKRA_URL` and
  `ZIKRA_TOKEN` are present in the environment. Token counts that previously
  only landed in `~/.claude/cache/zikra-stats.json` for the statusline now also
  land in the server `prompt_runs` table for cross-session analytics.

- **MCP project_scope enforcement** (`zikra/mcp_server.py`). Tokens minted with
  a `project_scope` value are now enforced for all project-scoped MCP tools
  (`zikra_search`, `zikra_save_memory`, `zikra_get_prompt`, `zikra_log_run`,
  `zikra_log_error`, `zikra_save_requirement`, `zikra_list_requirements`,
  `zikra_get_memory`, `zikra_delete_memory`, `zikra_promote_requirement`,
  `zikra_save_prompt`, `zikra_list_prompts`, `zikra_hygiene_report`). A
  scope-mismatched call returns a structured `token_scope_mismatch` error;
  scope-matched calls have `project` injected automatically.

- **`PROMOTION.md`** — public launch kit at the repo root. Canonical links,
  positioning, taglines, and submission copy for directories, awesome lists,
  newsletters, and launch platforms.

- **`prompts/zikra-audit.md`** — Claude Code prompt that audits a Zikra
  instance for project drift, type misclassification, ghost projects, and
  emerging-project signals. Read-only by default; emits remediation commands
  on confirmation.

### Changed

- **Search results cap raised** (`zikra/server.py`). `/api/ui/memories` `limit`
  cap raised from 200 → 1000 so pagination can grow to cover larger projects.
  Default still 50.

- **Architecture docs rewritten** (`docs/architecture.md`). Repositioned around
  the team-memory-OS framing. Adds Mermaid diagrams for system, request flow,
  role/scope model, and storage layout. Replaces the original pre-formatted
  ASCII diagram.

- **`docs/commands.md`** — example URLs replaced with `http://localhost:8000`
  to match the self-hosted default. The `User-Agent: curl/7.81.0` requirement
  note has been removed; it was only needed for older n8n configurations.

- **`setup.py`** — package version bumped from `1.0.1` to `1.0.13` to match
  `zikra/version.py`. The two had drifted apart over 9 releases.

### Fixed

- **Memory type cleanup** (database). 3 merges applied to consolidate stray
  one-off types: `run_diary` → `diary` (2 rows), `memory` → `reference` (1
  row), `knowledge` → `reference` (3 rows). DB count of distinct types reduced
  from 15 to 12.

- **`docs/onboarding.md`** — installer URL example changed from
  `n8n.yourdomain.com` to `zikra.yourdomain.com` to match the v1.0+ self-hosted
  topology.

## [1.0.10] — 2026-04-22

### Added

- **"Who are you?" login screen** (`ui.html`). Replaces the silent settings-panel
  bearer-token input with a full-viewport user-picker overlay. On first visit (or
  after a token expiry) the UI fetches `/api/ui/users` and renders a button for
  each known token label. Clicking a name reveals an inline token-paste field;
  confirming verifies against `/api/ui/bootstrap` before persisting to
  `localStorage`. An "Advanced" disclosure allows manual token entry for new
  users whose label hasn't been minted yet.

- **`GET /api/ui/users`** — unauthenticated endpoint returning
  `[{"label": "…"}, …]` from `access_tokens` (active, non-owner rows only).
  No tokens, no roles, no IDs are exposed.

- **Project-scoped tokens** (`project_scope` column on `access_tokens`).
  `NULL` = unrestricted. A non-null value restricts the token to that project
  only — any request targeting a different project is rejected with a structured
  403. Pass `"project_scope": "veltisai"` to `create_token` to mint a
  pre-scoped token.

- **Token usage tracking** (`token_hits` table). An append-only table records
  `(label, command, ts)` for every authenticated request via a FastAPI
  middleware. Webhook calls log the exact command (`search`, `save_memory`, …);
  UI calls log the path (`ui:bootstrap`, `ui:memories`, …). Non-blocking —
  inserted as a background task so it never adds latency.

- **`GET /api/ui/token-usage`** — authenticated endpoint returning per-label
  `hits_total`, `hits_7d`, `hits_24h`, and `last_seen`.

- **Graceful 403 handling in the UI**. Scope-mismatch errors show a banner with
  a "Switch to '<project>'" button that auto-switches the active project and
  reconnects. Scoped tokens auto-land on their project at login and on every
  page reload via the `project_scope` field returned by `/api/ui/bootstrap`.

### Fixed

- `renderProjSelector` owner gate removed — all authenticated roles now see the
  radio-button project list, not a plain text input.
- Global 401 handler now wipes `localStorage` and shows the "Who are you?"
  overlay instead of opening the gear panel.
- Login flow uses relative URLs (`/api/ui/users`, `/api/ui/bootstrap`) so the
  "Who are you?" screen works correctly when accessed via a remote domain
  (previously fetched `localhost:8100` from the user's browser).

### Schema

- `access_tokens`: new `project_scope TEXT` column (nullable, default NULL).
- New `token_hits (id, label, command, ts)` table with two indexes.
- SQLite: migration `008_token_hits_and_project_scope`.
- Postgres: columns/tables added via `init_pg()` migration guards and included
  in `_PG_TABLES` for fresh installs.

---

## [1.0.9] — 2026-04-21

### Added

- **Gemini CLI integration** (`hooks/gemini-hook.sh`). Registers for
  `AfterModel` and `SessionEnd` events. Parses the transcript JSONL Gemini
  writes each session and extracts token counts using both Gemini-native
  (`usageMetadata.promptTokenCount`) and OpenAI-style (`usage.input_tokens`)
  field names so it works across Gemini CLI versions. Updates the shared
  `~/.claude/cache/zikra-stats.json` cache and writes `last_tool=gemini`,
  `last_model`, so the statusline knows which tool is active.

- **Codex CLI integration** (`hooks/codex-hook.sh`). Registers for `Stop` and
  `PostToolUse` events. Probes `transcript_path` from the hook payload, falls
  back to `~/.codex/sessions/<session_id>/history.jsonl`. Parses OpenAI-style
  `usage.prompt_tokens` / `usage.completion_tokens`. Config is written to
  `~/.codex/config.toml` ([hooks] section) if the file exists, else to
  `~/.codex/hooks.json` (used by newer Codex versions).

- **Shell statusline** (`hooks/zikra-shell-status.sh`). Sources into
  `~/.bashrc` / `~/.zshrc` and renders the Zikra bar before each terminal
  prompt for Gemini and Codex sessions. Reuses `zikra-statusline.js` by
  piping a synthetic payload built from the shared cache. No token bar in
  shell mode (context window data is not available at shell level); all other
  fields (project, runs, memories, model) work normally.

- **Installer step: "Other AI tools"** (`installer.py`). New question after
  hook depth: choose Claude Code only / Gemini CLI / Codex CLI / both.
  Installer auto-detects which CLIs are on PATH and marks them "(detected)".
  Installs hooks, writes tool-specific config, and appends the shell statusline
  source line to RC files. Summary screen lists all integrated tools.

### Architecture note

All three tools share a single cache (`~/.claude/cache/zikra-stats.json`).
The Claude Code native statusline reads it via its existing hook. Gemini/Codex
hooks write to it after each session. The shell PROMPT_COMMAND reads it to
render the bar between non-Claude prompts.

---


All notable changes to Zikra are documented in this file.

The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to semver.

## [1.0.8] — 2026-04-21

### Changed

- **Statusline project detection now follows cwd.** `hooks/zikra-statusline.js`
  walks up from the current working directory looking for a `CLAUDE.md`
  containing `project: <name>` (or `ZIKRA_PROJECT=<name>`) and uses the first
  match. `global` is explicitly skipped so a root-level default does not
  override a more-specific project deeper in the tree. Falls back to the
  cached project in `~/.claude/cache/zikra-stats.json` if no match is found.
  Fixes sessions showing `global` while working inside a known project repo.

- **Statusline now respects the reported context window size.** Previously
  always framed usage against 200K. Now uses whatever size Claude Code
  reports in `context_window.context_window_size` for the session — no
  hardcoded limit. If the user is on a 1M-variant model the bar renders
  against 1M; on a 200K session it renders against 200K; if Anthropic
  ships a new window size tomorrow the statusline picks it up with no
  code change. 200K is kept only as a last-ditch fallback when the
  payload omits the field entirely.

## [1.0.7] — 2026-04-20

- Register `hygiene_report` in the hardcoded command list for `zikra_help`.
- Cache `orphan_count` and show a stale-memory warning in the statusline.
- Register `zikra_hygiene_report` MCP tool.
- New `hygiene.py` command — orphan / stale memory detection.
- Render wikilink edges bold purple in graph; add backlinks endpoint.
- `get_memory` returns `links_out` and `links_in` (wikilink backlinks).
- `save_memory` parses `[[wikilinks]]` and stores edges in `memory_links`.
- New `memory_links` table.
- New `delete_memory` command with admin role gating.
