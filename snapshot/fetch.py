"""Download the Yukon snapshot (no auth). Usage:

    uv run python -m snapshot.fetch --out snapshot/raw [--attribution-min 500] [--only NAME ...] [--resume]
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.yukon.org"
USER_AGENT = "pollen-research-snapshot (github.com/owizdom/pollen)"
MAX_RPS = 8
ATTR_RPS = 2
BUDGET_429 = 900.0
TRIES = 5
_last = [0.0]


def slug(name: str) -> str:
    return name.replace("/", "__")


def write_gz(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    with open(path, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as f:
        f.write(data)


def write_sums(out: Path) -> None:
    files = sorted(out.rglob("*.gz"))
    if (out / "FREEZE.json").exists():
        files.append(out / "FREEZE.json")
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}"
             for p in files]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n")


def _throttle(interval: float) -> None:
    wait = _last[0] + interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.monotonic()


def _retry_wait(e: urllib.error.HTTPError, attempt: int) -> float:
    h = e.headers
    ra = h.get("Retry-After") if h else None
    if ra:
        try:
            return max(float(ra), 0.0)
        except ValueError:
            pass
    reset = h.get("x-ratelimit-reset") if h else None
    if reset:
        try:
            return max(float(reset) - time.time(), 0.0) + 1.0
        except ValueError:
            pass
    return min(2.0 ** attempt, 60.0)


def _get_json(url: str):
    """The only network call. 429 is retried within a 15 minute budget; 5xx and
    timeouts get TRIES attempts with exponential backoff."""
    interval = 1.0 / MAX_RPS
    start = time.monotonic()
    delay, fails = 1.0, 0
    attempt = 0
    while True:
        attempt += 1
        _throttle(interval)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = _retry_wait(e, attempt)
                if time.monotonic() - start + wait > BUDGET_429:
                    raise RuntimeError(f"giving up on {url}: rate limited past budget") from e
                print(f"429 for {url}: waiting {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code < 500:
                raise
            err = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = e
        fails += 1
        if fails >= TRIES:
            raise RuntimeError(f"giving up on {url}: {err}") from err
        print(f"retry {fails} for {url}: {err}", file=sys.stderr)
        time.sleep(delay)
        delay *= 2


def _rows(data, key):
    return data if isinstance(data, list) else data[key]


def is_cancelled(sub) -> bool:
    return sub.get("status") == "cancelled"


def fetch_attribution(sid: str, warnings: list):
    _throttle(1.0 / ATTR_RPS)  # attribution calls: at most 2/s
    try:
        rec = _get_json(f"{BASE}/api/submissions/{sid}/attribution")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"submissionId": sid, "declaration": "unavailable", "httpStatus": 404}
        raise
    cursor = rec.get("nextCursor")
    seen = set()
    while cursor and cursor not in seen:
        seen.add(cursor)
        _throttle(1.0 / ATTR_RPS)
        try:
            more = _get_json(f"{BASE}/api/submissions/{sid}/attribution?cursor={urllib.parse.quote(str(cursor))}")
        except urllib.error.HTTPError:
            warnings.append(sid)
            return rec
        deps = list(rec.get("dependencies") or [])
        have = {d["submissionId"] for d in deps}
        for d in more.get("dependencies") or []:
            if d["submissionId"] not in have:
                have.add(d["submissionId"])
                deps.append(d)
        rec["dependencies"] = deps
        for k in ("proposals", "edges"):
            rec[k] = (rec.get(k) or []) + (more.get(k) or [])
        cursor = more.get("nextCursor")
        rec["nextCursor"] = cursor
    return rec


def _read_gz(path: Path):
    with gzip.open(path, "rb") as f:
        return json.loads(f.read())


def _attribution_for_bench(d: Path, subs: list, resume: bool) -> list:
    final = d / "attribution.json.gz"
    partial = d / "attribution.partial.jsonl"
    if resume and final.exists():
        return _read_gz(final)
    done = {}
    if resume and partial.exists():
        for line in partial.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue  # torn last line from a crash
                done[r["submissionId"]] = r
    elif partial.exists():
        partial.unlink()
    with open(partial, "w") as f:  # rewrite clean, then append
        for r in done.values():
            f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
        f.flush()
        for i, s in enumerate(subs, 1):
            if s["id"] in done:
                continue
            warn: list = []
            r = fetch_attribution(s["id"], warn)
            done[s["id"]] = r
            f.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")
            f.flush()
            if i % 100 == 0:
                print(f"  attribution {i}/{len(subs)}", file=sys.stderr)
    recs = sorted(done.values(), key=lambda r: r["submissionId"])
    write_gz(final, recs)
    partial.unlink()
    return recs


def write_freeze_md(path: Path, f: dict) -> None:
    lines = [
        "# Snapshot freeze", "",
        f"- Fetched at (UTC): {f['fetched_at']}",
        f"- API: {f['api']}", "",
        "## Rows per benchmark", "",
        "Counts are all submissions in the file, cancelled included.", "",
    ]
    lines += [f"- {n}: {c}" for n, c in sorted(f["counts"].items())]
    lines += ["", "## Attribution records", "",
              "Fetched for benchmarks with enough non-cancelled submissions or named explicitly.", ""]
    lines += [f"- {n}" for n in f.get("attribution", [])] or ["- none"]
    for key, title in (("attribution_unavailable", "Attribution unavailable (HTTP 404)"),
                       ("attribution_partial", "Attribution partial (cursor page failed)")):
        if f.get(key):
            lines += ["", f"### {title}", ""]
            lines += [f"- {n}: {', '.join(ids)}" for n, ids in sorted(f[key].items())]
    lines += ["", "## Redistribution", "",
              "The data are public API responses from api.yukon.org, fetched without credentials. "
              "Solver handles are public GitHub usernames, and notes are the solvers' public text. "
              "They are reproduced as published. Raise any removal request with the repository owner.", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def run(out: Path, attribution_min: int, only, resume: bool,
        attribution_for=None, freeze_md: Path | None = None) -> None:
    attribution_for = set(attribution_for or [])
    out.mkdir(parents=True, exist_ok=True)
    old = {}
    if only and (out / "FREEZE.json").exists():
        old = json.loads((out / "FREEZE.json").read_text())
    counts = dict(old.get("counts", {}))
    attributed = set(old.get("attribution", []))
    unavailable = dict(old.get("attribution_unavailable", {}))
    partial = dict(old.get("attribution_partial", {}))
    listing = _rows(_get_json(f"{BASE}/api/benchmarks"), "benchmarks")
    for b in listing:
        name = b["name"]
        if only and name not in only:
            continue
        d = out / slug(name)
        bid = b["id"]
        print(f"[{name}]", file=sys.stderr)
        attributed.discard(name)
        unavailable.pop(name, None)
        partial.pop(name, None)
        if resume and (d / "benchmark.json.gz").exists() and (d / "submissions.json.gz").exists():
            subs = _read_gz(d / "submissions.json.gz")["submissions"]
            print("  resume: stored files reused", file=sys.stderr)
        else:
            write_gz(d / "benchmark.json.gz", _get_json(f"{BASE}/api/benchmarks/{bid}"))
            subs = _rows(_get_json(f"{BASE}/api/benchmarks/{bid}/submissions"), "submissions")
            write_gz(d / "submissions.json.gz", {"submissions": subs})
        counts[name] = len(subs)
        live = [s for s in subs if not is_cancelled(s)]
        if len(live) >= attribution_min or name in attribution_for:
            recs = _attribution_for_bench(d, subs, resume)
            attributed.add(name)
            un = sorted(r["submissionId"] for r in recs if r.get("declaration") == "unavailable")
            pa = sorted(r["submissionId"] for r in recs if r.get("nextCursor"))
            if un:
                unavailable[name] = un
            if pa:
                partial[name] = pa
            if pa:
                print(f"WARNING: partial attribution for {name}: {', '.join(pa)}", file=sys.stderr)
        print(f"  {len(subs)} submissions", file=sys.stderr)
    freeze = {
        "fetched_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api": BASE,
        "counts": dict(sorted(counts.items())),
        "attribution": sorted(attributed),
    }
    if unavailable:
        freeze["attribution_unavailable"] = dict(sorted(unavailable.items()))
    if partial:
        freeze["attribution_partial"] = dict(sorted(partial.items()))
    (out / "FREEZE.json").write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n")
    write_sums(out)
    write_freeze_md(freeze_md if freeze_md is not None else out.parent / "FREEZE.md", freeze)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--attribution-min", type=int, default=500)
    ap.add_argument("--only", nargs="+", metavar="NAME")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--attribution-for", nargs="+", metavar="NAME", default=[])
    ap.add_argument("--freeze-md", type=Path, default=None,
                    help="default: FREEZE.md next to --out")
    a = ap.parse_args(argv)
    run(a.out, a.attribution_min, a.only, a.resume, a.attribution_for, a.freeze_md)


if __name__ == "__main__":
    main()
