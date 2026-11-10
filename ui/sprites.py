"""Игровые спрайты юнитов и текстуры интерфейса — загружаются из PNG файлов.

Все изображения хранятся в assets/:
  assets/units/   — спрайты юнитов с прозрачным фоном
  assets/ui/      — текстуры фона поля, панели и т.д.

Функция draw_unit_sprite загружает соответствующий PNG и отрисовывает его
в заданной области (x, y, w, h) с сохранением пропорций и альфа-канала.
"""

import math
import pygame
from pathlib import Path

# Папка со спрайтами юнитов
_ASSETS_DIR = Path(__file__).parent.parent / "assets" / "units"
# Папка с текстурами интерфейса
_UI_DIR = Path(__file__).parent.parent / "assets" / "ui"

# Кэш загруженных спрайтов юнитов: ключ — имя класса или ключ юнита
_SPRITE_CACHE: dict[str, pygame.Surface | None] = {}
# Кэш текстур интерфейса
_UI_TEXTURE_CACHE: dict[str, pygame.Surface | None] = {}

# Базовый цвет тела силуэта по классу (fallback, если картинка не загрузилась)
CLASS_BODY = {
    "warrior": (110, 140, 170),   # сталь / броня
    "mage": (150, 120, 200),      # мантия мага
    "archer": (160, 130, 100),    # кожа / куртка стрелка
    "healer": (120, 180, 120),    # зелёная хламат целителя
    "buffer": (180, 140, 220),    # пурпурная мантия баффера
    "assassin": (80, 60, 80),     # тёмная одежда ассасина
}

# Акцентный цвет (оружие, детали) по классу
CLASS_ACCENT = {
    "warrior": (210, 180, 100),   # золото / бронза
    "mage": (255, 220, 60),       # магическое свечение
    "archer": (110, 170, 110),    # зелёный лук
    "healer": (255, 255, 150),    # золотой свет целителя
    "buffer": (255, 200, 100),    # оранжевый баффера
    "assassin": (150, 50, 150),   # пурпурные лезвия ассасина
}

# Цвет кожи / лица / рук
DETAIL = (230, 210, 180)

# Сопоставление ключей юнитов к именам файлов спрайтов
_UNIT_TO_FILE = {
    "undead_warrior_skeleton": "skeleton.png",
    "demon_mage_imp": "imp.png",
    "warrior_freshman": "freshman.png",
    "archer_ranger": "ranger.png",
    "elf_archer_ranger": "elf_ranger.png",
    "warrior_veteran": "warrior_veteran.png",
    "warrior_champion": "warrior_champion.png",
    "warrior_knight": "warrior_knight.png",
    "orc_warrior_berserker": "orc_berserker.png",
    "orc_warrior_chief": "orc_chief.png",
    "mage_acolyte": "mage_acolyte.png",
    "mage_sorcerer": "mage_sorcerer.png",
    "mage_archmage": "mage_archmage.png",
    "mage_sage": "mage_sage.png",
    "demon_mage_succubus": "demon_succubus.png",
    "undead_warrior_lich": "undead_lich.png",
    "archer_scout": "archer_scout.png",
    "archer_marksman": "archer_marksman.png",
    "archer_battleheart": "archer_battleheart.png",
    "elf_archer_hunter": "elf_hunter.png",
    # Хилеры (существующие)
    "human_healer_priest": "priest.png",
    "orc_healer_shaman": "orc_shaman.png",
    "demon_healer_blood_priest": "demon_blood_priest.png",
    "elf_healer_dryad": "elf_dryad.png",
    "undead_healer_necromancer": "undead_necromancer.png",
    # Бафферы (существующие)
    "human_buffer_bard": "human_bard.png",
    "orc_buffer_warchief_advisor": "orc_warchief_advisor.png",
    "demon_buffer_demon_lord": "demon_lord.png",
    "elf_buffer_forest_guardian": "elf_forest_guardian.png",
    "undead_buffer_ghost_chieftain": "undead_ghost_chieftain.png",
    # Ассасины (существующие)
    "human_assassin_spy": "human_assassin_spy.png",
    "orc_assassin_raider": "orc_assassin_raider.png",
    "demon_assassin_shadow_killer": "demon_shadow_killer.png",
    "elf_assassin_shadow_walker": "elf_shadow_walker.png",
    "undead_assassin_death_stalker": "undead_death_stalker.png",
    # Новые тир 1 (демоны-воины, добавлены в баланс-батче)
    "demon_warrior_imp_guard": "demon_warrior_imp_guard.png",
    "orc_healer_witch": "orc_healer_witch.png",
    "elf_healer_spirit": "elf_healer_spirit.png",
    "undead_bone_shaman": "undead_bone_shaman.png",
    "demon_fire_totem": "demon_fire_totem.png",
    "human_assassin_knife": "human_assassin_knife.png",
    "undead_assassin_shadow": "undead_assassin_shadow.png",
    "orc_archer_slinger": "orc_archer_slinger.png",
    "undead_mage_bone": "undead_mage_bone.png",
    # Новые тир 2
    "demon_buffer_hell_priest": "demon_buffer_hell_priest.png",
    "undead_bone_buff": "undead_bone_buff.png",
    "human_assassin_blade": "human_assassin_blade.png",
    "orc_assassin_axe": "orc_assassin_axe.png",
    "demon_assassin_shadow_blade": "demon_assassin_shadow_blade.png",
    "elf_assassin_leaf_blade": "elf_assassin_leaf_blade.png",
    "undead_assassin_bone_blade": "undead_assassin_bone_blade.png",
    # Новые тир 3
    "orc_warrior_axe_bearer": "orc_warrior_axe_bearer.png",
    "undead_warrior_bone_guard": "undead_warrior_bone_guard.png",
    "demon_warrior_pit_lord": "demon_warrior_pit_lord.png",
    "demon_archer_fire_bow": "demon_archer_fire_bow.png",
    "undead_archer_bone_bow": "undead_archer_bone_bow.png",
    "human_assassin_dark_blade": "human_assassin_dark_blade.png",
    "orc_assassin_war_axe": "orc_assassin_war_axe.png",
    "demon_assassin_shadow_edge": "demon_assassin_shadow_edge.png",
    "elf_assassin_wind_blade": "elf_assassin_wind_blade.png",
    "undead_assassin_death_edge": "undead_assassin_death_edge.png",
    # Новые тир 4
    "human_warrior_paladin": "human_warrior_paladin.png",
    "human_mage_holy": "human_mage_holy.png",
    "demon_mage_fire_lord": "demon_mage_fire_lord.png",
    "human_healer_holy_priest": "human_healer_holy_priest.png",
    "demon_healer_soul_priest": "demon_healer_soul_priest.png",
    # Новые тир 5
    "orc_warrior_warlord": "orc_warrior_warlord.png",
    "elf_warrior_blade_dancer": "elf_warrior_blade_dancer.png",
    "orc_mage_shadow_shaman": "orc_mage_shadow_shaman.png",
    "elf_mage_star_mage": "elf_mage_star_mage.png",
    "orc_archer_war_bow": "orc_archer_war_bow.png",
    "elf_archer_star_bow": "elf_archer_star_bow.png",
    "orc_healer_war_shaman": "orc_healer_war_shaman.png",
    "elf_healer_star_druid": "elf_healer_star_druid.png",
    "undead_buffer_death_aura": "undead_buffer_death_aura.png",
    # Дополнительные
    "elf_warrior_blade_apprentice": "elf_warrior_blade_apprentice.png",
    "elf_mage_star_apprentice": "elf_mage_star_apprentice.png",
    "human_archer_longbow": "human_archer_longbow.png",
    "icon_damage": "icon_damage.png",
    "icon_kills": "icon_kills.png",
}

