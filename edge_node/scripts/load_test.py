"""Generate controlled orchestration traffic for the edge cluster.

The script uses only the Python standard library.  By default every request
is an idempotent DEPLOY for the same service, so a benchmark does not create
one container per request.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_GATEWAYS = tuple(
    f"http://localhost:{port}"
    for port in range(8001, 8013)
)

@dataclass(slots=True)
class RequestResult:
    request_id: int
    scheduled_at: str
    started_at: str
    gateway: str
    operation: str
    service: str
    requested_target: str
    status_code: int
    success: bool
    latency_ms: float
    leader: str
    term: str
    log_index: str
    acknowledgements: str
    committed_target: str
    automatic_target: str
    error: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def parse_response(error: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        raw = error.read()
        if not raw:
            return {"error": str(error)}
        body = json.loads(raw.decode("utf-8"))
        return body if isinstance(body, dict) else {"error": str(body)}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"error": str(error)}


def send_one(
    request_id: int,
    scheduled_at: str,
    gateway: str,
    payload: dict[str, Any],
    timeout: float,
) -> RequestResult:
    started_at = utc_now()
    started = time.perf_counter()
    status_code = 0
    response_body: dict[str, Any] = {}
    error_message = ""

    request = urllib.request.Request(
        url=gateway.rstrip("/") + "/orchestrate",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.status
            raw = response.read()
            if raw:
                decoded = json.loads(raw.decode("utf-8"))
                if isinstance(decoded, dict):
                    response_body = decoded
    except urllib.error.HTTPError as error:
        status_code = error.code
        response_body = parse_response(error)
        error_message = str(response_body.get("error", error))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        error_message = str(error)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        error_message = f"Phản hồi JSON không hợp lệ: {error}"

    latency_ms = (time.perf_counter() - started) * 1000
    success = 200 <= status_code < 300 and response_body.get("status") == "committed"
    if not success and not error_message:
        error_message = str(response_body.get("error", f"HTTP {status_code}"))

    return RequestResult(
        request_id=request_id,
        scheduled_at=scheduled_at,
        started_at=started_at,
        gateway=gateway,
        operation=str(payload["operation"]),
        service=str(payload["service"]),
        requested_target=str(payload["target"]),
        status_code=status_code,
        success=success,
        latency_ms=round(latency_ms, 3),
        leader=str(response_body.get("leader", "")),
        term=str(response_body.get("term", "")),
        log_index=str(response_body.get("log_index", "")),
        acknowledgements=str(response_body.get("acks", "")),
        committed_target=str(response_body.get("target", "")),
        automatic_target=str(response_body.get("automatic_target", "")),
        error=error_message,
    )


def choose_gateway(
    gateways: list[str],
    request_id: int,
    distribution: str,
    randomizer: random.Random,
    random_lock: threading.Lock,
) -> str:
    if distribution == "round-robin":
        return gateways[(request_id - 1) % len(gateways)]
    with random_lock:
        return randomizer.choice(gateways)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gửi tải có kiểm soát tới Edge Consensus Orchestrator."
    )
    parser.add_argument("--gateways", nargs="+", default=list(DEFAULT_GATEWAYS))
    parser.add_argument("--rate", type=float, default=1.0, help="Số request/giây.")
    parser.add_argument("--requests", type=int, default=100, help="Tổng số request.")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--distribution",
        choices=("round-robin", "random"),
        default="round-robin",
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--operation",
        choices=("DEPLOY", "REPLICATE", "MIGRATE", "REMOVE"),
        default="DEPLOY",
    )
    parser.add_argument("--service", default="patient-api")
    parser.add_argument("--target", default="AUTO")
    parser.add_argument("--source", default="edge-1")
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--output", type=Path)
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.rate <= 0:
        raise ValueError("--rate phải lớn hơn 0")
    if args.requests <= 0:
        raise ValueError("--requests phải lớn hơn 0")
    if args.workers <= 0:
        raise ValueError("--workers phải lớn hơn 0")
    if args.replicas <= 0:
        raise ValueError("--replicas phải lớn hơn 0")
    if not args.gateways:
        raise ValueError("Phải có ít nhất một gateway")
    if args.operation == "REMOVE" and args.target.upper() == "AUTO":
        raise ValueError("REMOVE cần --target cụ thể")
    if args.operation == "MIGRATE" and args.source == args.target:
        raise ValueError("MIGRATE cần source và target khác nhau")


def run_load(args: argparse.Namespace) -> tuple[list[RequestResult], dict[str, Any]]:
    validate_args(args)
    payload: dict[str, Any] = {
        "operation": args.operation,
        "service": args.service,
        "target": args.target,
        "replicas": args.replicas,
    }
    if args.operation == "MIGRATE":
        payload["source"] = args.source

    randomizer = random.Random(args.seed)
    random_lock = threading.Lock()
    interval = 1.0 / args.rate
    benchmark_started = time.perf_counter()
    futures = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for request_id in range(1, args.requests + 1):
            due = benchmark_started + (request_id - 1) * interval
            remaining = due - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)

            gateway = choose_gateway(
                args.gateways,
                request_id,
                args.distribution,
                randomizer,
                random_lock,
            )
            futures.append(
                executor.submit(
                    send_one,
                    request_id,
                    utc_now(),
                    gateway,
                    dict(payload),
                    args.timeout,
                )
            )

        results = [future.result() for future in as_completed(futures)]

    elapsed = time.perf_counter() - benchmark_started
    results.sort(key=lambda item: item.request_id)
    successful = [item for item in results if item.success]
    latencies = [item.latency_ms for item in successful]
    summary = {
        "requests": len(results),
        "success": len(successful),
        "failed": len(results) - len(successful),
        "success_rate_percent": round(100 * len(successful) / len(results), 3),
        "configured_rate_rps": args.rate,
        "observed_throughput_rps": round(len(results) / elapsed, 3),
        "elapsed_seconds": round(elapsed, 3),
        "latency_mean_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "latency_median_ms": round(statistics.median(latencies), 3) if latencies else 0.0,
        "latency_p95_ms": round(percentile(latencies, 0.95), 3),
        "gateways": args.gateways,
    }
    return results, summary


def write_results(path: Path, results: list[RequestResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(asdict(results[0]).keys())
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_args(args)
    except ValueError as error:
        parser.error(str(error))

    if args.output is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output = Path("results") / f"load-{stamp}.csv"

    results, summary = run_load(args)
    write_results(args.output, results)
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"CSV: {args.output.resolve()}")
    print(f"Summary: {summary_path.resolve()}")
    return 0 if summary["success"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
