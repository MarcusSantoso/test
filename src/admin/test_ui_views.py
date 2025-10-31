import asyncio
from datetime import datetime
import src.admin.main as admin


# Minimal fake widget class to emulate NiceGUI context manager behaviour
class FakeWidget:
    def __init__(self, **kwargs):
        self.kw = kwargs
        self.rows = kwargs.get("rows")
        self.children = []

    def classes(self, *_):
        return self
    def props(self, *_, **__):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_event_log_view_renders_table(monkeypatch):
    captured = {}

    def fake_table(**kwargs):
        captured["table_kwargs"] = kwargs
        return FakeWidget(**kwargs)

    monkeypatch.setattr(admin.ui, "table", fake_table)
    monkeypatch.setattr(admin.ui, "label", lambda *a, **k: FakeWidget())

    # fake repo with async query method
    class Repo:
        async def query(self, **kwargs):
            class Ev:
                id = 1
                when = datetime(2025, 1, 1, 0, 0, 0)
                source = "s"
                type = "t"
                user = "u"
                payload = {"a": 1}

            return [Ev()]

    asyncio.run(admin.event_log_view(Repo(), {}))
    assert "table_kwargs" in captured
    rows = captured["table_kwargs"].get("rows")
    assert rows is not None and len(rows) >= 1


def test_analytics_panel_today_and_since(monkeypatch):
    # Fake snapshot with structure expected by analytics_panel
    class DummySnapshot:
        def to_dict(self):
            return {
                "session_length": {"min": 1.0, "mean": 2.0, "median": 1.5, "p95": 3.0, "max": 4.0},
                "active_users": {"current": 0.0, "max": 2.0},
            }

    class FakeService:
        async def today(self):
            return DummySnapshot()

        async def since(self, _):
            return DummySnapshot()

    monkeypatch.setattr(admin, "EventAnalyticsService", lambda repo: FakeService())

    monkeypatch.setattr(admin.ui, "card", lambda *a, **k: FakeWidget(), raising=False)
    monkeypatch.setattr(admin.ui, "label", lambda *a, **k: FakeWidget(), raising=False)
    monkeypatch.setattr(admin.ui, "grid", lambda *a, **k: FakeWidget(), raising=False)
    monkeypatch.setattr(admin.ui, "column", lambda *a, **k: FakeWidget(), raising=False)

    asyncio.run(admin.analytics_panel(None, {"mode": "today"}))
    asyncio.run(admin.analytics_panel(None, {"mode": "since", "date": "2025-01-01"}))
