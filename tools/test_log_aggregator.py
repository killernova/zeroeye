"""
Regression tests for log_aggregator parsers.
Tests JSONLogParser, TextLogParser, NginxLogParser with hand-written
sample log lines covering valid and edge-case inputs.
"""

import json
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from log_aggregator import JSONLogParser, TextLogParser, NginxLogParser


def test_json_parser_valid():
    p = JSONLogParser()
    line = json.dumps({
        "timestamp": "2026-06-20T10:30:00",
        "level": "ERROR",
        "service": "api-gateway",
        "message": "Connection timeout",
        "request_id": "abc-123"
    })
    result = p.parse(line)
    assert result is not None, "Valid JSON should parse"
    assert result["level"] == "error", f"Expected error, got {result['level']}"
    assert result["service"] == "api-gateway"
    assert "Connection timeout" in result["message"]
    assert result["timestamp"] is not None


def test_json_parser_timestamp_extraction():
    p = JSONLogParser()
    line = json.dumps({"timestamp": "2026-06-20T10:30:00", "message": "test"})
    result = p.parse(line)
    assert result is not None
    assert result["timestamp"] is not None


def test_json_parser_malformed():
    p = JSONLogParser()
    result = p.parse("{invalid json")
    assert result is None, "Malformed JSON should return None"


def test_json_parser_empty_object():
    p = JSONLogParser()
    result = p.parse("{}")
    assert result is not None, "Empty JSON object should parse"


def test_json_parser_missing_fields():
    p = JSONLogParser()
    result = p.parse(json.dumps({"arbitrary": "data"}))
    assert result is not None
    assert result["level"] == "unknown"


def test_text_parser_standard():
    p = TextLogParser()
    line = "2026-06-20 10:30:00 [api-gateway] ERROR: Connection timeout"
    result = p.parse(line)
    assert result is not None, "Standard log should parse"
    assert result["level"] == "error"
    assert result["service"] == "api-gateway"
    assert result["timestamp"] is not None


def test_text_parser_syslog():
    p = TextLogParser()
    line = "Jun 20 10:30:00 myserver kernel: [BLOCKED] Unauthorized access attempt"
    result = p.parse(line)
    assert result is not None
    assert result["service"] == "kernel"
    assert result["timestamp"] is not None


def test_text_parser_warn_level():
    p = TextLogParser()
    line = "2026-06-20 10:30:00 [scheduler] WARNING: Disk space below threshold"
    result = p.parse(line)
    assert result is not None
    assert result["level"] == "warn"


def test_text_parser_debug_level():
    p = TextLogParser()
    line = "2026-06-20 10:30:00 [worker] DEBUG: Processing batch item 42"
    result = p.parse(line)
    assert result is not None
    assert result["level"] == "debug"


def test_text_parser_unknown_level():
    p = TextLogParser()
    line = "2026-06-20 10:30:00 [daemon] NOTIFY: Routine check completed"
    result = p.parse(line)
    assert result is not None
    # NOTIFY is not in LEVEL_PATTERNS, should be "unknown"
    assert result["level"] == "unknown"


def test_text_parser_empty_line():
    p = TextLogParser()
    result = p.parse("")
    assert result is None or result.get("message") == ""


def test_text_parser_no_timestamp():
    p = TextLogParser()
    line = "[worker] ERROR: Something broke"
    result = p.parse(line)
    assert result is not None
    assert result["level"] == "error"
    assert result["service"] == "worker"


def test_nginx_parser_valid():
    p = NginxLogParser()
    line = '192.168.1.1 - - [20/Jun/2026:10:30:00 +0000] "GET /api/health HTTP/1.1" 200 1234 "-" "curl/7.68"'
    result = p.parse(line)
    assert result is not None, "Valid nginx log should parse"
    assert result["status_code"] == 200
    assert result["method"] == "GET"
    assert result["path"] == "/api/health"
    assert result["remote_addr"] == "192.168.1.1"
    assert result["level"] == "info"


def test_nginx_parser_4xx():
    p = NginxLogParser()
    line = '10.0.0.1 - - [20/Jun/2026:10:31:00 +0000] "POST /api/login HTTP/1.1" 401 56 "-" "Mozilla/5.0"'
    result = p.parse(line)
    assert result is not None
    assert result["status_code"] == 401
    assert result["level"] == "warn"


def test_nginx_parser_5xx():
    p = NginxLogParser()
    line = '10.0.0.2 - - [20/Jun/2026:10:32:00 +0000] "GET /api/db HTTP/1.1" 503 89 "-" "kube-probe"'
    result = p.parse(line)
    assert result is not None
    assert result["status_code"] == 503
    assert result["level"] == "error"


def test_nginx_parser_malformed():
    p = NginxLogParser()
    result = p.parse("not an nginx log line")
    assert result is None, "Malformed nginx log should return None"


def test_extract_timestamp_iso8601():
    p = JSONLogParser()
    ts = p.extract_timestamp("2026-06-20T10:30:00Z test message")
    assert ts is not None, "ISO8601 timestamp should be extracted"


def test_extract_timestamp_standard():
    p = JSONLogParser()
    ts = p.extract_timestamp("2026-06-20 10:30:00 test message")
    assert ts is not None


def test_extract_timestamp_nginx():
    p = JSONLogParser()
    ts = p.extract_timestamp("[20/Jun/2026:10:30:00 +0000]")
    assert ts is not None, "Nginx timestamp should be extracted"


def test_extract_timestamp_syslog():
    p = JSONLogParser()
    ts = p.extract_timestamp("Jun 20 10:30:00 myserver message")
    assert ts is not None


def test_extract_timestamp_none():
    p = JSONLogParser()
    ts = p.extract_timestamp("no timestamp here")
    assert ts is None


def test_extract_level_case_insensitive():
    p = JSONLogParser()
    assert p.extract_level("error") == "error"
    assert p.extract_level("ERROR") == "error"
    assert p.extract_level("Error") == "error"
    assert p.extract_level("Warning") == "warn"
    assert p.extract_level("Debug") == "debug"


def test_extract_service_bracket():
    p = JSONLogParser()
    svc = p.extract_service("[payment-worker] processing")
    assert svc == "payment-worker"


def test_unknown_severity():
    p = TextLogParser()
    line = "2026-06-20 10:30:00 [daemon] CRIT: Something critical happened"
    result = p.parse(line)
    assert result is not None
    # "CRIT" doesn't match any pattern, should be "unknown"
    assert result["level"] == "unknown"


if __name__ == "__main__":
    test_json_parser_valid()
    test_json_parser_timestamp_extraction()
    test_json_parser_malformed()
    test_json_parser_empty_object()
    test_json_parser_missing_fields()
    test_text_parser_standard()
    test_text_parser_syslog()
    test_text_parser_warn_level()
    test_text_parser_debug_level()
    test_text_parser_unknown_level()
    test_text_parser_empty_line()
    test_text_parser_no_timestamp()
    test_nginx_parser_valid()
    test_nginx_parser_4xx()
    test_nginx_parser_5xx()
    test_nginx_parser_malformed()
    test_extract_timestamp_iso8601()
    test_extract_timestamp_standard()
    test_extract_timestamp_nginx()
    test_extract_timestamp_syslog()
    test_extract_timestamp_none()
    test_extract_level_case_insensitive()
    test_extract_service_bracket()
    test_unknown_severity()
    print(f"All {24} tests passed!")
