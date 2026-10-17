"""make reproduce: the whole chain, offline, in the order the spec fixes."""
from __future__ import annotations

import argparse

from analysis import confirmatory, exploratory, figures, numbers, secondary, sensitivity, study


def main(root=None, draws=10000, boot=2000) -> None:
    root = study.guard(root)
    confirmatory.run(root)
    secondary.run(root, draws=draws, boot=boot)
    sensitivity.run(root)
    exploratory.run(root, boot=boot)
    figures.run(root)
    numbers.write(root)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--draws", type=int, default=10000)
    ap.add_argument("--boot", type=int, default=2000)
    a = ap.parse_args()
    main(a.root, draws=a.draws, boot=a.boot)
