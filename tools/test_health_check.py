#!/usr/bin/env python3
"""
Tests for the retry / backoff logic added to health_check.py (issue #193).

Uses unittest.mock to stub out the underlying check functions so we can
precisely control what each attempt returns and verify:
  - 5xx responses trigger retries
  - 4xx responses do NOT trigger retries
  - Connection errors / timeouts trigger retries
  - Retry count is respected
  - Exponential backoff is applied
  - TCP retry behaves correctly
  - JSON output includes attempt details
"""

import json
import time
import unittest
from unittest.mock import MagicMock, call, patch

# Import the module under test.  We import by file path so the tests work
# regardless of the working directory.
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "health_check", os.path.join(_HERE, "health_check.py")
)
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


# -----------------------------------------------------------------------
# Helper to build a deterministic side_effect list for check_http_service
# Each entry is (status, detail, code).
# -----------------------------------------------------------------------

def _http_side_effects(*triples):
    """Return a list of (status, detail, code) tuples for mock side_effect."""
    return list(triples)


# -----------------------------------------------------------------------
# HTTP retry tests
# -----------------------------------------------------------------------

class TestHTTPRetryLogic(unittest.TestCase):
    """Tests for check_http_service_with_retry."""

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_success_no_retry(self, mock_check, mock_sleep):
        """First attempt succeeds -> no retry."""
        mock_check.return_value = ("OK", "HTTP 200", 200)

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=3, backoff_secs=1.0,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(code, 200)
        self.assertEqual(len(attempts), 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_5xx_triggers_retry(self, mock_check, mock_sleep):
        """5xx on first attempt triggers a retry; second attempt succeeds."""
        mock_check.side_effect = [
            ("CRITICAL", "HTTP 503: Service Unavailable", 503),
            ("OK", "HTTP 200", 200),
        ]

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=2, backoff_secs=1.0,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(code, 200)
        self.assertEqual(len(attempts), 2)
        # One sleep between attempt 1 and 2
        mock_sleep.assert_called_once_with(1.0)

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_4xx_does_not_retry(self, mock_check, mock_sleep):
        """4xx (e.g. 404) is non-retryable -> no retry."""
        mock_check.return_value = ("WARNING", "HTTP 404: Not Found", 404)

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=3, backoff_secs=1.0,
        )

        self.assertEqual(status, "WARNING")
        self.assertEqual(code, 404)
        self.assertEqual(len(attempts), 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_connection_error_triggers_retry(self, mock_check, mock_sleep):
        """Exception (status_code=0) triggers retry."""
        mock_check.side_effect = [
            ("CRITICAL", "Connection refused", 0),
            ("OK", "HTTP 200", 200),
        ]

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=2, backoff_secs=0.5,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(code, 200)
        self.assertEqual(len(attempts), 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_retry_count_respected(self, mock_check, mock_sleep):
        """With retries=3, at most 4 total attempts (1 original + 3 retries)."""
        mock_check.return_value = ("CRITICAL", "HTTP 500: Internal Server Error", 500)

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=3, backoff_secs=0.1,
        )

        self.assertEqual(status, "CRITICAL")
        self.assertEqual(code, 500)
        self.assertEqual(len(attempts), 4)
        # 3 sleeps between 4 attempts
        self.assertEqual(mock_sleep.call_count, 3)

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_exponential_backoff(self, mock_check, mock_sleep):
        """Backoff doubles each retry: 1.0, 2.0, 4.0."""
        mock_check.return_value = ("CRITICAL", "HTTP 502: Bad Gateway", 502)

        hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=3, backoff_secs=1.0,
        )

        expected_delays = [call(1.0), call(2.0), call(4.0)]
        mock_sleep.assert_has_calls(expected_delays)

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_zero_retries_single_attempt(self, mock_check, mock_sleep):
        """retries=0 means exactly 1 attempt (preserves old behavior)."""
        mock_check.return_value = ("CRITICAL", "HTTP 500", 500)

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=0, backoff_secs=1.0,
        )

        self.assertEqual(len(attempts), 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_attempts_contain_elapsed_ms(self, mock_check, mock_sleep):
        """Each attempt dict has an elapsed_ms key."""
        mock_check.side_effect = [
            ("CRITICAL", "HTTP 500", 500),
            ("OK", "HTTP 200", 200),
        ]

        _, _, _, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=1, backoff_secs=0.01,
        )

        self.assertEqual(len(attempts), 2)
        for att in attempts:
            self.assertIn("elapsed_ms", att)
            self.assertIsInstance(att["elapsed_ms"], float)
            self.assertIn("attempt", att)
            self.assertIn("status", att)
            self.assertIn("detail", att)
            self.assertIn("code", att)

    @patch("time.sleep")
    @patch.object(hc, "check_http_service")
    def test_5xx_then_4xx_stops_at_4xx(self, mock_check, mock_sleep):
        """After a 5xx retry, if next response is 4xx it should stop (non-retryable)."""
        mock_check.side_effect = [
            ("CRITICAL", "HTTP 500", 500),
            ("WARNING", "HTTP 403: Forbidden", 403),
        ]

        status, detail, code, attempts = hc.check_http_service_with_retry(
            "localhost", 8080, "/health", 5, retries=3, backoff_secs=0.01,
        )

        self.assertEqual(status, "WARNING")
        self.assertEqual(code, 403)
        self.assertEqual(len(attempts), 2)


