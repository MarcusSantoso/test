import random
from fastapi import Depends
from nicegui import ui
from pydantic import parse_obj_as
from contextlib import contextmanager
import logging
import copy


from user_service.models.user import UserRepository, get_user_repository
from src.event_service.repository import EventRepository, get_event_repository
from src.event_service.analytics import EventAnalyticsService
from src.event_service.time_utils import format_datetime
import hashlib
import json
from datetime import datetime, date

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


@ui.refreshable
async def event_log_view(event_repo: EventRepository, filters: dict) -> None:
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
                    ui.label(f"{label}: {value:.1f}s" if "session" in title.lower() else f"{label}: {value:.1f}")

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


async def _render_event_log_page(event_repo: EventRepository) -> None:
    filters: dict = {"type": None, "source": None, "user": None, "after": None, "before": None}
    analytics_filters: dict = {"mode": "today", "date": None}

    with ui.column().classes("mx-auto w-full max-w-6xl gap-4"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Admin / Event Logs").classes("text-2xl font-semibold")
        ui.link("Back to Admin", "/").classes("text-primary underline")

        with ui.card().classes("w-full"):
            ui.label("Filters").classes("text-lg font-semibold")
            inputs = {}
            with ui.grid(columns="repeat(auto-fit, minmax(200px, 1fr))").classes("gap-3 mt-2"):
                inputs["type"] = ui.input("Type").props("outlined")
                inputs["source"] = ui.input("Source URL").props("outlined")
                inputs["user"] = ui.input("User ID").props("outlined")
                inputs["after"] = ui.input("After").props("outlined type=datetime-local")
                inputs["before"] = ui.input("Before").props("outlined type=datetime-local")

            async def apply_filters():
                filters["type"] = (inputs["type"].value or "").strip() or None
                filters["source"] = (inputs["source"].value or "").strip() or None
                filters["user"] = (inputs["user"].value or "").strip() or None
                filters["after"] = _safe_datetime_input(inputs["after"].value)
                filters["before"] = _safe_datetime_input(inputs["before"].value)
                if filters["after"] and filters["before"] and filters["after"] > filters["before"]:
                    ui.notify("'After' must be before 'Before'")
                    return
                await event_log_view.refresh()

            async def clear_filters():
                for key, control in inputs.items():
                    control.value = None
                filters.update({"type": None, "source": None, "user": None, "after": None, "before": None})
                await event_log_view.refresh()

            with ui.row().classes("mt-3 gap-2"):
                ui.button("Apply Filters", icon="filter_alt", on_click=apply_filters)
                ui.button("Clear", color="grey", on_click=clear_filters)
                ui.button("Refresh", icon="refresh", on_click=event_log_view.refresh)

        await event_log_view(event_repo, filters)

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
                date_input.disable() if e.value == "today" else date_input.enable()
                await analytics_panel.refresh()

            async def apply_analytics():
                analytics_filters["date"] = date_input.value or None
                await analytics_panel.refresh()

            mode_toggle.on_value_change(update_mode)
            date_input.disable()

            with ui.row().classes("mt-2 gap-2"):
                ui.button("Update Analytics", icon="insights", on_click=apply_analytics)

        await analytics_panel(event_repo, analytics_filters)


@ui.page("/event-logs")
async def events_dashboard(
    event_repo: EventRepository = Depends(get_event_repository),
):
    await _render_event_log_page(event_repo)


@ui.page("/admin/event-logs")
async def events_dashboard_alias():
    ui.label("Redirecting to /admin/event-logs ...")
    ui.timer(0, lambda: ui.navigate.to("/admin/event-logs"), once=True)

PAGE_SIZE = 100 # should be adjustable

@ui.refreshable
async def user_list(user_repo: UserRepository, page: int = 1, search_term: str = "") -> None:

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
                friends = await user_repo.list_friends_v2(model_id)
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

    selected_names: list[str] = []

    async def confirm_delete():
        """Open a password dialog before deleting."""
        with ui.dialog() as dialog, ui.card():
            ui.label("Enter admin password to confirm deletion:")
            pwd = ui.input(password=True, password_toggle_button=True).props('outlined')

            async def handle_confirm():
                await check_password(dialog, pwd.value or "")

            with ui.row():
                ui.button("Cancel", on_click=dialog.close)
                ui.button("Confirm", on_click=handle_confirm)
        dialog.open()

    async def check_password(dialog, entered_password: str):
        if await is_authorized(entered_password or ""):
            dialog.close()
            await delete()
        else:
            ui.notify("Incorrect password!")

    async def is_authorized(raw_password: str) -> bool:
        candidate = (raw_password or "").strip()
        if not candidate:
            return False
        if candidate == Password:
            return True

        hashed_candidate = hashlib.sha256(candidate.encode()).hexdigest()
        # Require the supplied password to match each selected user
        for name in selected_names:
            user = await user_repo.get_by_name(name)
            if not user or getattr(user, "password", None) != hashed_candidate:
                return False
        return bool(selected_names)

    async def delete():
        nonlocal selected_names
        for name in selected_names:
            was_deleted = await user_repo.delete(name)
            if was_deleted:
                ui.notify(f"Deleted user '{name}'")
            else:
                ui.notify(f"Unable to delete user '{name}'")
        selected_names = []
        user_list.refresh(page=page, search_term=search_term)

    delete_btn = ui.button(on_click=confirm_delete, icon='delete', text='Delete selected users')
    delete_btn.disable()
    
    def toggle_delete_button(e):
        nonlocal selected_names

        def normalize_selection(raw):
            if raw is None:
                return []
            if isinstance(raw, dict):
                combined = raw.get('rows') or raw.get('selection') or raw.get('keys')
                if combined is not None:
                    return normalize_selection(combined)
                return []
            if not isinstance(raw, (list, tuple, set)):
                raw = [raw]
            names: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    if 'name' in item:
                        names.append(str(item['name']))
                    elif 'key' in item:
                        names.append(str(item['key']))
                else:
                    names.append(str(item))
            return names

        candidate = getattr(e, 'selection', None)
        if candidate is None and hasattr(e, 'args'):
            candidate = getattr(e, 'args', None)

        selected_names = normalize_selection(candidate)

        if selected_names:
            delete_btn.enable()
        else:
            delete_btn.disable()


    columns = [
        {'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left'},
        {'name': 'email', 'label': 'Email', 'field': 'email', 'align': 'left'},
        {'name': 'friends', 'label': 'Friends', 'field': 'friends', 'align': 'left'},
    ]
    table = ui.table(columns=columns, rows=users,
                     row_key='name',
                     on_select=toggle_delete_button)
    table.set_selection('multiple')

    # Pagination controls
    with ui.row().classes('items-center mt-4'):
        if page > 1:
            ui.button('Prev', on_click=lambda: user_list.refresh(page - 1, search_term))
        if offset + PAGE_SIZE < total:
            ui.button('Next', on_click=lambda: user_list.refresh(page + 1, search_term))

    all_user_names = [model.name for model in user_models]
    all_users_by_name = {model.name: model for model in user_models}

    async def send_friend_request():
        """Send friend request using V2 API."""
        requester_name = requester_select.value
        receiver_name = receiver_select.value
        if not requester_name or not receiver_name:
            ui.notify("Select both requester and receiver")
            return
        try:
            requester = await user_repo.get_by_name(requester_name)
            receiver = await user_repo.get_by_name(receiver_name)
            if not requester or not receiver:
                ui.notify("User not found")
                return
            
            await user_repo.create_friend_request_v2(requester.id, receiver.id)
            ui.notify(f"Friend request sent: {requester_name} → {receiver_name}")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            requester_select.value = None
            receiver_select.value = None
            user_list.refresh(page=page, search_term=search_term)

    async def accept_friend_request(requester_id: int, receiver_id: int, requester_name: str, receiver_name: str):
        """Accept friend request using V2 API."""
        try:
            await user_repo.accept_friend_request_v2(receiver_id, requester_id)
            ui.notify(f"{receiver_name} accepted {requester_name}'s request")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            user_list.refresh(page=page, search_term=search_term)

    async def deny_friend_request(requester_id: int, receiver_id: int, requester_name: str, receiver_name: str):
        """Deny friend request using V2 API."""
        try:
            removed = await user_repo.deny_friend_request_v2(receiver_id, requester_id)
            if removed:
                ui.notify(f"{receiver_name} denied {requester_name}'s request")
            else:
                ui.notify("No matching request to deny")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            user_list.refresh(page=page, search_term=search_term)

    async def delete_friendship(user_name: str, friend_name: str):
        """Delete a friendship using V2 API."""
        try:
            user = await user_repo.get_by_name(user_name)
            if not user:
                ui.notify(f"User '{user_name}' not found")
                return
            
            deleted = await user_repo.delete_friend_by_name_v2(user.id, friend_name)
            if deleted:
                ui.notify(f"Removed friendship: {user_name} ↔ {friend_name}")
            else:
                ui.notify(f"Friendship not found")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            user_list.refresh(page=page, search_term=search_term)

    ui.separator().classes('mt-6')
    ui.label("Manage Friendships").classes('text-lg font-semibold mt-2')
    with ui.row().classes('w-full items-center gap-2 mt-2'):
        requester_select = ui.select(all_user_names, label='Requester').props('outlined use-chips')
        receiver_select = ui.select(all_user_names, label='Receiver').props('outlined use-chips')
        ui.button('Send Friend Request', on_click=send_friend_request, icon='send')

    # Get ALL friend requests (not just for current page)
    all_friend_requests = await user_repo.list_all_friend_requests()
    request_rows: list[dict] = []
    for request in all_friend_requests:
        requester_user = await user_repo.get_by_id(request.requester_id)
        receiver_user = await user_repo.get_by_id(request.receiver_id)
        if requester_user and receiver_user:
            request_rows.append(
                {
                    "id": request.id,
                    "requester_id": request.requester_id,
                    "receiver_id": request.receiver_id,
                    "requester": requester_user.name,
                    "receiver": receiver_user.name,
                }
            )

    ui.label("Pending Friend Requests").classes('text-md font-medium mt-4')
    if request_rows:
        for row in request_rows:
            with ui.row().classes('items-center gap-3'):
                ui.label(f"{row['requester']} → {row['receiver']}")
                ui.button(
                    'Accept',
                    icon='check',
                    on_click=lambda r=row: accept_friend_request(
                        r['requester_id'], 
                        r['receiver_id'],
                        r['requester'],
                        r['receiver']
                    )
                )
                ui.button(
                    'Deny',
                    icon='close',
                    color='red',
                    on_click=lambda r=row: deny_friend_request(
                        r['requester_id'],
                        r['receiver_id'],
                        r['requester'],
                        r['receiver']
                    )
                )
    else:
        ui.label("No pending friend requests").classes('text-sm text-gray-500')

    # Display existing friendships with ability to remove them
    ui.separator().classes('mt-6')
    ui.label("Existing Friendships").classes('text-md font-medium mt-4')
    
    # Get all friendships for users on current page
    all_friendships: list[dict] = []
    for model in user_models:
        model_id = getattr(model, "id", None)
        if model_id is not None:
            try:
                friends = await user_repo.list_friends_v2(model_id)
                for friend in friends:
                    # Only show each friendship once (avoid duplicates)
                    if model.name < friend.name:
                        all_friendships.append({
                            "user1": model.name,
                            "user2": friend.name,
                        })
            except LookupError:
                pass
    
    if all_friendships:
        for friendship in all_friendships:
            with ui.row().classes('items-center gap-3'):
                ui.label(f"{friendship['user1']} ↔ {friendship['user2']}")
                ui.button(
                    'Remove',
                    icon='link_off',
                    color='orange',
                    on_click=lambda f=friendship: delete_friendship(f['user1'], f['user2'])
                )
    else:
        ui.label("No friendships on this page").classes('text-sm text-gray-500')

@ui.page("/")
async def index(user_repo: UserRepository = Depends(get_user_repository)):
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
        try:
            await user_repo.create(name=value, email=email_value, password=password_value)
            ui.notify(f"Created user '{value}'")
        except Exception as e:
            logger.exception("Create failed")
            ui.notify(f"Could not create user '{value}': {e}")
        finally:
            name.value = ""
            email.value = ""
            password.value = ""
            user_list.refresh(page=1, search_term=search.value or "")

    async def apply_search():
        user_list.refresh(page=1, search_term=search.value or "")
        
    with ui.column().classes('mx-auto w-full max-w-xl'):
        ui.link('Open Event Logs', '/event-logs').classes('self-end text-primary underline')
        with ui.row().classes('w-full items-center gap-2'):
            name = ui.input(label='Name').props('outlined')
            email = ui.input(label='Email').props('outlined')
        with ui.row().classes('w-full items-center gap-2 mt-2'):
            password = ui.input(label='Password', password=True, password_toggle_button=True).props('outlined')
            ui.button('Add', on_click=create, icon='add')
        with ui.row().classes('w-full items-center gap-2 mt-4'):
            search = ui.input('Search users...').props('outlined')
            ui.button('Search', on_click=apply_search, icon='search')
            ui.button('Open Event Logs', on_click=lambda: ui.open('/event-logs')).classes('ml-auto')

        await user_list(user_repo, page=1)
