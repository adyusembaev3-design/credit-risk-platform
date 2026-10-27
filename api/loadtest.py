"""Load test for the decision API: concurrent single-application requests, then batch throughput.

Start the API first (uvicorn api.main:app --port 8000), then in another terminal:
    python -m api.loadtest
    python -m api.loadtest --url https://<your-aws-url> --requests 1000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import numpy as np

from pipeline import config


async def run(url: str, n_requests: int, concurrency: int, batch_size: int) -> dict:
    import httpx

    async with httpx.AsyncClient(base_url=url, timeout=30) as client:
        r = await client.get("/api/applications/sample", params={"n": 100, "seed": 1})
        r.raise_for_status()
        apps = [{k: v for k, v in a.items() if k not in ("issue_date", "is_default")} for a in r.json()]
        await client.post("/api/score", json={"applications": apps[:1]})          # warm-up

        # 1. one request at a time: the latency a single caller sees, and the server's own scoring time
        solo, server = [], []
        for i in range(200):
            t0 = time.perf_counter()
            resp = await client.post("/api/score", json={"applications": [apps[i % len(apps)]]})
            solo.append((time.perf_counter() - t0) * 1000)
            server.append(resp.json()["latency_ms"])

        # 2. many callers at once: throughput, and latency under load
        lat, errors, sem = [], 0, asyncio.Semaphore(concurrency)

        async def one(i: int):
            nonlocal errors
            async with sem:
                t0 = time.perf_counter()
                resp = await client.post("/api/score", json={"applications": [apps[i % len(apps)]]})
                lat.append((time.perf_counter() - t0) * 1000)
                errors += resp.status_code != 200

        t0 = time.perf_counter()
        await asyncio.gather(*(one(i) for i in range(n_requests)))
        wall = time.perf_counter() - t0

        batch = [apps[i % len(apps)] for i in range(batch_size)]
        b_times = []
        for _ in range(5):
            t = time.perf_counter()
            resp = await client.post("/api/score", json={"applications": batch})
            resp.raise_for_status()
            b_times.append(time.perf_counter() - t)

    lat = np.array(lat)
    pct = lambda a: {f"p{q}": float(np.percentile(a, q)) for q in (50, 95, 99)}  # noqa: E731
    return {"single_caller_latency_ms": pct(solo), "server_scoring_ms": pct(server), "url": url, "requests": n_requests, "concurrency": concurrency, "errors": int(errors),
            "requests_per_s": n_requests / wall, "latency_ms": {
                "p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95)),
                "p99": float(np.percentile(lat, 99))},
            "batch_size": batch_size, "batch_applications_per_s": batch_size / float(np.median(b_times))}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--requests", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=1000)
    a = p.parse_args()
    res = asyncio.run(run(a.url.rstrip("/"), a.requests, a.concurrency, a.batch_size))
    tag = "local" if "localhost" in a.url or "127.0.0.1" in a.url else "remote"
    (config.REPORTS_DIR / f"api_loadtest_{tag}.json").write_text(json.dumps(res, indent=2))
    sc, sv = res["single_caller_latency_ms"], res["server_scoring_ms"]
    print(f"One caller: latency p50 {sc['p50']:.1f} ms, p95 {sc['p95']:.1f} ms "
          f"(server scoring time p50 {sv['p50']:.1f} ms)")
    lt = res["latency_ms"]
    print(f"{res['requests']:,} single-application requests, {res['concurrency']} concurrent: "
          f"{res['requests_per_s']:,.0f} req/s, latency p50 {lt['p50']:.1f} ms, p95 {lt['p95']:.1f} ms, "
          f"p99 {lt['p99']:.1f} ms, {res['errors']} errors")
    print(f"Batch of {res['batch_size']:,}: {res['batch_applications_per_s']:,.0f} applications/s")


if __name__ == "__main__":
    main()
