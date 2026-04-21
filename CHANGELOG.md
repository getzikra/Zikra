# Changelog

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
