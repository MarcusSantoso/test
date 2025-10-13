import random
from fastapi import Depends
from nicegui import ui
from pydantic import parse_obj_as
from contextlib import contextmanager
import logging
import copy


from user_service.models.user import UserRepository, UserSchema, get_user_repository

logger = logging.getLogger('uvicorn.error')

Password = "Nomoredaylightsavings"

Page_Size = 100 # should be adjustable

@ui.refreshable
async def user_list(user_repo: UserRepository, page: int = 1, search_term: str = "") -> None:

    # Fetch only a page of users
    offset = (page - 1) * PAGE_SIZE
    total = await user_repo.count(search=search_term)
    user_models = await user_repo.get_many(limit=PAGE_SIZE, offset=offset, search=search_term)
    users = [UserSchema.from_db_model(model).model_dump() for model in user_models]

    ui.label(f"Users (page {page}, total {total})")

    selected = []

    async def confirm_delete():
        """Open a password dialog before deleting."""
        with ui.dialog() as dialog, ui.card():
            ui.label("Enter admin password to confirm deletion:")
            pwd = ui.input(password=True, password_toggle_button=True).props('outlined')
            with ui.row():
                ui.button("Cancel", on_click=dialog.close)
                ui.button("Confirm", on_click=lambda: check_password(dialog, pwd.value))
        dialog.open()

    async def check_password(dialog, entered_password: str):
        if entered_password == Password:
            dialog.close()
            await delete_users()
        else:
            ui.notify("Incorrect password!")

    async def delete():
        nonlocal selected
        for user in selected:
            result = await user_repo.delete(user['name'])
            if result.rowcount > 0:
                ui.notify(f"Deleted user '{user['name']}'")
            else:
                ui.notify(f"Unable to delete user '{user['name']}'")
            # have to refresh to see updates???
        user_list.refresh(page=page, search_term=search_term)

    delete_btn = ui.button(on_click=confirm_delete, icon='delete', text='Delete selected users')
    delete_btn.disable()
    
    def toggle_delete_button(e):
        nonlocal selected
        selected = e.selection
        if selected:
            delete_btn.enable()
        else:
            delete_btn.disable()


    columns = [{'name': 'name', 'label': 'Name', 'field': 'name', 'align': 'left'}]
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

@ui.page("/")
async def index(user_repo: UserRepository = Depends(get_user_repository)):
    async def create() -> None:
        value = (name.value or '').strip()
        if not value:
            ui.notify('Please enter a name')
            return
        try:
            await user_repo.create(name=value)
            ui.notify(f"Created user '{value}'")
        except Exception as e:
            logger.exception("Create failed")
            ui.notify(f"Could not create user '{value}': {e}")
        finally:
            name.value = ""
            user_list.refresh(page=1, search_term=search.value or "")

    async def apply_search():
        user_list.refresh(page=1, search_term=search.value or "")
        
    with ui.column().classes('mx-auto w-full max-w-xl'):
        with ui.row().classes('w-full items-center gap-2'):
            name = ui.input(label='Name').props('outlined')
            ui.button('Add', on_click=create, icon='add')
        with ui.row().classes('w-full items-center gap-2 mt-4'):
            search = ui.input('Search users...').props('outlined')
            ui.button('Search', on_click=apply_search, icon='search')

        await user_list(user_repo, page=1)

