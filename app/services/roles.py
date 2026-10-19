"""Роли сотрудников в веб-панели и что каждой роли разрешено."""

ROLES = {
    "admin": "Администратор",
    "manager": "Менеджер",
    "operator": "Оператор",
    "viewer": "Наблюдатель",
}
ROLE_HINTS = {
    "admin": "всё, включая сотрудников, роли и журнал действий",
    "manager": "заказы, дилеры, клиенты, каталог, загрузка Excel, рассылки, настройки",
    "operator": "заказы: принять, отменить, ответить клиенту; чат с клиентами",
    "viewer": "только просмотр и статистика",
}

VIEW = {"orders.view", "dealers.view", "clients.view", "catalog.view", "chat.view"}
MANAGE = VIEW | {"orders.edit", "dealers.edit", "clients.edit", "catalog.edit", "upload", "stats",
                "broadcast", "settings", "chat.reply"}

# Права: что можно делать
PERMISSIONS = {
    "admin": MANAGE | {"staff", "audit"},
    "manager": MANAGE,
    "operator": {"orders.view", "orders.edit", "clients.view", "catalog.view", "chat.view", "chat.reply"},
    "viewer": VIEW | {"stats"},
}


def can(role: str | None, permission: str) -> bool:
    return permission in PERMISSIONS.get(role or "", set())
