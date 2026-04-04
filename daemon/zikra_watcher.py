#!/usr/bin/env python3
"""
zikra_watcher.py v7
Session capture daemon for Zikra persistent memory.

Polls Claude Code transcript JSONL files for mtime changes.
After DEBOUNCE seconds of stability, fires a log_run to the Zikra webhook.
Also handles short ad-hoc sessions (stable 2s, age < DEBOUNCE).

Works on: WSL, native Linux, macOS.
Uses only Python stdlib — no dependencies required.
"""

import os
import json
import time
import glob
import platform
import socket
import urllib.request
import urllib.error
import sys

# ── Configuration (patched by install.sh) ────────────────────────────────────
ZIKRA_URL        = "ZIKRA_URL_PLACEHOLDER"
BEARER           = "ZIKRA_TOKEN_PLACEHOLDER"
DEFAULT_PROJECT  = "DEFAULT_PROJECT_PLACEHOLDER"
ZIKRA_USER_AGENT = "curl/7.81.0"


def _load_token_file() -> None:
    """Load ~/.zikra/token into os.environ — stdlib only, no deps."""
    path = os.path.expanduser("~/.zikra/token")
    try:
        with open(path) as _f:
            for _line in _f:
                _line = _line.strip()
                if '=' in _line and not _line.startswith('#'):
                    _k, _, _v = _line.partition('=')
                    if _k.strip() and _k.strip() not in os.environ:
                        os.environ[_k.strip()] = _v.strip()
    except OSError:
        pass


_load_token_file()

# Override from environment when install.sh did not patch the file
# (e.g. running directly from source checkout)
if "PLACEHOLDER" in ZIKRA_URL:
    ZIKRA_URL = os.getenv("ZIKRA_URL", ZIKRA_URL)
if "PLACEHOLDER" in BEARER:
    BEARER = os.getenv("ZIKRA_TOKEN", BEARER)
if "PLACEHOLDER" in DEFAULT_PROJECT:
    DEFAULT_PROJECT = os.getenv("ZIKRA_PROJECT", os.getenv("DEFAULT_PROJECT", DEFAULT_PROJECT))
DEBOUNCE         = 30          # seconds of mtime stability before firing
POLL_INTERVAL    = 5           # seconds between polls
TRANSCRIPT_GLOB  = os.path.expanduser("~/.claude/projects/**/*.jsonl")

# ── Portable temp paths — use ~/.claude/ to avoid /tmp assumptions ────────────
_ZIKRA_STATE_DIR = os.path.expanduser("~/.claude")
PROMPT_ID_FILE   = os.path.join(_ZIKRA_STATE_DIR, ".zikra_prompt_id")
BOOT_MARKER      = os.path.join(_ZIKRA_STATE_DIR, ".zikra_boot")
LOG_PREFIX       = "[zikra_watcher]"


# ── Boot marker ───────────────────────────────────────────────────────────────
try:
    with open(BOOT_MARKER, 'w') as _f:
        _f.write(str(time.time()))
except OSError:
    pass


# ── Portable hostname ─────────────────────────────────────────────────────────
def get_hostname() -> str:
    """Return short hostname — works on Linux, macOS, and Windows."""
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown"))


# ── Zikra POST ────────────────────────────────────────────────────────────────

