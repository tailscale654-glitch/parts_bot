"""Роли сотрудников в веб-панели и что каждой роли разрешено."""

ROLES = {
    "admin": "Администратор",
    "manager": "Менеджер",
    "operator": "Оператор",
    "viewer": "Наблюдатель",
}
ROLE_HINTS = {
    "admin": "всё, включая сотрудников и роли",
    "manager": "заказы, дилеры, клиенты",
    "operator": "заказы: принять, отменить, ответить клиенту",
    "viewer": "только просмотр и статистика",
}

# Права: что можно делать
PERMISSIONS = {
    "admin": {"orders.view", "orders.edit", "dealers.view", "dealers.edit", "clients.view", "clients.edit",
              "stats", "staff"},
    "manager": {"orders.view", "orders.edit", "dealers.view", "dealers.edit", "clients.view", "clients.edit", "stats"},
    "operator": {"orders.view", "orders.edit", "clients.view"},
    "viewer": {"orders.view", "dealers.view", "clients.view", "stats"},
}


def can(role: str | None, permission: str) -> bool:
    return permission in PERMISSIONS.get(role or "", set())
