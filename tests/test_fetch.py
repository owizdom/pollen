"""Offline tests for snapshot.fetch: all network is faked."""
import email.message
import gzip
import io
import json
import time
import urllib.error

import pytest

import snapshot.fetch as F
from conftest import write_sums  # noqa: F401

T0 = 1_800_000_000.0


def http_error(url, code, headers=None):
    m = email.message.Message()
    for k, v in (headers or {}).items():
        m[k] = v
    return urllib.error.HTTPError(url, code, "err", m, io.BytesIO(b""))


class Clock:
    def __init__(self):
        self.now = T0
        self.sleeps = []

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += max(s, 0)

    def monotonic(self):
        return self.now

    time = monotonic


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(time, "sleep", c.sleep)
    monkeypatch.setattr(time, "monotonic", c.monotonic)
    monkeypatch.setattr(time, "time", c.time)
    F._last[0] = 0.0
    return c


def sub(i, status="accepted"):
    return {"id": i, "status": status, "createdAt": "2026-01-01T00:00:00Z"}


def record(sid, parents=("s0",), cursor=None):
    return {"submissionId": sid, "declaration": "provided",
            "dependencies": [{"submissionId": p, "rationale": "r", "evidence": "e"} for p in parents],
            "proposals": [], "edges": [], "nextCursor": cursor}


class Api:
    """Fake of the three benchmark endpoints plus a pluggable attribution handler."""

    def __init__(self, benches=None, attr=None, clock=None):
        self.benches = benches or {"x/big": [sub("s0"), sub("s1"), sub("s2")],
                                   "x/small": [sub("t0")]}
        self.attr = attr or (lambda url, sid: record(sid))
        self.attr_calls = []
        self.clock = clock

    def __call__(self, url):
        ids = {n: f"B{i}" for i, n in enumerate(self.benches)}
        if url.endswith("/api/benchmarks"):
            return {"benchmarks": [{"id": ids[n], "name": n} for n in self.benches]}
        for n, bid in ids.items():
            if url.endswith(f"/api/benchmarks/{bid}"):
                return {"benchmark": {"id": bid, "name": n, "direction": "-",
                                      "editablePaths": [], "sourceUrl": "u",
                                      "openedAt": "2026-01-01T00:00:00Z",
                                      "minScoreImprovementBips": None}}
            if url.endswith(f"/api/benchmarks/{bid}/submissions"):
                return {"submissions": self.benches[n]}
        if "/attribution" in url:
            sid = url.split("/api/submissions/")[1].split("/")[0]
            self.attr_calls.append((sid, url, self.clock.now if self.clock else None))
            return self.attr(url, sid)
        raise AssertionError(url)


def run(tmp_path, monkeypatch, api, *args, name="out"):
    monkeypatch.setattr(F, "_get_json", api)
    out = tmp_path / name / "raw"
    md = tmp_path / name / "FREEZE.md"
    F.main(["--out", str(out), "--freeze-md", str(md), *args])
    return out, md


def freeze(out):
    return json.loads((out / "FREEZE.json").read_text())


def gz(path):
    return json.loads(gzip.open(path).read())


# 1
def test_attribution_404_is_recorded_not_fatal(tmp_path, monkeypatch, clock):
    def attr(url, sid):
        if sid == "s1":
            raise http_error(url, 404)
        return record(sid)
    out, _ = run(tmp_path, monkeypatch, Api(attr=attr), "--attribution-min", "2")
    recs = {r["submissionId"]: r for r in gz(out / "x__big" / "attribution.json.gz")}
    assert recs["s1"] == {"submissionId": "s1", "declaration": "unavailable", "httpStatus": 404}
    assert freeze(out)["attribution_unavailable"] == {"x/big": ["s1"]}


# 2
def crash_on_s1(url, sid):
    if sid == "s1":
        raise RuntimeError("boom")
    return record(sid)


def test_resume_after_attribution_crash_fetches_attribution(tmp_path, monkeypatch, clock):
    api1 = Api(attr=crash_on_s1)
    with pytest.raises(Exception):
        run(tmp_path, monkeypatch, api1, "--attribution-min", "2", name="r")
    d = tmp_path / "r" / "raw" / "x__big"
    assert (d / "submissions.json.gz").exists() and not (d / "attribution.json.gz").exists()
    assert (d / "attribution.partial.jsonl").exists()

    api2 = Api()
    out, _ = run(tmp_path, monkeypatch, api2, "--attribution-min", "2", "--resume", name="r")
    assert (out / "x__big" / "attribution.json.gz").exists()
    assert "s0" not in [c[0] for c in api2.attr_calls]  # continued per submission
    assert freeze(out)["attribution"] == ["x/big"]

    ref, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "2", name="ref")
    assert ((out / "x__big" / "attribution.json.gz").read_bytes()
            == (ref / "x__big" / "attribution.json.gz").read_bytes())


def test_resume_does_not_fetch_attribution_for_small_benchmark(tmp_path, monkeypatch, clock):
    run(tmp_path, monkeypatch, Api(), "--attribution-min", "2", name="r")
    api = Api()
    out, _ = run(tmp_path, monkeypatch, api, "--attribution-min", "2", "--resume", name="r")
    assert not (out / "x__small" / "attribution.json.gz").exists()
    assert freeze(out)["attribution"] == ["x/big"]


