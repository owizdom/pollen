"""Paper figures from results/*.json and the treatment frames. Not part of the prereg-v1 lock."""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "paper/figures"

from analysis import dataset, study  # noqa: E402

plt.rcParams.update({"font.family": "serif", "font.size": 9, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 150})
TICKS = [0.25, 0.5, 0.67, 1, 1.5, 2, 3]


def _load(name):
    return json.loads((ROOT / "results" / f"{name}.json").read_text())


def _axis(ax, margin):
    ax.set_xscale("log")
    ax.set_xticks(TICKS)
    ax.set_xticklabels([f"{t:g}" for t in TICKS])
    ax.minorticks_off()
    ax.axvspan(margin[0], margin[1], color="0.93", zorder=0)
    ax.axvline(1, color="0.5", lw=0.8, zorder=1)


def forest_primary(conf):
    names = sorted(conf["benchmarks"])
    rows = [(n, conf["benchmarks"][n]["estimate"]) for n in names]
    p = conf["pooled"]
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    _axis(ax, conf["margin"])
    y = np.arange(len(rows) + 1)[::-1]
    for yi, (n, e) in zip(y[:-1], rows):
        lo, hi = math.exp(e["ci95"][0]), math.exp(e["ci95"][1])
        ax.plot([lo, hi], [yi, yi], color="black", lw=1)
        ax.plot(math.exp(e["log_or"]), yi, "o", color="black", ms=4)
    ax.plot([math.exp(p["ci95"][0]), math.exp(p["ci95"][1])], [0, 0], color="black", lw=1)
    ax.plot([math.exp(p["ci90"][0]), math.exp(p["ci90"][1])], [0, 0], color="black", lw=3.5)
    ax.plot(math.exp(p["log_or"]), 0, "D", color="white", mec="black", ms=6, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels([n.split("/", 1)[1] for n in names] + ["pooled (thick: 90%)"])
    ax.set_xlim(0.12, 3.2)
    ax.set_xlabel("odds ratio of promotion, cross-family vs same-family parent")
    ax.set_title(f"Pooled odds ratio {math.exp(p['log_or']):.2f}, 90% interval inside the margin",
                 loc="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "paper_forest_primary.pdf")
    fig.savefig(OUT / "paper_forest_primary.png", dpi=200)


def forest_sensitivity(conf, sens):
    labels = ["primary", "1 Unknown as family", "2 tree parent", "3 drop nonce rows", "4 coarse families",
              "5 drop first 72 h", "6 harness", "7 drop author", "8 one per sibling", "9 drop ambiguous"]
    keys = [None] + sorted(sens["sensitivities"])
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    _axis(ax, conf["margin"])
    for i, k in enumerate(keys):
        q = conf["pooled"] if k is None else sens["sensitivities"][k]["pooled"]
        yi = len(keys) - 1 - i
        ax.plot([math.exp(q["ci90"][0]), math.exp(q["ci90"][1])], [yi, yi], color="black", lw=2.5)
        ax.plot(math.exp(q["log_or"]), yi, "o", color="white", mec="black", ms=5, zorder=3)
    ax.set_yticks(range(len(keys))[::-1])
    ax.set_yticklabels(labels)
    ax.set_xlim(0.5, 2.0)
    ax.set_xticks([0.5, 0.67, 1, 1.5, 2])
    ax.set_xticklabels(["0.5", "0.67", "1", "1.5", "2"])
    ax.set_xlabel("pooled odds ratio with 90% interval")
    ax.set_title("No sensitivity analysis moves the pooled estimate out of the margin", loc="left",
                 fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "paper_forest_sensitivity.pdf")
    fig.savefig(OUT / "paper_forest_sensitivity.png", dpi=200)


def family_flow():
    """Cross-solver single-parent rows by parent family and child family, all study benchmarks."""
    c, switch, n_all = Counter(), 0, 0
    for b in study.benchmarks():
        f = dataset.build(b)
        f = f[(f["cross_solver"] == True) & f["cross_family"].notna()]  # noqa: E712
        c.update(zip(f["parent_family"], f["child_family"]))
        switch += int(f["cross_family"].astype(bool).sum())
        n_all += len(f)
    tot = Counter()
    for (pf, cf), n in c.items():
        tot[pf] += n
        tot[cf] += n
    fams = [f for f, _ in tot.most_common(6)]
    lab = fams + ["other"]
    idx = {f: i for i, f in enumerate(fams)}
    M = np.zeros((len(lab), len(lab)))
    for (pf, cf), n in c.items():
        M[idx.get(pf, len(fams)), idx.get(cf, len(fams))] += n
    share = 1 - switch / n_all  # the "other" cell folds several families, so not the trace
    fig, ax = plt.subplots(figsize=(4.8, 4.2))
    im = ax.imshow(M, cmap="Greys", norm=matplotlib.colors.LogNorm(vmin=1, vmax=M.max()))
    for i in range(len(lab)):
        for j in range(len(lab)):
            if M[i, j]:
                ax.text(j, i, f"{int(M[i, j]):,}", ha="center", va="center", fontsize=7,
                        color="white" if M[i, j] > M.max() ** 0.6 else "black")
    ax.set_xticks(range(len(lab)))
    ax.set_xticklabels(lab, rotation=40, ha="right")
    ax.set_yticks(range(len(lab)))
    ax.set_yticklabels(lab)
    ax.set_xlabel("child family")
    ax.set_ylabel("parent family")
    ax.spines[:].set_visible(False)
    ax.set_title(f"{100 * (1 - share):.0f}% of cross-solver steps switch vendor", loc="left", fontsize=9.5)
    fig.tight_layout()
    fig.savefig(OUT / "paper_family_flow.pdf")
    fig.savefig(OUT / "paper_family_flow.png", dpi=200)
    return {"switch_share": 1 - share, "families": fams, "total": int(M.sum())}


def main():
    conf, sens = _load("confirmatory"), _load("sensitivity")
    forest_primary(conf)
    forest_sensitivity(conf, sens)
    print(json.dumps(family_flow()))


if __name__ == "__main__":
    main()
