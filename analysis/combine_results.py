#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import glob
import math
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


RPS_RE = re.compile(r"^(?P<tag>.+)_chain_rps(?P<rps>\d+)\.csv$")


@dataclass
class SummaryRow:
    tag: str
    rps_target: int
    rows: int
    ok: int
    err: int
    ok_rps: float
    err_rate: float
    avg_ms: Optional[float]
    p95_ms: Optional[float]
    p50_ms: Optional[float]
    min_ms: Optional[float]
    max_ms: Optional[float]


def percentile(sorted_vals: List[float], p: float) -> Optional[float]:
    if not sorted_vals:
        return None
    if p <= 0:
        return sorted_vals[0]
    if p >= 1:
        return sorted_vals[-1]
    idx = int(math.floor(p * (len(sorted_vals) - 1)))
    return sorted_vals[idx]


def read_one_csv(path: str, duration_s: float) -> SummaryRow:
    base = os.path.basename(path)
    m = RPS_RE.match(base)
    if not m:
        raise ValueError(f"Unexpected filename format: {base}")

    tag = m.group("tag")
    rps = int(m.group("rps"))

    rows = 0
    ok = 0
    lat_ok: List[float] = []
    err = 0

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            is_ok = (row.get("ok", "0") or "0").strip() == "1"
            status = (row.get("status", "") or "").strip()
            lat_s = (row.get("latency_ms", "") or "").strip()

            if is_ok and status == "200":
                ok += 1
                try:
                    lat_ok.append(float(lat_s))
                except Exception:
                    ok -= 1
                    err += 1
            else:
                err += 1

    lat_ok.sort()
    avg_ms = (sum(lat_ok) / len(lat_ok)) if lat_ok else None
    p95_ms = percentile(lat_ok, 0.95)
    p50_ms = percentile(lat_ok, 0.50)
    min_ms = lat_ok[0] if lat_ok else None
    max_ms = lat_ok[-1] if lat_ok else None

    ok_rps = (ok / duration_s) if duration_s > 0 else 0.0
    err_rate = (err / rows * 100.0) if rows > 0 else 0.0

    return SummaryRow(
        tag=tag,
        rps_target=rps,
        rows=rows,
        ok=ok,
        err=err,
        ok_rps=ok_rps,
        err_rate=err_rate,
        avg_ms=avg_ms,
        p95_ms=p95_ms,
        p50_ms=p50_ms,
        min_ms=min_ms,
        max_ms=max_ms,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results_dir", default="results", help="Folder containing <tag>_chain_rps*.csv")
    ap.add_argument("--out", default="results/combined_results.csv", help="Output CSV path")
    ap.add_argument("--duration", type=float, default=10.0, help="Measured duration seconds used by loadgen")
    args = ap.parse_args()

    pattern = os.path.join(args.results_dir, "*_chain_rps*.csv")
    paths = sorted(glob.glob(pattern))

    if not paths:
        raise SystemExit(f"No result CSVs found with pattern: {pattern}")

    summaries: List[SummaryRow] = []
    for p in paths:
        try:
            summaries.append(read_one_csv(p, args.duration))
        except Exception as e:
            print(f"[WARN] Skipping {p}: {e}")

    summaries.sort(key=lambda x: (x.tag, x.rps_target))

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "tag", "rps_target", "rows", "ok", "err",
            "ok_rps", "err_rate",
            "avg_ms", "p95_ms", "p50_ms", "min_ms", "max_ms"
        ])
        for s in summaries:
            w.writerow([
                s.tag, s.rps_target, s.rows, s.ok, s.err,
                round(s.ok_rps, 3),
                round(s.err_rate, 3),
                "" if s.avg_ms is None else round(s.avg_ms, 3),
                "" if s.p95_ms is None else round(s.p95_ms, 3),
                "" if s.p50_ms is None else round(s.p50_ms, 3),
                "" if s.min_ms is None else round(s.min_ms, 3),
                "" if s.max_ms is None else round(s.max_ms, 3),
            ])

    print(f"Wrote: {args.out} ({len(summaries)} rows)")


if __name__ == "__main__":
    main()
