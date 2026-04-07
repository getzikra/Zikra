import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


class ServerContext:
    def __init__(self):
        self.port = _find_free_port()
        self.db_path = f"/tmp/zikra_fix_{self.port}.db"
        self.log_path = f"/tmp/zikra_fix_{self.port}.log"
        self.base = f"http://127.0.0.1:{self.port}"
        self.client = httpx.Client(timeout=10.0)
        self.proc = None

    def start(self):
        env = os.environ.copy()
        env.update(
            {
                "ZIKRA_TOKEN": "fix-token-123",
                "ZIKRA_PORT": str(self.port),
                "ZIKRA_DB_PATH": self.db_path,
                "ZIKRA_SKIP_ONBOARDING": "1",
                "DB_BACKEND": "sqlite",
            }
        )
        log_handle = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "zikra"],
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        self._wait_until_ready()

    def _wait_until_ready(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                response = self.client.get(f"{self.base}/health")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"server did not start on port {self.port}")

    def stop(self):
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.client.close()
        for path in (self.db_path, self.log_path):
            try:
                Path(path).unlink()
            except FileNotFoundError:
                pass

    def post(self, command: str, extra: dict | None = None, token: str = "fix-token-123"):
        payload = {"command": command}
        if extra:
            payload.update(extra)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        return self.client.post(f"{self.base}/webhook/zikra", headers=headers, json=payload)

    def get(self, path: str, token: str = "fix-token-123", **headers):
        req_headers = {"Authorization": f"Bearer {token}"}
        req_headers.update(headers)
        return self.client.get(f"{self.base}{path}", headers=req_headers)


def run_test(test_fn):
    ctx = ServerContext()
    ctx.start()
    try:
        test_fn(ctx)
        print(f"PASS: {test_fn.__name__}")
    except Exception as exc:
        print(f"FAIL: {test_fn.__name__} - {exc}")
    finally:
        ctx.stop()


def test_get_memory_enforces_project_scope_by_id(ctx: ServerContext):
    save = ctx.post(
        "save_memory",
        {
            "project": "proj_a",
            "title": "ID scoped memory",
            "memory_type": "decision",
            "content_md": "alpha only",
        },
    )
    assert save.status_code == 200, save.text
    saved = save.json()
    assert saved.get("status") == "saved", saved
    memory_id = saved["id"]

    good = ctx.post("get_memory", {"project": "proj_a", "id": memory_id})
    assert good.status_code == 200, good.text
    good_body = good.json()
    assert good_body.get("id") == memory_id, good_body
    assert good_body.get("project") == "proj_a", good_body

    bad = ctx.post("get_memory", {"project": "proj_b", "id": memory_id})
    assert bad.status_code == 200, bad.text
    bad_body = bad.json()
    assert bad_body == {"error": "Memory not found", "_use_command": "get_memory"}, bad_body


def test_create_token_rejects_owner_and_arbitrary_roles(ctx: ServerContext):
    owner = ctx.post("create_token", {"label": "owner-escalation", "role": "owner"})
    assert owner.status_code == 200, owner.text
    owner_body = owner.json()
    assert owner_body["error"] == "Invalid role 'owner'.", owner_body
    assert owner_body["allowed_roles"] == ["admin", "developer", "viewer"], owner_body

    bad = ctx.post("create_token", {"label": "bad-role", "role": "superadmin"})
    assert bad.status_code == 200, bad.text
    bad_body = bad.json()
    assert bad_body["error"] == "Invalid role 'superadmin'.", bad_body
    assert bad_body["allowed_roles"] == ["admin", "developer", "viewer"], bad_body

    ok = ctx.post("create_token", {"label": "viewer-ok", "role": "viewer"})
    assert ok.status_code == 200, ok.text
    ok_body = ok.json()
    assert ok_body["status"] == "created", ok_body
    assert ok_body["label"] == "viewer-ok", ok_body
    assert ok_body["person_name"] == "viewer-ok", ok_body
    assert ok_body["role"] == "viewer", ok_body
    assert ok_body["token"].startswith("token-"), ok_body


def test_log_error_requires_message_field(ctx: ServerContext):
    wrong = ctx.post("log_error", {"project": "proj", "title": "wrong", "content_md": "wrong"})
    assert wrong.status_code == 200, wrong.text
    wrong_body = wrong.json()
    assert "message is required" in wrong_body["error"], wrong_body
    assert "use 'message' instead" in wrong_body["hint"], wrong_body

    empty = ctx.post("log_error", {"project": "proj"})
    assert empty.status_code == 200, empty.text
    empty_body = empty.json()
    assert "message is required" in empty_body["error"], empty_body

    spaces = ctx.post("log_error", {"project": "proj", "message": "   "})
    assert spaces.status_code == 200, spaces.text
    spaces_body = spaces.json()
    assert "message is required" in spaces_body["error"], spaces_body

    good = ctx.post("log_error", {"project": "proj", "message": "real error", "context_md": "details"})
    assert good.status_code == 200, good.text
    good_body = good.json()
    assert good_body["status"] == "logged", good_body
    assert isinstance(good_body.get("id"), str) and good_body["id"], good_body


