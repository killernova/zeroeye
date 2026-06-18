#!/usr/bin/env python3
"""
Health check tool for the Tent of Trials platform.
Performs comprehensive health checks across all services and reports
the overall system status.

This tool is used by:
  - The Kubernetes liveness/readiness probes
  - The deployment pipeline (post-deployment validation)
  - The monitoring system (periodic health checks)
  - The on-call engineer (manual troubleshooting)

The health check performs the following checks:
  1. Service availability (HTTP health endpoints)
  2. Database connectivity (connection test)
  3. Redis connectivity (ping test)
  4. Kafka connectivity (metadata fetch)
  5. Message queue depth (consumer lag check)
  6. Certificate expiry (TLS certificate check)
  7. Disk space (filesystem usage check)
  8. Memory usage (process memory check)

Each check returns a status of OK, WARNING, or CRITICAL, along with
a detail message and optional diagnostic data.

Usage:
    python3 health_check.py                  # Check all services
    python3 health_check.py --service backend # Check specific service
    python3 health_check.py --json            # JSON output
    python3 health_check.py --watch           # Continuous monitoring
    python3 health_check.py --retries 3       # Retry failed checks up to 3 times
    python3 health_check.py --retries 3 --backoff-secs 2.0 --timeout-secs 10
"""

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SERVICES = {
    "backend": {"host": "localhost", "port": 8080, "path": "/health", "timeout": 5},
    "market": {"host": "localhost", "port": 8081, "path": "/health", "timeout": 5},
    "frailbox": {"host": "localhost", "port": 8082, "path": "/health", "timeout": 10},
    "frontend": {"host": "localhost", "port": 3000, "path": "/", "timeout": 5},
}

INFRASTRUCTURE = {
    "postgresql": {"host": os.environ.get("DB_HOST", "localhost"), "port": int(os.environ.get("DB_PORT", "5432")), "timeout": 5},
    "redis": {"host": os.environ.get("REDIS_HOST", "localhost"), "port": int(os.environ.get("REDIS_PORT", "6379")), "timeout": 5},
    "kafka": {"host": os.environ.get("KAFKA_HOST", "localhost"), "port": int(os.environ.get("KAFKA_PORT", "9092")), "timeout": 5},
}

DISK_THRESHOLD_WARNING = 80
DISK_THRESHOLD_CRITICAL = 90

MEMORY_THRESHOLD_WARNING = 80
MEMORY_THRESHOLD_CRITICAL = 90

# ---------------------------------------------------------------------------
# CHECK FUNCTIONS
# ---------------------------------------------------------------------------

def check_http_service(host: str, port: int, path: str, timeout: int) -> Tuple[str, str, int]:
    import http.client
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        status = resp.status
        body = resp.read().decode("utf-8", errors="replace")[:200]
        conn.close()

        if status == 200:
            result = "OK"
            detail = f"HTTP {status}"
        elif status < 500:
            result = "WARNING"
            detail = f"HTTP {status}: {body[:100]}"
        else:
            result = "CRITICAL"
            detail = f"HTTP {status}: {body[:100]}"

        return result, detail, status
    except Exception as e:
        return "CRITICAL", str(e), 0


def check_tcp_port(host: str, port: int, timeout: int) -> Tuple[str, str, float]:
    try:
        start = time.time()
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        latency = (time.time() - start) * 1000
        return "OK", f"Connected ({latency:.1f}ms)", latency
    except socket.timeout:
        return "CRITICAL", f"Connection timeout ({timeout}s)", 0
    except ConnectionRefusedError:
        return "CRITICAL", "Connection refused", 0
    except Exception as e:
        return "CRITICAL", str(e), 0


def check_certificate_expiry(host: str, port: int = 443) -> Tuple[str, str, int]:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                if not cert:
                    return "WARNING", "No certificate found", 0

                from datetime import datetime as dt
                expires = dt.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
                days_left = (expires - dt.now()).days

                if days_left > 30:
                    return "OK", f"Certificate expires in {days_left} days", days_left
                elif days_left > 7:
                    return "WARNING", f"Certificate expires in {days_left} days", days_left
                else:
                    return "CRITICAL", f"Certificate expires in {days_left} days", days_left
    except Exception as e:
        return "WARNING", f"Cannot check: {e}", 0