# Цвета для цветных квадратов-заглушек по классу (когда PNG не найден)
CLASS_FALLBACK_COLOR = {
    "warrior": (110, 140, 170),    # сталь / броня
    "mage": (150, 120, 200),      # мантия мага
    "archer": (160, 130, 100),    # кожа / куртка стрелка
    "healer": (120, 180, 120),    # зелёный целитель
    "buffer": (180, 140, 220),    # пурпурный баффер
    "assassin": (80, 60, 80),     # тёмный ассасин
}

# Сопоставление классов к именам файлов (fallback, если ключ не найден)
_CLASS_TO_FILE = {
    "warrior": "warrior.png",
    "mage": "mage.png",
    "archer": "archer.png",
}


def _load_sprite(unit_class: str, unit_key: str | None = None) -> pygame.Surface | None:
    """Загружает PNG спрайт для юнита (кэшируется).

    Приоритет поиска:
      1. unit_key — конкретный ключ юнита (например, "undead_warrior_skeleton")
      2. unit_class — класс юнита (warrior / mage / archer) как fallback

    Неуспешная загрузка тоже кэшируется (None), чтобы не Trying
    читать файл каждый кадр и не спамить предупреждениями в консоль.
    """
    cache_key = unit_key or unit_class
    if cache_key in _SPRITE_CACHE:
        return _SPRITE_CACHE[cache_key]

    # Определяем имя файла
    filename = None
    if unit_key and unit_key in _UNIT_TO_FILE:
        filename = _UNIT_TO_FILE[unit_key]
    if filename is None:
        filename = _CLASS_TO_FILE.get(unit_class, f"{unit_class}.png")
    path = _ASSETS_DIR / filename

    print(f"[DEBUG] Loading sprite: {path}", flush=True)
    try:
        surf = pygame.image.load(str(path))
        # convert_alpha()/convert() требуют активного дисплея (set_mode);
        # в headless без окна они падают — используем поверхность как есть.
        try:
            surf = surf.convert_alpha()
        except Exception:
            try:
                surf = surf.convert()
            except Exception:
                pass
        _SPRITE_CACHE[cache_key] = surf
        print(f"[DEBUG] Sprite loaded: {path}", flush=True)
        return surf
    except (pygame.error, FileNotFoundError, Exception) as e:
        print("ВНИМАНИЕ: Спрайт не найден:", cache_key, "(", path, ")", e, flush=True)
        _SPRITE_CACHE[cache_key] = None
        return None


