import csv, glob, os, re, statistics

def pctl(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    i = int(round((p/100)*(len(xs)-1)))
    return xs[i]

def summarize(pattern, out_path):
    rows = []
    for path in sorted(glob.glob(pattern)):
        m = re.search(r"rps(\d+)\.csv$", path)
        if not m:
            continue
        rps = int(m.group(1))

        ok_lats = []
        total = 0
        oks = 0
        bad = 0
        statuses = {}

        with open(path, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            for r in rd:
                total += 1
                status = r["status"]
                statuses[status] = statuses.get(status, 0) + 1
                if r["ok"] == "1":
                    oks += 1
                    ok_lats.append(float(r["latency_ms"]))
                else:
                    bad += 1

        avg = statistics.mean(ok_lats) if ok_lats else None
        p50 = pctl(ok_lats, 50)
        p90 = pctl(ok_lats, 90)
        p95 = pctl(ok_lats, 95)
        p99 = pctl(ok_lats, 99)

        rows.append({
            "rps_target": rps,
            "requests_completed": total,
            "ok": oks,
            "err": bad,
            "ok_rate": (oks/total) if total else 0.0,
            "avg_ms": avg if avg is not None else "",
            "p50_ms": p50 if p50 is not None else "",
            "p90_ms": p90 if p90 is not None else "",
            "p95_ms": p95 if p95 is not None else "",
            "p99_ms": p99 if p99 is not None else "",
            "status_counts": ";".join([f"{k}:{v}" for k,v in sorted(statuses.items())]),
            "source_file": os.path.basename(path),
        })

    rows.sort(key=lambda x: x["rps_target"])
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            wr.writeheader()
            wr.writerows(rows)

    print("Wrote", out_path, "rows=", len(rows))

if __name__ == "__main__":
    summarize("results/aws_chain_rps*.csv", "results/summary_aws.csv")
    summarize("results/gcp_chain_rps*.csv", "results/summary_gcp.csv")