import unittest
from log_aggregator import JSONLogParser, TextLogParser, NginxLogParser

class TestJSONLogParser(unittest.TestCase):
    def setUp(self):
        self.parser = JSONLogParser()

    def test_parse_valid_json(self):
        log_line = '{"timestamp": 1718900000, "level": "error", "service": "auth-api", "message": "Invalid token"}'
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['timestamp'], 1718900000)
        self.assertEqual(result['level'], "error")
        self.assertEqual(result['service'], "auth-api")
        self.assertEqual(result['message'], "Invalid token")
        
    def test_parse_alternative_fields(self):
        log_line = '{"time": 1718900001, "severity": "warn", "app": "payment-gateway", "msg": "Payment delayed"}'
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['timestamp'], 1718900001)
        self.assertEqual(result['level'], "warn")
        self.assertEqual(result['service'], "payment-gateway")
        self.assertEqual(result['message'], "Payment delayed")

    def test_parse_invalid_json(self):
        log_line = '{"time": 1718900001, "severity": "warn", '
        result = self.parser.parse(log_line)
        self.assertIsNone(result)

class TestTextLogParser(unittest.TestCase):
    def setUp(self):
        self.parser = TextLogParser()

    def test_parse_iso8601_error(self):
        log_line = "2024-06-20T15:30:00Z [database] ERROR: Connection refused"
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['level'], "error")
        self.assertEqual(result['service'], "database")
        self.assertEqual(result['message'], log_line)
        self.assertEqual(result['timestamp'], 1718897400)

    def test_parse_syslog_info(self):
        log_line = "Jun 20 15:30:00 worker-node [cache] INFO: Cache cleared"
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['level'], "info")
        self.assertEqual(result['service'], "cache")

    def test_parse_no_service(self):
        log_line = "2024-06-20 15:30:00 WARNING: Low disk space"
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['level'], "warn")
        self.assertIsNone(result['service'])

class TestNginxLogParser(unittest.TestCase):
    def setUp(self):
        self.parser = NginxLogParser()

    def test_parse_valid_nginx(self):
        log_line = '192.168.1.1 - - [20/Jun/2024:15:30:00 +0000] "GET /api/users HTTP/1.1" 200 1024 "-" "Mozilla/5.0"'
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['level'], "info")
        self.assertEqual(result['service'], "nginx")
        self.assertEqual(result['message'], "GET /api/users HTTP/1.1")
        self.assertEqual(result['fields']['status'], 200)

    def test_parse_nginx_error(self):
        log_line = '10.0.0.5 - bob [20/Jun/2024:15:35:00 +0000] "POST /api/login HTTP/1.1" 500 256 "-" "curl/7.68.0"'
        result = self.parser.parse(log_line)
        self.assertIsNotNone(result)
        self.assertEqual(result['level'], "error")
        self.assertEqual(result['fields']['status'], 500)

if __name__ == "__main__":
    unittest.main()