def zikra_post(payload: dict) -> bool:
    """POST JSON payload to Zikra. Returns True on HTTP 200."""
    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            ZIKRA_URL,
            data=data,
            headers={
                "Authorization":  f"Bearer {BEARER}",
                "Content-Type":   "application/json",
                "User-Agent":     ZIKRA_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            _ = resp.read()
            return resp.status == 200
    except Exception as exc:
        _log(f"POST failed: {exc}")
        return False


# ── Session extraction ────────────────────────────────────────────────────────

def extract_session_info(path: str) -> dict:
    """
    Parse a JSONL transcript and return:
      session_id, token counts, last assistant text (max 300 chars).
    """
    session_id            = ""
    tokens_input          = 0
    tokens_output         = 0
    tokens_cache_read     = 0
    tokens_cache_creation = 0
    last_assistant        = ""

    try:
        with open(path, "r", errors="replace") as f:
            lines = [l.strip() for l in f if l.strip()]

        for raw in lines:
            try:
                entry = json.loads(raw)
            except Exception:
                continue

            # Session ID
            if not session_id:
                session_id = (
                    entry.get("session_id")
                    or entry.get("message", {}).get("session_id", "")
                    or ""
                )

            # Token usage — two possible locations
            usage = (
                entry.get("usage")
                or entry.get("message", {}).get("usage")
                or {}
            )
            if usage:
                tokens_input          += usage.get("input_tokens",                  0)
                tokens_output         += usage.get("output_tokens",                 0)
                tokens_cache_read     += usage.get("cache_read_input_tokens",       0)
                tokens_cache_creation += usage.get("cache_creation_input_tokens",   0)

            # Last assistant message text
            role = entry.get("type") or entry.get("role") or ""
            msg  = entry.get("message", {})
            if role == "assistant" or msg.get("role") == "assistant":
                content = entry.get("content") or msg.get("content") or ""
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            last_assistant = block.get("text", "")
                elif isinstance(content, str):
                    last_assistant = content

    except Exception as exc:
        _log(f"extract error for {os.path.basename(path)}: {exc}")

    return {
        "session_id":            session_id,
        "tokens_input":          tokens_input,
        "tokens_output":         tokens_output,
        "tokens_cache_read":     tokens_cache_read,
        "tokens_cache_creation": tokens_cache_creation,
        "last_assistant":        last_assistant[:300],
    }


# ── Prompt ID linkage ─────────────────────────────────────────────────────────

def consume_prompt_id() -> str:
    """Read and delete the prompt ID file. Returns empty string if absent."""
    try:
        if os.path.exists(PROMPT_ID_FILE):
            with open(PROMPT_ID_FILE) as f:
                pid = f.read().strip()
            os.remove(PROMPT_ID_FILE)
            return pid
    except Exception:
        pass
    return ""


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    try:
        print(f"{LOG_PREFIX} {msg}", flush=True)
    except Exception:
        pass


# ── Main poll loop ────────────────────────────────────────────────────────────

def main() -> None:
    runner = get_hostname()

    # path → {"mtime": float, "stable_since": float, "fired": bool}
    seen: dict = {}

    _log(f"started — watching {TRANSCRIPT_GLOB}")
    _log(f"debounce={DEBOUNCE}s  poll={POLL_INTERVAL}s  runner={runner}")

    while True:
        time.sleep(POLL_INTERVAL)

        try:
            files = glob.glob(TRANSCRIPT_GLOB, recursive=True)
        except Exception as exc:
            _log(f"glob error: {exc}")
            continue

        now = time.time()

        for path in files:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                seen.pop(path, None)
                continue

            prev = seen.get(path)

            # First time seeing this file
            if prev is None:
                seen[path] = {"mtime": mtime, "stable_since": now, "fired": False}
                continue

            # File changed — reset
            if mtime != prev["mtime"]:
                seen[path] = {"mtime": mtime, "stable_since": now, "fired": False}
                continue

            # Already fired for this version
            if prev["fired"]:
                continue

            stable_for = now - prev["stable_since"]
            file_age   = now - mtime

            # Fire condition:
            #   Normal session: stable for >= DEBOUNCE seconds
            #   Short session:  stable >= 2s AND file age < DEBOUNCE (catch quick runs)
            should_fire = (
                stable_for >= DEBOUNCE
                or (stable_for >= 2.0 and file_age < DEBOUNCE)
            )

            if not should_fire:
                continue

            seen[path]["fired"] = True

            info      = extract_session_info(path)
            prompt_id = consume_prompt_id()

            output_summary = (
                info["last_assistant"][:250]
                if info["last_assistant"]
                else "Session ended"
            )

            payload: dict = {
                "command":               "log_run",
                "project":               DEFAULT_PROJECT,
                "runner":                runner,
                "status":                "success",
                "output_summary":        output_summary,
                "tokens_input":          info["tokens_input"],
                "tokens_output":         info["tokens_output"],
                "tokens_cache_read":     info["tokens_cache_read"],
                "tokens_cache_creation": info["tokens_cache_creation"],
            }

            if info["session_id"]:
                payload["session_id"] = info["session_id"]

            if prompt_id:
                payload["prompt_run_id"] = prompt_id

            ok = zikra_post(payload)
            _log(
                f"log_run {'OK' if ok else 'FAIL'} — "
                f"{os.path.basename(path)} "
                f"(in={info['tokens_input']} out={info['tokens_output']})"
            )

        # Prune seen entries for files that no longer exist on disk
        stale = [p for p in seen if not os.path.exists(p)]
        for p in stale:
            seen.pop(p, None)

        # Cap seen dict to 1000 most-recently-seen entries to bound memory
        if len(seen) > 1000:
            oldest = sorted(seen, key=lambda p: seen[p].get("stable_since", 0))
            for p in oldest[:len(seen) - 1000]:
                seen.pop(p, None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _log("stopped by user")
        sys.exit(0)
