# pragma: no cover
"""NiceGUI compatibility layer used by tests and local development.

This module tries to import the real `nicegui` package when it is installed so
the admin UI can render in live deployments. When NICEGUI_USE_STUB=1 (the test
suite sets this) or when the real package is missing, we fall back to a very
small stub that exposes just enough of the surface area for unit tests.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Callable


def _load_real_nicegui() -> bool:
    """Try to load the installed nicegui package instead of the stub."""
    current_init = Path(__file__).resolve()
    for entry in list(sys.path):
        if not entry:
            continue
        try:
            base = Path(entry)
        except (OSError, TypeError):
            continue

        candidate = base / "nicegui" / "__init__.py"
        if not candidate.exists():
            continue

        try:
            candidate_path = candidate.resolve()
        except OSError:
            continue

        if candidate_path == current_init:
            # Skip this file to avoid infinite recursion.
            continue

        spec = importlib.util.spec_from_file_location(__name__, str(candidate))
        if not spec or not spec.loader:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[__name__] = module
        spec.loader.exec_module(module)  # type: ignore[arg-type]
        globals().update(module.__dict__)
        return True
    return False


_force_stub_env = os.environ.get("NICEGUI_USE_STUB", "")
_use_stub = (
    bool(_force_stub_env)
    and _force_stub_env.strip().lower() not in {"0", "false", "no"}
)
if not _use_stub:
    _use_stub = not _load_real_nicegui()

if _use_stub:
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
            self._tables: list[Callable[..., Any]] = []
            self._buttons: dict[str, Callable[..., Any]] = {}

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

        def textarea(self, *args, **kwargs):
            w = FakeWidget()
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
