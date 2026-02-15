#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import matplotlib.pyplot as plt


@dataclass
class Row:
    tag: str
    rps: int
    ok_rps: float
    p95_ms: Optional[float]
    avg_ms: Optional[float]
    err_rate: float


def to_float(x: str) -> Optional[float]:
    x = (x or "").strip()
    if x == "":
        return None
    try:
        return float(x)
    except Exception:
        return None


def read_combined(path: str) -> List[Row]:
    rows: List[Row] = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(Row(
                tag=r["tag"],
                rps=int(r["rps_target"]),
                ok_rps=float(r["ok_rps"]),
                p95_ms=to_float(r.get("p95_ms", "")),
                avg_ms=to_float(r.get("avg_ms", "")),
                err_rate=float(r.get("err_rate", "0") or "0"),
            ))
    return rows


def write_wide_summary(rows: List[Row], out_csv: str) -> None:
    tags = sorted({r.tag for r in rows})
    rps_vals = sorted({r.rps for r in rows})

    by = {(r.tag, r.rps): r for r in rows}

    os.makedirs(os.path.dirname(out_csv) or ".", exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        header = ["rps"]
        for t in tags:
            header += [f"{t}_ok_rps", f"{t}_p95_ms", f"{t}_err_rate"]
        w.writerow(header)

        for rps in rps_vals:
            line = [rps]
            for t in tags:
                rr = by.get((t, rps))
                if rr is None:
                    line += ["", "", ""]
                else:
                    line += [
                        round(rr.ok_rps, 3),
                        "" if rr.p95_ms is None else round(rr.p95_ms, 3),
                        round(rr.err_rate, 3),
                    ]
            w.writerow(line)


def plot_execution_time_p95(rows: List[Row], out_png: str) -> None:
    tags = sorted({r.tag for r in rows})
    plt.figure()
    for t in tags:
        pts = sorted([r for r in rows if r.tag == t], key=lambda x: x.rps)
        xs = [p.rps for p in pts if p.p95_ms is not None]
        ys = [p.p95_ms for p in pts if p.p95_ms is not None]
        if xs:
            plt.plot(xs, ys, marker="o", label=t)
    plt.xlabel("Target RPS")
    plt.ylabel("P95 end-to-end latency (ms)")
    plt.title("Execution Time (P95) vs Load")
    plt.xscale("log")
    plt.yscale("log")
    plt.legend()
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    plt.savefig(out_png, dpi=180)
    plt.close()


def plot_throughput(rows: List[Row], out_png: str) -> None:
    tags = sorted({r.tag for r in rows})
    plt.figure()
    for t in tags:
        pts = sorted([r for r in rows if r.tag == t], key=lambda x: x.rps)
        xs = [p.rps for p in pts]
        ys = [p.ok_rps for p in pts]
        plt.plot(xs, ys, marker="o", label=t)
    plt.xlabel("Target RPS")
    plt.ylabel("Achieved OK RPS")
    plt.title("Throughput vs Load")
    plt.xscale("log")
    plt.yscale("log")
    plt.legend()
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    plt.savefig(out_png, dpi=180)
    plt.close()


def plot_speedup(rows: List[Row], out_png: str) -> None:
    tags = sorted({r.tag for r in rows})
    plt.figure()
    for t in tags:
        pts = sorted([r for r in rows if r.tag == t and r.p95_ms is not None], key=lambda x: x.rps)
        if not pts:
            continue
        baseline = pts[0].p95_ms
        if baseline is None or baseline <= 0:
            continue
        xs = [p.rps for p in pts]
        ys = [baseline / p.p95_ms for p in pts if p.p95_ms and p.p95_ms > 0]
        plt.plot(xs[:len(ys)], ys, marker="o", label=t)

    plt.xlabel("Target RPS")
    plt.ylabel("Speedup (baseline_p95 / p95)")
    plt.title("Speedup vs Load (relative to lowest RPS)")
    plt.xscale("log")
    plt.legend()
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    plt.savefig(out_png, dpi=180)
    plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combined", default="results/combined_results.csv", help="Combined CSV path")
    ap.add_argument("--out_dir", default="figures", help="Output directory for figures")
    args = ap.parse_args()

    rows = read_combined(args.combined)

    wide_csv = os.path.join(args.out_dir, "summary_by_rps.csv")
    write_wide_summary(rows, wide_csv)

    plot_execution_time_p95(rows, os.path.join(args.out_dir, "execution_time_p95.png"))
    plot_throughput(rows, os.path.join(args.out_dir, "throughput_ok_rps.png"))
    plot_speedup(rows, os.path.join(args.out_dir, "speedup_vs_rps.png"))

    print(f"Wrote: {wide_csv}")
    print(f"Wrote plots into: {args.out_dir}/")


if __name__ == "__main__":
    main()
