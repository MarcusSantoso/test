import random
from fastapi import Depends
from nicegui import ui
from pydantic import parse_obj_as
from contextlib import contextmanager
import logging
import copy


from user_service.models.user import UserRepository, UserSchema, get_user_repository


logger = logging.getLogger('uvicorn.error')

Page_Size = 100

@ui.refreshable
async def user_list(user_repo: UserRepository, page: int = 1) -> None:

    # Fetch only a page of users
    offset = (page - 1) * PAGE_SIZE
    user_models = await user_repo.get_many(limit=PAGE_SIZE, offset=offset)
    users = [UserSchema.from_db_model(model).model_dump() for model in user_models]

    ui.label(f"All Users (page {page})")

    selected = []

    async def delete():
        nonlocal selected
        for user in selected:
            result = await user_repo.delete(user['name'])
            if result.rowcount > 0:
                ui.notify(f"Deleted user '{user['name']}'")
            else:
                ui.notify(f"Unable to delete user `{user['name']}'")
            # have to refresh to see updates???
        user_list.refresh()

    button = ui.button(on_click=delete, icon='delete')
    button.disable()
    
    def toggle_delete_button(e):
        nonlocal selected
        selected = e.selection
        button.enabled = bool(selected)


    columns = [{'name': 'name', 'label': 'Name', 'field': 'name', 'required': True, 'align': 'left'}]
    table = ui.table(columns=columns, rows=users,
                     row_key='name',
                     on_select=toggle_delete_button)
    table.set_selection('multiple')

    # Pagination controls
    with ui.row():
        if page > 1:
            ui.button('Prev', on_click=lambda: user_list.refresh(page - 1))
        ui.button('Next', on_click=lambda: user_list.refresh(page + 1))

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
            user_list.refresh()

    with ui.column().classes('mx-auto'):
        # tailwind
        with ui.row().classes('w-full items-center px-4'):
            name = ui.input(label='Name')
            ui.button(on_click=create, icon='add')
        await user_list(user_repo)

