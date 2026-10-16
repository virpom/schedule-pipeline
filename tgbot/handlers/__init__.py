from .admin import admin_router
from .editor import editor_router
from .user import user_router

# ВАЖНО: editor_router идёт ДО user_router — у пользователя есть
# catch-all any_text, который иначе перехватил бы текстовый ввод старосты.
routers_list = [
    admin_router,
    editor_router,
    user_router,
]

__all__ = ["routers_list"]
