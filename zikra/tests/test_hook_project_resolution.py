"""Behavior tests for manifest-aware Zikra project resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_HOOK = REPO_ROOT / "hooks" / "zikra-project.sh"
CONTEXT_HOOK = REPO_ROOT / "hooks" / "zikra-context.sh"


def detect_project(cwd: Path, default: str = "global", **environment: str) -> str:
    env = {**os.environ, **environment}
    if "A2K_PROJECT" not in environment:
        env.pop("A2K_PROJECT", None)
    command = (
        f'source "{PROJECT_HOOK}"; '
        f'zikra_detect_project "$TEST_CWD" "$TEST_DEFAULT"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env={**env, "TEST_CWD": str(cwd), "TEST_DEFAULT": default},
    )
    return result.stdout.strip()


def write_manifest(root: Path, project_name: str) -> None:
    manifest_dir = root / ".a2k"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "apiVersion: a2k.a3t.ai/v0alpha1",
                "kind: ProjectBootstrap",
                "metadata:",
                f"  id: https://a3t.ai/a2k/projects/{project_name}",
                f"  name: {project_name}",
                "  owners: [https://github.com/a3tai/platform]",
                "  classification: internal",
                "spec:",
                "  roots: []",
                "  profiles: [core]",
                "  policy:",
                "    remoteFetch: disabled",
                "    mutation: proposal",
                "",
            ]
        ),
        encoding="utf-8",
    )


class HookProjectResolutionTest(unittest.TestCase):
    def test_a2k_project_override_has_highest_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, "manifest-project")
            self.assertEqual(
                detect_project(root, A2K_PROJECT="explicit-project"),
                "explicit-project",
            )

    def test_walks_up_to_manifest_and_uses_authorized_metadata_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, "manifest-project")
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/manifest-project.git",
                ],
                check=True,
            )
            nested = root / "src" / "nested"
            nested.mkdir(parents=True)
            self.assertEqual(detect_project(nested), "manifest-project")

    def test_foreign_manifest_cannot_override_git_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_manifest(root, "foreign-project")
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/local-project.git",
                ],
                check=True,
            )
            self.assertEqual(detect_project(root), "local-project")

    def test_trusted_map_authorizes_a_manifest_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / ".zikra").mkdir(parents=True)
            project = root / "checkout"
            project.mkdir()
            write_manifest(project, "mapped-project")
            (home / ".zikra" / "projects.map").write_text(
                f"{project}=mapped-project\n",
                encoding="utf-8",
            )
            self.assertEqual(
                detect_project(project, HOME=str(home)),
                "mapped-project",
            )

    def test_oversized_manifest_falls_back_without_delay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".a2k").mkdir()
            (root / ".a2k" / "manifest.yaml").write_text(
                "#" * (1024 * 1024 + 1),
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/fallback-repo.git",
                ],
                check=True,
            )
            self.assertEqual(detect_project(root), "fallback-repo")

    def test_malformed_manifest_falls_back_to_git_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".a2k").mkdir()
            (root / ".a2k" / "manifest.yaml").write_text(
                "metadata:\n  name: [not-a-scalar]\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    root,
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/example/fallback-repo.git",
                ],
                check=True,
            )
            self.assertEqual(detect_project(root), "fallback-repo")

    def test_context_hook_fails_silent_when_server_is_down(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            claude = home / ".claude"
            claude.mkdir(parents=True)
            (claude / "zikra-project.sh").write_text(
                PROJECT_HOOK.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            project = root / "project"
            project.mkdir()
            write_manifest(project, "manifest-project")
            payload = json.dumps({"cwd": str(project)})
            hook = CONTEXT_HOOK.read_text(encoding="utf-8")
            hook = hook.replace("ZIKRA_URL_PLACEHOLDER", "http://127.0.0.1:1")
            hook = hook.replace("ZIKRA_TOKEN_PLACEHOLDER", "test-reference")
            hook = hook.replace("DEFAULT_PROJECT_PLACEHOLDER", "global")
            installed_hook = root / "zikra-context.sh"
            installed_hook.write_text(hook, encoding="utf-8")

            try:
                result = subprocess.run(
                    ["bash", installed_hook],
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    env={**os.environ, "HOME": str(home)},
                )
            except subprocess.TimeoutExpired as error:
                self.fail(f"context hook did not fail fast: {error}")

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
