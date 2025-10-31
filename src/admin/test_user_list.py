import asyncio
from types import SimpleNamespace
import src.admin.main as admin


class FakeWidget:
    def __init__(self, **kwargs):
        self.kw = kwargs
        self.value = kwargs.get("value")
        self.disabled = False

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


class FakeDialog(FakeWidget):
    def open(self):
        self.opened = True

    def close(self):
        self.opened = False


class FakeRefreshable:
    async def __call__(self, *args, **kwargs):
        return None

    def refresh(self, *args, **kwargs):
        # synchronous no-op refresh to avoid coroutine warnings when code
        # calls refresh() without awaiting
        return None


class FakeUI:
    def __init__(self):
        self.buttons = {}
        self.inputs = {}
        self.last_input = None
        self.notifications = []
        self.tables = []
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
        if label:
            self.inputs[label] = w
        else:
            # store unnamed inputs for dialog pw
            self.last_input = w
        return w

    def toggle(self, options, value=None):
        w = FakeWidget()
        w.value = value
        return w

    def button(self, text=None, icon=None, on_click=None, color=None, **kwargs):
        key = text or icon or str(len(self.buttons))
        self.buttons[key] = on_click
        return FakeWidget()

    def notify(self, msg: str):
        self.notifications.append(msg)

    def table(self, *a, **k):
        on_select = k.get("on_select")
        if on_select is not None:
            self.tables.append(on_select)
        return FakeWidget(rows=k.get("rows"))

    def select(self, options, label=None, **k):
        w = FakeWidget()
        if label:
            self.inputs[label] = w
        return w

    def dialog(self):
        return FakeDialog()
    def separator(self, *a, **k):
        return FakeWidget()


def make_user(name, _id=1, email=None, password=None):
    return SimpleNamespace(name=name, id=_id, email=email or f"{name}@example.com", password=password)


def test_user_list_delete_flow(monkeypatch):
    ui = FakeUI()
    monkeypatch.setattr(admin, "ui", ui)

    # Avoid spawning NiceGUI background tasks by stubbing only the `refresh`
    # method on the real `user_list` function instead of replacing it.
    # This lets the real `user_list` implementation run (so it registers the
    # table on_select callback) while keeping refresh as a no-op in tests.
    try:
        monkeypatch.setattr(admin.user_list, "refresh", FakeRefreshable().refresh)
    except Exception:
        # if user_list isn't writable (unlikely), fall back to replacing the
        # whole callable to keep tests isolated
        monkeypatch.setattr(admin, "user_list", FakeRefreshable())

    # fake users
    users = [make_user("alice", 1), make_user("bob", 2)]

    class FakeRepo:
        def __init__(self):
            self.deleted = {}

        async def count(self, search=None):
            return len(users)

        async def get_many(self, limit, offset, search=None):
            return users

        async def list_friends_v2(self, model_id):
            # for model 1 return bob so we create an existing friendship entry
            if model_id == 1:
                return [make_user("bob", 2)]
            return []

        async def get_by_name(self, name):
            # return a user object with stored password equal to admin.Password
            return make_user(name, password=admin.Password)

        async def delete(self, name):
            self.deleted[name] = True
            return True

        async def list_all_friend_requests(self):
            return []

        async def create_friend_request_v2(self, requester_id, receiver_id):
            return True

        async def accept_friend_request_v2(self, receiver_id, requester_id):
            return True

        async def deny_friend_request_v2(self, receiver_id, requester_id):
            return True

        async def delete_friend_by_name_v2(self, user_id, friend_name):
            return True

    fake_repo = FakeRepo()

    # capture log events
    logged = {}

    async def fake_log(event_repo, **kwargs):
        logged["ok"] = True

    monkeypatch.setattr(admin, "_log_admin_event", fake_log)

    # call user_list
    asyncio.run(admin.user_list(fake_repo, page=1, event_repo=object()))

    # simulate selecting the first row via the table on_select callback
    assert ui.tables, "table on_select not captured"
    toggle_cb = ui.tables[0]
    # simulate event object with selection list of dicts
    evt = SimpleNamespace(selection=[{"name": "alice"}])
    # toggle selection
    if asyncio.iscoroutinefunction(toggle_cb):
        asyncio.run(toggle_cb(evt))
    else:
        toggle_cb(evt)

    # call Delete selected users to open the confirm dialog
    del_cb = ui.buttons.get("Delete selected users")
    assert del_cb is not None
    if asyncio.iscoroutinefunction(del_cb):
        asyncio.run(del_cb())
    else:
        del_cb()

    # set password to admin.Password for confirmation dialog and call Confirm
    ui.last_input.value = admin.Password
    confirm_cb = ui.buttons.get("Confirm")
    assert confirm_cb is not None
    if asyncio.iscoroutinefunction(confirm_cb):
        asyncio.run(confirm_cb())
    else:
        confirm_cb()

    # user should be deleted and log recorded
    assert fake_repo.deleted.get("alice") is True
    assert logged.get("ok") is True


