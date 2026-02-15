import asyncio
import aiohttp
import time
import csv
import os
import math

TARGET_URL = os.getenv("TARGET_URL", "http://localhost:8001/chain")
DURATION_SECONDS = float(os.getenv("DURATION_SECONDS", "10"))
WARMUP_SECONDS = float(os.getenv("WARMUP_SECONDS", "2"))
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "180"))
DRAIN_TIMEOUT_SECONDS = float(os.getenv("DRAIN_TIMEOUT_SECONDS", "120"))

RUN_TAG = os.getenv("RUN_TAG", "local")
RESULTS_DIR = os.getenv("RESULTS_DIR", "results")

print("USING TARGET_URL =", TARGET_URL)
print("RUN_TAG =", RUN_TAG)

RPS_POINTS = [1, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]


def make_prompt():
    return (
        "A" * 1000
        + "\nWrite a detailed explanation of cloud elasticity vs scalability.\n"
        + "Rules:\n"
        + "- 12 bullet points, each 2 sentences.\n"
        + "- Then write a 10-line summary.\n"
        + "- Be specific and technical.\n"
    )


async def worker(session, queue, results):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return

        send_ts = item
        try:
            start = time.perf_counter()
            async with session.post(TARGET_URL, json={"prompt": make_prompt()}) as resp:
                await resp.read()
                latency_ms = (time.perf_counter() - start) * 1000.0
                results.append((resp.status == 200, resp.status, latency_ms, ""))
        except Exception as e:
            latency_ms = (time.perf_counter() - send_ts) * 1000.0
            results.append((False, 0, latency_ms, str(e)))
        finally:
            queue.task_done()


async def paced_enqueue(queue, rps, seconds, label):
    interval = 1.0 / rps
    end = time.perf_counter() + seconds
    next_send = time.perf_counter()
    sent = 0
    last_print = time.perf_counter()

    while time.perf_counter() < end:
        now = time.perf_counter()
        if now >= next_send:
            await queue.put(now)
            sent += 1
            next_send += interval
        else:
            await asyncio.sleep(min(0.001, next_send - now))

        if time.perf_counter() - last_print >= 2.0:
            print(f"[{label}] sent={sent} queue={queue.qsize()}")
            last_print = time.perf_counter()

    return sent


def percentile(sorted_vals, p: float):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = int(math.floor(p * (len(sorted_vals) - 1)))
    return float(sorted_vals[idx])


async def run_point(rps: int, out_csv: str):
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
    queue = asyncio.Queue()
    results = []

    concurrency = min(50, max(5, rps * 3))

    async with aiohttp.ClientSession(timeout=timeout) as session:
        workers = [asyncio.create_task(worker(session, queue, results)) for _ in range(concurrency)]

        await paced_enqueue(queue, rps, WARMUP_SECONDS, f"warmup rps={rps}")
        await queue.join()
        results.clear()

        sent = await paced_enqueue(queue, rps, DURATION_SECONDS, f"measured rps={rps}")

        try:
            await asyncio.wait_for(queue.join(), timeout=DRAIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pass

        completed = len(results)

        for _ in workers:
            await queue.put(None)
        await asyncio.sleep(0.1)
        for w in workers:
            if not w.done():
                w.cancel()

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rps_target", "ok", "status", "latency_ms", "error"])
        for ok, status, lat, err in results:
            w.writerow([rps, 1 if ok else 0, status, round(lat, 3), err])

    oks = sum(1 for ok, *_ in results if ok)
    errs = completed - oks
    ok_rps = oks / DURATION_SECONDS
    err_rate = 0.0 if completed == 0 else (errs / completed) * 100.0

    ok_lats = sorted([lat for ok, _, lat, _ in results if ok])
    avg = (sum(ok_lats) / len(ok_lats)) if ok_lats else None
    p50 = percentile(ok_lats, 0.50)
    p90 = percentile(ok_lats, 0.90)
    p95 = percentile(ok_lats, 0.95)
    p99 = percentile(ok_lats, 0.99)

    print(
        f"RPS target={rps} sent={sent} completed={completed} ok={oks} "
        f"ok_rps={ok_rps:.2f} err%={err_rate:.1f} "
        f"avg_ms={(f'{avg:.1f}' if avg is not None else 'n/a')} "
        f"p95_ms={(f'{p95:.1f}' if p95 is not None else 'n/a')} -> {out_csv}"
    )

    return {
        "run_tag": RUN_TAG,
        "target_url": TARGET_URL,
        "rps_target": rps,
        "duration_s": DURATION_SECONDS,
        "timeout_s": TIMEOUT_SECONDS,
        "drain_timeout_s": DRAIN_TIMEOUT_SECONDS,
        "concurrency": concurrency,
        "sent": sent,
        "completed": completed,
        "ok": oks,
        "errors": errs,
        "ok_rps": ok_rps,
        "err_pct": err_rate,
        "avg_ms": avg,
        "p50_ms": p50,
        "p90_ms": p90,
        "p95_ms": p95,
        "p99_ms": p99,
        "per_request_csv": out_csv,
    }


def append_summary_row(summary_path: str, row: dict):
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    write_header = not os.path.exists(summary_path) or os.path.getsize(summary_path) == 0

    fields = [
        "run_tag",
        "target_url",
        "rps_target",
        "duration_s",
        "timeout_s",
        "drain_timeout_s",
        "concurrency",
        "sent",
        "completed",
        "ok",
        "errors",
        "ok_rps",
        "err_pct",
        "avg_ms",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "p99_ms",
        "per_request_csv",
    ]

    with open(summary_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            w.writeheader()
        w.writerow(row)


async def main():
    summary_path = os.path.join(RESULTS_DIR, f"{RUN_TAG}_summary.csv")

    if os.path.exists(summary_path):
        os.remove(summary_path)

    for rps in RPS_POINTS:
        per_request_path = os.path.join(RESULTS_DIR, f"{RUN_TAG}_chain_rps{rps}.csv")
        row = await run_point(rps, per_request_path)
        append_summary_row(summary_path, row)

    print(f"\nWROTE SUMMARY -> {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())