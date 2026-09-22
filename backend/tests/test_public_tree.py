"""Publishing gates inspect the index and every outgoing commit, including forced files."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

CHECKER_PATH = Path(__file__).resolve().parents[2] / "scripts/check_public_tree.py"
spec = importlib.util.spec_from_file_location("public_tree_check", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.mark.parametrize(
    "name",
    [
        "backend/notes.json",
        "backend/docs/extra.py",
        "frontend/src/MEMORY.md",
        "backend/.env",
        "backend/.local-data/raw.json",
        "frontend/test-results/a.png",
        "backend/scripts/report.json",
        "backend/app/secret.pem",
    ],
)
def test_private_and_document_paths_are_rejected(name):
    assert checker.path_errors(name)


def test_essential_code_and_explicit_license_are_allowed():
    for name in (
        "backend/app/agents/agent_player.py",
        "fixtures/clue-citations.json",
        "frontend/public/lobby/NotoSerifSC-OFL.txt",
    ):
        assert not checker.path_errors(name)


def test_secret_and_large_file_rejection():
    secret = ("sk-" + "aB9" * 15).encode()
    assert checker.content_errors("backend/app/config.py", secret)
    assert checker.content_errors("frontend/public/large.png", b"x" * (5 * 1024 * 1024 + 1))


def test_forced_ignored_file_and_deleted_intermediate_commit_are_checked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path).decode().strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / ".gitignore").write_text(".local-data/\n")
    git("add", ".gitignore")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    local = tmp_path / "backend/.local-data"
    local.mkdir(parents=True)
    (local / "report.json").write_text("{}")
    git("add", "-f", "backend/.local-data/report.json")
    assert any("report.json" in e for e in checker.check_tree(None, contracts=False))
    git("commit", "-qm", "accidental runtime data")
    leaked = git("rev-parse", "HEAD")
    git("rm", "backend/.local-data/report.json")
    git("commit", "-qm", "remove runtime data")
    assert not checker.check_tree("HEAD", contracts=False)
    commits = checker.outgoing("HEAD", base)
    assert leaked in commits
    assert checker.check_tree(leaked, contracts=False)
