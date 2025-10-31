"""Minimal stub of NiceGUI used for tests.

This provides a lightweight `ui` object with the small surface the tests and
admin UI import. It's intentionally minimal: widgets are fake objects that
support context manager usage, `.classes()`, `.props()`, `.enable()`,
`.disable()`, `.set_selection()`, and hold a `.value` where appropriate.

This is only for tests / local execution to avoid depending on the real
nicegui package in CI containers that don't have it installed.
"""
from __future__ import annotations
from contextlib import contextmanager
from types import SimpleNamespace
import asyncio
import functools
from typing import Any, Callable


class FakeWidget:
    def __init__(self, *args, **kwargs):
        self._classes = []
        self._props = []
        self._enabled = True
        self.value = None
        self.selection = None

    def classes(self, *args, **kwargs):
        # allow chaining
        return self

    def props(self, *args, **kwargs):
        return self

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False

    def set_selection(self, *args, **kwargs):
        self.selection = args[0] if args else None

    def on_value_change(self, cb: Callable[..., Any]):
        # store callback for tests if needed
        self._on_value_change = cb

    def on_click(self, cb: Callable[..., Any]):
        self._on_click = cb

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Navigate:
    def to(self, path: str):
        # no-op navigation stub
        return None


class _UI:
    def __init__(self):
        self.navigate = _Navigate()
        # record labels and notifications for tests to inspect
        self._labels: list[str] = []
        self._notifications: list[str] = []
        self._tables: list[callable] = []
        self._buttons: dict[str, callable] = {}

    def notify(self, msg: str):
        # record notifications for tests and be a no-op
        try:
            self._notifications.append(msg)
        except Exception:
            pass
        return None

    def label(self, *args, **kwargs):
        # record the shown label text (first positional arg) and return a widget
        text = args[0] if args else kwargs.get("text") if kwargs else None
        try:
            self._labels.append(text)
        except Exception:
            pass
        return FakeWidget()

    def table(self, *args, **kwargs):
        on_select = kwargs.get("on_select")
        if on_select is not None:
            try:
                self._tables.append(on_select)
            except Exception:
                pass
        return FakeWidget()

    def grid(self, *args, **kwargs):
        return FakeWidget()

    def card(self, *args, **kwargs):
        return FakeWidget()

    def column(self, *args, **kwargs):
        return FakeWidget()

    def row(self, *args, **kwargs):
        return FakeWidget()

    def button(self, *args, **kwargs):
        # capture a simple key for tests if provided
        text = None
        if args:
            text = args[0]
        if "text" in kwargs:
            text = kwargs.get("text")
        w = FakeWidget()
        try:
            if text is not None:
                # prefer text, else use icon/name
                self._buttons[str(text)] = kwargs.get("on_click")
        except Exception:
            pass
        return w

    def input(self, *args, **kwargs):
        w = FakeWidget()
        # mimic inputs having a `.value` attribute
        w.value = None
        return w

    def dialog(self, *args, **kwargs):
        # return a fake dialog that supports .open/.close
        w = FakeWidget()
        def open_():
            w._open = True
        def close_():
            w._open = False
        w.open = open_
        w.close = close_
        return w

    def select(self, *args, **kwargs):
        w = FakeWidget()
        w.value = None
        return w

    def toggle(self, *args, **kwargs):
        w = FakeWidget()
        w.value = None
        return w

    def separator(self, *args, **kwargs):
        return FakeWidget()

    # decorator helpers
    def refreshable(self, func: Callable[..., Any]):
        # attach a no-op synchronous refresh method and return function unchanged
        def _refresh(*args, **kwargs):
            # intentionally do nothing; tests may replace this with fakes
            return None

        setattr(func, "refresh", _refresh)
        return func

    def page(self, *page_args, **page_kwargs):
        def _decorator(func: Callable[..., Any]):
            # no-op; return original
            return func

        return _decorator


# expose a module-global `ui` instance
ui = _UI()

__all__ = ["ui"]
