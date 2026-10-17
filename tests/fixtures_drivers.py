"""Synthetic study tree for tests/test_drivers.py (spec 0001 sections 5 and 5.8).

build_study(root) writes, under root, a complete miniature repo:
  snapshot/raw/        frozen snapshot, 3 synthetic benchmarks (loadable by snapshot.load(root=...))
  lineage/frozen/      parents.json.gz, missing.json, SHA256SUMS per benchmark
  families/table.yaml, outcomes/denominator.yaml (copies of the real files)
  docs/prereg.md, docs/prereg-manifest.json (analysis.lock.write_manifest)
  placeholder code under snapshot/ families/ lineage/ outcomes/ analysis/ (hashed by the lock)
and a git repo tagged prereg-v1.

The planted truth (Study.truth) drives the assertions: a cross-family step multiplies the odds of
promotion by exp(BETA) for ordinary cross-solver rows; own-lineage rows carry no family effect.
Each excluded row kind meets exactly one exclusion rule, so counts are unambiguous.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lineage import build as lbuild
from lineage import trees as trees_mod

REPO = Path(__file__).resolve().parent.parent

ECDSA = "gpsanant/ecdsafail-challenge"
BENCH_A = "eigenlabs/bench-a"
BENCH_B = "eigenlabs/bench-b"

T0 = dt.datetime(2026, 3, 2, 0, 0, tzinfo=dt.timezone.utc)  # a Monday
GPT = "GPT 6"
CLAUDE = "Claude Opus 5.5"
DEVIN = "Devin"
OPEN_HOURS = 120           # benchmarks open at T0 + 120 h; window rows start at 170 h
BETA = 1.2                 # planted log odds ratio of a cross-family step
N_WEEK0 = 30               # rows before the confirmatory window
N_LATER = 530
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]

SPECS = {
    ECDSA: dict(own=140, own_switch=70, multi=12, novel=12, unk=15, seed=11, idx=0),
    BENCH_A: dict(own=40, own_switch=10, multi=9, novel=14, unk=11, seed=22, idx=1),
    BENCH_B: dict(own=140, own_switch=70, multi=15, novel=10, unk=13, seed=33, idx=2),
}

CODE = ["snapshot/load.py", "families/mapper.py", "lineage/parents.py", "outcomes/promotion.py",
        "analysis/__init__.py", "analysis/dataset.py"]


def slug_of(name: str) -> str:
    return name.replace("/", "__")


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(json.dumps(obj, sort_keys=True).encode())


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_snapshot_sums(raw: Path) -> None:
    files = sorted(raw.rglob("*.gz")) + [raw / "FREEZE.json"]
    (raw / "SHA256SUMS").write_text(
        "\n".join(f"{_sha(p)}  {p.relative_to(raw).as_posix()}" for p in files) + "\n")


@dataclass
class Bench:
    name: str
    raw: list                      # raw API submission dicts
    parents: dict                  # id -> (primary_link, tree_link)
    missing: list                  # tree shas that cannot be fetched
    truth: list = field(default_factory=list)   # per-row planted facts


@dataclass
class Study:
    root: Path
    benches: dict
    truth: dict                    # name -> list of row facts


def _link(ids, method, distance=None, child_side=None):
    return [list(ids), method, distance, child_side]


def _raw(i, bench_id, created, solver, model, status, *, promoted, score, sha, psha,
         harness=None, metrics=None, reason=None, note_extra=""):
    lines = [f"Model: {model}"] if model else []
    if harness:
        lines.append(f"Harness: {harness}")
    lines.append("Tried a change." + note_extra)
    return {
        "id": i, "benchmarkId": bench_id, "solverUsername": solver, "status": status,
        "note": "\n".join(lines), "officialScore": score,
        "officialMetrics": metrics,
        "promotionStatus": "promoted" if promoted else None,
        "promotedSourceRef": psha if promoted else None,
        "submissionCommitSha": sha, "createdAt": iso(created),
        "rejectionReason": reason,
        "promotionFinishedAt": iso(created + dt.timedelta(hours=1)) if promoted else None,
        "updatedAt": iso(created + dt.timedelta(minutes=30)),
    }


def gen_bench(name: str, spec: dict) -> Bench:
    rng = random.Random(spec["seed"])
    k = spec["idx"]
    tag = "abc"[k]
    regular = [f"{tag}{j:02d}" for j in range(12)]
    if name == ECDSA:
        regular[-1] = "owizdom"
    solvers = regular + ["mono", "dud"]
    shift = {s: rng.gauss(0, 0.5) for s in solvers}

    # row schedule: week 0 first, then the window
    hours = [5.0 * j for j in range(N_WEEK0)] + [170.0 + 2.5 * j for j in range(N_LATER)]
    kinds = ["normal"] * N_WEEK0
    pos = list(range(N_LATER))
    own_pos = set(rng.sample(range(100, N_LATER), spec["own"]))
    rest = [p for p in pos if p not in own_pos]
    pick = rng.sample(rest, spec["multi"] + spec["novel"] + spec["unk"])
    special = {}
    for n, p in enumerate(pick):
        special[p] = ("multi" if n < spec["multi"] else
                      "novel" if n < spec["multi"] + spec["novel"] else "unk")
    for p in pos:
        kinds.append("own" if p in own_pos else special.get(p, "normal"))
    flags = [True] * spec["own_switch"] + [False] * (spec["own"] - spec["own_switch"])
    rng.shuffle(flags)
    # exact promotions per own arm
    n_sw, n_same = spec["own_switch"], spec["own"] - spec["own_switch"]
    own_prom = {True: set(rng.sample(range(n_sw), int(0.45 * n_sw))),
                False: set(rng.sample(range(n_same), int(0.45 * n_same)))}
    own_seen = {True: 0, False: 0}

    root_id = f"{tag}root"
    root = _raw(root_id, f"id-{tag}", T0 - dt.timedelta(days=2), "zed", CLAUDE, "cancelled",
                promoted=False, score=None, sha=f"r{k}", psha=None)
    rows = [root]
    fam_of = {root_id: "Anthropic"}
    solver_of = {root_id: "zed"}
    earlier = []                   # facts for analysis rows so far
    parents, truth, missing = {}, [], []
    best = 1000.0
    n_prom = 0
    maxrow = {"q": 9000, "t": 9000}

    def fam_name(model):
        return {GPT: "OpenAI", CLAUDE: "Anthropic", DEVIN: "Unknown"}[model]

    def pool(sel):
        return [r for r in earlier if sel(r)]

    for i, (h, kind) in enumerate(zip(hours, kinds)):
        rid = f"{tag}{i:04d}"
        created = T0 + dt.timedelta(hours=h)
        week0 = i < N_WEEK0
        solver = None
        prim = _link([], "none")
        own_arm = None
        child_model = None
        prob = None
        if kind == "own":
            own_arm = flags[sum(1 for r in truth if r["kind"] == "own")]
            order = regular[:]
            rng.shuffle(order)
            parent = None
            for s in order:
                mine = [r for r in earlier if r["solver"] == s and r["family"] != "Unknown"]
                if mine:
                    parent, solver = rng.choice(mine), s
                    break
            assert parent is not None, "own-lineage parent not found"
            child_model = GPT if (fam_name(GPT) != parent["family"]) == own_arm else CLAUDE
            prim = _link([parent["id"]], "declared")
            pid = parent["id"]
            j = own_seen[own_arm]
            own_seen[own_arm] += 1
            prom = j in own_prom[own_arm]
            cross = None
        else:
            solver = rng.choice(solvers if kind == "normal" else regular)
            if kind == "unk":
                child_model = DEVIN
            elif solver == "mono":
                child_model = GPT
            else:
                child_model = rng.choice([GPT, CLAUDE])
            want_cross = False if solver == "mono" else rng.random() < 0.5
            cf = fam_name(child_model)
            if kind == "unk":
                cand = pool(lambda r: r["solver"] != solver and r["family"] != "Unknown")
                parent = rng.choice(cand) if cand else None
            else:
                cand = pool(lambda r: r["solver"] != solver and r["family"] != "Unknown"
                            and ((r["family"] != cf) == want_cross))
                parent = rng.choice(cand) if cand else None
                if kind == "normal" and rng.random() < 0.3:
                    # sometimes build on the current best (the latest promotion)
                    bests = [r for r in cand if r["promoted"]][-1:]
                    for r in earlier[::-1]:
                        if r["promoted"]:
                            if r in bests:
                                parent = r
                            break
            if kind == "novel":
                prim = _link([], "novel", 40, 30)
                pid = None
            elif kind == "multi":
                two = rng.sample(pool(lambda r: r["solver"] != solver
                                      and r["family"] != "Unknown"), 2)
                prim = _link([t["id"] for t in two], "multi")
                pid = two[0]["id"]
            else:
                pid = parent["id"] if parent else root_id
                prim = _link([pid], "declared")
            pf = fam_of[pid] if pid else None
            cross = (pf is not None and pf != cf and kind == "normal")
            if kind == "normal" and week0:
                prom = rng.random() < 0.6
            elif solver == "dud" and kind == "normal":
                prom = False
            elif kind == "normal":
                z = -1.3 + BETA * float(bool(cross)) + shift[solver]
                prom = rng.random() < 1 / (1 + math.exp(-z))
            else:
                prom = rng.random() < 0.3
        fam = fam_name(child_model)
        # tree link: usually the declared parent, sometimes a different earlier row
        tpool = [r for r in earlier]
        tp = rng.choice(tpool)["id"] if tpool and rng.random() < 0.2 else (pid if kind not in ("novel",) and pid else None)
        tree = _link([tp] if tp else [], "tree" if tp else "none", 12 if tp else None, 3 if tp else None)
        sha, psha = f"c{k}{i:05d}", f"p{k}{i:05d}"
        if prom:
            n_prom += 1
            score = 1000.0 - 0.5 * n_prom
            best = score
        else:
            score = 1000.0 + rng.random()
        metrics = None
        if name == ECDSA:
            if prom and n_prom % 4 == 0:      # a few Pareto improvements, most promotions are not
                maxrow["q"] -= 10
                maxrow["t"] -= 10
                metrics = {"qubits": maxrow["q"], "toffoli": maxrow["t"]}
            else:
                metrics = {"qubits": 9500 + rng.randint(0, 50), "toffoli": 9500 + rng.randint(0, 50)}
        harness = ["Codex", "Claude Code", "Cursor"][i % 3]   # independent of family
        extra = " Only the validation nonce changed." if (i % 37 == 5) else ""
        failed = (not prom) and kind == "normal" and not week0 and i % 41 == 7
        if failed:      # a failed row with no reason is an ambiguous failure (sensitivity 9)
            row = _raw(rid, f"id-{tag}", created, solver, child_model, "failed", promoted=False,
                       score=None, sha=sha, psha=psha, harness=harness, metrics=None,
                       reason=None, note_extra=extra)
        else:
            row = _raw(rid, f"id-{tag}", created, solver, child_model,
                       "accepted" if prom else "rejected", promoted=prom, score=score, sha=sha,
                       psha=psha, harness=harness, metrics=metrics,
                       reason=None if prom else "score did not improve current best",
                       note_extra=extra)
        rows.append(row)
        fam_of[rid] = fam
        solver_of[rid] = solver
        if week0 and prom:
            missing.append(psha)      # promoted trees in week 0 cannot be fetched: window starts in week 1
        parents[rid] = (prim, tree)
        fact = {"id": rid, "solver": solver, "kind": kind, "week0": week0, "family": fam,
                "promoted": bool(prom), "own_switch": own_arm,
                "cross_family": (bool(cross) if kind == "normal" else None),
                "parent": pid, "hours": h, "failed": failed,
                "nonce": bool(extra)}
        truth.append(fact)
        earlier.append(fact)
    return Bench(name, rows, parents, sorted(set(missing)), truth)


def _write_bench(root: Path, b: Bench, bid_idx: int) -> None:
    raw = root / "snapshot" / "raw"
    slug = slug_of(b.name)
    meta = {"benchmark": {
        "id": f"id-{'abc'[bid_idx]}", "name": b.name, "direction": "-",
        "editablePaths": ["src/main.py"], "sourceUrl": f"https://example.invalid/{slug}",
        "openedAt": iso(T0 + dt.timedelta(hours=OPEN_HOURS)), "minScoreImprovementBips": None,
        "baselineScore": 1000.0 + 5}}
    _gz(raw / slug / "benchmark.json.gz", meta)
    _gz(raw / slug / "submissions.json.gz", {"submissions": b.raw})
    out = {}
    for sid, (prim, tree) in b.parents.items():
        out[sid] = {"primary": prim, "tree": tree, "dropped": []}
    fro = root / "lineage" / "frozen"
    trees_mod._gz(fro / slug / "parents.json.gz", out)
    trees_mod.write_missing(fro / slug, b.missing)


def write_freeze(root: Path, counts: dict) -> None:
    raw = root / "snapshot" / "raw"
    (raw / "FREEZE.json").write_text(json.dumps(
        {"fetched_at": "2026-10-10T12:00:00Z", "api": "https://example.invalid/api",
         "counts": counts, "attribution": []}))
    write_snapshot_sums(raw)
    lbuild.write_sha256sums(root / "lineage" / "frozen")


def git(root, *args):
    return subprocess.run(GIT + list(args), cwd=root, check=True, capture_output=True,
                          text=True).stdout


def build_study(root: Path, specs=None) -> Study:
    root = Path(root)
    specs = specs or SPECS
    benches, counts = {}, {}
    for name, spec in specs.items():
        b = gen_bench(name, spec)
        _write_bench(root, b, spec["idx"])
        benches[name] = b
        counts[name] = len(b.raw)
    write_freeze(root, counts)
    (root / "families").mkdir(parents=True, exist_ok=True)
    (root / "outcomes").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "families" / "table.yaml", root / "families" / "table.yaml")
    shutil.copy(REPO / "outcomes" / "denominator.yaml", root / "outcomes" / "denominator.yaml")
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "prereg.md").write_text("synthetic prereg\nmargin: [0.80, 1.25]\n")
    for c in CODE:
        p = root / c
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# placeholder {c}\n")
    from analysis import lock
    lock.write_manifest(root)
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "freeze")
    git(root, "tag", "prereg-v1")
    return Study(root, benches, {n: b.truth for n, b in benches.items()})


# ---------------------------------------------------------------- criteria study (spec 5.6)

class RootSnapshot:
    """The snapshot package bound to one raw directory: benchmarks, load, benchmark_meta, attribution."""

    def __init__(self, root):
        self.raw = Path(root) / "snapshot" / "raw"

    def benchmarks(self):
        from snapshot import load
        return load.benchmarks(self.raw)

    def load(self, benchmark):
        from snapshot import load
        return load.load(benchmark, self.raw)

    def benchmark_meta(self, benchmark):
        from snapshot import load
        return load.benchmark_meta(benchmark, self.raw)

    def attribution(self, benchmark):
        from snapshot import load
        return load.attribution(benchmark, self.raw)


CRITERIA = {
    # name: (rows, promoted, claude_rows, fetchable)
    "x/pass": (520, 120, 260, True),
    "x/edge": (500, 100, 50, True),             # every threshold met exactly
    "x/few-rows": (499, 150, 250, True),
    "x/few-promoted": (520, 99, 260, True),
    "x/one-family": (520, 150, 20, True),       # Anthropic share 3.8% < 10%
    "x/unfetchable": (520, 150, 260, False),    # every tree commit is in missing.json
    ECDSA: (30, 3, 15, True),                   # fails every size rule, still included
}


def build_criteria_study(root: Path) -> Path:
    root = Path(root)
    counts = {}
    for name, (n, n_prom, n_claude, fetchable) in CRITERIA.items():
        slug = slug_of(name)
        miss = []
        order = sorted(range(n), key=lambda i: (i * 7919) % n)
        claude_idx = set(order[:n_claude])
        prom_idx = set(sorted(range(n), key=lambda i: (i * 104729) % n)[:n_prom])
        subs = []
        for i in range(n):
            prom = i in prom_idx
            model = CLAUDE if i in claude_idx else GPT
            created = T0 + dt.timedelta(hours=2 * i)
            sha, psha = f"c{slug}{i}", f"p{slug}{i}"
            subs.append(_raw(f"{slug}-{i}", "id-x", created, f"u{i % 9}", model,
                             "accepted" if prom else "rejected", promoted=prom,
                             score=1000.0 - i * 0.01 if prom else 1100.0, sha=sha, psha=psha,
                             reason=None if prom else "score did not improve current best"))
            if not fetchable:
                miss.append(psha if prom else sha)
        raw = root / "snapshot" / "raw"
        _gz(raw / slug / "benchmark.json.gz", {"benchmark": {
            "id": "id-x", "name": name, "direction": "-", "editablePaths": ["src/main.py"],
            "sourceUrl": "https://example.invalid", "openedAt": iso(T0 - dt.timedelta(days=1)),
            "minScoreImprovementBips": None, "baselineScore": 1200.0}})
        _gz(raw / slug / "submissions.json.gz", {"submissions": subs})
        counts[name] = len(subs)
        fro = root / "lineage" / "frozen"
        trees_mod._gz(fro / slug / "parents.json.gz", {})
        trees_mod.write_missing(fro / slug, miss)
    write_freeze(root, counts)
    return root


# ---------------------------------------------------------------- edits that re-lock the tree

def retag(root: Path) -> None:
    """Re-sign the manifest and move prereg-v1 to a new commit, so the lock check still passes."""
    from analysis import lock
    lock.write_manifest(root)
    git(root, "add", "-A")
    git(root, "commit", "-qm", "edit")
    git(root, "tag", "-f", "prereg-v1")


def _read_gz(p: Path):
    with gzip.open(p, "rb") as f:
        return json.loads(f.read())


def edit_notes(root: Path, name: str, notes: dict) -> None:
    """Replace the free-text body (everything after the Harness line) of the given rows' notes."""
    raw = Path(root) / "snapshot" / "raw"
    p = raw / slug_of(name) / "submissions.json.gz"
    data = _read_gz(p)
    for r in data["submissions"]:
        if r["id"] in notes:
            head = [ln for ln in r["note"].splitlines() if ln.startswith(("Model:", "Harness:"))]
            r["note"] = "\n".join(head + [notes[r["id"]]])
    _gz(p, data)
    write_snapshot_sums(raw)
    retag(Path(root))


def edit_parents(root: Path, name: str, fn) -> None:
    """fn(dict id -> {"primary","tree","dropped"}) edits the frozen parent links in place."""
    fro = Path(root) / "lineage" / "frozen"
    p = fro / slug_of(name) / "parents.json.gz"
    data = _read_gz(p)
    fn(data)
    trees_mod._gz(p, data)
    lbuild.write_sha256sums(fro)
    retag(Path(root))
