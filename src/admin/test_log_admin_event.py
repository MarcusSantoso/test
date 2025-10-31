import asyncio
import src.admin.main as admin


class DummyRepo:
    def __init__(self):
        self.calls = []

    async def create(self, event_schema):
        # store the schema (dict-like) so tests can assert
        # allow dict or pydantic-like mapping
        try:
            data = dict(event_schema)
        except Exception:
            data = {k: getattr(event_schema, k) for k in getattr(event_schema, "__dict__", {})}
        self.calls.append(data)
        return data


def test_log_admin_event_creates_event():
    repo = DummyRepo()
    asyncio.run(
        admin._log_admin_event(
            repo, event_type="test_event", payload={"x": 1}, user_id="u1"
        )
    )
    assert len(repo.calls) == 1
    e = repo.calls[0]
    assert e["type"] == "test_event"
    assert e["payload"] == {"x": 1}
