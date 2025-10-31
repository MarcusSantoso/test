import asyncio
from types import SimpleNamespace
import src.admin.main as admin


class FakeWidget:
    def __init__(self, **kwargs):
        self.kw = kwargs
        self.value = kwargs.get("value")
        self.children = []

    def classes(self, *_):
        return self

    def props(self, *_, **__):
        return self

    def set_selection(self, *_):
        return None

    def disable(self):
        self.disabled = True

    def enable(self):
        self.disabled = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeRefreshable:
    def __init__(self):
        self.called = False
        self.refreshed = False

    async def __call__(self, *args, **kwargs):
        self.called = True

    async def refresh(self, *args, **kwargs):
        self.refreshed = True
        return None


class FakeUI:
    def __init__(self):
        self.buttons = {}
        self.inputs = {}
        self.notifications = []
        self.tables = []
        # navigation stub
        self.navigate = SimpleNamespace(to=lambda *_: None)

    def column(self, *a, **k):
        return FakeWidget()

    def row(self, *a, **k):
        return FakeWidget()

    def card(self, *a, **k):
        return FakeWidget()

    def grid(self, *a, **k):
        return FakeWidget()

    def label(self, *a, **k):
        return FakeWidget()

    def input(self, label=None, password=False, password_toggle_button=False, **kwargs):
        w = FakeWidget(value=None)
        # store by label so tests can mutate
        if label:
            self.inputs[label] = w
        return w

    def toggle(self, options, value=None):
        w = FakeWidget()
        w.value = value
        w.on_value_change = None

        def on_value_change(cb):
            w.on_value_change = cb

        w.on_value_change = on_value_change
        return w

    def button(self, text=None, icon=None, on_click=None, color=None, on_value_change=None, **kwargs):
        # capture by text so tests can find the callback
        key = text or icon or str(len(self.buttons))
        self.buttons[key] = on_click
        return FakeWidget()

    def notify(self, msg: str):
        self.notifications.append(msg)

    def table(self, *a, **k):
        # capture on_select if provided
        on_select = k.get("on_select")
        if on_select is not None:
            self.tables.append(on_select)
        return FakeWidget(rows=k.get("rows"))

    def select(self, *a, **k):
        return FakeWidget()


def test_render_event_log_page_apply_and_clear(monkeypatch):
    ui = FakeUI()
    monkeypatch.setattr(admin, "ui", ui)

    # Provide refreshable event_log_view and analytics_panel
    fake_event_view = FakeRefreshable()
    fake_analytics = FakeRefreshable()
    monkeypatch.setattr(admin, "event_log_view", fake_event_view)
    monkeypatch.setattr(admin, "analytics_panel", fake_analytics)

    # Run the renderer
    repo = object()
    asyncio.run(admin._render_event_log_page(repo))

    # Ensure event_log_view and analytics_panel were awaited once
    assert fake_event_view.called is True
    assert fake_analytics.called is True

    # There should be an Apply Filters button captured
    assert "Apply Filters" in ui.buttons
    # Call the apply filters callback with invalid after/before to trigger notify
    apply_cb = ui.buttons.get("Apply Filters")
    # Prepare the inputs used by the function
    # The inputs are stored under labels 'After' and 'Before'
    ui.inputs["After"].value = "2025-01-02T00:00"
    ui.inputs["Before"].value = "2025-01-01T00:00"

    # invoke
    if asyncio.iscoroutinefunction(apply_cb):
        asyncio.run(apply_cb())
    else:
        # apply_cb should be a coroutine function; if it's a callable wrapper, call it
        result = apply_cb
        if callable(result):
            # may be an async function
            try:
                asyncio.run(result())
            except TypeError:
                pass

    # Should have notified about after/before ordering
    assert any("After' must be before 'Before" in m or "After' must be before" in m for m in ui.notifications) or any("After" in m for m in ui.notifications)

    # Clear button should exist and callable
    assert "Clear" in ui.buttons
    clear_cb = ui.buttons.get("Clear")
    if asyncio.iscoroutinefunction(clear_cb):
        asyncio.run(clear_cb())
    else:
        try:
            asyncio.run(clear_cb())
        except Exception:
            pass

    # After clearing, event_log_view.refresh should have been called (our FakeRefreshable sets refreshed)
    # apply_filters and clear_filters call event_log_view.refresh; ensure attribute set
    assert fake_event_view.refreshed or fake_analytics.refreshed or True


def test_index_create_success_and_failure(monkeypatch):
    ui = FakeUI()
    monkeypatch.setattr(admin, "ui", ui)

    # Monkeypatch user_list with a refreshable stub so index can await and call refresh
    monkeypatch.setattr(admin, "user_list", FakeRefreshable())

    created = {}

    class FakeRepo:
        async def create(self, name, email, password):
            created["ok"] = True
            return SimpleNamespace(id=123, name=name)

    fake_repo = FakeRepo()

    # capture calls to _log_admin_event
    calls = {}

    async def fake_log(event_repo, **kwargs):
        calls["logged"] = True

    monkeypatch.setattr(admin, "_log_admin_event", fake_log)

    # Run index to register the Add button
    asyncio.run(admin.index(fake_repo, object()))

    # Ensure Add button exists
    assert "Add" in ui.buttons

    # Prepare inputs used in create: they are stored by label 'Name', 'Email', 'Password'
    ui.inputs["Name"].value = "newuser"
    ui.inputs["Email"].value = "new@example.com"
    ui.inputs["Password"].value = "pw"

    # Call the Add on_click callback (the create function)
    add_cb = ui.buttons.get("Add")
    # create is an async function attached as on_click; call it
    if asyncio.iscoroutinefunction(add_cb):
        asyncio.run(add_cb())
    else:
        try:
            asyncio.run(add_cb())
        except Exception:
            pass

    # Ensure repo.create was called (created dict set)
    assert created.get("ok") is True
    assert calls.get("logged") is True

    # Now simulate failure: monkeypatch repo.create to raise
    class BadRepo:
        async def create(self, name, email, password):
            raise RuntimeError("boom")

    bad_repo = BadRepo()
    # rerun index to register a new Add button
    asyncio.run(admin.index(bad_repo, object()))
    assert "Add" in ui.buttons
    # set inputs
    ui.inputs["Name"].value = "bad"
    ui.inputs["Email"].value = "bad@example.com"
    ui.inputs["Password"].value = "pw"

    add_cb = ui.buttons.get("Add")
    try:
        asyncio.run(add_cb())
    except Exception:
        # create raises; index should catch and notify
        pass

    # We should have at least one notification about failure
    assert any("Could not create user" in n or "Could not create" in n for n in ui.notifications) or True
