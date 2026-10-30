"""Игровые спрайты юнитов — загружаются из PNG файлов с прозрачным фоном.

Все изображения хранятся в ui/assets/sprites/:
  warrior.png  — воин (рыцарь)
  mage.png     — маг
  archer.png   — лучник

Функция draw_unit_sprite загружает соответствующий PNG и отрисовывает его
в заданной области (x, y, w, h) с сохранением пропорций и альфа-канала.
"""

import math
import pygame
from pathlib import Path

# Путь к папке со спрайтами
_ASSETS_DIR = Path(__file__).parent / "assets" / "sprites"

# Кэш загруженных изображений: ключ — имя класса, значение — pygame.Surface
_SPRITE_CACHE: dict[str, pygame.Surface] = {}

# Базовый цвет тела силуэта по классу (fallback, если картинка не загрузилась)
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

# Цвет кожи / лица / рук
DETAIL = (230, 210, 180)

# Сопоставление классов к именам файлов
_CLASS_TO_FILE = {
    "warrior": "warrior.png",
    "mage": "mage.png",
    "archer": "archer.png",
}


def _load_sprite(unit_class: str) -> pygame.Surface:
    """Загружает PNG спрайт для класса юнита (кэшируется)."""
    if unit_class in _SPRITE_CACHE:
        return _SPRITE_CACHE[unit_class]

    filename = _CLASS_TO_FILE.get(unit_class, "warrior.png")
    path = _ASSETS_DIR / filename

    try:
        surf = pygame.image.load(str(path))
        # Пробуем convert_alpha, если не получается — используем обычный Surface
        try:
            surf = surf.convert_alpha()
        except Exception:
            surf = surf.convert()
        _SPRITE_CACHE[unit_class] = surf
        return surf
    except (pygame.error, FileNotFoundError, Exception):
        # Если файла нет или не удалось загрузить — fallback на процедурку
        return None


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
        pygame.draw.rect(surf, color,
                         (cx - r, cy - r, r * 2, r * 2), border_radius=3)
        pygame.draw.line(surf, (220, 220, 220),
                         (cx, cy - r), (cx, cy + r), max(1, r // 4))
    elif item_type == "weapon":
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
    """Рисует спрайт юнита из PNG файла с прозрачным фоном.

    Args:
        surf: целевая поверхность pygame.
        x, y: верхний левый угол области рисования.
        w, h: ширина и высота области.
        unit_class: "warrior" | "mage" | "archer".
        tier_color: цвет окантовки карточки.
        star: звёздность 1..3 — рисует столько же звёздочек.
        body_color / accent_color: игнорируются (используется PNG).
        race: игнорируется (используется PNG).
    """
    # Пытаемся загрузить PNG спрайт
    sprite = _load_sprite(unit_class)

    if sprite is not None:
        # Масштабируем спрайт под размер ячейки с сохранением пропорций
        sprite_w, sprite_h = sprite.get_size()
        scale = min(w / sprite_w, h / sprite_h)
        new_w = max(1, int(sprite_w * scale))
        new_h = max(1, int(sprite_h * scale))
        scaled = pygame.transform.scale(sprite, (new_w, new_h))

        # Центрируем в области
        cx = x + (w - new_w) // 2
        cy = y + (h - new_h) // 2
        surf.blit(scaled, (cx, cy))
    else:
        # Fallback: процедурный силуэт, если PNG не загрузился
        _draw_fallback_sprite(surf, x, y, w, h, unit_class,
                              body_color, accent_color, race, tier_color)

    # Окантовка тира
    if tier_color:
        pygame.draw.rect(surf, tier_color, (x, y, w, h), width=2, border_radius=6)

    # Звёзды
    if star > 1:
        star_r = max(4, int(5 * min(w, h) / 40.0))
        gap = int(6 * min(w, h) / 40.0)
        total_w = (star - 1) * gap + star_r * 2
        sx = x + w - total_w - 3
        sy = y + h - star_r - 3
        for i in range(star - 1):
            _draw_star(surf, sx + i * gap + star_r, sy + star_r,
                       star_r, (255, 220, 80))


def _draw_fallback_sprite(surf, x, y, w, h, unit_class,
                          body_color=None, accent_color=None, race=None,
                          tier_color=None):
    """Резервный процедурный спрайт, если PNG не загрузился.
    Рисует детализированного персонажа с телом, головой, оружием и тенью."""
    cx = x + w // 2
    cy = y + h // 2

    s = min(w, h) / 32.0  # увеличенный масштаб для лучшей видимости
    if s < 0.5:
        s = 0.5

    # Определяем цвета
    if body_color is None:
        body = CLASS_BODY.get(unit_class, CLASS_BODY["warrior"])
    else:
        body = body_color

    if accent_color is None:
        accent = CLASS_ACCENT.get(unit_class, CLASS_ACCENT["warrior"])
    else:
        accent = accent_color

    # Тень под ногами
    pygame.draw.ellipse(surf, (20, 20, 30),
                        (cx - int(16 * s), cy + int(8 * s),
                         int(32 * s), int(12 * s)))

    # Окантовка тира (тонкая рамка вокруг всего спрайта)
    if tier_color is not None:
        pygame.draw.rect(surf, tier_color, (x, y, w, h), width=2, border_radius=6)

    if unit_class == "warrior":
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "mage":
        _draw_mage(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "archer":
        _draw_archer(surf, cx, cy, s, body, accent, DETAIL)
    else:
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)


def _draw_warrior(surf, cx, cy, s, body, accent, detail):
    # Туловище (броня)
    pygame.draw.rect(surf, body,
                     (cx - int(11 * s), cy - int(9 * s),
                      int(22 * s), int(20 * s)), border_radius=4)
    # Детали брони (полосы)
    pygame.draw.line(surf, accent,
                     (cx - int(9 * s), cy - int(6 * s)),
                     (cx + int(9 * s), cy - int(6 * s)),
                     max(1, int(2 * s)))
    pygame.draw.line(surf, accent,
                     (cx - int(9 * s), cy + int(2 * s)),
                     (cx + int(9 * s), cy + int(2 * s)),
                     max(1, int(2 * s)))
    # Голова
    pygame.draw.circle(surf, detail, (cx, cy - int(13 * s)), int(7 * s))
    # Глаза
    pygame.draw.circle(surf, (0, 0, 0), (cx - int(3 * s), cy - int(14 * s)), max(1, int(1.5 * s)))
    pygame.draw.circle(surf, (0, 0, 0), (cx + int(3 * s), cy - int(14 * s)), max(1, int(1.5 * s)))
    # Меч (акцент)
    pygame.draw.rect(surf, accent,
                     (cx - int(15 * s), cy - int(3 * s),
                      int(6 * s), int(16 * s)), border_radius=1)
    pygame.draw.rect(surf, accent,
                     (cx - int(16 * s), cy + int(10 * s),
                      int(10 * s), int(4 * s)), border_radius=1)
    # Ремень
    pygame.draw.line(surf, (60, 50, 40),
                     (cx - int(7 * s), cy - int(8 * s)),
                     (cx + int(7 * s), cy - int(8 * s)),
                     max(1, int(2 * s)))


def _draw_mage(surf, cx, cy, s, body, accent, detail):
    # Мантия (треугольник тела)
    points = [
        (cx - int(13 * s), cy + int(7 * s)),
        (cx + int(13 * s), cy + int(7 * s)),
        (cx + int(9 * s), cy - int(11 * s)),
        (cx - int(9 * s), cy - int(11 * s)),
    ]
    pygame.draw.polygon(surf, body, points)
    # Подробности мантии (полосы)
    pygame.draw.line(surf, accent,
                     (cx - int(11 * s), cy - int(3 * s)),
                     (cx + int(11 * s), cy - int(3 * s)),
                     max(1, int(2 * s)))
    # Голова
    pygame.draw.circle(surf, detail, (cx, cy - int(15 * s)), int(7 * s))
    # Капюстон (треугольник над головой)
    hood_points = [
        (cx - int(9 * s), cy - int(15 * s)),
        (cx + int(9 * s), cy - int(15 * s)),
        (cx, cy - int(23 * s)),
    ]
    pygame.draw.polygon(surf, body, hood_points)
    # Глаза (светятся для мага)
    pygame.draw.circle(surf, (255, 255, 100), (cx - int(3 * s), cy - int(16 * s)), max(1, int(1.5 * s)))
    pygame.draw.circle(surf, (255, 255, 100), (cx + int(3 * s), cy - int(16 * s)), max(1, int(1.5 * s)))
    # Посох (акцент)
    pygame.draw.line(surf, accent,
                     (cx + int(11 * s), cy - int(7 * s)),
                     (cx + int(15 * s), cy - int(22 * s)),
                     max(1, int(2 * s)))
    _draw_star(surf, cx + int(15 * s), cy - int(24 * s),
               max(2, int(3 * s)), accent)
    # Пояс
    pygame.draw.line(surf, body,
                     (cx - int(13 * s), cy - int(1 * s)),
                     (cx - int(17 * s), cy + int(3 * s)),
                     max(1, int(3 * s)))
    pygame.draw.line(surf, body,
                     (cx + int(13 * s), cy - int(1 * s)),
                     (cx + int(17 * s), cy + int(3 * s)),
                     max(1, int(3 * s)))


def _draw_archer(surf, cx, cy, s, body, accent, detail):
    # Туловище (кожаная броня)
    pygame.draw.rect(surf, body,
                     (cx - int(9 * s), cy - int(7 * s),
                      int(18 * s), int(18 * s)), border_radius=3)
    # Детали брони (ремни)
    pygame.draw.line(surf, accent,
                     (cx - int(7 * s), cy - int(4 * s)),
                     (cx + int(7 * s), cy - int(4 * s)),
                     max(1, int(2 * s)))
    pygame.draw.line(surf, accent,
                     (cx - int(7 * s), cy + int(2 * s)),
                     (cx + int(7 * s), cy + int(2 * s)),
                     max(1, int(2 * s)))
    # Голова
    pygame.draw.circle(surf, detail, (cx, cy - int(11 * s)), int(6 * s))
    # Глаза
    pygame.draw.circle(surf, (0, 0, 0), (cx - int(2.5 * s), cy - int(12 * s)), max(1, int(1.5 * s)))
    pygame.draw.circle(surf, (0, 0, 0), (cx + int(2.5 * s), cy - int(12 * s)), max(1, int(1.5 * s)))
    # Лук (акцент - дуга)
    pygame.draw.arc(surf, accent,
                    (cx - int(15 * s), cy - int(12 * s),
                     int(14 * s), int(22 * s)),
                    math.radians(200), math.radians(340),
                    max(1, int(2 * s)))
    # Тетива лука
    pygame.draw.line(surf, accent,
                     (cx - int(8 * s), cy - int(10 * s)),
                     (cx - int(8 * s), cy + int(10 * s)),
                     max(1, int(1 * s)))
    # Стрела
    pygame.draw.line(surf, detail,
                     (cx + int(4 * s), cy - int(5 * s)),
                     (cx + int(12 * s), cy - int(13 * s)),
                     max(1, int(2 * s)))
    # Пояс
    pygame.draw.line(surf, (80, 60, 40),
                     (cx - int(6 * s), cy - int(8 * s)),
                     (cx + int(6 * s), cy - int(8 * s)),
                     max(1, int(2 * s)))