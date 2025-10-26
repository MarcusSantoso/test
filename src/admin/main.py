import random
from fastapi import Depends
from nicegui import ui
from pydantic import parse_obj_as
from contextlib import contextmanager
import logging
import copy


from user_service.models.user import UserRepository, get_user_repository
import hashlib

logger = logging.getLogger('uvicorn.error')

Password = "Nomoredaylightsavings"

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

    async def send_friend_request():
        requester = requester_select.value
        receiver = receiver_select.value
        if not requester or not receiver:
            ui.notify("Select both requester and receiver")
            return
        try:
            await user_repo.create_friend_request(requester, receiver)
            ui.notify(f"Friend request sent: {requester} → {receiver}")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            requester_select.value = None
            receiver_select.value = None
            user_list.refresh(page=page, search_term=search_term)

    async def accept_friend_request(requester: str, receiver: str):
        try:
            await user_repo.accept_friend_request(requester, receiver)
            ui.notify(f"{receiver} accepted {requester}'s request")
        except (ValueError, LookupError) as exc:
            ui.notify(str(exc))
        finally:
            user_list.refresh(page=page, search_term=search_term)

    async def deny_friend_request(requester: str, receiver: str):
        try:
            removed = await user_repo.deny_friend_request(requester, receiver)
            if removed:
                ui.notify(f"{receiver} denied {requester}'s request")
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

    friend_requests = await user_repo.list_all_friend_requests()
    request_rows: list[dict] = []
    for request in friend_requests:
        requester_user = await user_repo.get_by_id(request.requester_id)
        receiver_user = await user_repo.get_by_id(request.receiver_id)
        if requester_user and receiver_user:
            request_rows.append(
                {
                    "id": request.id,
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
                    on_click=lambda r=row: accept_friend_request(r['requester'], r['receiver'])
                )
                ui.button(
                    'Deny',
                    icon='close',
                    color='red',
                    on_click=lambda r=row: deny_friend_request(r['requester'], r['receiver'])
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
        with ui.row().classes('w-full items-center gap-2'):
            name = ui.input(label='Name').props('outlined')
            email = ui.input(label='Email').props('outlined')
        with ui.row().classes('w-full items-center gap-2 mt-2'):
            password = ui.input(label='Password', password=True, password_toggle_button=True).props('outlined')
            ui.button('Add', on_click=create, icon='add')
        with ui.row().classes('w-full items-center gap-2 mt-4'):
            search = ui.input('Search users...').props('outlined')
            ui.button('Search', on_click=apply_search, icon='search')

        await user_list(user_repo, page=1)