def test_attribution_for_explicit_list(tmp_path, monkeypatch, clock):
    out, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "999",
                 "--attribution-for", "x/small")
    assert (out / "x__small" / "attribution.json.gz").exists()
    assert not (out / "x__big" / "attribution.json.gz").exists()
    assert freeze(out)["attribution"] == ["x/small"]


def test_resume_honours_attribution_for(tmp_path, monkeypatch, clock):
    with pytest.raises(Exception):
        run(tmp_path, monkeypatch, Api(attr=lambda u, s: (_ for _ in ()).throw(RuntimeError("x"))),
            "--attribution-min", "999", "--attribution-for", "x/small", name="r")
    out, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "999",
                 "--attribution-for", "x/small", "--resume", name="r")
    assert (out / "x__small" / "attribution.json.gz").exists()


# 6
def test_attribution_rate_at_most_two_per_second(tmp_path, monkeypatch, clock):
    benches = {"x/big": [sub(f"s{i}") for i in range(8)]}
    api = Api(benches=benches, clock=clock)
    run(tmp_path, monkeypatch, api, "--attribution-min", "2")
    ts = [c[2] for c in api.attr_calls]
    assert len(ts) == 8
    for i in range(len(ts) - 2):
        assert ts[i + 2] - ts[i] >= 1.0 - 1e-9, ts


def fake_urlopen(clock, responder):
    calls = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        calls.append(clock.now)
        return Resp(json.dumps(responder(url, len(calls))).encode())
    return urlopen, calls


def test_429_honours_retry_after(monkeypatch, clock):
    def responder(url, n):
        if n <= 2:
            raise http_error(url, 429, {"Retry-After": "30"})
        return {"ok": True}
    uo, calls = fake_urlopen(clock, responder)
    monkeypatch.setattr(F.urllib.request, "urlopen", uo)
    assert F._get_json("https://x/api/benchmarks") == {"ok": True}
    assert calls[1] - calls[0] >= 30 and calls[2] - calls[1] >= 30


def test_429_honours_ratelimit_reset_epoch(monkeypatch, clock):
    def responder(url, n):
        if n == 1:
            raise http_error(url, 429, {"x-ratelimit-reset": str(int(T0 + 20))})
        return {"ok": True}
    uo, calls = fake_urlopen(clock, responder)
    monkeypatch.setattr(F.urllib.request, "urlopen", uo)
    assert F._get_json("https://x/api/benchmarks") == {"ok": True}
    assert 20 <= calls[1] - calls[0] < 600


def test_429_retries_for_at_least_ten_minutes(monkeypatch, clock):
    def responder(url, n):
        if clock.now - T0 < 590:
            raise http_error(url, 429)
        return {"ok": True}
    uo, calls = fake_urlopen(clock, responder)
    monkeypatch.setattr(F.urllib.request, "urlopen", uo)
    assert F._get_json("https://x/api/benchmarks") == {"ok": True}


# 7
def test_cursor_pages_dedupe_dependencies_in_order(monkeypatch, clock):
    def fake(url):
        if "cursor=" in url:
            return record("s9", ["b", "c"], None)
        return record("s9", ["a", "b"], "c1")
    monkeypatch.setattr(F, "_get_json", fake)
    rec = F.fetch_attribution("s9", [])
    assert [d["submissionId"] for d in rec["dependencies"]] == ["a", "b", "c"]
    assert rec["nextCursor"] is None


def test_page_error_recorded_as_partial(tmp_path, monkeypatch, clock):
    def attr(url, sid):
        if sid == "s1" and "cursor=" in url:
            raise http_error(url, 400)
        return record(sid, cursor="c1") if sid == "s1" else record(sid)
    out, _ = run(tmp_path, monkeypatch, Api(attr=attr), "--attribution-min", "2")
    assert freeze(out)["attribution_partial"] == {"x/big": ["s1"]}
    import snapshot.load as L
    L.attribution("x/big", root=out)  # listed as partial: no IntegrityError


# 8
def test_only_does_not_shrink_freeze(tmp_path, monkeypatch, clock):
    out, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "2", name="m")
    before = freeze(out)
    out, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "2",
                 "--only", "x/small", name="m")
    after = freeze(out)
    assert after["counts"] == before["counts"]
    assert after["attribution"] == ["x/big"]
    assert "FREEZE.json" in (out / "SHA256SUMS").read_text()
    import snapshot.load as L
    assert len(L.load("x/big", root=out)) == 3


# 9
def test_freeze_md_written_from_freeze_json(tmp_path, monkeypatch, clock):
    out, md = run(tmp_path, monkeypatch, Api(), "--attribution-min", "2")
    text = md.read_text()
    f = freeze(out)
    assert f["fetched_at"] in text
    assert f["api"] in text
    assert "x/big" in text and "x/small" in text and "3" in text
    assert "attribution" in text.lower()
    assert "redistribution" in text.lower()


def test_freeze_json_is_in_sha256sums_after_fetch(tmp_path, monkeypatch, clock):
    out, _ = run(tmp_path, monkeypatch, Api(), "--attribution-min", "2")
    assert "FREEZE.json" in (out / "SHA256SUMS").read_text()