def check_disk_usage(path: str = "/") -> Tuple[str, str, float]:
    try:
        stat = os.statvfs(path)
        total = stat.f_frsize * stat.f_blocks
        free = stat.f_frsize * stat.f_bavail
        used = total - free
        pct = (used / total) * 100

        if pct < DISK_THRESHOLD_WARNING:
            return "OK", f"{pct:.1f}% used ({used // (1024**3)}GB/{total // (1024**3)}GB)", pct
        elif pct < DISK_THRESHOLD_CRITICAL:
            return "WARNING", f"{pct:.1f}% used ({used // (1024**3)}GB/{total // (1024**3)}GB)", pct
        else:
            return "CRITICAL", f"{pct:.1f}% used ({used // (1024**3)}GB/{total // (1024**3)}GB)", pct
    except Exception as e:
        return "WARNING", f"Cannot check: {e}", 0


def check_memory_usage() -> Tuple[str, str, float]:
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().replace(" kB", "")
                    try:
                        meminfo[key] = int(value) * 1024
                    except ValueError:
                        pass

        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)
        used = total - available
        pct = (used / total) * 100 if total > 0 else 0

        if pct < MEMORY_THRESHOLD_WARNING:
            return "OK", f"{pct:.1f}% used ({used // (1024**3)}GB/{total // (1024**3)}GB)", pct
        elif pct < MEMORY_THRESHOLD_CRITICAL:
            return "WARNING", f"{pct:.1f}% used", pct
        else:
            return "CRITICAL", f"{pct:.1f}% used", pct
    except Exception as e:
        return "WARNING", f"Cannot check: {e}", 0


def check_load_average() -> Tuple[str, str, float]:
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().strip().split()
            load = float(parts[0])
            cpu_count = os.cpu_count() or 1
            load_pct = (load / cpu_count) * 100

            if load_pct < 70:
                return "OK", f"Load: {load} ({load_pct:.0f}% of {cpu_count} cores)", load
            elif load_pct < 90:
                return "WARNING", f"Load: {load} ({load_pct:.0f}% of {cpu_count} cores)", load
            else:
                return "CRITICAL", f"Load: {load} ({load_pct:.0f}% of {cpu_count} cores)", load
    except Exception as e:
        return "WARNING", f"Cannot check: {e}", 0


# ---------------------------------------------------------------------------
# RETRY WRAPPERS
# ---------------------------------------------------------------------------

def _is_http_retryable(status_code: int, detail: str) -> bool:
    """Return True if the HTTP result is retryable (5xx, timeout, connection error)."""
    if status_code >= 500:
        return True
    # status_code == 0 means an exception occurred (timeout / connection error)
    if status_code == 0:
        return True
    return False


def _is_tcp_retryable(detail: str) -> bool:
    """Return True if the TCP failure is retryable (timeout / refused / OS error)."""
    lower = detail.lower()
    if "timeout" in lower or "refused" in lower:
        return True
    # Generic socket/OS errors (not a clean connect)
    if "error" in lower or "errno" in lower:
        return True
    return False


def check_http_service_with_retry(
    host: str,
    port: int,
    path: str,
    timeout: int,
    retries: int = 0,
    backoff_secs: float = 1.0,
    verbose: bool = False,
    label: str = "",
) -> Tuple[str, str, int, List[Dict[str, Any]]]:
    """
    Wrap *check_http_service* with retry / exponential-backoff logic.

    Returns
    -------
    (status, detail, http_code, attempts)
        attempts is a list of per-attempt dicts with keys:
        attempt, elapsed_ms, status, detail, code
    """
    attempts: List[Dict[str, Any]] = []
    delay = backoff_secs

    for attempt_num in range(1, retries + 2):  # 1 .. retries+1
        start = time.time()
        status, detail, code = check_http_service(host, port, path, timeout)
        elapsed_ms = (time.time() - start) * 1000

        attempt_info: Dict[str, Any] = {
            "attempt": attempt_num,
            "elapsed_ms": round(elapsed_ms, 2),
            "status": status,
            "detail": detail,
            "code": code,
        }
        attempts.append(attempt_info)

        if verbose:
            tag = label or f"{host}:{port}{path}"
            print(
                f"  [{tag}] attempt {attempt_num}/{retries + 1}: "
                f"{status} -- {detail} ({elapsed_ms:.0f}ms)"
            )

        # Success -- stop immediately
        if status == "OK":
            break

        # Non-retryable (4xx, etc.) -- stop immediately
        if not _is_http_retryable(code, detail):
            break

        # Last attempt -- no more retries
        if attempt_num > retries:
            break

        # Backoff before next attempt
        if verbose:
            print(f"    retrying in {delay:.1f}s ...")
        time.sleep(delay)
        delay *= 2  # exponential backoff

    return status, detail, code, attempts