def load_ui_texture(name: str) -> pygame.Surface | None:
    """Загружает текстуру интерфейса из assets/ui/ (кэшируется)."""
    if name in _UI_TEXTURE_CACHE:
        return _UI_TEXTURE_CACHE[name]

    path = _UI_DIR / name
    print(f"[DEBUG] Loading UI texture: {path}", flush=True)
    try:
        surf = pygame.image.load(str(path)).convert()
        _UI_TEXTURE_CACHE[name] = surf
        print(f"[DEBUG] UI texture loaded: {path}", flush=True)
        return surf
    except (pygame.error, FileNotFoundError, Exception) as e:
        print("ВНИМАНИЕ: Текстура UI не найдена:", name, "(", path, ")", flush=True)
        _UI_TEXTURE_CACHE[name] = None
        return None


def preload_sprites(unit_classes: list[str]) -> dict[str, pygame.Surface | None]:
    """Загружает спрайты заранее (один раз при старте) и кэширует.

    Возвращает словарь класс -> Surface (или None, если не найден).
    """
    result: dict[str, pygame.Surface | None] = {}
    for cls in unit_classes:
        result[cls] = _load_sprite(cls)
    return result


def preload_unit_sprites(unit_keys: list[str]) -> dict[str, pygame.Surface | None]:
    """Загружает спрайты по ключам юнитов заранее (один раз при старте)."""
    result: dict[str, pygame.Surface | None] = {}
    for key in unit_keys:
        result[key] = _load_sprite("", unit_key=key)
    return result


def get_sprite(unit_class: str, unit_key: str | None = None) -> pygame.Surface | None:
    """Вернуть кэшированный спрайт, загружая при первом обращении."""
    return _load_sprite(unit_class, unit_key=unit_key)


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


def draw_unit_sprite(surf, x, y, w, h, unit_class, unit_key=None,
                     tier_color=None, star=1,
                     body_color=None, accent_color=None, race=None):
    """Рисует спрайт юнита из PNG файла с прозрачным фоном.

    Args:
        surf: целевая поверхность pygame.
        x, y: верхний левый угол области рисования.
        w, h: ширина и высота области.
        unit_class: "warrior" | "mage" | "archer" (fallback, если unit_key не найден).
        unit_key: ключ юнита из data/units.json (например, "undead_warrior_skeleton").
        tier_color: цвет окантовки карточки.
        star: звёздность 1..3 — рисует столько же звёздочек.
        body_color / accent_color: игнорируются (используется PNG).
        race: игнорируется (используется PNG).
    """
    # Пытаемся загрузить PNG спрайт (сначала по ключу юнита, потом по классу)
    sprite = _load_sprite(unit_class, unit_key=unit_key)

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
        # Fallback: цветной квадрат с первой буквой имени юнита,
        # чтобы игрок понимал, кто это, вместо пустого прямоугольника.
        _draw_fallback_square(surf, x, y, w, h, unit_class, unit_key)

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

    # Фон под телом — чуть темнее, для объёма
    pygame.draw.rect(surf, tuple(max(0, c - 20) for c in body),
                     (cx - int(10 * s), cy - int(7 * s),
                      int(20 * s), int(16 * s)), border_radius=4)

    if unit_class == "warrior":
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "mage":
        _draw_mage(surf, cx, cy, s, body, accent, DETAIL)
    elif unit_class == "archer":
        _draw_archer(surf, cx, cy, s, body, accent, DETAIL)
    else:
        _draw_warrior(surf, cx, cy, s, body, accent, DETAIL)


def _draw_fallback_square(surf, x, y, w, h, unit_class, unit_key):
    """Рисует цветной квадрат с первой буквой имени юнита (fallback без PNG).

    Используется, когда спрайт не найден — вместо пустого прямоугольника
    игрок видит цветной квадрат с буквой, чтобы понимать, кто это.
    """
    # Определяем букву: из unit_key (ключ юнита) или из unit_class
    display_letter = "?"
    if unit_key:
        # Берём первую букву ключа (например, "warrior_veteran" -> "W")
        display_letter = unit_key.split("_")[0][0].upper()
    elif unit_class:
        display_letter = unit_class[0].upper()

    # Цвет фона по классу
    bg_color = CLASS_FALLBACK_COLOR.get(unit_class, CLASS_FALLBACK_COLOR["warrior"])

    # Заливка квадрата
    pygame.draw.rect(surf, bg_color, (x, y, w, h), border_radius=6)
    # Тёмная обводка
    pygame.draw.rect(surf, (40, 40, 50), (x, y, w, h), width=2, border_radius=6)

    # Буква по центру
    font_size = max(12, int(min(w, h) * 0.5))
    font = pygame.font.Font(None, font_size)
    letter_surf = font.render(display_letter, True, (255, 255, 255))
    letter_rect = letter_surf.get_rect(center=(x + w // 2, y + h // 2))
    surf.blit(letter_surf, letter_rect)


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