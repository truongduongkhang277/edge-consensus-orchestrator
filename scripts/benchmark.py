"""Gửi nhiều yêu cầu và xuất thống kê latency cơ bản, không cần thư viện ngoài."""
import argparse
import json
import statistics
import time
import urllib.request


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * p))]


parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8001")
parser.add_argument("--requests", type=int, default=100)
args = parser.parse_args()
latencies, success = [], 0
for i in range(args.requests):
    body = json.dumps({"operation": "DEPLOY", "service": f"bench-{i}", "target": f"edge-{i % 3 + 1}"}).encode()
    request = urllib.request.Request(args.url + "/orchestrate", data=body, method="POST", headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            success += response.status == 201
    except Exception:
        pass
    latencies.append((time.perf_counter() - started) * 1000)
print(json.dumps({"requests": args.requests, "committed": success,
                  "success_rate": success / args.requests,
                  "latency_mean_ms": round(statistics.mean(latencies), 2),
                  "latency_p95_ms": round(percentile(latencies, .95), 2),
                  "latency_max_ms": round(max(latencies), 2)}, indent=2))
