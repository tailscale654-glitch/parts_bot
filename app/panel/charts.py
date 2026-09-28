"""Простые столбчатые диаграммы в SVG — без внешних библиотек (панель работает и без интернета)."""
from __future__ import annotations

import math
from decimal import Decimal
from html import escape

from markupsafe import Markup

W, H = 900, 200  # внутренние координаты; на странице диаграмма растягивается по ширине
LEFT, BOTTOM, TOP = 72, 24, 10


def _nice_step(value: float, integer: bool) -> float:
    """Шаг сетки: 1, 2 или 5 × 10ⁿ — чтобы подписи были круглыми."""
    raw = value / 4 if value > 0 else 1
    power = 10 ** math.floor(math.log10(raw))
    for k in (1, 2, 5, 10):
        if raw <= k * power:
            step = k * power
            break
    return max(step, 1) if integer else step


def _short(value: float) -> str:
    for size, unit in ((1_000_000_000, " млрд"), (1_000_000, " млн"), (1_000, " тыс")):
        if value >= size:
            return f"{round(value / size, 2):g}{unit}"
    return f"{round(value, 2):g}"


def bar_chart(points: list[tuple[str, float | Decimal, str]], label_every: int | None = None) -> Markup:
    """points: (подпись под столбиком, значение, подсказка при наведении)."""
    if not points:
        return Markup('<p class="muted">Нет данных за период.</p>')
    biggest = max(float(v) for _, v, _ in points)
    step = _nice_step(biggest, all(float(v).is_integer() for _, v, _ in points))
    ticks = max(1, math.ceil(biggest / step)) if biggest > 0 else 4
    top = step * ticks
    plot_w, plot_h = W - LEFT - 8, H - BOTTOM - TOP
    slot = plot_w / len(points)
    gap = 2 if slot > 6 else 0.5  # зазор между столбиками
    bar_w = min(max(slot - gap, 1), 48)  # при паре дней столбики не во всю ширину
    every = label_every or max(1, round(len(points) / 12))
    parts = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">']
    for i in range(ticks + 1):  # сетка и подписи шкалы
        value = step * i
        y = TOP + plot_h - plot_h * i / ticks
        parts.append(f'<line class="grid" x1="{LEFT}" x2="{W - 8}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="axis" x="{LEFT - 6}" y="{y + 4:.1f}" text-anchor="end">{_short(value)}</text>')
    for i, (label, value, tip) in enumerate(points):
        h = plot_h * float(value) / top
        x = LEFT + i * slot + (slot - bar_w) / 2
        y = TOP + plot_h - h
        radius = min(4, bar_w / 2, h)
        parts.append(f'<g class="bar"><title>{escape(tip)}</title>'
                     f'<rect class="hit" x="{LEFT + i * slot:.1f}" y="{TOP}" width="{slot:.1f}" height="{plot_h}"/>')
        if h > 0:  # скруглён только верх: прямоугольник + «шапка»
            parts.append(f'<rect class="fill" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="{radius:.1f}"/>'
                         f'<rect class="fill" x="{x:.1f}" y="{y + h / 2:.1f}" width="{bar_w:.1f}" height="{h / 2:.1f}"/>')
        parts.append('</g>')
        if i % every == 0:
            parts.append(f'<text class="axis" x="{x + bar_w / 2:.1f}" y="{H - 6}" text-anchor="middle">{escape(label)}</text>')
    parts.append("</svg>")
    return Markup("".join(parts))
