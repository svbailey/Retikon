from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import time
from typing import Any

import httpx


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return ordered[int(k)]
    weight = k - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _load_image_base64(path: str) -> str:
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


def _build_payload(
    query_text: str | None,
    image_base64: str | None,
    top_k: int,
    mode: str | None,
    modalities: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"top_k": top_k}
    if query_text:
        payload["query_text"] = query_text
    if image_base64:
        payload["image_base64"] = image_base64
    if mode:
        payload["mode"] = mode
    if modalities:
        payload["modalities"] = [m.strip() for m in modalities.split(",") if m.strip()]
    return payload


async def _worker(
    name: str,
    queue: asyncio.Queue[int | None],
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    results: list[float],
    status_counts: dict[int, int],
    error_count: list[int],
) -> None:
    while True:
        token = await queue.get()
        if token is None:
            queue.task_done()
            return
        start = time.perf_counter()
        status_code: int | None = None
        try:
            response = await client.post(url, headers=headers, json=payload)
            status_code = response.status_code
            if status_code < 200 or status_code >= 300:
                error_count[0] += 1
        except httpx.HTTPError:
            error_count[0] += 1
        finally:
            elapsed = time.perf_counter() - start
            results.append(elapsed)
            if status_code is not None:
                status_counts[status_code] = status_counts.get(status_code, 0) + 1
            queue.task_done()


async def run_load_test(
    url: str,
    auth_token: str | None,
    qps: float,
    duration: float,
    concurrency: int,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    total_requests = max(1, int(qps * duration))
    queue: asyncio.Queue[int | None] = asyncio.Queue()
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    results: list[float] = []
    status_counts: dict[int, int] = {}
    error_count = [0]

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        workers = [
            asyncio.create_task(
                _worker(
                    f"worker-{i}",
                    queue,
                    client,
                    url,
                    headers,
                    payload,
                    results,
                    status_counts,
                    error_count,
                )
            )
            for i in range(concurrency)
        ]

        start = time.perf_counter()
        interval = 1.0 / qps if qps > 0 else 0.0
        for i in range(total_requests):
            await queue.put(i)
            if interval:
                await asyncio.sleep(interval)

        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        elapsed = time.perf_counter() - start

    success = len(results) - error_count[0]
    summary = {
        "url": url,
        "requests": len(results),
        "success": success,
        "errors": error_count[0],
        "status_counts": status_counts,
        "elapsed_seconds": round(elapsed, 4),
        "throughput_rps": round(len(results) / elapsed, 4) if elapsed > 0 else 0.0,
        "latency_p50_ms": round(_percentile(results, 0.5) * 1000.0, 2),
        "latency_p90_ms": round(_percentile(results, 0.9) * 1000.0, 2),
        "latency_p95_ms": round(_percentile(results, 0.95) * 1000.0, 2),
        "latency_p99_ms": round(_percentile(results, 0.99) * 1000.0, 2),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test the query service.")
    parser.add_argument("--url", default=os.getenv("QUERY_URL"))
    parser.add_argument(
        "--auth-token",
        default=os.getenv("RETIKON_AUTH_TOKEN") or os.getenv("RETIKON_JWT"),
    )
    parser.add_argument("--qps", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--query-text", default="Retikon demo query")
    parser.add_argument("--image-path", help="Optional image path to send as base64.")
    parser.add_argument("--mode", help="Optional query mode (text|all|image|audio).")
    parser.add_argument(
        "--modalities",
        help="Comma-separated modalities (document,transcript,image,audio).",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    if not args.url:
        raise SystemExit("--url or QUERY_URL is required")

    image_base64 = None
    if args.image_path:
        image_base64 = _load_image_base64(args.image_path)

    payload = _build_payload(
        args.query_text,
        image_base64,
        args.top_k,
        args.mode,
        args.modalities,
    )
    summary = asyncio.run(
        run_load_test(
            url=args.url,
            auth_token=args.auth_token,
            qps=args.qps,
            duration=args.duration,
            concurrency=args.concurrency,
            payload=payload,
            timeout_seconds=args.timeout,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
