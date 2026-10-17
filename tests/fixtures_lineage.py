"""Synthetic rows and trees for tests/test_lineage.py."""
import datetime as dt
import subprocess
from pathlib import Path

from snapshot.model import Submission

T0 = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)


def at(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def sub(i, minutes, solver="alice", promoted=False, commit_sha=None, **kw):
    return Submission(
        id=i, benchmark="b1", solver=solver, created_at=at(minutes),
        status="accepted" if promoted else "rejected", promoted=promoted,
        cancelled=False, score=None, commit_sha=commit_sha, **kw)


def tree(*lines, path="src/main.py"):
    return {path: list(lines)}


def lines(prefix, n):
    return [f"{prefix}{k}" for k in range(n)]


def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", *args], cwd=cwd,
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def make_repo(root: Path):
    """Two commits touching an editable and a non-editable path."""
    repo = root / "origin"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "src").mkdir()
    (repo / "src/main.py").write_text("a\nb\nc\n")
    (repo / "README.md").write_text("readme v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "one")
    sha1 = git(repo, "rev-parse", "HEAD")
    (repo / "src/main.py").write_text("a\nB\nc\nd\n")
    (repo / "README.md").write_text("readme v2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "two")
    sha2 = git(repo, "rev-parse", "HEAD")
    return repo, sha1, sha2
