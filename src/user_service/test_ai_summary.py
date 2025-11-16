from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.user_service.api import app, SummarizeRequest, _resolve_ai_engine
from src.shared.ai_summarization_engine import _coerce_response_text


class DummyEngine:
    def __init__(self) -> None:
        self.model = "dummy-model"
        self.calls: list[SummarizeRequest] = []

    async def summarize(self, text: str, *, options=None) -> str:
        self.calls.append(
            SummarizeRequest(
                text=text,
                context=getattr(options, "instructions", None),
                max_words=getattr(options, "max_words", None),
            )
        )
        return f"summary:{text[:10]}"


def test_ai_summarize_endpoint(monkeypatch):
    dummy = DummyEngine()

    def override():
        return dummy

    app.dependency_overrides[_resolve_ai_engine] = override

    client = TestClient(app)
    response = client.post(
        "/ai/summarize",
        json={"text": "Hello world from tests", "context": "bullet", "max_words": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "summary:Hello worl"
    assert data["model"] == "dummy-model"
    assert data["word_count"] == len(data["summary"].split())
    assert dummy.calls[0].context == "bullet"
    assert dummy.calls[0].max_words == 25

    app.dependency_overrides.clear()


def test_coerce_response_text_handles_various_shapes():
    assert _coerce_response_text(" hello ") == "hello"
    assert _coerce_response_text([" a ", "b "]) == "a b"

    obj = SimpleNamespace(
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(text="from text attribute"),
                ],
            )
        ]
    )
    assert _coerce_response_text(obj).startswith("from text")

    obj2 = {"content": {"value": " nested content "}}
    assert _coerce_response_text(obj2) == "nested content"
