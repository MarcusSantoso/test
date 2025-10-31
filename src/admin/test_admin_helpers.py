import src.admin.main as admin
from datetime import datetime, date


def test_safe_datetime_input_none():
    assert admin._safe_datetime_input(None) is None


def test_safe_datetime_input_valid():
    dt = admin._safe_datetime_input("2025-10-15T13:32")
    assert isinstance(dt, datetime)
    assert dt.year == 2025


def test_safe_datetime_input_invalid(monkeypatch):
    recorded = {}
    monkeypatch.setattr(admin.ui, "notify", lambda msg: recorded.setdefault("msg", msg))
    assert admin._safe_datetime_input("not-a-date") is None
    assert "Invalid datetime" in recorded["msg"]


def test_safe_date_input_valid():
    d = admin._safe_date_input("2025-10-10")
    assert isinstance(d, date)
    assert d == date(2025, 10, 10)


def test_safe_date_input_invalid(monkeypatch):
    recorded = {}
    monkeypatch.setattr(admin.ui, "notify", lambda msg: recorded.setdefault("msg", msg))
    assert admin._safe_date_input("bad") is None
    assert "Invalid date" in recorded["msg"]


def test_format_payload_short_and_long():
    short = {"a": 1}
    out_short = admin._format_payload(short)
    assert '"a": 1' in out_short

    long = {"x": "a" * 500}
    out_long = admin._format_payload(long)
    assert out_long.endswith("...") or len(out_long) < 200
