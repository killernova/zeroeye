"""
Regression tests for log_aggregator parsers.

Tests use hand-written sample log lines covering valid and malformed JSON,
plain text application logs, syslog-style lines, Nginx access logs, empty
lines, and edge cases. Tests do NOT rely on parser-generated fixtures.
"""

import sys
import os
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

from log_aggregator import JSONLogParser, TextLogParser, NginxLogParser



class TestJSONLogParser(unittest.TestCase):

    def setUp(self):
        self.parser = JSONLogParser()

    def test_valid_json_with_all_fields(self):
        line = json.dumps({
            "timestamp": "2026-06-20T10:30:00Z",
            "level": "error",
            "service": "auth-service",
            "message": "Login failed for user admin",
        })
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "json")
        self.assertEqual(result["level"], "error")
        self.assertEqual(result["service"], "auth-service")
        self.assertEqual(result["message"], "Login failed for user admin")

    def test_valid_json_with_alternate_keys(self):
        line = json.dumps({
            "time": "2026-06-20T10:30:00Z",
            "severity": "warning",
            "logger": "api",
            "msg": "Rate limit exceeded",
        })
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "warning")
        self.assertEqual(result["service"], "api")
        self.assertEqual(result["message"], "Rate limit exceeded")

    def test_json_with_at_timestamp(self):
        line = json.dumps({
            "@timestamp": "2026-06-20T10:30:00Z",
            "level": "info",
            "message": "Indexing complete",
        })
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["timestamp"], "2026-06-20T10:30:00Z")

    def test_json_default_level_when_missing(self):
        line = json.dumps({"message": "no level here"})
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "info")

    def test_malformed_json_returns_none(self):
        lines = ["{broken json", "not json at all", "{", "", "}{"]
        for line in lines:
            result = self.parser.parse(line)
            self.assertIsNone(result), f"Expected None for: {line!r}"

    def test_json_array_returns_none(self):
        result = self.parser.parse("[1, 2, 3]")
        self.assertIsNone(result)

    def test_json_string_returns_none(self):
        result = self.parser.parse('"just a string"')
        self.assertIsNone(result)

    def test_json_empty_message(self):
        line = json.dumps({"level": "debug", "message": ""})
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["message"], "")


class TestTextLogParser(unittest.TestCase):

    def setUp(self):
        self.parser = TextLogParser()

    def test_iso8601_timestamp_extraction(self):
        line = "2026-06-20T10:30:00 [AUTH] ERROR Login failed"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "text")
        self.assertTrue(result["timestamp"] is not None)
        self.assertEqual(result["level"], "error")
        self.assertEqual(result["service"], "AUTH")

    def test_standard_timestamp_extraction(self):
        line = "2026-06-20 10:30:00 WARNING Disk almost full"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["timestamp"] is not None)
        self.assertEqual(result["level"], "warn")

    def test_syslog_timestamp_extraction(self):
        line = "Jun 20 10:30:00 myhost sshd[1234]: INFO Connection from 10.0.0.1"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["timestamp"] is not None)
        self.assertEqual(result["level"], "info")

    def test_empty_line_returns_none(self):
        self.assertTrue(self.parser.parse("") is None)
        self.assertTrue(self.parser.parse("   ") is None)
        self.assertTrue(self.parser.parse("\n") is None)
        self.assertTrue(self.parser.parse("\t\t") is None)

    def test_unknown_severity(self):
        line = "2026-06-20T10:30:00 Something happened here"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "unknown")

    def test_critical_severity(self):
        line = "2026-06-20T10:30:00 CRITICAL System shutdown initiated"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "error")

    def test_fatal_severity(self):
        line = "2026-06-20T10:30:00 FATAL Out of memory"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "error")

    def test_debug_severity(self):
        line = "2026-06-20T10:30:00 DEBUG Cache hit ratio 0.85"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "debug")

    def test_service_extraction_brackets(self):
        line = "2026-06-20T10:30:00 [PAYMENT] INFO Transaction completed"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["service"], "PAYMENT")

    def test_no_service_found(self):
        line = "just a plain log line with no service marker"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["service"] is None)

    def test_message_is_full_line(self):
        line = "2026-06-20T10:30:00 INFO hello world"
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["message"], line.strip())


class TestNginxLogParser(unittest.TestCase):

    def setUp(self):
        self.parser = NginxLogParser()

    def _make_nginx_line(self, status="200", request="GET / HTTP/1.1"):
        return (
            "127.0.0.1 - - [20/Jun/2026:10:30:00 +0000] "
            f'"{request}" {status} 1234 "https://ref.example.com" "Mozilla/5.0"'
        )

    def test_valid_nginx_log(self):
        line = self._make_nginx_line()
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "nginx")
        self.assertEqual(result["service"], "nginx")
        self.assertTrue(result["fields"]["remote_addr"] == "127.0.0.1")
        self.assertTrue(result["fields"]["status"] == 200)
        self.assertTrue(result["fields"]["body_bytes"] == "1234")

    def test_2xx_status_is_info(self):
        line = self._make_nginx_line(status="200")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "info")

    def test_3xx_status_is_info(self):
        line = self._make_nginx_line(status="302")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "info")

    def test_4xx_status_is_warn(self):
        line = self._make_nginx_line(status="404")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "warn")

    def test_5xx_status_is_error(self):
        line = self._make_nginx_line(status="500")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "error")

    def test_503_status_is_error(self):
        line = self._make_nginx_line(status="503")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], "error")

    def test_timestamp_extraction(self):
        line = self._make_nginx_line()
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["timestamp"] is not None)
        self.assertIsInstance(result["timestamp"], int)

    def test_malformed_nginx_returns_none(self):
        lines = [
            "this is not nginx log",
            "",
            "127.0.0.1 missing brackets and quotes",
            '127.0.0.1 - - "GET / HTTP/1.1" 200',
        ]
        for line in lines:
            result = self.parser.parse(line)
            self.assertIsNone(result), f"Expected None for: {line!r}"

    def test_request_field_preserved(self):
        line = self._make_nginx_line(request="POST /api/v1/login HTTP/1.1")
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["message"], "POST /api/v1/login HTTP/1.1")
        self.assertTrue(result["fields"]["request"] == "POST /api/v1/login HTTP/1.1")

    def test_user_agent_preserved(self):
        line = self._make_nginx_line()
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["fields"]["user_agent"] == "Mozilla/5.0")

    def test_referer_preserved(self):
        line = self._make_nginx_line()
        result = self.parser.parse(line)
        self.assertIsNotNone(result)
        self.assertTrue(result["fields"]["referer"] == "https://ref.example.com")


class TestParserEdgeCases(unittest.TestCase):

    def test_json_parser_does_not_parse_nginx(self):
        parser = JSONLogParser()
        line = '127.0.0.1 - - [20/Jun/2026:10:30:00 +0000] "GET / HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
        self.assertTrue(parser.parse(line) is None)

    def test_text_parser_fallback_for_nginx(self):
        parser = TextLogParser()
        line = '127.0.0.1 - - [20/Jun/2026:10:30:00 +0000] "GET / HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
        result = parser.parse(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["format"], "text")

    def test_unicode_in_json_message(self):
        parser = JSONLogParser()
        line = json.dumps({"level": "info", "message": "User\u00e9 logged in"})
        result = parser.parse(line)
        self.assertIsNotNone(result)
        self.assertIn("logged in", result["message"])


if __name__ == "__main__":
    import unittest
    unittest.main()
