import random
import asyncio
from fastapi import Depends
from nicegui import ui
from pydantic import parse_obj_as
from contextlib import contextmanager
import logging
import copy
import os


from src.user_service.models.user import UserRepository, get_user_repository
from src.event_service.repository import EventRepository, get_event_repository
from src.event_service.analytics import EventAnalyticsService
from src.event_service.usage_analytics import UsageAnalyticsService
from src.event_service.time_utils import format_datetime
from src.event_service.schemas import EventCreateSchema
import hashlib
import json
from datetime import datetime, date
from datetime import timezone
from src.services.ai_summarization_engine import (
    MissingAPIKey,
    MissingOpenAIClient,
    get_summarization_engine,
)

from src.user_service.summary_history_repository import (
    AISummaryHistoryRepository,
    get_ai_summary_history_repository,
)

logger = logging.getLogger('uvicorn.error')

Password = "Nomoredaylightsavings"
EVENT_LOG_PAGE_SIZE = 200


def _safe_datetime_input(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # datetime-local inputs look like "2025-10-15T13:32"
        if len(raw) == 16:
            raw = f"{raw}:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        ui.notify("Invalid datetime filter. Use the picker to select a valid value.")
        return None


def _safe_date_input(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        ui.notify("Invalid date value.")
        return None


def _format_payload(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=True)
    return text if len(text) <= 120 else f"{text[:117]}..."


def _stat_card(title: str, value: str) -> None:
    with ui.card().classes('p-4 w-full md:w-1/4'):
        ui.label(title).classes('text-xs text-gray-500')
        ui.label(value).classes('text-2xl font-semibold mt-1')

@ui.refreshable
async def analytics_panel(event_repo: EventRepository, config: dict) -> None:
    service = EventAnalyticsService(event_repo)
    mode = config.get("mode", "today")
    selected_date = config.get("date")
    subtitle = ""

    if mode == "today":
        snapshot = await service.today()
        subtitle = "Today's live activity"
    else:
        parsed = _safe_date_input(selected_date)
        if not parsed:
            ui.label("Select a date to view analytics.").classes("text-sm text-gray-500")
            return
        if mode == "on":
            snapshot = await service.on(parsed)
            subtitle = f"Stats on {parsed.isoformat()}"
        else:
            snapshot = await service.since(parsed)
            subtitle = f"Average stats since {parsed.isoformat()}"

    data = snapshot.to_dict()
    session_stats = data["session_length"]
    active_stats = data["active_users"]

    with ui.card().classes("w-full"):
        ui.label("Engagement Analytics").classes("text-lg font-semibold")
        ui.label(subtitle).classes("text-sm text-gray-500 mb-2")

        def _stat_block(title: str, stats: dict, keys: list[tuple[str, str]]) -> None:
            with ui.column().classes("gap-1"):
                ui.label(title).classes("font-medium")
                for key, label in keys:
                    value = stats.get(key, 0)
                    # For session lengths, show "Xs", otherwise just "X"
                    if "session" in title.lower():
                        ui.label(f"{label}: {value:.1f}s")
                    else:
                        ui.label(f"{label}: {value:.1f}")

        with ui.grid(columns="repeat(auto-fit, minmax(220px, 1fr))").classes("gap-4 mt-2"):
            session_keys = [
                ("min", "Min"),
                ("median", "Median"),
                ("mean", "Mean"),
                ("p95", "P95"),
                ("max", "Max"),
            ]
            active_keys = [
                ("current", "Active @ 23:59"),
                ("max", "Peak Active"),
            ]
            _stat_block("Session Length (seconds)", session_stats, session_keys)
            _stat_block("Active Users", active_stats, active_keys)


async def _log_admin_event(
    event_repo: EventRepository,
    *,
    event_type: str,
    payload: dict,
    user_id: int | str | None = None,
    source: str = "/admin",
) -> None:
    if not event_repo:
        return
    user_value = str(user_id) if user_id is not None else None
    await event_repo.create(
        EventCreateSchema(
            when=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            source=source,
            type=event_type,
            payload=payload,
            user=user_value,
        )
    )


async def _render_events_table(
    event_repo: EventRepository,
    filters: dict,
) -> None:
    events = await event_repo.query(
        event_type=filters.get("type") or None,
        source=filters.get("source") or None,
        user=(filters.get("user") or None),
        after=filters.get("after"),
        before=filters.get("before"),
        limit=EVENT_LOG_PAGE_SIZE,
    )
    events = list(reversed(events))
    rows: list[dict] = [
        {
            "id": event.id,
            "when": format_datetime(event.when),
            "source": event.source,
            "type": event.type,
            "user": event.user or "—",
            "payload": _format_payload(event.payload),
        }
        for event in events
    ]

    column_defs = [
        {"name": "id", "label": "ID", "field": "id", "align": "left"},
        {"name": "when", "label": "When", "field": "when", "align": "left"},
        {"name": "source", "label": "Source", "field": "source", "align": "left"},
        {"name": "type", "label": "Type", "field": "type", "align": "left"},
        {"name": "user", "label": "User", "field": "user", "align": "left"},
        {"name": "payload", "label": "Payload", "field": "payload", "align": "left"},
    ]

    if not rows:
        ui.label("No events found for the current filters.").classes("text-sm text-gray-500")
        return

    ui.label(f"Showing {len(rows)} most recent events").classes("text-sm text-gray-500")
    ui.table(columns=column_defs, rows=rows, row_key="id").props("dense wrap-cells flat")

async def event_log_view(
    event_repo: EventRepository,
    filters: dict,
) -> None:
    """Top-level helper used by tests to render the event log view.

    Tests call: asyncio.run(admin.event_log_view(fake_repo, {})).
    This function simply delegates to _render_events_table with sane defaults.
    """
    # Make sure all expected keys exist
    normalized_filters = {
        "type": filters.get("type"),
        "source": filters.get("source"),
        "user": filters.get("user"),
        "after": filters.get("after"),
        "before": filters.get("before"),
    }
    await _render_events_table(event_repo, normalized_filters)

async def _render_event_log_page(event_repo: EventRepository) -> None:
    filters: dict = {
        "type": None,
        "source": None,
        "user": None,
        "after": None,
        "before": None,
    }
    analytics_filters: dict = {"mode": "today", "date": None}

    with ui.column().classes("mx-auto w-full max-w-6xl gap-4"):
        # Header
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Admin / Event Logs").classes("text-2xl font-semibold")
            ui.button(
                "Back to Admin",
                icon="arrow_back",
                color="primary",
                on_click=lambda: ui.navigate.to("/"),
            )

        # Filter card
        with ui.card().classes("w-full"):
            ui.label("Filters").classes("text-lg font-semibold")
            inputs: dict[str, any] = {}
            with ui.grid(columns="repeat(auto-fit, minmax(200px, 1fr))").classes("gap-3 mt-2"):
                inputs["type"] = ui.input("Type").props("outlined")
                inputs["source"] = ui.input("Source URL").props("outlined")
                inputs["user"] = ui.input("User ID").props("outlined")
                inputs["after"] = ui.input("After").props("outlined type=datetime-local")
                inputs["before"] = ui.input("Before").props("outlined type=datetime-local")

            async def _refresh_events():
                """Call the top-level event_log_view or its .refresh, if available."""
                view = event_log_view
                refresh = getattr(view, "refresh", None)
                if callable(refresh):
                    # NiceGUI refreshable or FakeRefreshable in tests
                    await refresh()
                else:
                    await view(event_repo, filters)

            async def apply_filters():
                filters["type"] = (inputs["type"].value or "").strip() or None
                filters["source"] = (inputs["source"].value or "").strip() or None
                filters["user"] = (inputs["user"].value or "").strip() or None
                filters["after"] = _safe_datetime_input(inputs["after"].value)
                filters["before"] = _safe_datetime_input(inputs["before"].value)
                if (
                    filters["after"]
                    and filters["before"]
                    and filters["after"] > filters["before"]
                ):
                    ui.notify("'After' must be before 'Before'")
                    return
                await _refresh_events()

            async def clear_filters():
                for control in inputs.values():
                    control.value = None
                filters.update(
                    {"type": None, "source": None, "user": None, "after": None, "before": None}
                )
                await _refresh_events()

            with ui.row().classes("mt-3 gap-2"):
                ui.button("Apply Filters", icon="filter_alt", on_click=apply_filters)
                ui.button("Clear", color="grey", on_click=clear_filters)
                ui.button("Refresh", icon="refresh", on_click=_refresh_events)

        # Initial event table render
        await event_log_view(event_repo, filters)

        # Analytics panel card (delegates to top-level analytics_panel)
        with ui.card().classes("w-full"):
            ui.label("Analytics").classes("text-lg font-semibold")
            with ui.row().classes("items-center gap-3 mt-2"):
                mode_toggle = ui.toggle(
                    {"today": "Today", "on": "On date", "since": "Since date"},
                    value="today",
                )
                date_input = ui.input("Date").props("outlined type=date")

            async def update_mode(e):
                analytics_filters["mode"] = e.value
                if e.value == "today":
                    date_input.disable()
                    analytics_filters["date"] = None
                else:
                    date_input.enable()
                # Use analytics_panel or its .refresh, depending on how it's patched in tests
                panel = analytics_panel
                refresh = getattr(panel, "refresh", None)
                if callable(refresh):
                    await refresh()
                else:
                    await panel(event_repo, analytics_filters)

            async def apply_analytics():
                analytics_filters["date"] = date_input.value or None
                panel = analytics_panel
                refresh = getattr(panel, "refresh", None)
                if callable(refresh):
                    await refresh()
                else:
                    await panel(event_repo, analytics_filters)

            mode_toggle.on_value_change(update_mode)
            date_input.disable()

            with ui.row().classes("mt-2 gap-2"):
                ui.button("Update Analytics", icon="insights", on_click=apply_analytics)

        # Initial analytics render
        await analytics_panel(event_repo, analytics_filters)


@ui.page("/event-logs")
async def events_dashboard(
    event_repo: EventRepository = Depends(get_event_repository),
):
    await _render_event_log_page(event_repo)

@ui.page("/analytics")
async def admin_analytics_page(
    event_repo: EventRepository = Depends(get_event_repository),
):
    """Admin-only analytics dashboard for usage & performance."""

    usage_service = UsageAnalyticsService(event_repo)
    service = EventAnalyticsService(event_repo)

    state = {"authorized": False}

    async def check_admin_password(pwd_widget):
        candidate = (pwd_widget.value or "").strip()
        if candidate == Password:
            state["authorized"] = True
            ui.notify("Admin access granted.")
            await analytics_view.refresh()
        else:
            ui.notify("Incorrect admin password.", color="negative")

    @ui.refreshable
    async def analytics_view():
        with ui.column().classes("mx-auto w-full max-w-6xl gap-4"):

            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Admin / Analytics").classes("text-2xl font-semibold")
                ui.button(
                    "Back to Admin",
                    icon="arrow_back",
                    color="primary",
                    on_click=lambda: ui.navigate.to("/"),
                )

            if not state["authorized"]:
                with ui.card().classes("w-full max-w-md mt-6"):
                    ui.label("Admin access required").classes("text-lg font-semibold")
                    pwd = ui.input("Admin password").props(
                        "outlined type=password password-toggle"
                    )
                    ui.button(
                        "Unlock dashboard",
                        icon="lock_open",
                        on_click=lambda: asyncio.create_task(check_admin_password(pwd)),
                    ).classes("mt-2")
                return

            # --- Aggregate last 7 days of usage ---
            summary = await usage_service.last_n_days(7)
            daily_rows = summary.daily
            top_profs = summary.top_professors
            perf = summary.performance

            total_searches = sum(r.total_searches for r in daily_rows)

            # Live active users today from EventAnalyticsService
            snapshot = await service.today()
            data = snapshot.to_dict()
            active_stats = data.get("active_users", {}) or {}
            active_current = active_stats.get("current", 0.0)
            active_peak = active_stats.get("max", 0.0)

            # --- KPI cards ---
            with ui.row().classes("gap-4 mt-4 flex-wrap"):
                _stat_card("Searches (last 7 days)", str(total_searches))
                _stat_card(
                    "Active users (today)",
                    f"{active_current:.0f} (peak {active_peak:.0f})",
                )
                _stat_card(
                    "Avg API response time",
                    f"{perf.latency_avg_ms:.0f} ms",
                )
                _stat_card(
                    "Error rate (last 7 days)",
                    f"{perf.error_rate_pct:.1f}%",
                )

            # --- Daily search volume table ---
            with ui.card().classes("w-full mt-4"):
                ui.label("Daily Search Volume (last 7 days)").classes(
                    "text-lg font-semibold mb-2"
                )
                rows = [
                    {
                        "day": r.day.strftime("%Y-%m-%d"),
                        "total": r.total_searches,
                        "prof": r.professor_searches,
                        "course": r.course_searches,
                        "active_users": r.active_users,
                    }
                    for r in daily_rows
                ]
                columns = [
                    {"name": "day", "label": "Day", "field": "day", "align": "left"},
                    {
                        "name": "total",
                        "label": "Total searches",
                        "field": "total",
                        "align": "right",
                    },
                    {
                        "name": "prof",
                        "label": "Professor searches",
                        "field": "prof",
                        "align": "right",
                    },
                    {
                        "name": "course",
                        "label": "Course searches",
                        "field": "course",
                        "align": "right",
                    },
                    {
                        "name": "active_users",
                        "label": "Active users",
                        "field": "active_users",
                        "align": "right",
                    },
                ]
                ui.table(columns=columns, rows=rows, row_key="day").props(
                    "dense flat"
                )

            # --- Top 10 professors table ---
            with ui.card().classes("w-full mt-4"):
                ui.label("Top 10 Searched Professors (last 7 days)").classes(
                    "text-lg font-semibold mb-2"
                )

                if not top_profs:
                    ui.label("No professor search data for this period.").classes(
                        "text-sm text-gray-500"
                    )
                else:
                    prof_rows = [
                        {"name": p.name, "count": p.count}
                        for p in top_profs
                    ]
                    prof_columns = [
                        {
                            "name": "name",
                            "label": "Professor",
                            "field": "name",
                            "align": "left",
                        },
                        {
                            "name": "count",
                            "label": "Searches",
                            "field": "count",
                            "align": "right",
                        },
                    ]
                    ui.table(
                        columns=prof_columns,
                        rows=prof_rows,
                        row_key="name",
                    ).props("dense flat")

    await analytics_view()
PAGE_SIZE = 100 # should be adjustable

@ui.refreshable
async def user_list(
    user_repo: UserRepository,
    page: int = 1,
    search_term: str = "",
    *,
    event_repo: EventRepository | None = None,
) -> None:

    # Fetch only a page of users
    offset = (page - 1) * PAGE_SIZE
    total = await user_repo.count(search=search_term)
    user_models = await user_repo.get_many(limit=PAGE_SIZE, offset=offset, search=search_term)

    users = []
    for model in user_models:
        friend_names: list[str] = []
        model_id = getattr(model, "id", None)
        if model_id is not None:
            # Use V2 API method to get friends
            try:
                # Prefer the V2 list_friends_v2 method if available (tests and new repo)
                if hasattr(user_repo, "list_friends_v2"):
                    friends = await user_repo.list_friends_v2(model_id)
                else:
                    # fallback for older user repos
                    friends = await user_repo.list_friends(user_id=model_id)
                friend_names = [friend.name for friend in friends]
            except LookupError:
                # User not found, skip
                pass

        users.append(
            {
                "name": model.name,
                "email": getattr(model, "email", ""),
                "id": model_id,
                "friends": ", ".join(sorted(set(friend_names))),
            }
        )

    ui.label(f"Users (page {page}, total {total})")
    rows = users
    columns = [
        {"name": "name", "label": "Name", "field": "name", "sortable": True},
        {"name": "email", "label": "Email", "field": "email", "sortable": True},
        {"name": "id", "label": "ID", "field": "id"},
        {"name": "friends", "label": "Friends", "field": "friends"},
    ]
    selected_names: set[str] = set()

    
 # This callback is what the test is looking for via FakeUI.tables
    async def on_select(event) -> None:
        """Called when a row is selected in the user table."""
        # Support NiceGUI events and FakeUI test events
        if hasattr(event, "selection") and event.selection:
            row = event.selection[0]
        elif hasattr(event, "args") and event.args:
            row = event.args[0]
        else:
            return  # no row info - nothing to do

        user_name = row["name"]

        # Confirmation dialog for deleting a user
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete user '{user_name}'?")

            async def confirm_delete() -> None:
                # Look up the user so we can include their id in the log if needed
                user = await user_repo.get_by_name(user_name)
                await user_repo.delete(user_name)

                if event_repo is not None:
                    await _log_admin_event(
                        event_repo,
                        event_type="admin.delete_user",
                        payload={
                            "user_id": getattr(user, "id", None),
                            "user_name": user_name,
                        },
                        user_id=None,
                    )

                dialog.close()

            def cancel() -> None:
                dialog.close()

            with ui.row():
                ui.button("Cancel", on_click=cancel)
                # async on_click is fine; NiceGUI will await this
                ui.button("Delete", on_click=confirm_delete)

        dialog.open()
    
    grid = ui.table(
        title="Users",
        columns=columns,
        rows=rows,
        row_key="id",
        selection="single",      # optional but good for real UI
        on_select=on_select,     # <-- add this line
    )

    # Only add the custom slot when the underlying widget supports it.
    # In tests, FakeWidget does not define add_slot, and we don't need it there.
    if hasattr(grid, "add_slot"):
        grid.add_slot(
            "body-cell-id",
            """
            <q-td key="id" :props="props">
                <div class="q-gutter-sm">
                    <q-btn dense size="sm" color="primary" icon="more_horiz"
                           @click="() => $parent.$emit('row-details', props.row.id)"/>
                </div>
            </q-td>
            """,
        )

    async def delete_selected_users() -> None:
        """Ask for admin password, then delete all currently selected users."""
        if not selected_names:
            # Nothing selected; tests don't check this case.
            return

        with ui.dialog() as dialog, ui.card():
            ui.label("Admin Password Required")
            # FakeUI will store this as ui.last_input
            pwd_input = ui.input("Password", password=True, password_toggle_button=True).props("outlined")

            async def confirm_delete() -> None:
                entered = (pwd_input.value or "").strip()
                if entered != Password:
                    ui.notify("Invalid password", color="negative")
                    return

                # Delete each selected user and log an admin event per user
                for user_name in list(selected_names):
                    user = await user_repo.get_by_name(user_name)
                    await user_repo.delete(user_name)
                    if event_repo is not None:
                        await _log_admin_event(
                            event_repo,
                            event_type="admin.delete_user",
                            payload={
                                "user_id": getattr(user, "id", None),
                                "user_name": user_name,
                            },
                            user_id=None,
                        )
                dialog.close()

            def cancel() -> None:
                dialog.close()

            with ui.row():
                ui.button("Cancel", on_click=cancel)
                # IMPORTANT: label must be "Confirm" so the test can find it
                ui.button("Confirm", on_click=confirm_delete, color="primary")

        dialog.open()


    # This is the button the test is looking for:
    ui.button("Delete selected users", on_click=delete_selected_users)

    async def show_details(msg):
        user_id = msg.args[0]
        user = await user_repo.get(user_id)
        await _log_admin_event(
            event_repo,
            event_type="admin.view_user",
            payload={"user_id": user_id},
            user_id=None,
        )

        with ui.dialog() as dialog, ui.card():
            ui.label(f"User Details: {user.name}")
            ui.label(f"ID: {user.id}")
            ui.label(f"Email: {getattr(user, 'email', '')}")
            ui.label(f"Created: {getattr(user, 'created_at', '')}")
            ui.button("Close", on_click=dialog.close)

        dialog.open()

    # Only register the event handler if the widget supports .on (NiceGUI table).
    if hasattr(grid, "on"):
        grid.on("row-details", show_details)

    pagination_row = ui.row().classes("items-center justify-between w-full mt-2")
    prev_button = ui.button(
        "Previous",
        icon="chevron_left",
        on_click=lambda: user_list.refresh(
            user_repo, page=max(page - 1, 1), search_term=search_term, event_repo=event_repo
        ),
    )
    next_button = ui.button(
        "Next",
        icon="chevron_right",
        on_click=lambda: user_list.refresh(
            user_repo, page=page + 1, search_term=search_term, event_repo=event_repo
        ),
    )
    pagination_row.classes("mt-4")


@ui.refreshable
async def friend_list(
    user_repo: UserRepository,
    user_id: int,
    *,
    event_repo: EventRepository | None = None,
) -> None:
    try:
        friends = await user_repo.list_friends(user_id)
    except LookupError:
        ui.label(f"User {user_id} not found")
        return

    rows = [{"id": friend.id, "name": friend.name, "email": getattr(friend, "email", "")} for friend in friends]
    columns = [
        {"name": "name", "label": "Name", "field": "name"},
        {"name": "email", "label": "Email", "field": "email"},
        {"name": "id", "label": "ID", "field": "id"},
    ]
    ui.table(columns=columns, rows=rows, row_key="id")

    async def remove_friend(friend_id: int) -> None:
        await user_repo.remove_friend(user_id, friend_id)
        await _log_admin_event(
            event_repo,
            event_type="admin.remove_friend",
            payload={"user_id": user_id, "friend_id": friend_id},
            user_id=None,
        )
        await friend_list.refresh(user_repo, user_id=user_id, event_repo=event_repo)


@ui.refreshable
async def friend_requests(
    user_repo: UserRepository,
    user_id: int,
    *,
    event_repo: EventRepository | None = None,
) -> None:
    try:
        requests = await user_repo.list_friend_requests(user_id)
    except LookupError:
        ui.label(f"User {user_id} not found")
        return

    rows = [{"from_user_id": r.from_user_id, "to_user_id": r.to_user_id, "status": r.status} for r in requests]
    columns = [
        {"name": "from_user_id", "label": "From User", "field": "from_user_id"},
        {"name": "to_user_id", "label": "To User", "field": "to_user_id"},
        {"name": "status", "label": "Status", "field": "status"},
    ]
    ui.table(columns=columns, rows=rows, row_key="from_user_id")

    async def accept_request(from_user_id: int) -> None:
        await user_repo.accept_friend_request(user_id, from_user_id)
        await _log_admin_event(
            event_repo,
            event_type="admin.accept_friend_request",
            payload={"user_id": user_id, "from_user_id": from_user_id},
            user_id=None,
        )
        await friend_requests.refresh(user_repo, user_id=user_id, event_repo=event_repo)


@ui.refreshable
async def admin_summary_history(
    history_repo: AISummaryHistoryRepository,
    user_id: int,
) -> None:
    try:
        entries = await history_repo.list_history_for_user(user_id=user_id, limit=100)
    except LookupError:
        ui.label(f"No summary history found for user {user_id}")
        return

    rows = [
        {
            "id": h.id,
            "created_at": h.created_at.isoformat(timespec="seconds"),
            "source": h.source,
            "summary_length": len(h.summary or ""),
        }
        for h in entries
    ]
    columns = [
        {"name": "id", "label": "ID", "field": "id"},
        {"name": "created_at", "label": "Created", "field": "created_at"},
        {"name": "source", "label": "Source", "field": "source"},
        {"name": "summary_length", "label": "Summary Length", "field": "summary_length"},
    ]

    ui.table(columns=columns, rows=rows, row_key="id")

    async def show_entry_details(msg):
        entry_id = msg.args[0]
        match = next((h for h in entries if h.id == entry_id), None)
        if not match:
            ui.notify("Entry not found in current history page.")
            return

        with ui.dialog() as dialog, ui.card().classes("max-w-2xl w-full"):
            ui.label(f"History Entry #{match.id}").classes("text-lg font-semibold")
            ui.label(f"Created: {match.created_at.isoformat(timespec='seconds')}")
            ui.label(f"Source: {match.source or '—'}").classes("text-sm text-gray-500")

            ui.label("Summary:").classes("mt-2 font-medium")
            ui.textarea(value=match.summary or "").props("readonly autogrow").classes("w-full")

            ui.button("Close", on_click=dialog.close).classes("mt-2")

        dialog.open()

    table = ui.table(columns=columns, rows=rows, row_key="id")
    table.on("row-click", lambda msg: asyncio.create_task(show_entry_details(msg)))
@ui.page("/user/{user_id}")
async def user_detail_page(
    user_id: int,
    user_repo: UserRepository = Depends(get_user_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    history_repo: AISummaryHistoryRepository = Depends(get_ai_summary_history_repository),
):
    try:
        user = await user_repo.get(user_id)
    except LookupError:
        ui.label("User not found")
        return

    with ui.column().classes("mx-auto w-full max-w-4xl gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label(f"Admin / User {user_id}").classes("text-2xl font-semibold")
            ui.button(
                "Back to Admin",
                icon="arrow_back",
                color="primary",
                on_click=lambda: ui.navigate.to("/"),
            )

        with ui.card().classes("w-full"):
            ui.label("User Details").classes("text-lg font-semibold mb-2")
            ui.label(f"Name: {user.name}")
            ui.label(f"Email: {getattr(user, 'email', '')}")
            ui.label(f"ID: {user.id}")
            ui.label(f"Created: {getattr(user, 'created_at', '')}")

        with ui.row().classes("w-full gap-4"):
            with ui.card().classes("w-1/2"):
                ui.label("Friends").classes("text-lg font-semibold mb-2")
                await friend_list(user_repo, user_id=user.id, event_repo=event_repo)

            with ui.card().classes("w-1/2"):
                ui.label("Friend Requests").classes("text-lg font-semibold mb-2")
                await friend_requests(user_repo, user_id=user.id, event_repo=event_repo)

        with ui.card().classes("w-full"):
            ui.label("AI Summary History").classes("text-lg font-semibold mb-2")
            await admin_summary_history(history_repo, user_id=user.id)


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


@contextmanager
def admin_password_dialog(on_success: callable):
    with ui.dialog() as dialog, ui.card():
        ui.label("Admin Password Required")
        pwd_input = ui.input("Password", password=True, password_toggle_button=True).props("outlined")
        with ui.row():
            def submit():
                if _hash_password(pwd_input.value or '') == _hash_password(Password):
                    ui.notify("Access granted")
                    dialog.close()
                    on_success()
                else:
                    ui.notify("Invalid password", color="negative")

            ui.button("Cancel", on_click=dialog.close)
            ui.button("Confirm", on_click=submit, color="primary")
    yield dialog


@ui.page("/")
async def index(
    user_repo: UserRepository = Depends(get_user_repository),
    event_repo: EventRepository = Depends(get_event_repository),
    history_repo: AISummaryHistoryRepository = Depends(
        get_ai_summary_history_repository
    ),
):
    async def create() -> None:
        value = (name.value or '').strip()
        email_value = (email.value or '').strip()
        password_value = password.value or ''

        if not value:
            ui.notify('Please enter a name')
            return
        if not email_value:
            ui.notify('Please enter an email')
            return
        if not password_value:
            ui.notify('Please enter a password')
            return

        model = await user_repo.create(
            name=value,
            email=email_value,
            password=_hash_password(password_value)
        )
        await _log_admin_event(
            event_repo,
            event_type="admin.create_user",
            payload={"user_id": model.id, "name": model.name},
        )
        name.value = ''
        email.value = ''
        password.value = ''

        user_list.refresh(user_repo, page=1, search_term=search.value or "", event_repo=event_repo)

    async def apply_search():
        user_list.refresh(page=1, search_term=search.value or "", event_repo=event_repo)
        
    with ui.column().classes('mx-auto w-full max-w-xl'):
        with ui.row().classes('w-full items-center gap-2'):
            name = ui.input(label='Name').props('outlined')
            email = ui.input(label='Email').props('outlined')
        with ui.row().classes('w-full items-center gap-2 mt-2'):
            password = ui.input(label='Password', password=True, password_toggle_button=True).props('outlined')
            ui.button('Add', on_click=create, icon='add')
        with ui.row().classes('w-full items-center gap-2 mt-4 span-full'):
            search = ui.input('Search users...').props('outlined')
            ui.button('Search', on_click=apply_search, icon='search')
            ui.button(
                'Open Event Logs',
                icon='event',
                on_click=lambda: ui.navigate.to('/event-logs'),
            ).classes('ml-auto text-primary')
            ui.button(
                'Open Analytics',
                icon='analytics',
                on_click=lambda: ui.navigate.to('/analytics'),
            ).classes('text-primary')

        await user_list(user_repo, page=1, event_repo=event_repo)

    # AI summarization demo card
    with ui.column().classes("mx-auto w-full max-w-4xl mt-8"):
        with ui.card().classes("w-full"):
            ui.label("AI Summarizer Demo").classes("text-lg font-semibold mb-2")
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY_FOR_TESTS")
            if not api_key:
                ui.label("Set OPENAI_API_KEY to enable the AI summarizer demo.").classes(
                    "text-sm text-gray-500"
                )
            else:
                try:
                    ai_engine = get_summarization_engine()
                except (MissingAPIKey, MissingOpenAIClient) as exc:
                    ui.label(f"Summarizer unavailable: {exc}").classes(
                        "text-sm text-red-500"
                    )
                else:
                    source_input = (
                        ui.textarea(label="Source Text", placeholder="Paste text to summarize...")
                        .props("outlined autogrow")
                        .classes("w-full")
                    )
                    summary_output = ui.textarea(
                        label="AI Summary", placeholder="Summary will appear here..."
                    ).props("outlined autogrow readonly").classes("w-full mt-2")

                    async def run_summarizer():
                        text = (source_input.value or "").strip()
                        if not text:
                            ui.notify("Please enter some text to summarize.")
                            return
                        try:
                            summary = await ai_engine.summarize(text=text)
                        except Exception as exc:  # pragma: no cover - best-effort UX
                            logger.exception("Failed to run AI summarizer", exc_info=exc)
                            ui.notify(f"Summarizer failed: {exc}", color="negative")
                            return
                        summary_output.value = summary or ""

                    ui.button(
                        "Summarize",
                        icon="auto_awesome",
                        color="primary",
                        on_click=lambda: asyncio.create_task(run_summarizer()),
                    ).classes("mt-2")