def test_promote_requirement_scopes_title_lookup_by_project(ctx: ServerContext):
    alpha = ctx.post(
        "save_requirement",
        {"project": "alpha", "title": "Shared Req", "content_md": "alpha body"},
    )
    beta = ctx.post(
        "save_requirement",
        {"project": "beta", "title": "Shared Req", "content_md": "beta body"},
    )
    assert alpha.status_code == 200 and beta.status_code == 200, (alpha.text, beta.text)

    promoted = ctx.post(
        "promote_requirement",
        {"project": "alpha", "title": "Shared Req", "promote_to": "decision"},
    )
    assert promoted.status_code == 200, promoted.text
    promoted_body = promoted.json()
    assert promoted_body["status"] == "promoted", promoted_body

    alpha_get = ctx.post("get_memory", {"project": "alpha", "title": "Shared Req"})
    beta_get = ctx.post("get_memory", {"project": "beta", "title": "Shared Req"})
    assert alpha_get.status_code == 200 and beta_get.status_code == 200, (alpha_get.text, beta_get.text)
    assert alpha_get.json()["memory_type"] == "decision", alpha_get.json()
    assert beta_get.json()["memory_type"] == "requirement", beta_get.json()


def test_search_limit_is_clamped_for_negative_and_huge_values(ctx: ServerContext):
    for i in range(120):
        response = ctx.post(
            "save_memory",
            {
                "project": "limitproof",
                "title": f"Limit {i}",
                "content_md": "decision corpus",
            },
        )
        assert response.status_code == 200, response.text

    negative = ctx.post(
        "search",
        {"project": "limitproof", "query": "decision corpus", "limit": -5},
    )
    assert negative.status_code == 200, negative.text
    negative_body = negative.json()
    assert negative_body["count"] == 1, negative_body
    assert len(negative_body["results"]) == 1, negative_body

    huge = ctx.post(
        "search",
        {"project": "limitproof", "query": "decision corpus", "limit": 9999999},
    )
    assert huge.status_code == 200, huge.text
    huge_body = huge.json()
    assert huge_body["count"] == 100, huge_body
    assert len(huge_body["results"]) == 100, huge_body


def test_bad_json_returns_400(ctx: ServerContext):
    resp = ctx.client.post(
        f"{ctx.base}/webhook/zikra",
        content=b"this is not json",
        headers={
            "Authorization": "Bearer fix-token-123",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "error" in body, f"expected 'error' key in response: {body}"


def test_mcp_sse_advertises_correct_messages_path(ctx: ServerContext):
    headers = {
        "Authorization": "Bearer fix-token-123",
        "Accept": "text/event-stream",
    }
    with ctx.client.stream("GET", f"{ctx.base}/mcp/sse", headers=headers) as sse:
        assert sse.status_code == 200, sse.text
        assert "text/event-stream" in sse.headers.get("content-type", ""), sse.headers
        chunks = []
        for chunk in sse.iter_text():
            if chunk:
                chunks.append(chunk)
            if any("session_id=" in piece for piece in chunks):
                break
        body = "".join(chunks)
    assert "/mcp/messages?session_id=" in body, body
    assert "/mcp/mcp/messages" not in body, body


def test_viewer_token_can_read_but_cannot_write(ctx: ServerContext):
    seed = ctx.post(
        "save_memory",
        {"project": "rbac", "title": "RBAC seed", "content_md": "viewer can search this"},
    )
    assert seed.status_code == 200, seed.text
    memory_id = seed.json()["id"]

    token_resp = ctx.post("create_token", {"label": "rbac-viewer", "role": "viewer"})
    assert token_resp.status_code == 200, token_resp.text
    viewer_token = token_resp.json()["token"]

    search = ctx.post("search", {"project": "rbac", "query": "viewer"}, token=viewer_token)
    assert search.status_code == 200, search.text
    assert search.json()["count"] >= 1, search.json()

    get_memory = ctx.post("get_memory", {"project": "rbac", "id": memory_id}, token=viewer_token)
    assert get_memory.status_code == 200, get_memory.text
    assert get_memory.json()["id"] == memory_id, get_memory.json()

    save = ctx.post(
        "save_memory",
        {"project": "rbac", "title": "blocked", "content_md": "nope"},
        token=viewer_token,
    )
    assert save.status_code == 403, save.text
    assert save.json() == {"error": "insufficient permissions", "required_role": "developer"}, save.json()

    create = ctx.post("create_token", {"label": "blocked", "role": "viewer"}, token=viewer_token)
    assert create.status_code == 403, create.text
    assert create.json() == {"error": "insufficient permissions", "required_role": "owner"}, create.json()


TESTS = [
    test_get_memory_enforces_project_scope_by_id,
    test_create_token_rejects_owner_and_arbitrary_roles,
    test_log_error_requires_message_field,
    test_promote_requirement_scopes_title_lookup_by_project,
    test_search_limit_is_clamped_for_negative_and_huge_values,
    test_bad_json_returns_400,
    test_mcp_sse_advertises_correct_messages_path,
    test_viewer_token_can_read_but_cannot_write,
]


def run_all() -> bool:
    results = []
    for test_fn in TESTS:
        ctx = ServerContext()
        ctx.start()
        try:
            test_fn(ctx)
            results.append((test_fn.__name__, "PASS", None))
        except Exception as exc:
            results.append((test_fn.__name__, "FAIL", str(exc)))
        finally:
            ctx.stop()

    print()
    print(f"{'#':<4} {'Test':<55} {'Result'}")
    print("-" * 80)
    passed = 0
    for idx, (name, status, err) in enumerate(results, 1):
        print(f"{idx:<4} {name:<55} {status}")
        if err:
            print(f"     Error: {err}")
        if status == "PASS":
            passed += 1
    print()
    print(f"Results: {passed}/{len(results)} passed")
    return passed == len(results)


def test_suite():
    assert run_all(), "One or more integration tests failed"


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