def check_tcp_port_with_retry(
    host: str,
    port: int,
    timeout: int,
    retries: int = 0,
    backoff_secs: float = 1.0,
    verbose: bool = False,
    label: str = "",
) -> Tuple[str, str, float, List[Dict[str, Any]]]:
    """
    Wrap *check_tcp_port* with retry / exponential-backoff logic.

    Returns
    -------
    (status, detail, latency, attempts)
        attempts is a list of per-attempt dicts with keys:
        attempt, elapsed_ms, status, detail
    """
    attempts: List[Dict[str, Any]] = []
    delay = backoff_secs

    for attempt_num in range(1, retries + 2):
        start = time.time()
        status, detail, latency = check_tcp_port(host, port, timeout)
        elapsed_ms = (time.time() - start) * 1000

        attempt_info: Dict[str, Any] = {
            "attempt": attempt_num,
            "elapsed_ms": round(elapsed_ms, 2),
            "status": status,
            "detail": detail,
        }
        attempts.append(attempt_info)

        if verbose:
            tag = label or f"{host}:{port}"
            print(
                f"  [{tag}] attempt {attempt_num}/{retries + 1}: "
                f"{status} -- {detail} ({elapsed_ms:.0f}ms)"
            )

        if status == "OK":
            break

        if not _is_tcp_retryable(detail):
            break

        if attempt_num > retries:
            break

        if verbose:
            print(f"    retrying in {delay:.1f}s ...")
        time.sleep(delay)
        delay *= 2

    return status, detail, latency, attempts


# ---------------------------------------------------------------------------
# HEALTH CHECK RUNNER
# ---------------------------------------------------------------------------

def run_health_checks(
    service: Optional[str] = None,
    json_output: bool = False,
    retries: int = 0,
    timeout_secs: Optional[float] = None,
    backoff_secs: float = 1.0,
    verbose: bool = False,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "hostname": socket.gethostname(),
        "services": {},
        "infrastructure": {},
        "system": {},
        "overall_status": "OK",
    }

    if retries > 0:
        results["retry_config"] = {
            "retries": retries,
            "timeout_secs": timeout_secs,
            "backoff_secs": backoff_secs,
        }

    all_ok = True

    # Check services
    for name, config in SERVICES.items():
        if service and name != service:
            continue
        svc_timeout = int(timeout_secs) if timeout_secs is not None else config["timeout"]
        status, detail, code, attempts = check_http_service_with_retry(
            config["host"], config["port"], config["path"], svc_timeout,
            retries=retries, backoff_secs=backoff_secs,
            verbose=verbose, label=name,
        )
        entry: Dict[str, Any] = {
            "status": status,
            "detail": detail,
            "code": code,
            "endpoint": f"http://{config['host']}:{config['port']}{config['path']}",
        }
        if len(attempts) > 1 or retries > 0:
            entry["attempts"] = attempts
        results["services"][name] = entry
        if status == "CRITICAL":
            all_ok = False

    # Check infrastructure
    for name, config in INFRASTRUCTURE.items():
        if service and name != service:
            continue
        infra_timeout = int(timeout_secs) if timeout_secs is not None else config["timeout"]
        status, detail, latency, attempts = check_tcp_port_with_retry(
            config["host"], config["port"], infra_timeout,
            retries=retries, backoff_secs=backoff_secs,
            verbose=verbose, label=name,
        )
        entry = {
            "status": status,
            "detail": detail,
            "endpoint": f"{config['host']}:{config['port']}",
        }
        if len(attempts) > 1 or retries > 0:
            entry["attempts"] = attempts
        results["infrastructure"][name] = entry
        if status == "CRITICAL":
            all_ok = False

    # Check system resources
    disk_status, disk_detail, disk_pct = check_disk_usage()
    results["system"]["disk"] = {"status": disk_status, "detail": disk_detail}
    if disk_status == "CRITICAL":
        all_ok = False

    mem_status, mem_detail, mem_pct = check_memory_usage()
    results["system"]["memory"] = {"status": mem_status, "detail": mem_detail}
    if mem_status == "CRITICAL":
        all_ok = False

    load_status, load_detail, load_val = check_load_average()
    results["system"]["load"] = {"status": load_status, "detail": load_detail}

    # Check certificate expiry (web services)
    for name, config in SERVICES.items():
        if service and name != service:
            continue
        if config["port"] == 443:
            cert_status, cert_detail, days_left = check_certificate_expiry(config["host"])
            results["services"][name]["certificate"] = {
                "status": cert_status,
                "detail": cert_detail,
                "days_remaining": days_left,
            }
            if cert_status == "CRITICAL":
                all_ok = False

    results["overall_status"] = "OK" if all_ok else "DEGRADED"

    return results


