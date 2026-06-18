#!/usr/bin/env python3
"""
Tests for deterministic seed support in data_generator.py.

Verifies that:
- Same seed produces byte-for-byte identical output across runs
- Different seeds produce different data
- --print-seed flag behaviour works correctly
- All data types (users, orders, trades, ticks, candles) are deterministic
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr

import pytest

# Ensure the tools directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from data_generator import (
    DataGenerator,
    parse_args,
    random_datetime,
    random_email,
    random_phone,
)


# ---------------------------------------------------------------------------
# Helper: run the generator with a given seed and return the generated data
# ---------------------------------------------------------------------------

def _generate_all(seed: int, users=10, orders=20, trades=30, ticks=50, candles=30):
    """Create a DataGenerator, generate all data types, and return them."""
    gen = DataGenerator(seed)
    user_data = gen.generate_users(users)
    order_data = gen.generate_orders(orders)
    trade_data = gen.generate_trades(trades)
    tick_data = gen.generate_ticks("BTC/USD", ticks)
    candle_data = gen.generate_candles("BTC/USD", 60, candles)
    return {
        "users": user_data,
        "orders": order_data,
        "trades": trade_data,
        "ticks": tick_data,
        "candles": candle_data,
    }


# ---------------------------------------------------------------------------
# Deterministic output tests for multiple seeds
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 42, 123, 9999, 2**20])
def test_same_seed_produces_identical_user_data(seed):
    """Same seed must produce byte-for-byte identical user data."""
    run1 = _generate_all(seed)
    run2 = _generate_all(seed)
    assert json.dumps(run1["users"], sort_keys=True) == json.dumps(run2["users"], sort_keys=True), \
        f"User data differs for seed {seed}"


@pytest.mark.parametrize("seed", [0, 42, 123, 9999, 2**20])
def test_same_seed_produces_identical_order_data(seed):
    """Same seed must produce byte-for-byte identical order data."""
    run1 = _generate_all(seed)
    run2 = _generate_all(seed)
    assert json.dumps(run1["orders"], sort_keys=True) == json.dumps(run2["orders"], sort_keys=True), \
        f"Order data differs for seed {seed}"


@pytest.mark.parametrize("seed", [0, 42, 123, 9999, 2**20])
def test_same_seed_produces_identical_trade_data(seed):
    """Same seed must produce byte-for-byte identical trade data."""
    run1 = _generate_all(seed)
    run2 = _generate_all(seed)
    assert json.dumps(run1["trades"], sort_keys=True) == json.dumps(run2["trades"], sort_keys=True), \
        f"Trade data differs for seed {seed}"


@pytest.mark.parametrize("seed", [0, 42, 123, 9999, 2**20])
def test_same_seed_produces_identical_tick_data(seed):
    """Same seed must produce byte-for-byte identical tick data."""
    run1 = _generate_all(seed)
    run2 = _generate_all(seed)
    assert json.dumps(run1["ticks"], sort_keys=True) == json.dumps(run2["ticks"], sort_keys=True), \
        f"Tick data differs for seed {seed}"


@pytest.mark.parametrize("seed", [0, 42, 123, 9999, 2**20])
def test_same_seed_produces_identical_candle_data(seed):
    """Same seed must produce byte-for-byte identical candle data."""
    run1 = _generate_all(seed)
    run2 = _generate_all(seed)
    assert json.dumps(run1["candles"], sort_keys=True) == json.dumps(run2["candles"], sort_keys=True), \
        f"Candle data differs for seed {seed}"


# ---------------------------------------------------------------------------
# Different seeds produce different data
# ---------------------------------------------------------------------------

def test_different_seeds_produce_different_user_data():
    """Different seeds must produce different user data."""
    data_by_seed = {}
    for seed in [1, 2, 3]:
        result = _generate_all(seed, users=10)
        data_by_seed[seed] = json.dumps(result["users"], sort_keys=True)

    # All three outputs must be distinct
    values = list(data_by_seed.values())
    assert len(set(values)) == 3, "Expected 3 distinct user datasets for 3 different seeds"


def test_different_seeds_produce_different_order_data():
    """Different seeds must produce different order data."""
    data_by_seed = {}
    for seed in [100, 200, 300]:
        result = _generate_all(seed, users=5, orders=20)
        data_by_seed[seed] = json.dumps(result["orders"], sort_keys=True)

    values = list(data_by_seed.values())
    assert len(set(values)) == 3, "Expected 3 distinct order datasets for 3 different seeds"


def test_different_seeds_produce_different_tick_data():
    """Different seeds must produce different tick data."""
    data_by_seed = {}
    for seed in [10, 20, 30]:
        result = _generate_all(seed, ticks=50)
        data_by_seed[seed] = json.dumps(result["ticks"], sort_keys=True)

    values = list(data_by_seed.values())
    assert len(set(values)) == 3, "Expected 3 distinct tick datasets for 3 different seeds"


# ---------------------------------------------------------------------------
# --print-seed behaviour
# ---------------------------------------------------------------------------

def test_print_seed_outputs_seed_to_stderr():
    """--print-seed flag should cause the seed to be printed to stderr."""
    script = os.path.join(os.path.dirname(__file__), "data_generator.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, script, "--print-seed", "--seed", "7777",
             "-o", tmpdir, "--users", "1", "--orders", "0", "--trades", "0",
             "--ticks", "0", "--candles", "0"],
            capture_output=True, text=True,
        )
        assert "SEED: 7777" in result.stderr, \
            f"Expected 'SEED: 7777' in stderr, got: {result.stderr}"


def test_no_seed_auto_generates_and_prints():
    """When no --seed is given, a random seed should be generated and printed."""
    script = os.path.join(os.path.dirname(__file__), "data_generator.py")
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, script, "-o", tmpdir,
             "--users", "1", "--orders", "0", "--trades", "0",
             "--ticks", "0", "--candles", "0"],
            capture_output=True, text=True,
        )
        # Should contain SEED: <number> on stderr
        assert "SEED:" in result.stderr, \
            f"Expected 'SEED:' in stderr when no --seed provided, got: {result.stderr}"


def test_no_seed_runs_are_reproducible():
    """Running without --seed should print a seed; re-running with that seed gives same output."""
    script = os.path.join(os.path.dirname(__file__), "data_generator.py")

    with tempfile.TemporaryDirectory() as tmpdir1:
        result1 = subprocess.run(
            [sys.executable, script, "-o", tmpdir1,
             "--users", "5", "--orders", "0", "--trades", "0",
             "--ticks", "0", "--candles", "0"],
            capture_output=True, text=True,
        )
        # Extract seed from stderr
        seed_line = [l for l in result1.stderr.splitlines() if "SEED:" in l][0]
        captured_seed = int(seed_line.split("SEED:")[1].strip())

        # Read generated users
        users_file1 = os.path.join(tmpdir1, "users.json")
        with open(users_file1) as f:
            data1 = f.read()

    # Re-run with the captured seed
    with tempfile.TemporaryDirectory() as tmpdir2:
        result2 = subprocess.run(
            [sys.executable, script, "--seed", str(captured_seed), "-o", tmpdir2,
             "--users", "5", "--orders", "0", "--trades", "0",
             "--ticks", "0", "--candles", "0"],
            capture_output=True, text=True,
        )
        users_file2 = os.path.join(tmpdir2, "users.json")
        with open(users_file2) as f:
            data2 = f.read()

    assert data1 == data2, \
        f"Re-running with captured seed {captured_seed} did not produce identical output"


# ---------------------------------------------------------------------------
# Metadata inclusion
# ---------------------------------------------------------------------------

def test_json_export_includes_seed_metadata():
    """JSON exports should include a metadata block with the seed."""
    seed = 42
    gen = DataGenerator(seed)
    users = gen.generate_users(5)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        tmppath = f.name

    try:
        gen.export_json(tmppath, users, include_metadata=True)
        with open(tmppath) as f:
            exported = json.load(f)
        assert "metadata" in exported, "Exported JSON should contain a 'metadata' key"
        assert exported["metadata"]["seed"] == seed, \
            f"Metadata seed should be {seed}, got {exported['metadata']['seed']}"
        assert "data" in exported, "Exported JSON should contain a 'data' key"
        assert len(exported["data"]) == 5, "Exported data should contain 5 users"
    finally:
        os.unlink(tmppath)


# ---------------------------------------------------------------------------
# Helper function determinism
# ---------------------------------------------------------------------------

def test_random_email_deterministic_with_rng():
    """random_email with the same rng state must produce the same result."""
    import random as _random
    rng1 = _random.Random(99)
    rng2 = _random.Random(99)
    assert random_email("Alice", "Smith", rng1) == random_email("Alice", "Smith", rng2)


def test_random_phone_deterministic_with_rng():
    """random_phone with the same rng state must produce the same result."""
    import random as _random
    rng1 = _random.Random(55)
    rng2 = _random.Random(55)
    assert random_phone(rng1) == random_phone(rng2)


def test_random_datetime_deterministic_with_rng():
    """random_datetime with the same rng state must produce the same result."""
    import random as _random
    rng1 = _random.Random(77)
    rng2 = _random.Random(77)
    assert random_datetime(rng=rng1) == random_datetime(rng=rng2)


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------

def test_parse_args_seed_default_is_none():
    """Default seed in parse_args should be None (auto-generate)."""
    args = parse_args([])
    assert args.seed is None


def test_parse_args_print_seed_flag():
    """--print-seed flag should be recognized."""
    args = parse_args(["--print-seed"])
    assert args.print_seed is True


def test_parse_args_explicit_seed():
    """--seed should accept an integer value."""
    args = parse_args(["--seed", "12345"])
    assert args.seed == 12345


# ---------------------------------------------------------------------------
# Tick / candle timestamps are deterministic (no time.time())
# ---------------------------------------------------------------------------

def test_tick_timestamps_are_deterministic():
    """Tick timestamps must be based on a fixed base, not wall-clock time."""
    gen1 = DataGenerator(42)
    ticks1 = gen1.generate_ticks("BTC/USD", 10)
    gen2 = DataGenerator(42)
    ticks2 = gen2.generate_ticks("BTC/USD", 10)

    for t1, t2 in zip(ticks1, ticks2):
        assert t1["timestamp"] == t2["timestamp"], \
            f"Tick timestamps differ: {t1['timestamp']} vs {t2['timestamp']}"

    # Timestamps should be sequential from a known base
    base_ts = 1704067200000  # 2024-01-01T00:00:00Z
    for i, tick in enumerate(ticks1):
        assert tick["timestamp"] == base_ts + i * 1000


def test_candle_timestamps_are_deterministic():
    """Candle timestamps must be based on a fixed base, not wall-clock time."""
    gen1 = DataGenerator(42)
    candles1 = gen1.generate_candles("ETH/USD", 60, 10)
    gen2 = DataGenerator(42)
    candles2 = gen2.generate_candles("ETH/USD", 60, 10)

    for c1, c2 in zip(candles1, candles2):
        assert c1["time"] == c2["time"], \
            f"Candle timestamps differ: {c1['time']} vs {c2['time']}"

    base_ts = 1704067200000
    interval_ms = 60 * 60 * 1000
    for i, candle in enumerate(candles1):
        assert candle["time"] == base_ts + i * interval_ms
