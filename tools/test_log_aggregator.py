"""
Unit tests for the legacy log aggregator parsers (JSON, plain text, and Nginx formats).
"""

import sys
import os
import unittest
from datetime import datetime, timezone

# Add parent directory to path so we can import log_aggregator
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import log_aggregator

class TestLogParsers(unittest.TestCase):
    """
    Test suite for structured JSON, plain text, and Nginx log parsing logic.
    """

    def setUp(self):
        """
        Set up the parser instances for each test case.
        """
        self.json_parser = log_aggregator.JSONLogParser()
        self.text_parser = log_aggregator.TextLogParser()
        self.nginx_parser = log_aggregator.NginxLogParser()

    def test_json_parser_valid(self):
        """
        Test that JSONLogParser correctly extracts structured fields from valid JSON lines.
        """
        # Standard JSON log line
        log_line = '{"timestamp": "2026-06-20T12:34:56", "level": "error", "service": "payment-api", "message": "Transaction failed", "user_id": 123}'
        parsed = self.json_parser.parse(log_line)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['timestamp'], "2026-06-20T12:34:56")
        self.assertEqual(parsed['level'], "error")
        self.assertEqual(parsed['service'], "payment-api")
        self.assertEqual(parsed['message'], "Transaction failed")
        self.assertEqual(parsed['format'], "json")
        self.assertEqual(parsed['fields']['user_id'], 123)

        # Alternative field names (severity, logger, msg)
        alt_line = '{"time": "2026-06-20T12:35:00", "severity": "warn", "logger": "auth-service", "msg": "User login attempt"}'
        parsed_alt = self.json_parser.parse(alt_line)
        self.assertIsNotNone(parsed_alt)
        self.assertEqual(parsed_alt['timestamp'], "2026-06-20T12:35:00")
        self.assertEqual(parsed_alt['level'], "warn")
        self.assertEqual(parsed_alt['service'], "auth-service")
        self.assertEqual(parsed_alt['message'], "User login attempt")

    def test_json_parser_invalid_and_malformed(self):
        """
        Test JSONLogParser error handling with invalid, empty, or non-dict JSON lines.
        """
        # Malformed JSON (syntax error)
        malformed = '{"timestamp": "2026", "level": "info", service: unquoted}'
        self.assertIsNone(self.json_parser.parse(malformed))
        
        # Valid JSON but not a dictionary (e.g., list or integer)
        non_dict = '[1, 2, 3]'
        self.assertIsNone(self.json_parser.parse(non_dict))

        # Empty line
        self.assertIsNone(self.json_parser.parse(''))

    def test_text_parser_valid(self):
        """
        Test TextLogParser with various valid plaintext formats, levels, and timestamps.
        """
        # Standard format: YYYY-MM-DD HH:MM:SS [Service] Message
        line1 = '2026-06-20 12:34:56 [db_worker] ERROR: Connection lost to host'
        parsed1 = self.text_parser.parse(line1)
        self.assertIsNotNone(parsed1)
        
        # Confirm timestamp extraction matching 2026-06-20 12:34:56 UTC
        dt = datetime(2026, 6, 20, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(parsed1['timestamp'], int(dt.timestamp()))
        self.assertEqual(parsed1['level'], 'error')
        self.assertEqual(parsed1['service'], 'db_worker')
        self.assertEqual(parsed1['format'], 'text')

        # Syslog format: Jun 20 12:34:56 machine_name [SERVICE] log message
        line2 = 'Jun 20 12:34:56 testbox [AUTH_SERVICE] User authenticated'
        parsed2 = self.text_parser.parse(line2)
        self.assertIsNotNone(parsed2)
        # Year defaults to 1900 in strptime if not specified
        dt_syslog = datetime(1900, 6, 20, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(parsed2['timestamp'], int(dt_syslog.timestamp()))
        self.assertEqual(parsed2['level'], 'unknown')
        self.assertEqual(parsed2['service'], 'AUTH_SERVICE')

        # Documented Parser Limitation:
        # The parser fails to parse uppercase services like "SERVICE:" if a timestamp (e.g. "12:34:56")
        # appears earlier in the line because the regex search stops at the first colon match ("56:").
        line_limitation = 'Jun 20 12:34:56 testbox AUTH_SERVICE: User authenticated'
        parsed_limit = self.text_parser.parse(line_limitation)
        self.assertIsNotNone(parsed_limit)
        self.assertIsNone(parsed_limit['service'], "Parser limitation: service is None because timestamp colon is matched first")

    def test_text_parser_edge_cases(self):
        """
        Test TextLogParser with empty lines and malformed inputs.
        """
        # Empty and white-space lines should return None
        self.assertIsNone(self.text_parser.parse('   '))
        self.assertIsNone(self.text_parser.parse(''))
        
        # Unstructured text line (no clear timestamp, level, or service)
        garbage = 'some raw system console print statement'
        parsed = self.text_parser.parse(garbage)
        self.assertIsNotNone(parsed)
        self.assertIsNone(parsed['timestamp'])
        self.assertEqual(parsed['level'], 'unknown')
        self.assertIsNone(parsed['service'])
        self.assertEqual(parsed['message'], garbage)

    def test_nginx_parser_valid(self):
        """
        Test NginxLogParser with standard access log formats, status codes, and HTTP code mapping.
        """
        # 1. Successful HTTP 200 (Level = info)
        nginx_200 = '127.0.0.1 - - [20/Jun/2026:12:34:56 +0000] "GET /api/v1/health HTTP/1.1" 200 123 "https://referer.com" "Mozilla/5.0"'
        parsed1 = self.nginx_parser.parse(nginx_200)
        self.assertIsNotNone(parsed1)
        
        dt = datetime(2026, 6, 20, 12, 34, 56, tzinfo=timezone.utc)
        self.assertEqual(parsed1['timestamp'], int(dt.timestamp()))
        self.assertEqual(parsed1['level'], 'info')
        self.assertEqual(parsed1['service'], 'nginx')
        self.assertEqual(parsed1['fields']['remote_addr'], '127.0.0.1')
        self.assertEqual(parsed1['fields']['status'], 200)
        self.assertEqual(parsed1['fields']['body_bytes'], '123')
        self.assertEqual(parsed1['fields']['user_agent'], 'Mozilla/5.0')
        self.assertEqual(parsed1['format'], 'nginx')

        # 2. Client error HTTP 403 (Level = warn)
        nginx_403 = '10.0.0.1 - - [20/Jun/2026:12:35:00 +0000] "POST /admin HTTP/1.1" 403 99 "-" "curl/7.68.0"'
        parsed2 = self.nginx_parser.parse(nginx_403)
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2['level'], 'warn')
        self.assertEqual(parsed2['fields']['status'], 403)

        # 3. Server error HTTP 500 (Level = error)
        nginx_500 = '192.168.1.100 - - [20/Jun/2026:12:35:05 +0000] "GET /crash HTTP/1.1" 500 5000 "-" "-"'
        parsed3 = self.nginx_parser.parse(nginx_500)
        self.assertIsNotNone(parsed3)
        self.assertEqual(parsed3['level'], 'error')
        self.assertEqual(parsed3['fields']['status'], 500)

    def test_nginx_parser_invalid(self):
        """
        Test NginxLogParser with malformed log formats to ensure they return None and don't crash.
        """
        # Malformed log line (missing fields/incorrect format)
        malformed = '127.0.0.1 - [bad-date] GET / HTTP/1.1'
        self.assertIsNone(self.nginx_parser.parse(malformed))

if __name__ == '__main__':
    unittest.main()