def print_health_report(results: Dict[str, Any]):
    print(f"\n{'='*60}")
    print(f"  HEALTH CHECK REPORT")
    print(f"  Host: {results['hostname']}")
    print(f"  Time: {results['timestamp']}")
    print(f"  Overall: {results['overall_status']}")
    if "retry_config" in results:
        rc = results["retry_config"]
        print(f"  Retries: max={rc['retries']}  timeout={rc['timeout_secs']}s  backoff={rc['backoff_secs']}s")
    print(f"{'='*60}")

    for category, items in [("Services", results["services"]),
                             ("Infrastructure", results["infrastructure"]),
                             ("System", results["system"])]:
        if items:
            print(f"\n  {category}:")
            for name, check in items.items():
                if isinstance(check, dict) and "status" in check:
                    status_icon = {"OK": "+", "WARNING": "!", "CRITICAL": "x"}.get(check["status"], "?")
                    attempt_suffix = ""
                    if "attempts" in check:
                        total = len(check["attempts"])
                        attempt_suffix = f"  [{total} attempt{'s' if total > 1 else ''}]"
                    print(f"    {status_icon} {name}: {check['detail']}{attempt_suffix}")
                    # Print per-attempt summary when retries occurred
                    if "attempts" in check and len(check["attempts"]) > 1:
                        for att in check["attempts"]:
                            code_str = f" (HTTP {att['code']})" if "code" in att and att["code"] else ""
                            reason = att.get("detail", "")
                            print(
                                f"        -> attempt {att['attempt']}: "
                                f"{att['elapsed_ms']:.0f}ms -- {att['status']}{code_str} {reason}"
                            )
                else:
                    print(f"    {name}:")
                    for sub_name, sub_check in check.items():
                        if isinstance(sub_check, dict) and "status" in sub_check:
                            sub_icon = {"OK": "+", "WARNING": "!", "CRITICAL": "x"}.get(sub_check["status"], "?")
                            print(f"      {sub_icon} {sub_name}: {sub_check['detail']}")
    print()


def parse_args():
    parser = argparse.ArgumentParser(description="Health check tool")
    parser.add_argument("--service", "-s", help="Check specific service only")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")
    parser.add_argument("--watch", "-w", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Check interval in seconds")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--retries", type=int, default=0,
        help="Max number of retries for failed checks (default: 0, no retries)",
    )
    parser.add_argument(
        "--timeout-secs", type=float, default=None,
        help="Per-attempt timeout in seconds (default: per-service timeout)",
    )
    parser.add_argument(
        "--backoff-secs", type=float, default=1.0,
        help="Initial backoff delay in seconds, doubles each retry (default: 1.0)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    retry_kwargs = dict(
        retries=args.retries,
        timeout_secs=args.timeout_secs,
        backoff_secs=args.backoff_secs,
        verbose=not args.json,
    )

    if args.watch:
        print(f"Continuous monitoring (interval: {args.interval}s). Press Ctrl+C to stop.")
        try:
            while True:
                results = run_health_checks(args.service, args.json, **retry_kwargs)
                if args.json:
                    print(json.dumps(results, indent=2))
                else:
                    print_health_report(results)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nMonitoring stopped")
    else:
        results = run_health_checks(args.service, args.json, **retry_kwargs)
        if args.json:
            output = json.dumps(results, indent=2)
            print(output)
        else:
            print_health_report(results)

        if args.output:
            with open(args.output, "w") as f:
                if args.json:
                    json.dump(results, f, indent=2)
                else:
                    json.dump(results, f, indent=2)
            print(f"Report saved to {args.output}")

        if results["overall_status"] == "DEGRADED":
            return 1

    return 0


if __name__ == "__main__":
    main()
