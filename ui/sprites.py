"""Процедурные арт-силуэты юнитов по классам.

Рисует читаемые «персонажи» вместо цветных прямоугольников, используя только
примитивы pygame (круги, прямоугольники, линии, многоугольники). Нет внешних
ассетов — всё генерируется на лету.

Классы: warrior, mage, archer.
Цвет тира — окантовка карточки.
Звёзды — звёздочки в правом нижнем углу (★1, ★2, ★3).
"""

import math
import pygame


# Базовый цвет тела силуэта по классу (если не задан team_color)
CLASS_BODY = {
    "warrior": (110, 140, 170),   # сталь / броня
    "mage": (150, 120, 200),      # мантия мага
    "archer": (160, 130, 100),    # кожа / куртка стрелка
}

# Акцентный цвет (оружие, детали) по классу
CLASS_ACCENT = {
    "warrior": (210, 180, 100),   # золото / бронза
    "mage": (255, 220, 60),       # магическое свечение
    "archer": (110, 170, 110),    # зелёный лук
}

# Базовый цвет тела силуэта по расе (переопределяет классовый, если задан)
RACE_BODY = {
    "human": (110, 140, 170),    # сталь / кожа человека
    "orc": (80, 160, 80),        # зелёная кожа орка
    "demon": (180, 60, 60),      # красная кожа демона
    "elf": (120, 180, 140),      # серебристо-зелёная кожа эльфа
    "undead": (120, 100, 140),   # серо-фиолетовая кожа нежити
}

# Акцентный цвет по расе (оружие, детали, магия)
RACE_ACCENT = {
    "human": (210, 180, 100),    # золото / бронза
    "orc": (140, 200, 60),       # ярко-зелёное оружие орка
    "demon": (255, 100, 100),    # огненно-красное
    "elf": (200, 255, 200),      # магический зелёный свет
    "undead": (180, 160, 220),   # некромантический фиолетовый
}

# Цвет кожи / лица / рук
DETAIL = (230, 210, 180)


def _star_points(cx, cy, r_outer, r_inner, n=5):
    """Координаты звёзды с n лучами."""
    pts = []
    for i in range(n * 2):
        ang = -math.pi / 2 + i * math.pi / n
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + math.cos(ang) * r, cy + math.sin(ang) * r))
    return pts


def _draw_star(surf, cx, cy, r, color):
    """Рисует одну звёздочку."""
    if r < 1:
        return
    pts = _star_points(cx, cy, r, r * 0.4)
    if len(pts) >= 3:
        pygame.draw.polygon(surf, color, pts)


ITEM_ICON = {
    "armor": (150, 150, 150),      # щит / латы
    "weapon": (200, 60, 60),       # меч
    "accessory": (100, 150, 255),  # сапоги / кольцо
    "legendary": (255, 215, 0),    # сердце дракона
}


