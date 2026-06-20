import unittest

from tools.log_aggregator import JSONLogParser, NginxLogParser, TextLogParser


class JSONLogParserTests(unittest.TestCase):
    def test_parses_structured_json_log(self):
        parser = JSONLogParser()

        entry = parser.parse(
            '{"timestamp":"2026-06-20T03:20:00Z","level":"ERROR",'
            '"service":"payments","message":"charge declined","request_id":"req-123"}'
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["format"], "json")
        self.assertEqual(entry["timestamp"], "2026-06-20T03:20:00Z")
        self.assertEqual(entry["level"], "ERROR")
        self.assertEqual(entry["service"], "payments")
        self.assertEqual(entry["message"], "charge declined")
        self.assertEqual(entry["fields"]["request_id"], "req-123")

    def test_rejects_malformed_and_non_object_json(self):
        parser = JSONLogParser()

        self.assertIsNone(parser.parse('{"timestamp": "2026-06-20T03:20:00Z"'))
        self.assertIsNone(parser.parse('["not", "a", "log", "object"]'))


class TextLogParserTests(unittest.TestCase):
    def test_parses_standard_text_log_with_timestamp_level_and_service(self):
        parser = TextLogParser()

        entry = parser.parse(
            "2026-06-20 03:21:45 ERROR [checkout] payment gateway timeout"
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["format"], "text")
        self.assertEqual(entry["timestamp"], 1781925705)
        self.assertEqual(entry["level"], "error")
        self.assertEqual(entry["service"], "checkout")
        self.assertEqual(
            entry["message"],
            "2026-06-20 03:21:45 ERROR [checkout] payment gateway timeout",
        )

    def test_parses_syslog_style_line_and_documents_service_extraction_limit(self):
        parser = TextLogParser()

        entry = parser.parse("Jun 20 03:22:10 API: background task completed")

        self.assertIsNotNone(entry)
        self.assertIsInstance(entry["timestamp"], int)
        self.assertEqual(entry["level"], "unknown")
        self.assertIsNone(
            entry["service"],
            "Current service extraction stops at the first colon-like token, "
            "so syslog HH:MM:SS prevents later API: service detection.",
        )

    def test_parses_plain_text_uppercase_service_prefix(self):
        parser = TextLogParser()

        entry = parser.parse("API: background task completed")

        self.assertIsNotNone(entry)
        self.assertIsNone(entry["timestamp"])
        self.assertEqual(entry["level"], "unknown")
        self.assertEqual(entry["service"], "API")

    def test_returns_none_for_empty_lines(self):
        parser = TextLogParser()

        self.assertIsNone(parser.parse(""))
        self.assertIsNone(parser.parse("   \t"))


class NginxLogParserTests(unittest.TestCase):
    def test_parses_successful_access_log(self):
        parser = NginxLogParser()

        entry = parser.parse(
            '203.0.113.10 - alice [20/Jun/2026:03:23:11 +0000] '
            '"GET /health HTTP/1.1" 200 42 "-" "curl/8.0"'
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["format"], "nginx")
        self.assertEqual(entry["timestamp"], 1781925791)
        self.assertEqual(entry["level"], "info")
        self.assertEqual(entry["service"], "nginx")
        self.assertEqual(entry["message"], "GET /health HTTP/1.1")
        self.assertEqual(entry["fields"]["remote_addr"], "203.0.113.10")
        self.assertEqual(entry["fields"]["remote_user"], "-")
        self.assertEqual(entry["fields"]["status"], 200)
        self.assertEqual(entry["fields"]["body_bytes"], "42")
        self.assertEqual(entry["fields"]["user_agent"], "curl/8.0")

    def test_classifies_http_client_and_server_errors(self):
        parser = NginxLogParser()

        not_found = parser.parse(
            '203.0.113.11 - - [20/Jun/2026:03:24:00 +0000] '
            '"GET /missing HTTP/1.1" 404 12 "-" "Mozilla/5.0"'
        )
        upstream_failure = parser.parse(
            '203.0.113.12 - - [20/Jun/2026:03:24:30 +0000] '
            '"POST /orders HTTP/1.1" 502 128 "-" "Mozilla/5.0"'
        )

        self.assertEqual(not_found["level"], "warn")
        self.assertEqual(upstream_failure["level"], "error")

    def test_rejects_malformed_nginx_lines(self):
        parser = NginxLogParser()

        self.assertIsNone(parser.parse("not an nginx access log"))


if __name__ == "__main__":
    unittest.main()
