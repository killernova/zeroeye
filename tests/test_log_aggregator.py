import pytest
import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from tools.log_aggregator import parse_json_log, parse_plain_text, parse_nginx_log

class TestJSONParser:
    def test_valid_json(self):
        line = '{"level":"error","msg":"disk full"}'
        result = parse_json_log(line)
        assert result is not None
        assert result["level"] == "error"
    
    def test_invalid_json(self):
        result = parse_json_log("not json")
        assert result is None
    
    def test_empty_line(self):
        result = parse_json_log("")
        assert result is None

class TestPlainTextParser:
    def test_standard_format(self):
        line = "2024-01-01 ERROR Something failed"
        result = parse_plain_text(line)
        assert result is not None

class TestNginxParser:
    def test_access_log(self):
        line = '192.168.1.1 - - [01/Jan/2024:00:00:00 +0000] "GET / HTTP/1.1" 200 612'
        result = parse_nginx_log(line)
        assert result is not None