# -----------------------------------------------------------------------
# TCP retry tests
# -----------------------------------------------------------------------

class TestTCPRetryLogic(unittest.TestCase):
    """Tests for check_tcp_port_with_retry."""

    @patch("time.sleep")
    @patch.object(hc, "check_tcp_port")
    def test_tcp_success_no_retry(self, mock_check, mock_sleep):
        mock_check.return_value = ("OK", "Connected (5.0ms)", 5.0)

        status, detail, latency, attempts = hc.check_tcp_port_with_retry(
            "localhost", 5432, 5, retries=3, backoff_secs=1.0,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(len(attempts), 1)
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    @patch.object(hc, "check_tcp_port")
    def test_tcp_timeout_triggers_retry(self, mock_check, mock_sleep):
        mock_check.side_effect = [
            ("CRITICAL", "Connection timeout (5s)", 0),
            ("OK", "Connected (3.0ms)", 3.0),
        ]

        status, detail, latency, attempts = hc.check_tcp_port_with_retry(
            "localhost", 5432, 5, retries=2, backoff_secs=0.5,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(len(attempts), 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("time.sleep")
    @patch.object(hc, "check_tcp_port")
    def test_tcp_refused_triggers_retry(self, mock_check, mock_sleep):
        mock_check.side_effect = [
            ("CRITICAL", "Connection refused", 0),
            ("CRITICAL", "Connection refused", 0),
            ("OK", "Connected (2.0ms)", 2.0),
        ]

        status, detail, latency, attempts = hc.check_tcp_port_with_retry(
            "localhost", 6379, 5, retries=3, backoff_secs=0.1,
        )

        self.assertEqual(status, "OK")
        self.assertEqual(len(attempts), 3)

    @patch("time.sleep")
    @patch.object(hc, "check_tcp_port")
    def test_tcp_retry_count_respected(self, mock_check, mock_sleep):
        mock_check.return_value = ("CRITICAL", "Connection refused", 0)

        status, detail, latency, attempts = hc.check_tcp_port_with_retry(
            "localhost", 5432, 5, retries=2, backoff_secs=0.01,
        )

        self.assertEqual(status, "CRITICAL")
        # 1 original + 2 retries = 3 attempts
        self.assertEqual(len(attempts), 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep")
    @patch.object(hc, "check_tcp_port")
    def test_tcp_exponential_backoff(self, mock_check, mock_sleep):
        mock_check.return_value = ("CRITICAL", "Connection timeout (5s)", 0)

        hc.check_tcp_port_with_retry(
            "localhost", 5432, 5, retries=3, backoff_secs=1.0,
        )

        expected = [call(1.0), call(2.0), call(4.0)]
        mock_sleep.assert_has_calls(expected)


# -----------------------------------------------------------------------
# Retryable classification tests
# -----------------------------------------------------------------------

class TestRetryableClassification(unittest.TestCase):
    """Test the internal _is_http_retryable and _is_tcp_retryable helpers."""

    def test_http_5xx_is_retryable(self):
        self.assertTrue(hc._is_http_retryable(500, "HTTP 500"))
        self.assertTrue(hc._is_http_retryable(502, "HTTP 502"))
        self.assertTrue(hc._is_http_retryable(503, "HTTP 503"))

    def test_http_4xx_not_retryable(self):
        self.assertFalse(hc._is_http_retryable(400, "HTTP 400"))
        self.assertFalse(hc._is_http_retryable(401, "HTTP 401"))
        self.assertFalse(hc._is_http_retryable(403, "HTTP 403"))
        self.assertFalse(hc._is_http_retryable(404, "HTTP 404"))
        self.assertFalse(hc._is_http_retryable(429, "HTTP 429"))

    def test_http_connection_error_retryable(self):
        # code == 0 means an exception was caught
        self.assertTrue(hc._is_http_retryable(0, "Connection refused"))

    def test_http_2xx_not_retryable(self):
        # Success should not trigger retry logic (but the wrapper checks OK first)
        self.assertFalse(hc._is_http_retryable(200, "HTTP 200"))

    def test_tcp_timeout_retryable(self):
        self.assertTrue(hc._is_tcp_retryable("Connection timeout (5s)"))

    def test_tcp_refused_retryable(self):
        self.assertTrue(hc._is_tcp_retryable("Connection refused"))

    def test_tcp_os_error_retryable(self):
        self.assertTrue(hc._is_tcp_retryable("[Errno 111] Connection error"))

    def test_tcp_unknown_not_retryable(self):
        self.assertFalse(hc._is_tcp_retryable("Something unexpected"))


# -----------------------------------------------------------------------
# Integration: run_health_checks includes retry info
# -----------------------------------------------------------------------

class TestRunHealthChecksRetry(unittest.TestCase):
    """Verify that run_health_checks threads retry params through."""

    @patch.object(hc, "check_load_average", return_value=("OK", "Load: 0.1", 0.1))
    @patch.object(hc, "check_memory_usage", return_value=("OK", "50% used", 50.0))
    @patch.object(hc, "check_disk_usage", return_value=("OK", "40% used", 40.0))
    @patch.object(hc, "check_tcp_port_with_retry")
    @patch.object(hc, "check_http_service_with_retry")
    def test_retry_config_in_output(
        self, mock_http, mock_tcp, mock_disk, mock_mem, mock_load,
    ):
        mock_http.return_value = ("OK", "HTTP 200", 200, [
            {"attempt": 1, "elapsed_ms": 10.0, "status": "OK", "detail": "HTTP 200", "code": 200},
        ])
        mock_tcp.return_value = ("OK", "Connected (5.0ms)", 5.0, [
            {"attempt": 1, "elapsed_ms": 5.0, "status": "OK", "detail": "Connected (5.0ms)"},
        ])

        results = hc.run_health_checks(retries=2, backoff_secs=0.5, timeout_secs=10)

        self.assertIn("retry_config", results)
        self.assertEqual(results["retry_config"]["retries"], 2)
        self.assertEqual(results["retry_config"]["backoff_secs"], 0.5)
        self.assertEqual(results["retry_config"]["timeout_secs"], 10)

    @patch.object(hc, "check_load_average", return_value=("OK", "Load: 0.1", 0.1))
    @patch.object(hc, "check_memory_usage", return_value=("OK", "50% used", 50.0))
    @patch.object(hc, "check_disk_usage", return_value=("OK", "40% used", 40.0))
    @patch.object(hc, "check_tcp_port_with_retry")
    @patch.object(hc, "check_http_service_with_retry")
    def test_no_retry_config_when_zero(
        self, mock_http, mock_tcp, mock_disk, mock_mem, mock_load,
    ):
        mock_http.return_value = ("OK", "HTTP 200", 200, [
            {"attempt": 1, "elapsed_ms": 10.0, "status": "OK", "detail": "HTTP 200", "code": 200},
        ])
        mock_tcp.return_value = ("OK", "Connected (5.0ms)", 5.0, [
            {"attempt": 1, "elapsed_ms": 5.0, "status": "OK", "detail": "Connected (5.0ms)"},
        ])

        results = hc.run_health_checks(retries=0)

        self.assertNotIn("retry_config", results)

    @patch.object(hc, "check_load_average", return_value=("OK", "Load: 0.1", 0.1))
    @patch.object(hc, "check_memory_usage", return_value=("OK", "50% used", 50.0))
    @patch.object(hc, "check_disk_usage", return_value=("OK", "40% used", 40.0))
    @patch.object(hc, "check_tcp_port_with_retry")
    @patch.object(hc, "check_http_service_with_retry")
    def test_attempts_in_service_entry(
        self, mock_http, mock_tcp, mock_disk, mock_mem, mock_load,
    ):
        """When retries > 0, attempts list is included in service entry."""
        mock_http.return_value = ("OK", "HTTP 200", 200, [
            {"attempt": 1, "elapsed_ms": 10.0, "status": "OK", "detail": "HTTP 200", "code": 200},
        ])
        mock_tcp.return_value = ("OK", "Connected", 5.0, [
            {"attempt": 1, "elapsed_ms": 5.0, "status": "OK", "detail": "Connected"},
        ])

        results = hc.run_health_checks(retries=2)

        for svc_name, svc_data in results["services"].items():
            self.assertIn("attempts", svc_data)

        for infra_name, infra_data in results["infrastructure"].items():
            self.assertIn("attempts", infra_data)


# -----------------------------------------------------------------------
# JSON output mode tests
# -----------------------------------------------------------------------

class TestJSONOutput(unittest.TestCase):
    """Verify JSON output contains retry information."""

    @patch.object(hc, "check_load_average", return_value=("OK", "Load: 0.1", 0.1))
    @patch.object(hc, "check_memory_usage", return_value=("OK", "50% used", 50.0))
    @patch.object(hc, "check_disk_usage", return_value=("OK", "40% used", 40.0))
    @patch.object(hc, "check_tcp_port_with_retry")
    @patch.object(hc, "check_http_service_with_retry")
    def test_json_serializable_with_retries(
        self, mock_http, mock_tcp, mock_disk, mock_mem, mock_load,
    ):
        """Results with retries must be JSON-serializable."""
        mock_http.return_value = ("CRITICAL", "HTTP 500", 500, [
            {"attempt": 1, "elapsed_ms": 12.5, "status": "CRITICAL", "detail": "HTTP 500", "code": 500},
            {"attempt": 2, "elapsed_ms": 15.3, "status": "OK", "detail": "HTTP 200", "code": 200},
        ])
        mock_tcp.return_value = ("OK", "Connected", 5.0, [
            {"attempt": 1, "elapsed_ms": 5.0, "status": "OK", "detail": "Connected"},
        ])

        results = hc.run_health_checks(retries=1, backoff_secs=0.5)

        # Must not raise
        json_str = json.dumps(results, indent=2)
        parsed = json.loads(json_str)

        self.assertIn("retry_config", parsed)
        self.assertEqual(parsed["retry_config"]["retries"], 1)

        # Check that at least one service has attempts
        has_attempts = any(
            "attempts" in svc for svc in parsed["services"].values()
        )
        self.assertTrue(has_attempts)


# -----------------------------------------------------------------------
# CLI argument parsing tests
# -----------------------------------------------------------------------

class TestCLIParsing(unittest.TestCase):
    """Verify the new CLI arguments are parsed correctly."""

    @patch("sys.argv", ["health_check.py", "--retries", "5", "--timeout-secs", "10", "--backoff-secs", "2.0"])
    def test_retry_args(self):
        args = hc.parse_args()
        self.assertEqual(args.retries, 5)
        self.assertEqual(args.timeout_secs, 10.0)
        self.assertEqual(args.backoff_secs, 2.0)

    @patch("sys.argv", ["health_check.py"])
    def test_default_args(self):
        args = hc.parse_args()
        self.assertEqual(args.retries, 0)
        self.assertIsNone(args.timeout_secs)
        self.assertEqual(args.backoff_secs, 1.0)


# -----------------------------------------------------------------------
# Text output tests
# -----------------------------------------------------------------------

class TestTextOutput(unittest.TestCase):
    """Verify that the text report includes retry information."""

    @patch("sys.stdout", new_callable=lambda: open(os.devnull, "w"))
    def test_report_shows_attempt_count(self, mock_stdout):
        import io
        buf = io.StringIO()

        results = {
            "timestamp": "2026-06-18T12:00:00",
            "hostname": "test-host",
            "overall_status": "DEGRADED",
            "retry_config": {"retries": 3, "timeout_secs": None, "backoff_secs": 1.0},
            "services": {
                "backend": {
                    "status": "CRITICAL",
                    "detail": "HTTP 500",
                    "code": 500,
                    "endpoint": "http://localhost:8080/health",
                    "attempts": [
                        {"attempt": 1, "elapsed_ms": 100.0, "status": "CRITICAL", "detail": "HTTP 500", "code": 500},
                        {"attempt": 2, "elapsed_ms": 150.0, "status": "CRITICAL", "detail": "HTTP 500", "code": 500},
                    ],
                },
            },
            "infrastructure": {},
            "system": {},
        }

        # Capture print output
        import contextlib
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            hc.print_health_report(results)

        output = f.getvalue()
        self.assertIn("2 attempts", output)
        self.assertIn("attempt 1", output)
        self.assertIn("attempt 2", output)
        self.assertIn("100ms", output)
        self.assertIn("retry_config" in output or "Retries:" in output, [True])
        self.assertIn("Retries:", output)


if __name__ == "__main__":
    unittest.main()
