"""Таблицы базы данных."""
from datetime import datetime

from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    """Дилер (точка продаж) в конкретном регионе."""

    __tablename__ = "dealers"
    __table_args__ = (UniqueConstraint("region_id", "name", name="uq_dealers_region_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

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
