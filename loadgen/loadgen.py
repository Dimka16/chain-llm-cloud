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
print("USING TARGET_URL =", TARGET_URL)

RPS_POINTS = [1,10,50,100,200,300,400,500,600,700,800,900,1000]

def make_prompt():
    return (
        "A"*1000
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
    ok_rps = oks / DURATION_SECONDS
    err_rate = 0.0 if completed == 0 else (1.0 - oks / completed) * 100.0

    ok_lats = sorted([lat for ok, _, lat, _ in results if ok])
    p95 = ok_lats[math.floor(0.95 * (len(ok_lats)-1))] if ok_lats else None
    avg = (sum(ok_lats)/len(ok_lats)) if ok_lats else None

    avg_s = f"{avg:.1f}" if avg is not None else "n/a"
    p95_s = f"{p95:.1f}" if p95 is not None else "n/a"

    print(f"RPS target={rps} sent={sent} completed={completed} ok={oks} ok_rps={ok_rps:.2f} err%={err_rate:.1f} avg_ms={avg_s} p95_ms={p95_s} -> {out_csv}")

async def main():
    tag = os.getenv("RUN_TAG", "local")
    for rps in RPS_POINTS:
        await run_point(rps, f"results/{tag}_chain_rps{rps}.csv")

if __name__ == "__main__":
    asyncio.run(main())
