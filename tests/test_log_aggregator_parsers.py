"""
Regression tests for log aggregator parsers.

Tests JSONLogParser, TextLogParser, and NginxLogParser against hand-written
sample log lines covering valid input, malformed data, edge cases, and format-specific fields.
"""

import unittest
from datetime import datetime
from tools.log_aggregator import JSONLogParser, TextLogParser, NginxLogParser


class TestJSONLogParser(unittest.TestCase):
    """Test JSONLogParser with valid and malformed JSON logs."""

    def setUp(self):
        self.parser = JSONLogParser()

    def test_valid_json_log_complete(self):
        """Parse valid JSON log with all fields."""
        line = '{"timestamp": "2024-01-15T10:30:45.123Z", "level": "ERROR", "service": "api-gateway", "message": "Connection timeout"}'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'ERROR')
        self.assertEqual(result.get('service'), 'api-gateway')
        self.assertEqual(result.get('message'), 'Connection timeout')
        self.assertIn('timestamp', result)

    def test_valid_json_minimal_fields(self):
        """Parse JSON log with only message field."""
        line = '{"message": "Minimal log entry"}'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('message'), 'Minimal log entry')

    def test_json_with_nested_objects(self):
        """Parse JSON log with nested objects."""
        line = '{"timestamp": "2024-01-15T10:30:45Z", "level": "INFO", "message": "Request processed", "metadata": {"user_id": 123, "duration_ms": 45}}'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'INFO')
        self.assertEqual(result.get('message'), 'Request processed')

    def test_malformed_json_incomplete(self):
        """Handle malformed JSON with missing closing brace."""
        line = '{"timestamp": "2024-01-15T10:30:45Z", "level": "ERROR", "message": "Incomplete'
        result = self.parser.parse(line)
        
        # Parser should return None or handle gracefully
        self.assertIsNone(result)

    def test_malformed_json_invalid_syntax(self):
        """Handle invalid JSON syntax."""
        line = '{timestamp: 2024-01-15, level: ERROR, not valid json}'
        result = self.parser.parse(line)
        
        self.assertIsNone(result)

    def test_empty_json_object(self):
        """Parse empty JSON object."""
        line = '{}'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result, {})

    def test_json_with_unknown_severity(self):
        """Parse JSON log with non-standard severity level."""
        line = '{"level": "TRACE", "message": "Debug trace info"}'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'TRACE')

    def test_json_timestamp_formats(self):
        """Parse various ISO 8601 timestamp formats."""
        test_cases = [
            '{"timestamp": "2024-01-15T10:30:45Z", "message": "UTC format"}',
            '{"timestamp": "2024-01-15T10:30:45.123Z", "message": "With milliseconds"}',
            '{"timestamp": "2024-01-15T10:30:45+00:00", "message": "With timezone"}',
            '{"timestamp": "2024-01-15 10:30:45", "message": "Space separator"}',
        ]
        
        for line in test_cases:
            result = self.parser.parse(line)
            self.assertIsNotNone(result, f"Failed to parse: {line}")
            self.assertIn('timestamp', result)


class TestTextLogParser(unittest.TestCase):
    """Test TextLogParser with plain text and syslog-style logs."""

    def setUp(self):
        self.parser = TextLogParser()

    def test_syslog_format_standard(self):
        """Parse standard syslog format."""
        line = 'Jan 15 10:30:45 webserver nginx: [error] Connection refused'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertIn('timestamp', result)
        self.assertIn('message', result)

    def test_application_log_with_level(self):
        """Parse application log with explicit level."""
        line = '2024-01-15 10:30:45 ERROR [api-service] Failed to connect to database'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'ERROR')
        self.assertIn('message', result)

    def test_log_with_brackets_level(self):
        """Parse log with bracketed severity level."""
        line = '[WARN] 2024-01-15 10:30:45 - Deprecated API endpoint accessed'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'WARN')

    def test_plain_text_no_structure(self):
        """Parse plain text without structured fields."""
        line = 'Something went wrong in the application'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('message'), 'Something went wrong in the application')

    def test_multiword_service_name(self):
        """Parse log with multi-word service name."""
        line = '2024-01-15 10:30:45 INFO [user-authentication-service] Login successful'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertIn('message', result)

    def test_timestamp_edge_cases(self):
        """Parse logs with various timestamp formats."""
        test_cases = [
            '2024-01-15T10:30:45.123456Z INFO Application started',
            'Jan 15 10:30:45 INFO Application started',
            '01/15/2024 10:30:45 INFO Application started',
            '2024-01-15 10:30:45,123 INFO Application started',
        ]
        
        for line in test_cases:
            result = self.parser.parse(line)
            self.assertIsNotNone(result, f"Failed to parse: {line}")

    def test_empty_line(self):
        """Handle empty line gracefully."""
        line = ''
        result = self.parser.parse(line)
        
        # Should return None or empty dict, not raise exception
        self.assertTrue(result is None or result == {})

    def test_whitespace_only_line(self):
        """Handle whitespace-only line."""
        line = '   \t  \n  '
        result = self.parser.parse(line)
        
        self.assertTrue(result is None or result == {})

    def test_log_with_special_characters(self):
        """Parse log with special characters in message."""
        line = '2024-01-15 10:30:45 ERROR [service] Failed: "Quota exceeded" (code=429) & retry later'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('level'), 'ERROR')
        self.assertIn('message', result)