def test_user_list_send_accept_deny_and_remove(monkeypatch):
    ui = FakeUI()
    monkeypatch.setattr(admin, "ui", ui)

    users = [make_user("alice", 1), make_user("bob", 2), make_user("carol", 3)]

    class FakeRepo2:
        def __init__(self):
            self.sent = False
            self.accepted = False
            self.denied = False
            self.removed = False

        async def count(self, search=None):
            return len(users)

        async def get_many(self, limit, offset, search=None):
            return users

        async def list_friends_v2(self, model_id):
            if model_id == 1:
                return [make_user("bob", 2)]
            return []

        async def get_by_name(self, name):
            for u in users:
                if u.name == name:
                    return u
            return None

        async def get_by_id(self, _id):
            for u in users:
                if u.id == _id:
                    return u
            return None

        async def create_friend_request_v2(self, requester_id, receiver_id):
            self.sent = True
            return True

        async def accept_friend_request_v2(self, receiver_id, requester_id):
            self.accepted = True
            return True

        async def deny_friend_request_v2(self, receiver_id, requester_id):
            self.denied = True
            return True

        async def list_all_friend_requests(self):
            # single request from alice -> bob
            return [SimpleNamespace(id=11, requester_id=1, receiver_id=2)]

        async def delete_friend_by_name_v2(self, user_id, friend_name):
            self.removed = True
            return True

    fake_repo = FakeRepo2()

    logged = {}

    async def fake_log(event_repo, **kwargs):
        logged.setdefault("calls", 0)
        logged["calls"] += 1

    monkeypatch.setattr(admin, "_log_admin_event", fake_log)

    asyncio.run(admin.user_list(fake_repo, page=1, event_repo=object()))

    # Send Friend Request
    # populate requester/select values
    if "Requester" in ui.inputs:
        ui.inputs["Requester"].value = "alice"
    if "Receiver" in ui.inputs:
        ui.inputs["Receiver"].value = "bob"

    send_cb = ui.buttons.get("Send Friend Request")
    assert send_cb is not None
    # call it (may be async)
    res = send_cb() if callable(send_cb) else None
    if asyncio.iscoroutine(res):
        asyncio.run(res)

    assert fake_repo.sent is True

    # Accept / Deny buttons created for pending requests
    accept_cb = ui.buttons.get("Accept")
    deny_cb = ui.buttons.get("Deny")
    assert accept_cb is not None
    assert deny_cb is not None

    # call accept
    res = accept_cb()
    if asyncio.iscoroutine(res):
        asyncio.run(res)
    elif asyncio.iscoroutinefunction(accept_cb):
        asyncio.run(accept_cb())

    assert fake_repo.accepted is True

    # call deny (should still work, but our repo records it)
    res = deny_cb()
    if asyncio.iscoroutine(res):
        asyncio.run(res)
    elif asyncio.iscoroutinefunction(deny_cb):
        asyncio.run(deny_cb())

    assert fake_repo.denied is True

    # Remove friendship (Remove button)
    remove_cb = ui.buttons.get("Remove")
    if remove_cb is not None:
        res = remove_cb()
        if asyncio.iscoroutine(res):
            asyncio.run(res)

    assert fake_repo.removed is True


