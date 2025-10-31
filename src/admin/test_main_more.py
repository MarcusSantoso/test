import asyncio
from types import SimpleNamespace
import src.admin.main as admin


def test_safe_datetime_and_date_and_format(monkeypatch):
    # capture notifications
    notes = []
    monkeypatch.setattr(admin.ui, "notify", lambda msg: notes.append(msg))

    # valid datetime-local without seconds should append :00
    dt = admin._safe_datetime_input("2025-10-15T13:32")
    assert dt is not None
    assert dt.second == 0

    # invalid datetime should notify and return None
    bad = admin._safe_datetime_input("not-a-date")
    assert bad is None
    assert any("Invalid datetime" in n for n in notes)

    # valid date
    d = admin._safe_date_input("2025-10-15")
    assert d is not None

    # invalid date
    notes.clear()
    badd = admin._safe_date_input("2025-15-99")
    assert badd is None
    assert any("Invalid date" in n for n in notes)

    # format payload truncation
    payload = {"k": "x" * 200}
    out = admin._format_payload(payload)
    assert isinstance(out, str)
    assert len(out) <= 120 or out.endswith("...")


class FakeEventRepo:
    def __init__(self, events=None):
        self._events = events or []

    async def query(self, **kwargs):
        return self._events

    async def create(self, obj):
        # record created for inspection
        self._created = getattr(self, "_created", [])
        self._created.append(obj)


def test_event_log_view_shows_no_events_and_render_page(monkeypatch):
    # ensure ui label/notifications are fresh
    admin.ui._labels.clear()
    admin.ui._notifications.clear()

    # use fake event repo with no events
    repo = FakeEventRepo(events=[])

    # call event_log_view directly
    asyncio.run(admin.event_log_view(repo, {}))
    assert any("No events found" in (t or "") for t in admin.ui._labels)

    # Now call the full render page which builds many UI widgets
    # Provide a fake EventAnalyticsService so analytics_panel won't fail
    class FakeSnapshot:
        def to_dict(self):
            return {"session_length": {"mean": 1.0}, "active_users": {"current": 2.0}}

    class FakeAnalytics:
        def __init__(self, repo):
            pass

        async def today(self):
            return FakeSnapshot()

        async def on(self, d):
            return FakeSnapshot()

        async def since(self, d):
            return FakeSnapshot()

    monkeypatch.setattr(admin, "EventAnalyticsService", FakeAnalytics)

    # call render page (async)
    asyncio.run(admin._render_event_log_page(repo))


def test_analytics_panel_modes(monkeypatch):
    # ensure ui label/notifications are fresh
    admin.ui._labels.clear()
    admin.ui._notifications.clear()

    # Fake analytics service that returns expected dict
    class FakeSnapshot:
        def to_dict(self):
            return {"session_length": {"mean": 3.0}, "active_users": {"current": 5.0}}

    class FakeAnalytics:
        def __init__(self, repo):
            pass

        async def today(self):
            return FakeSnapshot()

        async def on(self, d):
            return FakeSnapshot()

        async def since(self, d):
            return FakeSnapshot()

    monkeypatch.setattr(admin, "EventAnalyticsService", FakeAnalytics)

    # mode today should work
    asyncio.run(admin.analytics_panel(object(), {"mode": "today"}))

    # mode on with invalid date should prompt label/notify path
    asyncio.run(admin.analytics_panel(object(), {"mode": "on", "date": "bad-date"}))
    assert any("Select a date" in (t or "") for t in admin.ui._labels) or any("Invalid date" in n for n in admin.ui._notifications)
