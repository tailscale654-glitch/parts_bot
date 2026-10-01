"""Таблицы базы данных."""
from datetime import datetime

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.names import dealer_key

SUPPORTED_LANGUAGES = ("ru", "en", "uz")


class Base(DeclarativeBase):
    pass


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # служебный код, например "tashkent_city"
    name_ru: Mapped[str] = mapped_column(String(128))
    name_en: Mapped[str | None] = mapped_column(String(128))
    name_uz: Mapped[str | None] = mapped_column(String(128))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    # None = пользователь ещё не выбрал язык / регион
    language: Mapped[str | None] = mapped_column(String(2))
    region_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id", ondelete="SET NULL"))
    # заблокирован в веб-панели: бот ему не отвечает (кроме администраторов из ADMIN_IDS)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # lazy="joined" — регион загружается сразу вместе с пользователем
    region: Mapped[Region | None] = relationship(lazy="joined")


class CarModel(Base):
    """Модель автомобиля (JAC JS4, JAC T8 ...). Таблица называется models."""

    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(128), unique=True)
    name_en: Mapped[str | None] = mapped_column(String(128))
    name_uz: Mapped[str | None] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Node(Base):
    """Узел автомобиля (Двигатель, Тормозная система ...)."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(128), unique=True)
    name_en: Mapped[str | None] = mapped_column(String(128))
    name_uz: Mapped[str | None] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Part(Base):
    """Деталь. Одна строка = деталь для конкретной модели и узла."""

    __tablename__ = "parts"
    __table_args__ = (UniqueConstraint("model_id", "part_number", name="uq_parts_model_part_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("models.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    name_ru: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    name_uz: Mapped[str | None] = mapped_column(String(255))
    part_number: Mapped[str] = mapped_column(String(64), index=True)
    description_ru: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    description_uz: Mapped[str | None] = mapped_column(Text)
    photo: Mapped[str | None] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    model: Mapped[CarModel] = relationship(lazy="joined")
    node: Mapped[Node] = relationship(lazy="joined")


class Dealer(Base):
    """Дилер. Регион, телефон и адрес берутся из справочника дилеров (если он загружен)."""

    __tablename__ = "dealers"

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # «ключ» названия для сопоставления: «OOO «ASIAMOTOR»» и «"Asia Motor" MChJ» → asiamotor
    name_key: Mapped[str] = mapped_column(
        String(255), unique=True, default=lambda ctx: dealer_key(ctx.get_current_parameters()["name"])
    )
    code: Mapped[str | None] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # есть в последней выгрузке
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")  # «Активный» в справочнике
    in_directory: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    region: Mapped[Region] = relationship(lazy="joined")


class Stock(Base):
    """Цена и остаток детали у конкретного дилера."""

    __tablename__ = "stocks"
    __table_args__ = (UniqueConstraint("part_id", "dealer_id", name="uq_stocks_part_dealer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id", ondelete="CASCADE"), index=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id", ondelete="CASCADE"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    delivery_days: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    part: Mapped[Part] = relationship(lazy="joined")
    dealer: Mapped[Dealer] = relationship(lazy="joined")


class CartItem(Base):
    """Позиция в корзине: конкретная деталь у конкретного дилера (stock) и количество."""

    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "stock_id", name="uq_cart_user_stock"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock: Mapped[Stock] = relationship(lazy="joined")


ORDER_STATUSES = ("NEW", "CONFIRMED", "READY", "COMPLETED", "CANCELLED")


class Order(Base):
    """Заказ — всегда у одного дилера. Корзина с деталями от 2 дилеров = 2 заказа."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)  # номер заказа (начинается с 10001)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(lazy="joined")
    dealer: Mapped[Dealer] = relationship(lazy="joined")
    items: Mapped[list["OrderItem"]] = relationship(
        lazy="selectin", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )


class OrderItem(Base):
    """Позиция заказа. Название, артикул и цена копируются — чтобы история не менялась после нового Excel."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[int | None] = mapped_column(ForeignKey("parts.id", ondelete="SET NULL"))
    stock_id: Mapped[int | None] = mapped_column(ForeignKey("stocks.id", ondelete="SET NULL"))
    part_number: Mapped[str] = mapped_column(String(64))
    name_ru: Mapped[str] = mapped_column(String(255))
    name_en: Mapped[str | None] = mapped_column(String(255))
    name_uz: Mapped[str | None] = mapped_column(String(255))
    model_name: Mapped[str | None] = mapped_column(String(128))
    node_name: Mapped[str | None] = mapped_column(String(128))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    order: Mapped[Order] = relationship(back_populates="items")


class DealerStaff(Base):
    """Сотрудник дилера: Telegram-пользователь, который получает заказы своего дилера."""

    __tablename__ = "dealer_staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)  # один дилер на человека
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    dealer: Mapped[Dealer] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")


class DealerInvite(Base):
    """Одноразовая ссылка-приглашение для сотрудника дилера (действует 7 дней)."""

    __tablename__ = "dealer_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    dealer: Mapped[Dealer] = relationship(lazy="joined")


class OrderMessage(Base):
    """Переписка по заказу между клиентом и дилером (через бота)."""

    __tablename__ = "order_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    to_side: Mapped[str] = mapped_column(String(8))  # client | dealer
    text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebUser(Base):
    """Вход в веб-панель. Логин и пароль выдаёт бот администратору (в Telegram)."""

    __tablename__ = "web_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer", server_default="viewer")  # см. services/roles.py
    # меняется при каждом новом пароле — старые входы (cookie) перестают работать
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")


class PanelInvite(Base):
    """Приглашение сотрудника в веб-панель с ролью (одноразовое, 7 дней)."""

    __tablename__ = "panel_invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(32), unique=True)
    role: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class PartTranslation(Base):
    """Перевод названия детали, заданный в веб-панели. Главнее словаря app/data/part_names.json
    и сохраняется при следующих загрузках складской выгрузки."""

    __tablename__ = "part_translations"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True)  # part_name_key(name_en)
    name_en: Mapped[str] = mapped_column(String(255))
    name_ru: Mapped[str | None] = mapped_column(String(255))
    name_uz: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class BotSetting(Base):
    """Настройки, которые меняются в веб-панели без перезапуска (контакты менеджера и т. п.)."""

    __tablename__ = "bot_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Broadcast(Base):
    """Рассылка клиентам из веб-панели. status: sending | done | interrupted."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(255), default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="sending", server_default="sending")
    total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sent: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    author: Mapped[User | None] = relationship(lazy="joined")


class AuditLog(Base):
    """Журнал действий в веб-панели: кто, что и когда изменил."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    login: Mapped[str] = mapped_column(String(64), default="", server_default="")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="", server_default="")
    details: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class SyncRun(Base):
    """Одна синхронизация остатков с CarSale (сервис sync). status: running | ok | failed."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="carsale", server_default="carsale")
    trigger: Mapped[str] = mapped_column(String(16), default="schedule", server_default="schedule")
    status: Mapped[str] = mapped_column(String(16), default="running", server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    dealers: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    pieces: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")


CARSALE_OP_STATUSES = ("queued", "running", "done", "dry", "failed", "unknown")


class CarsaleOp(Base):
    """Запись заказа бота в CarSale («Оформить заказ» при выдаче клиенту).
    Одна запись на заказ (уникально) — так заказ не попадёт в CarSale дважды."""

    __tablename__ = "carsale_ops"
    __table_args__ = (UniqueConstraint("order_id", "kind", name="uq_carsale_ops_order_kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16), default="sale", server_default="sale")
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order: Mapped[Order] = relationship(lazy="joined")
