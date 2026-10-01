"""Журнал действий веб-панели («📝 Журнал»)."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog, WebUser

ACTIONS = {
    "login": "Вход в панель",
    "order.status": "Статус заказа",
    "order.message": "Сообщение по заказу",
    "staff.invite": "Приглашение сотрудника",
    "staff.role": "Роль сотрудника",
    "staff.active": "Доступ сотрудника",
    "staff.password": "Новый пароль сотруднику",
    "dealer.edit": "Данные дилера",
    "dealer.enabled": "Дилер вкл/выкл",
    "dealer.invite": "Приглашение для дилера",
    "dealer.staff_remove": "Сотрудник дилера убран",
    "client.message": "Сообщение клиенту",
    "client.blocked": "Блокировка клиента",
    "part.translation": "Перевод детали",
    "upload.apply": "Загрузка Excel",
    "sync.run": "Синхронизация CarSale (вручную)",
    "sync.sale": "Продажа в CarSale",
    "broadcast": "Рассылка",
    "settings.contacts": "Контакты менеджера",
    "region.edit": "Регион",
}


async def log(session: AsyncSession, web: WebUser, action: str, target: str = "", details: str = "") -> None:
    """Записать действие. Коммитит сам (вызывать после основного изменения)."""
    session.add(AuditLog(user_id=web.user_id, login=web.login, action=action,
                         target=target[:255], details=details[:2000]))
    await session.commit()
