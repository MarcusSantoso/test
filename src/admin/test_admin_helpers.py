from __future__ import annotations

import sys
import types
from datetime import datetime, date

import pytest

# --- Stub src.shared.ai_summarization_engine if missing -----------------------

if "src.shared.ai_summarization_engine" not in sys.modules:
    ai_mod = types.ModuleType("src.shared.ai_summarization_engine")

    class MissingAPIKey(Exception):
        pass

    class MissingOpenAIClient(Exception):
        pass

    def get_summarization_engine():
        # In tests we never actually call this, but main.py imports it.
        raise MissingOpenAIClient("AI engine not available in test environment")

    ai_mod.MissingAPIKey = MissingAPIKey
    ai_mod.MissingOpenAIClient = MissingOpenAIClient
    ai_mod.get_summarization_engine = get_summarization_engine

    sys.modules["src.shared.ai_summarization_engine"] = ai_mod

# NOTE: we DO NOT stub src.event_service.usage_analytics anymore;
# the real module exists and is used by other tests.

# Now it's safe to import main
import src.admin.main as admin  # noqa: E402


def test_safe_datetime_input_valid_with_minutes_only():
    raw = "2025-10-15T13:32"
    dt = admin._safe_datetime_input(raw)
    assert isinstance(dt, datetime)
    assert dt.year == 2025
    assert dt.month == 10
    assert dt.day == 15
    assert dt.hour == 13
    assert dt.minute == 32
    assert dt.second == 0


def test_safe_datetime_input_valid_with_seconds():
    raw = "2025-10-15T13:32:45"
    dt = admin._safe_datetime_input(raw)
    assert isinstance(dt, datetime)
    assert dt.second == 45


def test_safe_datetime_input_none():
    assert admin._safe_datetime_input(None) is None


def test_safe_datetime_input_invalid_returns_none():
    raw = "not-a-datetime"
    dt = admin._safe_datetime_input(raw)
    assert dt is None


def test_safe_date_input_valid():
    raw = "2025-10-15"
    d = admin._safe_date_input(raw)
    assert isinstance(d, date)
    assert d.year == 2025
    assert d.month == 10
    assert d.day == 15


def test_safe_date_input_none():
    assert admin._safe_date_input(None) is None


def test_safe_date_input_invalid_returns_none():
    assert admin._safe_date_input("15/10/2025") is None


def test_format_payload_short_no_truncation():
    payload = {"foo": "bar", "n": 1}
    text = admin._format_payload(payload)
    assert text.startswith("{")
    assert text.endswith("}")
    assert len(text) <= 120


def test_format_payload_long_truncation():
    big_value = "x" * 200
    payload = {"long": big_value}
    text = admin._format_payload(payload)
    assert len(text) == 120
    assert text.endswith("...")