def draw_item_icon(surf, cx, cy, size, item_type):
    """Рисует процедурную иконку предмета по типу."""
    color = ITEM_ICON.get(item_type, (160, 160, 160))
    r = max(2, int(size * 0.45))
    if item_type == "armor":
        # щит
        pygame.draw.rect(surf, color,
                         (cx - r, cy - r, r * 2, r * 2), border_radius=3)
        pygame.draw.line(surf, (220, 220, 220),
                         (cx, cy - r), (cx, cy + r), max(1, r // 4))
    elif item_type == "weapon":
        # меч: ручка + лезвие
        handle_w = max(1, r // 3)
        handle_h = r
        blade_w = max(1, r // 2)
        blade_h = r * 2
        pygame.draw.rect(surf, (100, 70, 40),
                         (cx - handle_w // 2, cy + r // 2, handle_w, handle_h),
                         border_radius=1)
        pygame.draw.rect(surf, color,
                         (cx - blade_w // 2, cy - blade_h // 2,
                          blade_w, blade_h), border_radius=1)
        pygame.draw.line(surf, (255, 255, 255),
                         (cx - blade_w // 3, cy - blade_h // 2 + 2),
                         (cx + blade_w // 3, cy - blade_h // 2 + 2), 1)
    elif item_type == "accessory":
        # ботинки: две ножки с подошвой
        boot_w = max(1, r // 3)
        boot_h = r
        sole_h = max(1, r // 4)
        pygame.draw.rect(surf, color,
                         (cx - r - 2, cy - boot_h // 2, boot_w, boot_h),
                         border_radius=1)
        pygame.draw.rect(surf, color,
                         (cx + 2, cy - boot_h // 2, boot_w, boot_h),
                         border_radius=1)
        pygame.draw.rect(surf, (80, 60, 40),
                         (cx - r - 4, cy + boot_h // 2 - sole_h // 2,
                          2 * r + 8, sole_h), border_radius=1)
    elif item_type == "legendary":
        # сердце
        pygame.draw.circle(surf, color, (cx - r // 2, cy - r // 2), r)
        pygame.draw.circle(surf, color, (cx + r // 2, cy - r // 2), r)
        pygame.draw.polygon(surf, color, [
            (cx - r, cy), (cx + r, cy), (cx, cy + r),
        ])
    else:
        pygame.draw.circle(surf, color, (cx, cy), r)


def draw_tooltip(surf, x, y, text, font=None):
    """Рисует подсказку с текстом в точке (x, y), проверяя границы экрана."""
    font = font or pygame.font.Font(None, 16)
    lines = text.split("\n")
    pads = 6
    line_h = font.get_linesize()
    w = max(font.size(l)[0] for l in lines) + pads * 2
    h = line_h * len(lines) + pads * 2
    bg = pygame.Surface((w, h), pygame.SRCALPHA)
    bg.fill((30, 30, 40, 230))
    pygame.draw.rect(bg, (200, 200, 100), (0, 0, w, h), width=1, border_radius=4)

    # Проверяем границы экрана — не уходим за правый и нижний край
    screen_w = surf.get_width()
    screen_h = surf.get_height()
    if x + w > screen_w:
        x = screen_w - w - 4
    if x < 0:
        x = 4
    if y + h > screen_h:
        y = screen_h - h - 4
    if y < 0:
        y = 4

    surf.blit(bg, (x, y))
    for i, line in enumerate(lines):
        t = font.render(line, True, (255, 255, 255))
        surf.blit(t, (x + pads, y + pads + i * line_h))


def draw_unit_sprite(surf, x, y, w, h, unit_class, tier_color=None, star=1,
                     body_color=None, accent_color=None, race=None):
    """Рисует процедурный силуэт юнита в прямоугольнике (x, y, w, h).

    Args:
        surf: целевая поверхность pygame.
        x, y: верхний левый угол области рисования.
        w, h: ширина и высота области.
        unit_class: "warrior" | "mage" | "archer" (любая строка — дефолт warrior).
        tier_color: цвет окантовки (из TIER_COLORS) — рисуется рамкой вокруг.
        star: звёздность 1..3 — рисует столько же звёздочек в правом нижнем углу.
        body_color / accent_color: переопределение цветов тела и акцента.
        race: расa юнита ("human", "orc", "demon", "elf", "undead") —
            определяет цвет тела и акцента, если не заданы body_color/accent_color.
    """
    cx = x + w // 2
    cy = y + h // 2

    # Определяем цвета: приоритет body_color/accent_color > расовые > классовые
    if body_color is None:
        if race and race in RACE_BODY:
            # Смешиваем цвет расы с цветом класса для уникального оттенка
            class_body = CLASS_BODY.get(unit_class, CLASS_BODY["warrior"])
            race_body = RACE_BODY[race]
            body = tuple((class_body[i] + race_body[i]) // 2 for i in range(3))
        else:
            body = CLASS_BODY.get(unit_class, CLASS_BODY["warrior"])
    else:
        body = body_color

    if accent_color is None:
        if race and race in RACE_ACCENT:
            accent = RACE_ACCENT[race]
        else:
            accent = CLASS_ACCENT.get(unit_class, CLASS_ACCENT["warrior"])
    else:
        accent = accent_color

    # Масштаб под размер ячейки
    s = min(w, h) / 40.0  # базовый модуль 40
    if s < 0.5:
        s = 0.5

    # ----- Окантовка тира -----
    if tier_color:
        pygame.draw.rect(surf, tier_color, (x, y, w, h), width=2, border_radius=6)

    # ----- Тень тела -----
    pygame.draw.ellipse(surf, (30, 30, 40),
                        (cx - int(14 * s), cy + int(4 * s),
                         int(28 * s), int(10 * s)))

    # ----- Класс-специфичный силуэт -----
    if unit_class == "warrior":
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "mage":
        _draw_mage(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "archer":
        _draw_archer(surf, cx, cy, s, body, accent, DETAIL)
    else:
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)

    # ----- Звёзды -----
    if star > 1:
        star_r = max(4, int(5 * s))  # минимум 4px, чтобы было видно на маленьких карточках доски
        gap = int(6 * s)
        total_w = (star - 1) * gap + star_r * 2
        sx = x + w - total_w - 3
        sy = y + h - star_r - 3
        for i in range(star - 1):
            _draw_star(surf, sx + i * gap + star_r, sy + star_r,
                       star_r, (255, 220, 80))


def _draw_warrior(surf, cx, cy, s, body, accent, detail):
    """Воин: массивная броня, меч за спиной, щит."""
    # Тело (броня)
    pygame.draw.rect(surf, body,
                     (cx - int(10 * s), cy - int(8 * s),
                      int(20 * s), int(18 * s)), border_radius=3)
    # Шлем
    pygame.draw.circle(surf, detail, (cx, cy - int(12 * s)), int(6 * s))
    # Меч за спиной (наклонная линия)
    pygame.draw.line(surf, accent,
                     (cx - int(6 * s), cy - int(4 * s)),
                     (cx - int(10 * s), cy - int(14 * s)),
                     max(1, int(2 * s)))
    # Щит (слева)
    pygame.draw.rect(surf, accent,
                     (cx - int(14 * s), cy - int(2 * s),
                      int(8 * s), int(12 * s)), border_radius=2)
    # Ремень
    pygame.draw.line(surf, (60, 50, 40),
                     (cx - int(6 * s), cy - int(8 * s)),
                     (cx + int(6 * s), cy - int(8 * s)),
                     max(1, int(2 * s)))


def _draw_mage(surf, cx, cy, s, body, accent, detail):
    """Маг: длинная мантия, жезл, звёзда на жезле."""
    # Мантия (трапеция)
    points = [
        (cx - int(12 * s), cy + int(6 * s)),
        (cx + int(12 * s), cy + int(6 * s)),
        (cx + int(8 * s), cy - int(10 * s)),
        (cx - int(8 * s), cy - int(10 * s)),
    ]
    pygame.draw.polygon(surf, body, points)
    # Капюшон
    pygame.draw.circle(surf, detail, (cx, cy - int(14 * s)), int(6 * s))
    # Жезл (вертикальная линия со звездой наверху)
    pygame.draw.line(surf, accent,
                     (cx + int(10 * s), cy - int(6 * s)),
                     (cx + int(14 * s), cy - int(18 * s)),
                     max(1, int(2 * s)))
    _draw_star(surf, cx + int(14 * s), cy - int(20 * s),
               max(2, int(3 * s)), accent)
    # Рукава
    pygame.draw.line(surf, body,
                     (cx - int(12 * s), cy - int(2 * s)),
                     (cx - int(16 * s), cy + int(2 * s)),
                     max(1, int(3 * s)))
    pygame.draw.line(surf, body,
                     (cx + int(12 * s), cy - int(2 * s)),
                     (cx + int(16 * s), cy + int(2 * s)),
                     max(1, int(3 * s)))


def _draw_archer(surf, cx, cy, s, body, accent, detail):
    """Стрелок: лук, стрела, капюшон, худая figura."""
    # Тело
    pygame.draw.rect(surf, body,
                     (cx - int(8 * s), cy - int(6 * s),
                      int(16 * s), int(16 * s)), border_radius=2)
    # Капюшон
    pygame.draw.circle(surf, detail, (cx, cy - int(10 * s)), int(5 * s))
    # Лук (дуга слева)
    pygame.draw.arc(surf, accent,
                    (cx - int(14 * s), cy - int(10 * s),
                     int(12 * s), int(20 * s)),
                    math.radians(200), math.radians(340),
                    max(1, int(2 * s)))
    # Тетива
    pygame.draw.line(surf, accent,
                     (cx - int(8 * s), cy - int(10 * s)),
                     (cx - int(8 * s), cy + int(10 * s)),
                     max(1, int(1 * s)))
    # Стрела (диагональ)
    pygame.draw.line(surf, detail,
                     (cx + int(4 * s), cy - int(4 * s)),
                     (cx + int(12 * s), cy - int(12 * s)),
                     max(1, int(2 * s)))