class TestNginxLogParser(unittest.TestCase):
    """Test NginxLogParser with access logs and edge cases."""

    def setUp(self):
        self.parser = NginxLogParser()

    def test_nginx_access_log_standard(self):
        """Parse standard Nginx access log format."""
        line = '192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "GET /api/users HTTP/1.1" 200 1234 "-" "Mozilla/5.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('status'), '200')
        self.assertEqual(result.get('method'), 'GET')
        self.assertEqual(result.get('path'), '/api/users')
        self.assertIn('ip', result)
        self.assertIn('timestamp', result)

    def test_nginx_access_log_404(self):
        """Parse Nginx log with 404 status (client error)."""
        line = '10.0.0.50 - - [15/Jan/2024:10:30:45 +0000] "GET /missing HTTP/1.1" 404 162 "-" "curl/7.68.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('status'), '404')
        self.assertEqual(result.get('level'), 'WARN')  # 4xx should be WARN

    def test_nginx_access_log_500(self):
        """Parse Nginx log with 500 status (server error)."""
        line = '10.0.0.50 - - [15/Jan/2024:10:30:45 +0000] "POST /api/process HTTP/1.1" 500 512 "-" "python-requests/2.28.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('status'), '500')
        self.assertEqual(result.get('level'), 'ERROR')  # 5xx should be ERROR

    def test_nginx_access_log_post_with_referer(self):
        """Parse POST request with referer."""
        line = '192.168.1.100 - user123 [15/Jan/2024:10:30:45 +0000] "POST /api/login HTTP/1.1" 201 89 "https://example.com/login" "Mozilla/5.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('method'), 'POST')
        self.assertEqual(result.get('status'), '201')
        self.assertEqual(result.get('user'), 'user123')

    def test_nginx_malformed_missing_status(self):
        """Handle malformed Nginx log missing status code."""
        line = '192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "GET /api/users HTTP/1.1"'
        result = self.parser.parse(line)
        
        # Parser may return None or partial data depending on implementation
        # Should not raise exception
        self.assertTrue(result is None or isinstance(result, dict))

    def test_nginx_malformed_invalid_method(self):
        """Parse log with malformed HTTP method."""
        line = '192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "INVALID /path HTTP/1.1" 400 0 "-" "-"'
        result = self.parser.parse(line)
        
        # Parser should handle gracefully
        self.assertIsNotNone(result)

    def test_nginx_log_with_query_string(self):
        """Parse request with query string parameters."""
        line = '192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "GET /search?q=test&page=2 HTTP/1.1" 200 5432 "-" "Mozilla/5.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('method'), 'GET')
        self.assertIn('/search', result.get('path', ''))

    def test_nginx_log_ipv6_address(self):
        """Parse log with IPv6 address."""
        line = '2001:db8::1 - - [15/Jan/2024:10:30:45 +0000] "GET /api/status HTTP/1.1" 200 123 "-" "curl/7.68.0"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('ip'), '2001:db8::1')

    def test_nginx_empty_user_agent(self):
        """Parse log with empty user agent."""
        line = '192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "GET /health HTTP/1.1" 200 2 "-" "-"'
        result = self.parser.parse(line)
        
        self.assertIsNotNone(result)
        self.assertEqual(result.get('status'), '200')

    def test_nginx_error_log_format(self):
        """Parse Nginx error log format (different from access log)."""
        line = '2024/01/15 10:30:45 [error] 12345#12345: *1 connect() failed (111: Connection refused)'
        result = self.parser.parse(line)
        
        # Parser may not fully support error log format - document limitation
        # Should not crash
        self.assertTrue(result is None or isinstance(result, dict))

    def test_http_status_classification(self):
        """Verify HTTP status code classification into severity levels."""
        test_cases = [
            ('200', 'INFO'),   # 2xx success
            ('201', 'INFO'),
            ('301', 'INFO'),   # 3xx redirect
            ('304', 'INFO'),
            ('400', 'WARN'),   # 4xx client error
            ('404', 'WARN'),
            ('500', 'ERROR'),  # 5xx server error
            ('503', 'ERROR'),
        ]
        
        for status, expected_level in test_cases:
            line = f'192.168.1.100 - - [15/Jan/2024:10:30:45 +0000] "GET / HTTP/1.1" {status} 0 "-" "-"'
            result = self.parser.parse(line)
            
            if result:
                self.assertEqual(result.get('level'), expected_level, 
                               f"Status {status} should map to level {expected_level}")


class TestParserEdgeCases(unittest.TestCase):
    """Test edge cases across all parsers."""

    def test_extremely_long_line(self):
        """Ensure parsers handle very long log lines without crashing."""
        long_message = 'A' * 10000
        
        json_line = f'{{"message": "{long_message}"}}'
        json_parser = JSONLogParser()
        json_result = json_parser.parse(json_line)
        self.assertTrue(json_result is None or isinstance(json_result, dict))
        
        text_line = f'2024-01-15 10:30:45 INFO {long_message}'
        text_parser = TextLogParser()
        text_result = text_parser.parse(text_line)
        self.assertTrue(text_result is None or isinstance(text_result, dict))

    def test_unicode_characters(self):
        """Parse logs with unicode characters."""
        json_line = '{"message": "用户登录成功 🎉", "level": "INFO"}'
        json_parser = JSONLogParser()
        json_result = json_parser.parse(json_line)
        
        self.assertIsNotNone(json_result)
        self.assertIn('用户登录成功', json_result.get('message', ''))

    def test_null_byte_handling(self):
        """Ensure parsers handle null bytes gracefully."""
        line_with_null = 'INFO\x00Message with null byte'
        text_parser = TextLogParser()
        
        # Should not crash
        result = text_parser.parse(line_with_null)
        self.assertTrue(result is None or isinstance(result, dict))


if __name__ == '__main__':
    unittest.main()