"""Run a repeatable experiment matrix and calculate 95% confidence intervals."""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_GATEWAYS = tuple(
    f"http://localhost:{port}"
    for port in range(8001, 8013)
)

RUN_SUMMARY_FIELDS = (
    "rate_rps",
    "gateway_count",
    "run",
    "selected_gateways",
    "requests",
    "success",
    "failed",
    "success_rate_percent",
    "mean_latency_ms",
    "p95_latency_ms",
    "completed",
    "process_exit_code",
    "result_file",
)

AGGREGATE_FIELDS = (
    "rate_rps",
    "gateway_count",
    "runs",
    "mean_latency_ms",
    "ci95_low_ms",
    "ci95_high_ms",
    "mean_p95_latency_ms",
    "mean_success_rate_percent",
)


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def confidence_interval_95(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    margin = 1.96 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - margin, mean + margin


def read_result(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    successes = [row for row in rows if row["success"].lower() == "true"]
    latencies = [float(row["latency_ms"]) for row in successes]
    return {
        "requests": len(rows),
        "success": len(successes),
        "failed": len(rows) - len(successes),
        "success_rate_percent": 100 * len(successes) / len(rows) if rows else 0.0,
        "mean_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 0.95),
    }


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_aggregate_rows(run_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[float, int], list[dict[str, Any]]] = defaultdict(list)
    for row in run_rows:
        if not row.get("completed"):
            continue
        grouped[(float(row["rate_rps"]), int(row["gateway_count"]))].append(row)

    aggregate_rows: list[dict[str, Any]] = []
    for (rate, gateway_count), rows in sorted(grouped.items()):
        means = [float(row["mean_latency_ms"]) for row in rows]
        p95_values = [float(row["p95_latency_ms"]) for row in rows]
        success_rates = [float(row["success_rate_percent"]) for row in rows]
        mean, low, high = confidence_interval_95(means)
        aggregate_rows.append(
            {
                "rate_rps": rate,
                "gateway_count": gateway_count,
                "runs": len(rows),
                "mean_latency_ms": round(mean, 3),
                "ci95_low_ms": round(low, 3),
                "ci95_high_ms": round(high, 3),
                "mean_p95_latency_ms": round(statistics.fmean(p95_values), 3),
                "mean_success_rate_percent": round(statistics.fmean(success_rates), 3),
            }
        )
    return aggregate_rows


def save_progress(output_dir: Path, run_rows: list[dict[str, Any]]) -> None:
    write_csv(
        output_dir / "runs_summary.csv",
        run_rows,
        RUN_SUMMARY_FIELDS,
    )
    write_csv(
        output_dir / "aggregate_summary.csv",
        build_aggregate_rows(run_rows),
        AGGREGATE_FIELDS,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chạy ma trận thực nghiệm Edge Consensus Orchestrator."
    )
    parser.add_argument("--gateways", nargs="+", default=list(DEFAULT_GATEWAYS))
    parser.add_argument(
        "--rates",
        nargs="+",
        type=float,
        default=[0.5, 1, 1.5, 2, 2.5, 3],
    )
    parser.add_argument("--gateway-counts", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--cooldown", type=float, default=2.0)
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
    parser.add_argument("--output-dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.runs <= 0 or args.requests <= 0:
        raise SystemExit("--runs và --requests phải lớn hơn 0")
    if any(count <= 0 or count > len(args.gateways) for count in args.gateway_counts):
        raise SystemExit("--gateway-counts phải nằm trong số gateway đã cung cấp")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir or Path("results") / f"experiment-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    load_script = Path(__file__).with_name("load_test.py")
    randomizer = random.Random(args.seed)
    run_rows: list[dict[str, Any]] = []

    total_cases = len(args.rates) * len(args.gateway_counts) * args.runs
    case_number = 0
    interrupted = False
    current_case: dict[str, Any] | None = None
    current_recorded = False

    try:
        for rate in args.rates:
            for gateway_count in args.gateway_counts:
                for run_number in range(1, args.runs + 1):
                    case_number += 1
                    selected = randomizer.sample(args.gateways, gateway_count)
                    result_path = output_dir / (
                        f"r{rate:g}-g{gateway_count}-run{run_number:02d}.csv"
                    )
                    current_case = {
                        "rate": rate,
                        "gateway_count": gateway_count,
                        "run_number": run_number,
                        "selected": selected,
                        "result_path": result_path,
                    }
                    current_recorded = False
                    command = [
                        sys.executable,
                        str(load_script),
                        "--gateways",
                        *selected,
                        "--rate",
                        str(rate),
                        "--requests",
                        str(args.requests),
                        "--workers",
                        str(args.workers),
                        "--timeout",
                        str(args.timeout),
                        "--distribution",
                        "round-robin",
                        "--seed",
                        str(args.seed + case_number),
                        "--operation",
                        args.operation,
                        "--service",
                        args.service,
                        "--target",
                        args.target,
                        "--replicas",
                        str(args.replicas),
                        "--output",
                        str(result_path),
                    ]
                    if args.operation == "MIGRATE":
                        command.extend(["--source", args.source])

                    print(
                        f"[{case_number}/{total_cases}] rate={rate:g}, "
                        f"gateways={gateway_count}, run={run_number}"
                    )
                    completed = subprocess.run(command, check=False)
                    if not result_path.exists():
                        print(f"Không tạo được kết quả: {result_path}", file=sys.stderr)
                        continue

                    summary = read_result(result_path)
                    is_complete = (
                        completed.returncode == 0
                        and summary["requests"] == args.requests
                    )
                    run_rows.append(
                        {
                            "rate_rps": rate,
                            "gateway_count": gateway_count,
                            "run": run_number,
                            "selected_gateways": "|".join(selected),
                            **{key: round(value, 3) if isinstance(value, float) else value
                               for key, value in summary.items()},
                            "completed": is_complete,
                            "process_exit_code": completed.returncode,
                            "result_file": str(result_path),
                        }
                    )
                    current_recorded = True
                    save_progress(output_dir, run_rows)
                    if args.cooldown > 0 and case_number < total_cases:
                        time.sleep(args.cooldown)

    except KeyboardInterrupt:
        interrupted = True
        print("\nĐã nhận Ctrl+C. Đang lưu các kết quả đã hoàn thành...", file=sys.stderr)
        if current_case and not current_recorded:
            result_path = current_case["result_path"]
            if result_path.exists():
                summary = read_result(result_path)
                run_rows.append(
                    {
                        "rate_rps": current_case["rate"],
                        "gateway_count": current_case["gateway_count"],
                        "run": current_case["run_number"],
                        "selected_gateways": "|".join(current_case["selected"]),
                        **{key: round(value, 3) if isinstance(value, float) else value
                           for key, value in summary.items()},
                        "completed": False,
                        "process_exit_code": 130,
                        "result_file": str(result_path),
                    }
                )

    finally:
        save_progress(output_dir, run_rows)

    runs_path = output_dir / "runs_summary.csv"
    aggregate_path = output_dir / "aggregate_summary.csv"
    print(f"Chi tiết từng lần chạy: {runs_path.resolve()}")
    print(f"Tổng hợp và 95% CI: {aggregate_path.resolve()}")
    if interrupted:
        return 130
    return 0 if run_rows else 1


if __name__ == "__main__":
    sys.exit(main())