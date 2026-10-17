"""Synthetic rows and tiny real git repos for tests/test_lineage.py."""
import datetime as dt
import shutil
import subprocess
from pathlib import Path

from snapshot.model import Submission

T0 = dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
PATHS = ["src/main.py"]


def at(minutes):
    return T0 + dt.timedelta(minutes=minutes)


def sub(i, minutes, solver="alice", promoted=False, finished=None, **kw):
    kw.setdefault("finished_at", at(minutes) if finished is None else finished)
    return Submission(
        id=i, benchmark="b1", solver=solver, created_at=at(minutes),
        status="accepted" if promoted else "rejected", promoted=promoted,
        cancelled=False, score=None, **kw)


def lines(prefix, n):
    return [f"{prefix}{k}" for k in range(n)]


def git(cwd, *args, text=True):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", *args], cwd=cwd,
                       check=True, capture_output=True, text=text)
    return r.stdout.strip() if text else r.stdout


class Repo:
    """A non-bare repo whose commits hold arbitrary file contents."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True)
        git(self.path, "init", "-q")
        git(self.path, "config", "uploadpack.allowAnySHA1InWant", "true")
        git(self.path, "config", "uploadpack.allowReachableSHA1InWant", "true")
        self.n = 0

    def commit(self, files: dict) -> str:
        """files: path -> list[str] lines, or bytes. Replaces the whole worktree."""
        for p in self.path.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
        for name, content in files.items():
            f = self.path / name
            f.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                f.write_bytes(content)
            else:
                f.write_text("".join(x + "\n" for x in content))
        self.n += 1
        git(self.path, "add", "-A")
        git(self.path, "commit", "-q", "--allow-empty", "-m", f"c{self.n}")
        return git(self.path, "rev-parse", "HEAD")


class World:
    """Rows plus one commit per row in a single repo (the repo is also the mirror)."""

    def __init__(self, tmp_path):
        self.repo = Repo(tmp_path / "world")
        self.path = str(self.repo.path)
        self.subs = {}
        self.trees = {}  # sub id -> commit sha (absent = no tree)

    def add(self, i, minutes, content, **kw):
        s = sub(i, minutes, **kw)
        self.subs[i] = s
        if content is not None:
            self.trees[i] = self.repo.commit({"src/main.py": content})
        return s

    def parents(self, child, earlier=None, attribution=None, own=None):
        from lineage import parents
        if earlier is None:
            earlier = [s for s in self.subs.values() if s.id != child.id]
        return parents.parents(child, earlier, attribution or {}, self.trees,
                               own or [], mirror=self.path, paths=PATHS)
