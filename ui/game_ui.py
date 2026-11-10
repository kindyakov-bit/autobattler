"""Pygame UI for AutoBattler MVP with real-time animated battles.

Features:
  - Tick-by-tick battle animation for each round
  - Visual effects (damage numbers, death animations)
  - Pause/resume (SPACE), speed control (+/-)
  - Round progress dots at bottom
  - Interactive draft phase (W=Buy S=Sell D=Place F=Remove R=Roll Enter=Done)
"""

import math
import random
import time
import pygame
import sys
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ui.sprites import draw_unit_sprite, draw_item_icon, draw_tooltip, preload_sprites, preload_unit_sprites, load_ui_texture
from game.core.team import build_combat_team
from game.core.player import Player, BENCH_MAX
from game.core.shop import ROLL_COST, accumulate_item_bonuses, ShopError
from game.core.economy import START_HP, pvp_round_damage
from game.core.unit_name import base_name, star_level, star_multiplier


@lru_cache(maxsize=16)
def _cached_font(size: int, bold: bool = False):
    """Шрифт создаётся один раз на (size, bold). Эффекты боя рисуются каждый
    кадр, и пересоздание SysFont на каждый кадр было заметной утечкой CPU."""
    try:
        return pygame.font.SysFont("arial", size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)

# ── Раскладка фазы драфта: единая система масштабирования ──────────────────
# Все размеры вычисляются от констант ниже. Хитбоксы и рисование используют
# одни и те же числа, иначе «невидимые» слоты остаются кликабельными.

# Screen margins
SCREEN_MARGIN = 20

# ── Shop card constants ─────────────────────────────────────────────────
SHOP_Y0 = 85
SHOP_CARD_COUNT = 5          # сколько карточек в витрине
SHOP_CARD_MARGIN = 12        # отступ между карточками
SHOP_CARD_PADDING = 16       # внутренний отступ внутри карточки
SHOP_CARD_ASPECT = 0.75      # высота/ширина карточки (магазин не должен перекрывать скамейку)

# ── Bench (скамейка) constants ──────────────────────────────────────────
BENCH_X0 = 20
BENCH_Y0 = 268
BENCH_COLS = 3          # 3 колонки (было 5)
BENCH_CELL_SIZE = 95    # размер одной ячейки скамейки
BENCH_CELL_MARGIN = 10  # отступ между ячейками скамейки
BENCH_SIDE_PAD = BENCH_X0 - 10  # отступ слотов от краёв рамки (панель начинается с x=10)
BENCH_ROWS = 3          # 3 строки (было 2)
# BENCH_MAX импортируется из game.core.player — единый источник для ядра и UI.

# ── Board (тактическое поле 5×5) constants ──────────────────────────────
BOARD_Y0 = 268
BOARD_COLS = 5
BOARD_ROWS = 5
BOARD_CELL_SIZE = 78         # размер одной ячейки поля
BOARD_CELL_MARGIN = 6        # отступ между ячейками поля

# Sprite fill ratio: спрайт занимает эту долю от размера ячейки (70-80%)
SPRITE_FILL_RATIO = 0.75

# ── Цветовая палитра визуального стиля ─────────────────────────────────
COLOR_PANEL_BG = (30, 40, 55)          # темный фон панелей
COLOR_PANEL_BORDER = (80, 100, 130)    # рамка панелей
COLOR_PANEL_BORDER_GOLD = (255, 215, 0)  # золотая рамка (актив/ховер)
COLOR_CELL_EMPTY = (45, 55, 70)        # пустая ячейка скамейки/поля
COLOR_CELL_EMPTY_BORDER = (90, 110, 140) # рамка пустой ячейки
COLOR_TEAM_PLAYER_CIRCLE = (60, 120, 220)  # круг под ногами союзника
COLOR_TEAM_ENEMY_CIRCLE = (220, 60, 60)    # круг под ногами врага
COLOR_HP_BG = (40, 40, 45)             # фон полоски здоровья
COLOR_HP_BORDER = (200, 200, 200)      # рамка полоски здоровья
COLOR_TEXT_BG = (0, 0, 0, 140)         # полупрозрачный черный для текста

# Цвет рамки по цене юнита — как в TFT/Underlords: сразу видно, что дорого.
# Ключ — цена из data/units.json.
TIER_COLORS = {
    1: (150, 150, 150),   # серый (обычный)
    2: (90, 200, 120),    # зелёный (необычный)
    3: (90, 150, 255),    # синий (редкий)
    4: (255, 215, 0),     # жёлтый (эпический)
    5: (255, 140, 0),     # оранжевый (легендарный)
}
TIER_COLOR_DEFAULT = (150, 150, 150)

# Символ звезды. '★' (U+2605) отсутствует в стандартных шрифтах pygame и
# рисуется квадратом-заглушкой, поэтому используем '*'.
STAR_CHAR = "*"

# Килл-бонус: золото за каждого убитого врага (экономика «фарм на боях»).
KILL_GOLD_PER_UNIT = 1

# ── Геометрия полосы продажи под панелью бенча (вычисляется в _sell_bin_rect) ──



# ── Панель участников матча (игрок + 7 ботов) ──────────────────────────────
# Горизонтальный компактный список в верхней части экрана (под HUD, над
# магазином в драфте и над полем боя). Все 8 участников помещаются без скролла.
PLAYER_LIST_Y = 44          # верхняя панель (под HUD, над магазином/полем боя)
PLAYER_LIST_H = 40          # высота панели (размещается между HUD и магазином/полем боя)
PLAYER_LIST_PAD = 8         # отступ между элементами и краями
PLAYER_LIST_ITEM_H = 24     # высота элемента одного участника
HP_BAR_W = 56               # ширина полоски HP участника
HP_BAR_H = 4

# Цвета индикатора HP (зелёный > 50, жёлтый 25-50, красный < 25).
COLOR_HP_GREEN = (90, 220, 90)
COLOR_HP_YELLOW = (235, 200, 60)
COLOR_HP_RED = (235, 80, 80)
COLOR_TEXT_MUTED = (150, 150, 160)
COLOR_PLAYER_GOLD = (255, 215, 0)
COLOR_DEAD_TEXT = (120, 120, 120)

# Горячая клавиша сводной таблицы.
KEY_LEADERBOARD = pygame.K_TAB


# ── Visual effects system ────────────────────────────────────────────────

class DamageNumber:
    """Floating damage number or text label (MISS / REVIVE / +heal) over a unit."""
    def __init__(self, x, y, amount, color=(255, 100, 50)):
        self.x = x
        self.y = y
        self.color = color
        self.life = 40  # frames to live
        self.max_life = 40
        # Строка — отображаемая метка (MISS/REVIVE/+N), число — урон ("-N").
        if isinstance(amount, str):
            self.amount = 0
            self.label = amount
        else:
            self.amount = int(amount)
            self.label = None

    def update(self):
        self.y -= 1.5
        self.life -= 1
        return self.life > 0

    def draw(self, screen, font):
        text = self.label if self.label is not None else f"-{self.amount}"
        surf = font.render(text, True, self.color)
        # Draw with slight shadow for readability
        sx, sy = int(self.x), int(self.y)
        screen.blit(surf, (sx - 1, sy + 1))
        screen.blit(surf, (sx + 1, sy + 1))
        screen.blit(surf, (sx, sy))


class DeathEffect:
    """Visual effect when a unit dies."""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.life = 30
        self.max_life = 30
        # Spawn particles
        self.particles = []
        for _ in range(8):
            angle = (2 * math.pi / 8) * _ + 0.1
            speed = 1.5 + random.uniform(-0.5, 0.5)
            self.particles.append({
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 1.0,
                'size': 2 + random.randint(0, 3),
                'color': (200, 50, 50),
            })

    def update(self):
        self.life -= 1
        alive = []
        for p in self.particles:
            p['vx'] *= 0.96
            p['vy'] *= 0.96
            if self.life > 0:
                alive.append(p)
        return self.life > 0

    def draw(self, screen):
        alpha = min(1.0, self.life / self.max_life)
        for p in self.particles:
            size = int(p['size'] * alpha)
            if size > 0:
                pygame.draw.circle(screen, p['color'],
                                   (int(self.x + p['vx'] * (30 - self.life)),
                                    int(self.y + p['vy'] * (30 - self.life))),
                                   max(1, size))


class AttackLine:
    """Visual line showing an attack from attacker to target."""
    def __init__(self, x1, y1, x2, y2, color=None):
        self.x1, self.y1 = x1, y1
        self.x2, self.y2 = x2, y2
        self.life = 8
        self.color = color

    def update(self):
        self.life -= 1
        return self.life > 0

    def draw(self, screen):
        alpha = min(1.0, self.life / 8) * 255
        if self.color is not None:
            color = (int(self.color[0] * alpha / 255), int(self.color[1] * alpha / 255), int(self.color[2] * alpha / 255))
        else:
            color = (int(255 * alpha / 255), int(200 * alpha / 255), int(50 * alpha / 255))
        width = max(1, int(3 * alpha / 255))
        pygame.draw.line(screen, color, (self.x1, self.y1), (self.x2, self.y2), width)


class HitParticles:
    """Particle burst on hit impact."""
    def __init__(self, x, y, is_critical=False):
        self.x = x
        self.y = y
        self.life = 20
        self.max_life = 20
        color = (255, 255, 50) if is_critical else (255, 150, 50)
        self.particles = []
        count = 12 if is_critical else 6
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.0, 3.0) if is_critical else random.uniform(0.5, 2.0)
            self.particles.append({
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed,
                'size': random.randint(2, 4) if is_critical else random.randint(1, 3),
                'color': color,
            })

    def update(self):
        self.life -= 1
        alive = []
        for p in self.particles:
            p['vx'] *= 0.92
            p['vy'] *= 0.92
            p['vy'] += 0.15  # slight gravity
            if self.life > 0:
                alive.append(p)
        self.particles = alive
        return self.life > 0

    def draw(self, screen):
        alpha = min(1.0, self.life / self.max_life)
        for p in self.particles:
            size = max(1, int(p['size'] * alpha))
            if size > 0:
                pygame.draw.circle(screen, p['color'],
                                   (int(self.x + p['vx'] * (20 - self.life)),
                                    int(self.y + p['vy'] * (20 - self.life))),
                                   size)


class CriticalEffect:
    """Flash + enlarged damage number for critical hits."""
    def __init__(self, x, y, amount):
        self.x = x
        self.y = y
        self.amount = int(amount)
        self.life = 25
        self.max_life = 25
        self.flash_radius = 0
        self.max_flash_radius = 60

    def update(self):
        self.life -= 1
        self.flash_radius = int(self.max_flash_radius * (1 - self.life / self.max_life))
        return self.life > 0

    def draw(self, screen, font):
        alpha = min(1.0, self.life / self.max_life)
        # Flash ring
        flash_color = (255, int(200 * alpha), int(50 * alpha))
        width = max(1, int(4 * alpha))
        if self.flash_radius > 0:
            pygame.draw.circle(screen, flash_color, (int(self.x), int(self.y)), self.flash_radius, width)
        # Enlarged damage number
        surf = font.render(f"-{self.amount}!", True, (255, 255, 100))
        surf.set_alpha(int(255 * alpha))
        r = surf.get_rect(center=(int(self.x), int(self.y) - 10))
        screen.blit(surf, r)


class AbilityEffect:
    """Visual effect when an ability is cast — expanding ring + particles."""
    
    # Цвета для разных типов способностей
    COLORS = {
        "aoe_damage": ((255, 80, 30), (255, 200, 50)),      # оранжевый/жёлтый (огненный шар)
        "aoe_damage_slow": ((100, 150, 255), (200, 220, 255)),  # синий (замедление)
        "aoe_damage_buff": ((255, 50, 50), (255, 150, 100)),  # красно-оранжевый
        "single_target_critical": ((255, 255, 50), (255, 200, 100)),  # жёлтый/золотой (крит)
        "buff_allies": ((50, 200, 50), (100, 255, 100)),     # зелёный (бафф союзников)
        "heal": ((100, 255, 100), (150, 255, 150)),          # зелёный (исцеление)
        "assassin_teleport": ((200, 50, 200), (255, 100, 255)),  # пурпурный (телепорт убийцы)
    }

    def __init__(self, x, y, ability_name="", effect_type="aoe_damage", color=None):
        self.x = x
        self.y = y
        self.ability_name = ability_name
        self.effect_type = effect_type
        self.max_life = 30
        self.life = self.max_life
        
        # Expanding ring — starts small and grows
        self.ring_max_radius = 70
        self.ring_radius = 5
        
        # Particles — start spread out, fly outward
        self.particles = []
        colors = color or self.COLORS.get(effect_type, ((255, 255, 255), (200, 200, 200)))
        for _ in range(16):
            angle = random.uniform(0, 2 * math.pi)
            speed = 1.5 + random.uniform(0.5, 3.0)
            self.particles.append({
                'angle': angle,
                'speed': speed,
                'size': 2 + random.randint(1, 4),
                'color': random.choice(colors),
            })

    def update(self):
        self.life -= 1
        self.ring_radius = int(self.ring_max_radius * (1 - self.life / self.max_life))
        return self.life > 0

    def draw(self, screen):
        alpha = self.life / self.max_life
        
        # Draw expanding ring — starts small, grows to max
        progress = 1 - (self.life / self.max_life)  # 0→1 as life decreases
        color = self.COLORS.get(self.effect_type, ((255, 255, 255), (200, 200, 200)))[0]
        radius = int(5 + (self.ring_max_radius - 5) * progress)
        if radius > 0:
            pygame.draw.circle(screen, color, (int(self.x), int(self.y)), radius, 
                             max(1, int(3 * alpha)))
        
        # Draw particles — fly outward from center
        for p in self.particles:
            dist = progress * (self.ring_max_radius + 20)
            px = self.x + math.cos(p['angle']) * dist
            py = self.y + math.sin(p['angle']) * dist
            size = max(1, int(p['size'] * alpha))
            if size > 0:
                pygame.draw.circle(screen, p['color'], (int(px), int(py)), size)
        
        # Draw ability name above effect
        if self.life > self.max_life - 5:
            _font = _cached_font(16, bold=True)
            name_surf = _font.render(self.ability_name.upper(), True,
                                  self.COLORS.get(self.effect_type, ((255, 255, 0)))[1])
            r = name_surf.get_rect(center=(int(self.x), int(self.y) - self.ring_radius - 15))
            screen.blit(name_surf, r)

    def _font_render(self, text, bold, color):
        return _cached_font(16, bold=bold).render(text, True, color)


# ── Main UI class ────────────────────────────────────────────────────────

class GameUI:
    """Graphical interface for AutoBattler with real-time battle animation."""

    def __init__(self, width=1200, height=800):
        self.width = width
        self.height = height
        self.running = False
        self.clock = None
        self.font_large = None
        self.font_small = None
        self.font_tiny = None
        self.font_micro = None
        # Скорость анимации — сохраняется между раундами
        self.ticks_per_frame = 1
        self.speed_display_timer = 0
        # Выделение в магазине (для мыши)
        self.selected_shop_idx = None
        self.selected_bench_idx = None
        # Определения юнитов из data/units.json. Инициализируем сразу:
        # крип-раунды (1-3) не заходят в драфт, но уже используют эти данные.
        self.all_units: dict = {}
        self._cost_by_display_name: dict = {}
        # Звук и тряска экрана (можно отключить флагом)
        self.sound_enabled = True
        self.sound = None
        self.shake = 0                # текущая сила тряски в пикселях
        self.shake_rng = random.Random(1234)   # свой RNG, чтобы не жевать seed боя
        self.battle_surface = None    # для тряски рисуем бой на отдельный слой
        # Мышь в драфте
        self.hover_shop_idx = None
        self.hover_item_idx = None
        self.selected_item_idx = None  # предмет, выбранный для применения к юниту
        self.lvl_icon_rect = None      # rect иконки уровня магазина (для клика мышью)
        self.selected_field_cell = None  # (row, col) выбранная клетка тактического поля
        self.drag_bench_idx = None  # индекс юнита наベンче, которого тащим
        self.drag_board_idx = None  # индекс юнита на доске, которого тащим с клетки на клетку
        self.drag_board_orig = None  # исходная (row, col) для возврата, если клетка занята
        self.drag_board_data = None  # данные юнта (имя, звезда, статы) при драге с поля
        self.draft_message = None  # (текст, tick) для показа причины отказа ShopError
        # ── Состояние панели участников / просмотра доски / лидерборда ─────
        self.leaderboard_open = False          # Tab — сводная таблица всех участников
        self.viewing_board = None              # None | ("player",) | ("bot", index)
        self.player_list_rects = []            # [(rect, participant)] для хит-тестов клика
        self._game_instance = None             # ссылка на Game для режима просмотра (run(game))

    def rng_shake(self) -> float:
        """Случайное число 0..1 для тряски."""
        return self.shake_rng.random()

    def display_name(self, key: str) -> str:
        """Русское имя юнита для отрисовки. key — ключ JSON или 'ключ★N'.

        Бой оперирует ключами ('warrior_freshman'), а русские имена лежат
        в data/units.json['units'][key]['name']. Раньше в бой уходил ключ
        как есть — карточки в бою показывали 'warrior_freshman' вместо
        «Новобранец», а tier_color (индекс по русским именам) всегда брал
        дефолт. Плюс звёздность: 'ключ★2' -> «Рыцарь*».
        """
        if not key:
            return "?"
        base = key.split("★")[0]
        ud = self.all_units.get(base)
        ru = ud.get("name", key) if ud else key
        star = self.star_suffix(key)
        return ru + ("" if not star else " " + star)

    def tier_color(self, display_name: str):
        """Цвет рамки по цене юнита. display_name — русское имя из JSON.

        Может прийти со звёздным суффиксом («Рыцарь *») — его отрезаем:
        индекс цен построен по чистым именам, суффикс ломал поиск,
        и звёздные юниты всегда получали дефолтный цвет.
        """
        base = display_name.rsplit(" " + STAR_CHAR, 1)[0] \
            if (" " + STAR_CHAR) in display_name else display_name
        cost = self._cost_by_display_name.get(base)
        if cost is None:
            return TIER_COLOR_DEFAULT
        return TIER_COLORS.get(cost, TIER_COLOR_DEFAULT)

    @staticmethod
    def star_suffix(name: str) -> str:
        """'*','**' по звёздности из имени вида warrior_knight★2."""
        if STAR_CHAR in name:
            tail = name.split(STAR_CHAR, 1)[1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                return STAR_CHAR * (int(digits) - 1)
        if "★" in name:                      # на случай старых данных
            tail = name.split("★", 1)[1]
            digits = "".join(ch for ch in tail if ch.isdigit())
            if digits:
                return STAR_CHAR * (int(digits) - 1)
        return ""

    def fit_text(self, text: str, max_width: int, font=None) -> str:
        """Обрезать текст с '…', чтобы он влезал в фиксированный бокс."""
        font = font or self.font_tiny
        if font.size(text)[0] <= max_width:
            return text
        out = text
        while out and font.size(out + "…")[0] > max_width:
            out = out[:-1]
        return out + "…"

    def _rebuild_cost_index(self):
        """Индекс «русское имя -> цена» для цветовых тиров."""
        self._cost_by_display_name = {
            ud.get("name", key): ud.get("cost", 1)
            for key, ud in self.all_units.items()
        }

    def init(self):
        """Initialize pygame and fonts."""
        pygame.init()
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("AutoBattler MVP - Real-time Battle")
        self.clock = pygame.time.Clock()

        from game.audio import SoundBank
        self.sound = SoundBank(enabled=self.sound_enabled)

        # Отдельный слой боя — только для эффекта тряски
        self.battle_surface = pygame.Surface((self.width, self.height))

        try:
            self.font_large = pygame.font.SysFont("arial", 28, bold=True)
            self.font_small = pygame.font.SysFont("arial", 18)
            self.font_tiny = pygame.font.SysFont("arial", 14)
            # Мельче tiny — для бенча и доски, где слоты узкие
            self.font_micro = pygame.font.SysFont("arial", 11)
        except Exception:
            self.font_large = pygame.font.Font(None, 28)
            self.font_small = pygame.font.Font(None, 18)
            self.font_tiny = pygame.font.Font(None, 14)
            self.font_micro = pygame.font.Font(None, 16)

        # Загружаем спрайты юнитов по ключам (один раз при старте).
        unit_keys = [
            "undead_warrior_skeleton", "demon_mage_imp",
            "warrior_freshman", "archer_ranger", "elf_archer_ranger",
            # Хилеры
            "human_healer_priest", "orc_healer_shaman",
            "demon_healer_blood_priest", "elf_healer_dryad",
            "undead_healer_necromancer",
            # Бафферы
            "human_buffer_bard", "orc_buffer_warchief_advisor",
            "demon_buffer_demon_lord", "elf_buffer_forest_guardian",
            "undead_buffer_ghost_chieftain",
            # Ассасины
            "human_assassin_spy", "orc_assassin_raider",
            "demon_assassin_shadow_killer", "elf_assassin_shadow_walker",
            "undead_assassin_death_stalker",
            # Новые тир 1
            "orc_healer_witch", "elf_healer_spirit",
            "undead_bone_shaman", "demon_fire_totem",
            "human_assassin_knife", "undead_assassin_shadow",
            "orc_archer_slinger", "undead_mage_bone",
            # Новые тир 2
            "demon_buffer_hell_priest", "undead_bone_buff",
            "human_assassin_blade", "orc_assassin_axe",
            "demon_assassin_shadow_blade", "elf_assassin_leaf_blade",
            "undead_assassin_bone_blade",
            # Новые тир 3
            "orc_warrior_axe_bearer", "undead_warrior_bone_guard",
            "demon_archer_fire_bow", "undead_archer_bone_bow",
            "human_assassin_dark_blade", "orc_assassin_war_axe",
            "demon_assassin_shadow_edge", "elf_assassin_wind_blade",
            "undead_assassin_death_edge",
            # Новые тир 4
            "human_warrior_paladin", "human_mage_holy",
            "demon_mage_fire_lord", "human_healer_holy_priest",
            "demon_healer_soul_priest",
            # Новые тир 5
            "orc_warrior_warlord", "elf_warrior_blade_dancer",
            "orc_mage_shadow_shaman", "elf_mage_star_mage",
            "orc_archer_war_bow", "elf_archer_star_bow",
            "orc_healer_war_shaman", "elf_healer_star_druid",
            "undead_buffer_death_aura",
            # Дополнительные
            "elf_warrior_blade_apprentice", "elf_mage_star_apprentice",
            "human_archer_longbow",
        ]
        self._sprite_surfaces = preload_unit_sprites(unit_keys)

        # Обратная карта: русское отображаемое имя -> ключ юнита (для поиска спрайта в бое).
        # unit.name в движке боя содержит русское имя (например, "Скелет"), а не ключ.
        self._name_to_unit_key: dict[str, str] = {}
        for key, ud in self.all_units.items():
            self._name_to_unit_key[ud.get("name", key)] = key

        # Текстуры интерфейса (фон поля, панели)
        self._board_bg = load_ui_texture("board_bg.png")
        self._panel_bg = load_ui_texture("panel_bg.png")

        # Иконки для экрана результатов боя (урон, киллы) — лежат в assets/units/
        from pathlib import Path
        _icons_dir = Path(__file__).parent.parent / "assets" / "units"
        try:
            self._icon_damage = pygame.image.load(str(_icons_dir / "icon_damage.png")).convert_alpha()
        except Exception:
            self._icon_damage = None
        try:
            self._icon_kills = pygame.image.load(str(_icons_dir / "icon_kills.png")).convert_alpha()
        except Exception:
            self._icon_kills = None
        try:
            self._icon_heal = pygame.image.load(str(_icons_dir / "icon_heal.png")).convert_alpha()
        except Exception:
            self._icon_heal = None

    # ── Вспомогательные методы отрисовки ───────────────────────────────

    def draw_rounded_panel(self, surf, x, y, w, h, radius=10,
                           bg_color=COLOR_PANEL_BG,
                           border_color=COLOR_PANEL_BORDER,
                           border_width=2):
        """Рисует панель со скругленными углами и окантовкой."""
        # Фон
        pygame.draw.rect(surf, bg_color, (x, y, w, h), border_radius=radius)
        # Окантовка
        if border_width > 0:
            pygame.draw.rect(surf, border_color, (x, y, w, h),
                             width=border_width, border_radius=radius)

    def draw_textured_rect(self, surf, x, y, w, h, texture_name=None):
        """Рисует текстуру, растянутую на заданный прямоугольник."""
        texture = None
        if texture_name == "board" and self._board_bg is not None:
            texture = self._board_bg
        elif texture_name == "panel" and self._panel_bg is not None:
            texture = self._panel_bg
        if texture is None:
            return
        scaled = pygame.transform.smoothscale(texture, (w, h))
        surf.blit(scaled, (x, y))

    def draw_hp_bar(self, surf, x, y, w, h, hp_pct,
                    fill_color=(60, 200, 60)):
        """Рисует полоску здоровья: темный фон + заливка + белая рамка + текст HP."""
        hp_pct = max(0.0, min(1.0, hp_pct))
        # Фон
        pygame.draw.rect(surf, COLOR_HP_BG, (x, y, w, h), border_radius=2)
        # Заливка
        fill_w = int((w - 2) * hp_pct)
        if fill_w > 0:
            pygame.draw.rect(surf, fill_color, (x + 1, y + 1, fill_w, h - 2),
                             border_radius=1)
        # Белая рамка
        pygame.draw.rect(surf, COLOR_HP_BORDER, (x, y, w, h),
                         width=1, border_radius=2)

    def draw_team_circle(self, surf, cx, cy, radius, is_player=True):
        """Рисует цветной круг под ногами юнита (индикатор принадлежности команды)."""
        color = COLOR_TEAM_PLAYER_CIRCLE if is_player else COLOR_TEAM_ENEMY_CIRCLE
        pygame.draw.circle(surf, color, (cx, cy), radius)
        # Белый обвод圈 для контраста
        pygame.draw.circle(surf, (255, 255, 255), (cx, cy), radius, width=1)

    def draw_text_overlay(self, surf, text, font, x, y, w, h,
                          bg_color=COLOR_TEXT_BG,
                          text_color=(255, 255, 255),
                          align="center"):
        """Рисует текст на полупрозрачной черной подложке."""
        # Создаем поверхность с альфа-каналом для подложки
        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        overlay.fill(bg_color)
        surf.blit(overlay, (x, y))
        # Текст
        text_surf = font.render(text, True, text_color)
        if align == "center":
            tr = text_surf.get_rect(center=(x + w // 2, y + h // 2))
        elif align == "left":
            tr = text_surf.get_rect(midleft=(x + 4, y + h // 2))
        else:
            tr = text_surf.get_rect(center=(x + w // 2, y + h // 2))
        surf.blit(text_surf, tr)

    def play_sound(self, name: str, volume: float = 1.0):
        """Проиграть звук, если звук включён."""
        if self.sound is None:
            return
        self.sound.play(name, volume)

    def add_shake(self, amount: float):
        """Добавить тряску экрана (в пикселях, максимум 14)."""
        self.shake = min(14.0, self.shake + amount)

    def draw_header(self, round_num, gold, is_creep, hp=None, player=None):
        """Draw header with round info, player's match HP, level and XP."""
        status = "CREEP" if is_creep else "PvP"
        if hp is None:
            text = f"Раунд {round_num} [{status}]   Золото: {gold}"
            color = (255, 255, 100)
        else:
            text = (f"Раунд {round_num} [{status}]   Золото: {gold}   "
                    f"HP: {hp}")
            if hp <= 30:
                color = (255, 80, 80)     # опасно
            elif hp <= 60:
                color = (255, 200, 60)    # предупреждение
            else:
                color = (255, 255, 100)
        surf = self.font_small.render(text, True, color)
        self.screen.blit(surf, (16, 8))

        # Уровень и опыт игрока
        if player is not None:
            lvl_text = f"Уровень: {player.level} ({player.xp}/{player.xp_to_next_level} XP)"
            lvl_color = (100, 255, 100) if player.xp >= player.xp_to_next_level else (200, 200, 200)
            lvl_surf = self.font_small.render(lvl_text, True, lvl_color)
            self.screen.blit(lvl_surf, (16, 28))

    def draw_battle_log(self, log, max_lines=6):
        """Draw battle event log on the right side in a semi-transparent panel."""
        panel_w = 330
        panel_h = max_lines * 20 + 16
        panel_x = self.width - panel_w - 12
        panel_y = self.height - panel_h - 48

        # Полупрозрачная тёмная панель со скруглёнными углами
        log_bg = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
        log_bg.fill((20, 25, 35, 200))
        self.screen.blit(log_bg, (panel_x, panel_y))
        pygame.draw.rect(self.screen, (80, 100, 130), (panel_x, panel_y, panel_w, panel_h),
                         width=1, border_radius=6)

        # Заголовок лога
        title = self.font_tiny.render("ЛОГ БОЯ", True, (255, 215, 0))
        self.screen.blit(title, (panel_x + 8, panel_y + 4))

        y_start = panel_y + 24
        for i, event in enumerate(log[-max_lines:]):
            etype = event.get("type", "")
            if etype == "kill":
                text = f"KILL tick {event.get('tick', '?')}"
                color = (255, 100, 100)
            elif etype == "miss":
                text = f"MISS tick {event.get('tick', '?')}"
                color = (180, 180, 180)
            elif etype == "lifesteal":
                heal = event.get("heal", 0)
                text = f"Вампир +{heal:.0f} HP tick {event.get('tick', '?')}"
                color = (100, 255, 100)
            elif etype == "revive":
                text = f"ВОСКРЕШЕНИЕ tick {event.get('tick', '?')}"
                color = (200, 200, 100)
            else:
                dmg = event.get("damage", 0)
                text = f"[{event.get('tick', '?')}] hit: {dmg:.1f} dmg"
                color = (200, 200, 200)

            surf = self.font_tiny.render(text, True, color)
            self.screen.blit(surf, (panel_x + 8, y_start + i * 20))

    def draw_vs(self, cx, cy, target=None):
        """Draw VS separator between teams."""
        surf = target if target is not None else self.screen
        pygame.draw.line(surf, (100, 100, 100),
                        (cx - 3, 60), (cx - 3, self.height - 200), width=2)
        vs_surf = self.font_large.render("VS", True, (255, 255, 255))
        surf.blit(vs_surf, (cx - 28, cy))

    def draw_result(self, winner, ticks):
        """Draw result overlay."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        text = f"WINNER: {winner.upper()} ({ticks} ticks)"
        surf = self.font_large.render(text, True, (255, 255, 100))
        rect = surf.get_rect(center=(self.width // 2, self.height // 2))
        self.screen.blit(surf, rect)

    def draw_battle_stats(self, state):
        """Draw detailed post-battle statistics with styled panel."""
        # Лениво перестроим карту имён → ключей, если all_units уже загружен
        if not self._name_to_unit_key and self.all_units:
            self._name_to_unit_key = {}
            for key, ud in self.all_units.items():
                self._name_to_unit_key[ud.get("name", key)] = key

        # Затемнение всего экрана
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))

        # Центрированная панель со скруглёнными углами и золотой окантовкой
        panel_w = 640
        panel_h = 420
        panel_x = (self.width - panel_w) // 2
        panel_y = (self.height - panel_h) // 2 - 20

        # Фон панели (текстура дерева/камня или сплошной цвет)
        if self._panel_bg is not None:
            scaled = pygame.transform.smoothscale(self._panel_bg, (panel_w, panel_h))
            self.screen.blit(scaled, (panel_x, panel_y))
        else:
            pygame.draw.rect(self.screen, (30, 40, 55), (panel_x, panel_y, panel_w, panel_h),
                             border_radius=14)

        # Золотая окантовка панели
        pygame.draw.rect(self.screen, (255, 215, 0), (panel_x, panel_y, panel_w, panel_h),
                         width=3, border_radius=14)

        cx = self.width // 2
        cy = panel_y + 30

        # Заголовок
        title = self.font_large.render("ИТОГ БОЯ", True, (255, 215, 0))
        self.screen.blit(title, title.get_rect(center=(cx, cy)))
        cy += 40

        # ── Табло урона и киллов по командам ──
        dmg = state.get("dmg_by_team", {})
        kills = state.get("kills_by_team", {})

        teams = list(dmg.keys())
        if len(teams) >= 2:
            t1, t2 = teams[0], teams[1]
        else:
            t1, t2 = "player", "enemy"

        t1_dmg = dmg.get(t1, 0)
        t2_dmg = dmg.get(t2, 0)
        t1_k = kills.get(t1, 0)
        t2_k = kills.get(t2, 0)

        t1_label = "Игрок" if t1 == "player" else t1
        t2_label = "Враг" if t2 == "enemy" else t2

        # Иконка урона слева от заголовка "Урон"
        if self._icon_damage is not None:
            icon_scaled = pygame.transform.smoothscale(self._icon_damage, (24, 24))
            self.screen.blit(icon_scaled, (cx - 145, cy - 14))

        dmg_label_surf = self.font_small.render("Урон", True, (255, 215, 0))
        self.screen.blit(dmg_label_surf, (cx - 115, cy - 8))

        # Левая сторона — Игрок (зелёный)
        t1_label_surf = self.font_small.render(t1_label, True, (100, 255, 100))
        self.screen.blit(t1_label_surf, (cx - 210, cy + 10))
        t1_dmg_surf = self.font_small.render(f"{t1_dmg:.1f}", True, (100, 255, 100))
        self.screen.blit(t1_dmg_surf, (cx - 210, cy + 30))
        t1_k_surf = self.font_small.render(f"Киллы: {t1_k}", True, (100, 255, 100))
        self.screen.blit(t1_k_surf, (cx - 210, cy + 50))

        # Правая сторона — Враг (красный)
        t2_label_surf = self.font_small.render(t2_label, True, (255, 100, 100))
        t2_label_rect = t2_label_surf.get_rect(right=cx + 210, centery=cy + 20)
        self.screen.blit(t2_label_surf, t2_label_rect)
        t2_dmg_surf = self.font_small.render(f"{t2_dmg:.1f}", True, (255, 100, 100))
        t2_dmg_rect = t2_dmg_surf.get_rect(right=cx + 210, centery=cy + 40)
        self.screen.blit(t2_dmg_surf, t2_dmg_rect)
        t2_k_surf = self.font_small.render(f"Киллы: {t2_k}", True, (255, 100, 100))
        t2_k_rect = t2_k_surf.get_rect(right=cx + 210, centery=cy + 60)
        self.screen.blit(t2_k_surf, t2_k_rect)

        # VS посередине
        vs_surf = self.font_large.render("VS", True, (255, 255, 255))
        self.screen.blit(vs_surf, vs_surf.get_rect(center=(cx, cy + 30)))
        cy += 80

        # ── Топ урона ──
        top_d = state.get("top_damage", [])
        if top_d:
            if self._icon_damage is not None:
                icon_scaled = pygame.transform.smoothscale(self._icon_damage, (20, 20))
                self.screen.blit(icon_scaled, (panel_x + 20, cy - 8))
            top_d_label = self.font_small.render("Топ урона:", True, (255, 215, 0))
            self.screen.blit(top_d_label, (panel_x + 50, cy - 6))
            cy += 24
            for name, dmg_val, team, star in top_d:
                # Маленький спрайт юнита (32x32) слева от имени
                base_name = name.split(" ")[0] if " " in name else name
                unit_key = self._name_to_unit_key.get(base_name)
                if unit_key:
                    draw_unit_sprite(
                        self.screen, panel_x + 30, cy - 4, 32, 32,
                        "", unit_key=unit_key, star=1,
                    )
                star_str = STAR_CHAR * star if star > 1 else ""
                line = f"{name}{star_str}  {dmg_val:.1f}"
                surf = self.font_tiny.render(line, True, (220, 220, 220))
                self.screen.blit(surf, (panel_x + 70, cy - 4))
                cy += 24
            cy += 12

        # ── Топ киллов ──
        top_k = state.get("top_kills", [])
        if top_k:
            if self._icon_kills is not None:
                icon_scaled = pygame.transform.smoothscale(self._icon_kills, (20, 20))
                self.screen.blit(icon_scaled, (panel_x + 20, cy - 8))
            top_k_label = self.font_small.render("Топ киллов:", True, (255, 215, 0))
            self.screen.blit(top_k_label, (panel_x + 50, cy - 6))
            cy += 24
            for name, k, team, star in top_k:
                base_name = name.split(" ")[0] if " " in name else name
                unit_key = self._name_to_unit_key.get(base_name)
                if unit_key:
                    draw_unit_sprite(
                        self.screen, panel_x + 30, cy - 4, 32, 32,
                        "", unit_key=unit_key, star=1,
                    )
                star_str = STAR_CHAR * star if star > 1 else ""
                line = f"{name}{star_str}  {k}x"
                surf = self.font_tiny.render(line, True, (220, 220, 220))
                self.screen.blit(surf, (panel_x + 70, cy - 4))
                cy += 24
            cy += 20

        # ── Топ хиления ──
        top_h = state.get("top_heal", [])
        if top_h:
            if self._icon_heal is not None:
                icon_scaled = pygame.transform.smoothscale(self._icon_heal, (20, 20))
                self.screen.blit(icon_scaled, (panel_x + 20, cy - 8))
            top_h_label = self.font_small.render("Топ хиления:", True, (100, 255, 100))
            self.screen.blit(top_h_label, (panel_x + 50, cy - 6))
            cy += 24
            for name, h, team, star in top_h:
                base_name = name.split(" ")[0] if " " in name else name
                unit_key = self._name_to_unit_key.get(base_name)
                if unit_key:
                    draw_unit_sprite(
                        self.screen, panel_x + 30, cy - 4, 32, 32,
                        "", unit_key=unit_key, star=1,
                    )
                star_str = STAR_CHAR * star if star > 1 else ""
                line = f"{name}{star_str}  {h:.1f} HP"
                surf = self.font_tiny.render(line, True, (150, 255, 150))
                self.screen.blit(surf, (panel_x + 70, cy - 4))
                cy += 24
            cy += 20

        # ── Кнопка "Продолжить" ──
        btn_w = 200
        btn_h = 40
        btn_x = cx - btn_w // 2
        btn_y = panel_y + panel_h - 55
        mouse_pos = pygame.mouse.get_pos()
        hover = btn_x <= mouse_pos[0] <= btn_x + btn_w and btn_y <= mouse_pos[1] <= btn_y + btn_h

        btn_color = (60, 160, 40) if not hover else (80, 200, 60)
        pygame.draw.rect(self.screen, btn_color, (btn_x, btn_y, btn_w, btn_h),
                         border_radius=8)
        pygame.draw.rect(self.screen, (255, 215, 0), (btn_x, btn_y, btn_w, btn_h),
                         width=2, border_radius=8)
        btn_text = self.font_small.render("Продолжить", True, (255, 255, 255))
        self.screen.blit(btn_text, btn_text.get_rect(center=(cx, btn_y + btn_h // 2)))

    # ── Участники матча: сбор данных ──────────────────────────────────────

    def _hp_color(self, hp: int, max_hp: int):
        """Цвет индикатора HP: зелёный > 50, жёлтый 25-50, красный < 25."""
        if max_hp <= 0:
            return COLOR_DEAD_TEXT
        pct = hp / max_hp
        if pct > 0.5:
            return COLOR_HP_GREEN
        if pct > 0.25:
            return COLOR_HP_YELLOW
        return COLOR_HP_RED

    def _board_units_for_player(self, player) -> list:
        """Привести board игрока к списку единиц для отображения в доске."""
        out = []
        for u in player.board:
            base = base_name(u["name"])
            star = int(u.get("star", 1))
            ud = self.all_units.get(base, {})
            out.append({
                "name": self.display_name(u["name"]),
                "key": base,
                "star": star,
                "cls": ud.get("class", "warrior"),
                "cost": ud.get("cost", 1),
                "race": ud.get("race", "human"),
            })
        return out

    def _gather_participants(self) -> list:
        """Собрать список участников (игрок + боты) для панели и таблицы.

        Источник данных зависит от режима:
          - интерактивный матч (run_interactive_match): self.match_bots
          - просмотр записи (run(game)): game_instance.bots
        """
        participants = []
        interactive = getattr(self, "match_bots", None) is not None
        game = self._game_instance

        if interactive:
            player = getattr(self, "player", None)
            player_hp = self.player_hp
            bots = self.match_bots
        elif game is not None:
            player = getattr(self, "player", None)
            player_hp = game.player_hp
            bots = game.bots
        else:
            player = getattr(self, "player", None)
            player_hp = getattr(self, "player_hp", START_HP)
            bots = []

        # Игрок — всегда первый (индекс 0).
        if player is not None:
            participants.append({
                "kind": "player", "index": 0, "name": "Player",
                "hp": int(player_hp), "max_hp": START_HP,
                "level": int(getattr(player, "level", 1)),
                "gold": int(getattr(player, "gold", 0)),
                "board_units": self._board_units_for_player(player),
                "bench_count": len(getattr(player, "reserve", [])),
                "dead": player_hp <= 0,
            })
        else:
            participants.append({
                "kind": "player", "index": 0, "name": "Player",
                "hp": int(player_hp), "max_hp": START_HP,
                "level": 1, "gold": 0,
                "board_units": [], "bench_count": 0,
                "dead": player_hp <= 0,
            })

        # Боты.
        for i, bot in enumerate(bots):
            participants.append({
                "kind": "bot", "index": i + 1, "name": bot.get("name", f"Bot {i+1}"),
                "hp": int(bot.get("hp", START_HP)), "max_hp": START_HP,
                "level": int(bot.get("level", 1)),
                "gold": int(bot.get("gold", 0)),
                "board_units": bot.get("board_units", []),
                "bench_count": 0,
                "dead": bot.get("hp", START_HP) <= 0,
            })
        return participants

    def _find_participant(self, participants):
        if self.viewing_board is None:
            return None
        kind, index = self.viewing_board
        for p in participants:
            if p["kind"] == kind and p["index"] == index:
                return p
        return None

    def _is_viewing(self, p) -> bool:
        if self.viewing_board is None:
            return False
        if p["kind"] == "player":
            return self.viewing_board == ("player",)
        return self.viewing_board == ("bot", p["index"])

    def handle_player_list_click(self, mx: int, my: int) -> bool:
        """Клик по панели участников — открыть/закрыть доску участника.
        Возвращает True, если клик обработан 판еллю."""
        for rect, p in self.player_list_rects:
            if rect.collidepoint(mx, my):
                self.leaderboard_open = False
                if p["kind"] == "player":
                    self.viewing_board = ("player", 0)
                else:
                    self.viewing_board = ("bot", p["index"])
                self.play_sound("click")
                return True
        return False

    # ── Отрисовка: панель участников ──────────────────────────────────────

    def draw_player_list_panel(self, participants):
        """Горизонтальная компактная панель всех участников (верх экрана).

        Показывает имя, HP (цветовая индикация), уровень, золото (игрок) и
        статус жив/выбыл. Клик по элементу открывает доску участника.
        """
        n = len(participants)
        if n == 0:
            return
        panel_x = PLAYER_LIST_PAD
        panel_y = PLAYER_LIST_Y
        panel_w = self.width - 2 * PLAYER_LIST_PAD
        panel_h = PLAYER_LIST_H
        self.draw_rounded_panel(
            self.screen, panel_x, panel_y, panel_w, panel_h,
            radius=8, border_width=1,
        )
        # Мелкий шрифт и верхняя строка: иначе заголовок налезает на имя
        # первого участника (имена начинаются с panel_y + 15).
        title = self.font_micro.render("Участники матча", True, (200, 200, 200))
        self.screen.blit(title, (panel_x + 6, panel_y + 2))

        item_w = (panel_w - (n - 1) * PLAYER_LIST_PAD) // n
        mx, my = pygame.mouse.get_pos()
        self.player_list_rects = []

        for i, p in enumerate(participants):
            ix = panel_x + i * (item_w + PLAYER_LIST_PAD)
            rect = pygame.Rect(ix + 4, panel_y + 13, item_w - 8, PLAYER_LIST_ITEM_H)
            hovered = rect.collidepoint(mx, my)
            self.player_list_rects.append((rect, p))
            dead = p["dead"]
            if self._is_viewing(p):
                name_color = (100, 255, 100)
            elif hovered and not dead:
                name_color = (255, 255, 100)
            elif dead:
                name_color = COLOR_DEAD_TEXT
            else:
                name_color = (255, 255, 255)

            # Строка 1: имя (слева) и уровень (справа)
            name_text = self.fit_text(p["name"], item_w - 70, self.font_micro)
            name_surf = self.font_micro.render(name_text, True, name_color)
            self.screen.blit(name_surf, (rect.x + 2, rect.y + 2))
            lvl_surf = self.font_micro.render(f"Lvl {p['level']}", True, name_color)
            self.screen.blit(lvl_surf, (rect.right - lvl_surf.get_width() - 2, rect.y + 2))

            # Строка 2: полоска HP + значение HP + золото игрока
            hp_x = rect.x + 2
            hp_y = rect.y + 12
            hp_pct = p["hp"] / p["max_hp"] if p["max_hp"] else 0.0
            hp_color = self._hp_color(p["hp"], p["max_hp"]) if not dead else COLOR_DEAD_TEXT
            pygame.draw.rect(self.screen, COLOR_HP_BG, (hp_x, hp_y, HP_BAR_W, HP_BAR_H))
            fill_w = max(0, int((HP_BAR_W - 2) * hp_pct))
            if fill_w > 0:
                pygame.draw.rect(self.screen, hp_color, (hp_x + 1, hp_y + 1, fill_w - 2, HP_BAR_H - 2))
            pygame.draw.rect(self.screen, COLOR_HP_BORDER, (hp_x, hp_y, HP_BAR_W, HP_BAR_H), width=1)
            hp_text = self.font_micro.render(f"{int(p['hp'])}/{p['max_hp']}", True, (200, 200, 200))
            self.screen.blit(hp_text, (hp_x + HP_BAR_W + 5, hp_y - 1))

            if p["kind"] == "player" and not dead:
                gold_text = self.font_micro.render(f"${p['gold']}", True, COLOR_PLAYER_GOLD)
                self.screen.blit(gold_text, (rect.right - gold_text.get_width() - 2, hp_y - 1))
            elif dead:
                dead_text = self.font_micro.render("выбыл", True, COLOR_DEAD_TEXT)
                self.screen.blit(dead_text, (rect.right - dead_text.get_width() - 2, hp_y - 1))

    # ── Отрисовка: окно просмотра доски участника ─────────────────────────

    def draw_board_view(self, participant):
        """Модальное окно с доской участника ( юниты, звёзды, тир, уровень )."""
        panel_w = 560
        panel_h = 360
        panel_x = (self.width - panel_w) // 2
        panel_y = (self.height - panel_h) // 2
        self.board_view_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)

        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 210))
        self.screen.blit(overlay, (0, 0))

        self.draw_rounded_panel(
            self.screen, panel_x, panel_y, panel_w, panel_h,
            radius=12, border_width=2, border_color=COLOR_PANEL_BORDER_GOLD,
        )
        title = "Ваша доска" if participant["kind"] == "player" else f"Доска: {participant['name']}"
        title_surf = self.font_large.render(title, True, (255, 215, 0))
        self.screen.blit(title_surf, title_surf.get_rect(center=((panel_x + panel_w) // 2, panel_y + 26)))

        dead = participant["dead"]
        stats_y = panel_y + 62
        lvl_surf = self.font_small.render(
            f"Уровень: {participant['level']}   "
            f"Юнитов на доске: {len(participant['board_units'])}   "
            f"Скамейка: {participant['bench_count']}",
            True, (220, 220, 220))
        self.screen.blit(lvl_surf, (panel_x + 22, stats_y))
        status_color = COLOR_DEAD_TEXT if dead else COLOR_HP_GREEN
        status_surf = self.font_small.render("ВЫБЫВШИЙ" if dead else "ЖИВ", True, status_color)
        self.screen.blit(status_surf, (panel_x + 22, stats_y + 26))

        units = participant["board_units"]
        grid_x = panel_x + 22
        grid_y = stats_y + 70
        cell = 62
        cols = 7
        for idx, u in enumerate(units):
            cx = grid_x + (idx % cols) * (cell + 8)
            cy = grid_y + (idx // cols) * (cell + 8)
            pygame.draw.rect(self.screen, COLOR_CELL_EMPTY, (cx, cy, cell, cell), border_radius=4)
            pygame.draw.rect(self.screen, COLOR_CELL_EMPTY_BORDER, (cx, cy, cell, cell), width=1, border_radius=4)
            tier = self.tier_color(u["name"])
            sprite_size = int(cell * 0.72)
            sx = cx + (cell - sprite_size) // 2
            sy = cy + 5
            draw_unit_sprite(
                self.screen, sx, sy, sprite_size, sprite_size,
                u["cls"], unit_key=u["key"], star=u["star"],
                tier_color=tier, race=u.get("race", "human"),
            )
            name_surf = self.font_micro.render(
                self.fit_text(u["name"], cell - 6, self.font_micro), True, (220, 220, 220))
            self.screen.blit(name_surf, (cx + 3, cy + cell - 14))
        if not units:
            empty = self.font_small.render("Доска пуста", True, COLOR_TEXT_MUTED)
            self.screen.blit(empty, (grid_x, grid_y))

        # Кнопка закрыть
        btn_w = 130
        btn_h = 34
        btn_x = panel_x + panel_w - btn_w - 22
        btn_y = panel_y + panel_h - btn_h - 22
        mx, my = pygame.mouse.get_pos()
        hover = btn_x <= mx <= btn_x + btn_w and btn_y <= my <= btn_y + btn_h
        self.board_close_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)
        btn_color = (60, 160, 40) if not hover else (80, 200, 60)
        pygame.draw.rect(self.screen, btn_color, (btn_x, btn_y, btn_w, btn_h), border_radius=6)
        pygame.draw.rect(self.screen, (255, 215, 0), (btn_x, btn_y, btn_w, btn_h), width=2, border_radius=6)
        btn_text = self.font_small.render("Закрыть", True, (255, 255, 255))
        self.screen.blit(btn_text, btn_text.get_rect(center=(btn_x + btn_w // 2, btn_y + btn_h // 2)))
        esc = self.font_tiny.render("Esc или клик вне окна — закрыть", True, COLOR_TEXT_MUTED)
        self.screen.blit(esc, (panel_x + 22, panel_y + panel_h - 34))

    # ── Отрисовка: сводная таблица (лидерборд) ────────────────────────────

    def draw_leaderboard(self, participants):
        """Полноэкранная сводная таблица, отсортированная по убыванию HP."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 225))
        self.screen.blit(overlay, (0, 0))

        panel_w = 940
        panel_h = 580
        panel_x = (self.width - panel_w) // 2
        panel_y = (self.height - panel_h) // 2
        self.draw_rounded_panel(
            self.screen, panel_x, panel_y, panel_w, panel_h,
            radius=14, border_width=3, border_color=COLOR_PANEL_BORDER_GOLD,
        )
        title = self.font_large.render("СВОДНАЯ ТАБЛИЦА УЧАСТНИКОВ", True, (255, 215, 0))
        self.screen.blit(title, title.get_rect(center=((panel_x + panel_w) // 2, panel_y + 30)))

        ranked = sorted(participants, key=lambda p: p["hp"], reverse=True)
        cols = [
            ("Место", 52),
            ("Имя", 160),
            ("HP", 72),
            ("Уровень", 64),
            ("Юниты", 62),
            ("2★", 42),
            ("3★", 42),
            ("Золото", 62),
            ("Статус", 76),
        ]
        total_w = sum(w for _, w in cols)
        start_x = panel_x + (panel_w - total_w) // 2
        header_y = panel_y + 86
        row_h = 34
        x = start_x
        for label, w in cols:
            surf = self.font_small.render(label, True, (190, 210, 240))
            self.screen.blit(surf, (x + 8, header_y + 7))
            x += w
        pygame.draw.line(self.screen, (80, 100, 130), (start_x, header_y + row_h),
                         (start_x + total_w, header_y + row_h), 1)

        y = header_y + row_h + 10
        for place, p in enumerate(ranked, start=1):
            if y + row_h > panel_y + panel_h - 70:
                break
            x = start_x
            place_color = (255, 215, 0) if place == 1 else (200, 200, 200)
            surf = self.font_small.render(str(place), True, place_color)
            self.screen.blit(surf, (x + 8, y + 9))
            x += 52
            dead = p["dead"]
            name_color = COLOR_DEAD_TEXT if dead else (255, 255, 255)
            surf = self.font_small.render(self.fit_text(p["name"], 150, self.font_small), True, name_color)
            self.screen.blit(surf, (x + 8, y + 9))
            x += 160
            hp_color = self._hp_color(p["hp"], p["max_hp"]) if not dead else COLOR_DEAD_TEXT
            surf = self.font_small.render(f"{p['hp']}/{p['max_hp']}", True, hp_color)
            self.screen.blit(surf, (x + 8, y + 9))
            x += 72
            surf = self.font_small.render(str(p["level"]), True, (220, 220, 220))
            self.screen.blit(surf, (x + 8, y + 9))
            x += 64
            star2 = sum(1 for u in p["board_units"] if u["star"] == 2)
            star3 = sum(1 for u in p["board_units"] if u["star"] == 3)
            surf = self.font_small.render(str(len(p["board_units"])), True, (220, 220, 220))
            self.screen.blit(surf, (x + 8, y + 9))
            x += 62
            surf = self.font_small.render(str(star2), True, (200, 220, 100) if star2 else (100, 100, 100))
            self.screen.blit(surf, (x + 8, y + 9))
            x += 42
            surf = self.font_small.render(str(star3), True, (255, 215, 0) if star3 else (100, 100, 100))
            self.screen.blit(surf, (x + 8, y + 9))
            x += 42
            if p["kind"] == "player":
                surf = self.font_small.render(f"${p['gold']}", True, COLOR_PLAYER_GOLD)
            else:
                surf = self.font_small.render("—", True, COLOR_TEXT_MUTED)
            self.screen.blit(surf, (x + 8, y + 9))
            x += 62
            status = "ВЫБЫЛ" if dead else "ЖИВ"
            surf = self.font_small.render(status, True, COLOR_DEAD_TEXT if dead else COLOR_HP_GREEN)
            self.screen.blit(surf, (x + 8, y + 9))
            y += row_h

        hint = self.font_tiny.render(
            "Обновляется после каждого раунда  |  Tab — открыть/закрыть  |  Esc — закрыть",
            True, COLOR_TEXT_MUTED)
        self.screen.blit(hint, hint.get_rect(center=((panel_x + panel_w) // 2, panel_y + panel_h - 32)))

    def draw_controls(self):
        """Draw control hints at bottom."""
        text = "SPACE=Pause  +/-=Speed  ESC=Quit  |  Tab — таблица участников  |  Клик по участнику — доска"
        surf = self.font_tiny.render(text, True, (150, 150, 150))
        self.screen.blit(surf, (self.width // 2 - 330, self.height - 16))

    def draw_round_progress(self, completed_count, total):
        """Draw round progress dots at bottom."""
        for i in range(total):
            dot_x = self.width // 2 - (total * 15) + i * 30
            if i < completed_count:
                pygame.draw.circle(self.screen, (100, 255, 100),
                                 (dot_x, self.height - 48), 6)
            else:
                pygame.draw.circle(self.screen, (80, 80, 80),
                                 (dot_x, self.height - 48), 6)

    def draw_round_title(self, title):
        """Draw a round title overlay."""
        surf = self.font_large.render(title, True, (255, 255, 100))
        r = surf.get_rect(center=(self.width // 2, self.height // 3))
        self.screen.blit(surf, r)

    def draw_pause_overlay(self):
        """Draw PAUSED overlay."""
        surf = self.font_large.render("PAUSED", True, (255, 255, 100))
        r = surf.get_rect(center=(self.width // 2, self.height // 2))
        self.screen.blit(surf, r)

    def _draw_interactive_draft(self, player, shop_items: list[dict], gold: int,
                                 round_num: int, is_creep: bool, synergy_data: dict,
                                 race_synergy_data: dict | None = None, shop=None):
        """Draw interactive draft phase with keyboard controls."""
        self.screen.fill((20, 30, 40))

        # ── HUD: верхняя панель с плашкой (Раунд, Золото, HP) ──
        hud_x = 20
        hud_y = 8
        hud_w = 320
        hud_h = 34
        self.draw_rounded_panel(
            self.screen, hud_x, hud_y, hud_w, hud_h,
            radius=8, border_width=2,
        )
        status = "CREEP" if is_creep else "PvP"
        header = f"ROUND {round_num} [{status}]"
        header_surf = self.font_small.render(header, True, (255, 215, 0))
        gold_surf = self.font_small.render(f"Золото: {gold}", True, (255, 215, 0))
        # Одна строка: раунд слева, золото справа — иначе две строки не влезают
        # в плашку высотой 34 и налезают друг на друга / выходят за рамку.
        text_y = hud_y + (hud_h - header_surf.get_height()) // 2
        self.screen.blit(header_surf, (hud_x + 10, text_y))
        self.screen.blit(gold_surf, (hud_x + hud_w - 10 - gold_surf.get_width(), text_y))

        # ── SHOP section: динамическая ширина карточек под экран ──
        mx, my = pygame.mouse.get_pos()
        shop_y = SHOP_Y0
        # Вычисляем ширину карточки так, чтобы SHOP_CARD_COUNT карточек
        # идеально вписывались в ширину экрана с отступами.
        shop_area_right = self.width - SCREEN_MARGIN - 130  # место под правую панель
        available_shop_width = shop_area_right - SCREEN_MARGIN
        shop_card_w = max(
            100,
            (available_shop_width - (SHOP_CARD_COUNT - 1) * SHOP_CARD_MARGIN)
            // SHOP_CARD_COUNT,
        )
        # Высота ограничена сверху: ниже SHOP_Y0 + card_h начинается бенч/поле
        # (BENCH_Y0), иначе на широких экранах карточки налезают на нижнюю секцию.
        shop_card_h = min(int(shop_card_w * SHOP_CARD_ASPECT), BENCH_Y0 - SHOP_Y0 - 12)
        shop_step = shop_card_w + SHOP_CARD_MARGIN
        item_x = SCREEN_MARGIN
        slot_color = (60, 80, 100)
        max_shop_slots = min(len(shop_items), SHOP_CARD_COUNT)

        # Правая вертикальная панель: реролл + апгрейд уровня + покупка опыта
        right_panel_x = self.width - 130
        right_panel_y = shop_y
        right_panel_w = 115
        right_panel_h = max(shop_card_h, 170)
        self.draw_textured_rect(self.screen, right_panel_x, right_panel_y,
                                right_panel_w, right_panel_h, texture_name="panel")
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER,
                         (right_panel_x, right_panel_y, right_panel_w, right_panel_h),
                         width=1, border_radius=6)

        # Кнопка реролла магазина (клик мышью)
        reroll_rect = pygame.Rect(right_panel_x + 10, right_panel_y + 8, right_panel_w - 20, 26)
        hover_reroll = reroll_rect.collidepoint(mx, my)
        pygame.draw.rect(self.screen, (80, 120, 160) if not hover_reroll else (120, 160, 200),
                         reroll_rect, border_radius=4)
        rr_surf = self.font_tiny.render(f"Reroll (${ROLL_COST})", True, (255, 255, 255))
        self.screen.blit(rr_surf, rr_surf.get_rect(center=reroll_rect.center))
        if hover_reroll:
            draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                         f"Перебросить витрину магазина\nза {ROLL_COST} золота (клавиша R)", self.font_tiny)

        # Кнопка покупки опыта (Level Up) — под кнопкой реролла
        lvlup_rect = pygame.Rect(right_panel_x + 10, right_panel_y + 40, right_panel_w - 20, 26)
        self.lvlup_rect = lvlup_rect  # сохраняем для обработки клика
        hover_lvlup = lvlup_rect.collidepoint(mx, my)
        can_buy_xp = (shop is not None and self.player is not None
                      and self.player.gold >= Player.XP_COST_GOLD
                      and self.player.level < Player.MAX_LEVEL)
        lvlup_color = (100, 180, 100) if can_buy_xp else (80, 80, 80)
        if hover_lvlup and can_buy_xp:
            lvlup_color = (140, 220, 140)
        pygame.draw.rect(self.screen, lvlup_color, lvlup_rect, border_radius=4)
        lvlup_surf = self.font_tiny.render(f"XP (${Player.XP_COST_GOLD})", True, (255, 255, 255))
        self.screen.blit(lvlup_surf, lvlup_surf.get_rect(center=lvlup_rect.center))
        if hover_lvlup:
            if can_buy_xp:
                draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                             f"Купить {Player.XP_PER_PURCHASE} XP за ${Player.XP_COST_GOLD}\n"
                             f"Уровень: {self.player.level}\n"
                             f"Опыт: {self.player.xp}/{self.player.xp_to_next_level}",
                             self.font_tiny)
            else:
                draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                             "Недостаточно золота или достигнут макс. уровень",
                             self.font_tiny)

        # Уровень игрока — над кнопками (аккуратно, не перекрывая текст)
        if player is not None:
            player_lvl_rect = pygame.Rect(right_panel_x + 10, right_panel_y + 72, right_panel_w - 20, 32)
            hover_pl = player_lvl_rect.collidepoint(mx, my)
            pl_color = (100, 220, 100) if player.xp >= player.xp_to_next_level else (200, 200, 200)
            pygame.draw.rect(self.screen, (60, 80, 100), player_lvl_rect, border_radius=4)
            pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, player_lvl_rect, width=1, border_radius=4)
            pl_surf = self.font_tiny.render(f"Lvl {player.level}", True, pl_color)
            self.screen.blit(pl_surf, pl_surf.get_rect(center=(player_lvl_rect.centerx, player_lvl_rect.y + 9)))
            xp_surf = self.font_tiny.render(f"{player.xp}/{player.xp_to_next_level}", True, pl_color)
            self.screen.blit(xp_surf, xp_surf.get_rect(center=(player_lvl_rect.centerx, player_lvl_rect.y + 23)))

        # Уровень магазина привязан к уровню игрока.
        if shop is not None:
            lvl = shop.level
            # Апгрейд отключен — уровень магазина равен уровню игрока.
            up_cost = None
            up_text = ""
            max_cost = shop.MAX_COST_BY_LEVEL.get(lvl, 1)
            unit_candidates = [u for u, c in shop.unit_costs.items()
                               if c <= max_cost and shop.pool.available(u) > 0]
            unit_chance_pct = int(100 / len(unit_candidates)) if unit_candidates else 0
            item_chance_pct = int(100 / len(shop.item_data)) if shop.item_data else 0
        else:
            lvl = 1
            up_cost = None
            up_text = ""
            unit_chance_pct = 0
            item_chance_pct = 0

        # Цвет иконки по шансу выпадения юнита текущего уровня
        if up_cost is None:
            lvl_color = (150, 200, 150)
        elif unit_chance_pct >= 50:
            lvl_color = (100, 220, 100)
        elif unit_chance_pct >= 25:
            lvl_color = (255, 220, 80)
        else:
            lvl_color = (220, 80, 80)

        # Иконка уровня магазина — круг с цифрой (под кнопками)
        icon_r = 14
        icon_cx = right_panel_x + right_panel_w // 2
        # Ниже блока Lvl/опыт (тот занимает +72..+104), иначе круг налезает на него.
        icon_cy = right_panel_y + 122
        self.lvl_icon_rect = pygame.Rect(icon_cx - icon_r, icon_cy - icon_r,
                                         icon_r * 2, icon_r * 2)
        hover_lvl = self.lvl_icon_rect.collidepoint(mx, my)
        pygame.draw.circle(self.screen, lvl_color, (icon_cx, icon_cy), icon_r)
        pygame.draw.circle(self.screen, (255, 255, 255), (icon_cx, icon_cy), icon_r, width=2)
        lvl_digit = self.font_tiny.render(str(lvl), True, (30, 30, 40))
        self.screen.blit(lvl_digit, lvl_digit.get_rect(center=(icon_cx, icon_cy)))

        # Текст уровня под иконкой
        lvl_text = self.font_tiny.render(f"Shop {lvl}", True, lvl_color)
        self.screen.blit(lvl_text, lvl_text.get_rect(center=(icon_cx, icon_cy + 24)))
        up_surf = self.font_tiny.render(up_text, True, (200, 200, 100))
        self.screen.blit(up_surf, up_surf.get_rect(center=(icon_cx, icon_cy + 38)))

        if hover_lvl:
            tip = f"Уровень магазина {lvl}\nШанс юнита: {unit_chance_pct}%\n"
            tip += "Уровень привязан к игроку\n"
            tip += f"Шанс предмета: {item_chance_pct}%"
            draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                         tip, self.font_tiny)

        # Карточки юнитов в витрине магазина (один цикл — рисование + hover для подсказки)
        shop_hover_tooltip = None
        shop_hover_rect = None
        for i in range(max_shop_slots):
            item = shop_items[i]
            if item is None:
                continue
            x = item_x + i * shop_step
            name_key = item.get("name", "?")
            if not name_key.startswith("ITEM:"):
                name = self.all_units.get(name_key, {}).get("name", name_key)
                cls = self.all_units.get(name_key, {}).get("class", "warrior")
                cost = self.all_units.get(name_key, {}).get("cost", 1)
                ud = self.all_units.get(name_key, {})
            else:
                name = name_key[len("ITEM:"):]
                cls = None
                cost = item.get("cost", 1)
                ud = None

            slot_rect = pygame.Rect(x, shop_y, shop_card_w, shop_card_h)
            hovered = slot_rect.collidepoint(mx, my)
            if hovered:
                self.hover_shop_idx = i
                shop_hover_tooltip = (x, name_key, name, cls, cost, ud, item)
                shop_hover_rect = slot_rect
            else:
                # Если больше не наведен — сбрасываем hover, чтобы подсказка не залипала
                if self.hover_shop_idx == i:
                    self.hover_shop_idx = None

            # Фон карточки без цветной рамки (рамка убрана, выделение — через цвет названия)
            pygame.draw.rect(self.screen, (60, 80, 100), slot_rect, border_radius=6)

            # Название юнита цветом по редкости (цене/тиру)
            name_color = self.tier_color(name) if not name_key.startswith("ITEM:") else (255, 255, 255)
            if hovered:
                name_color = (255, 255, 100)  # подсветка при наведении
            # Имя юнита над картинкой с полупрозрачной подложкой
            self.draw_text_overlay(
                self.screen, name, self.font_tiny,
                x + SHOP_CARD_PADDING, shop_y + shop_card_h - 34,
                shop_card_w - 2 * SHOP_CARD_PADDING, 22,
                align="left",
                text_color=name_color,
            )

            # Силуэт юнита в центре карточки (занимает ~70-80% от размера карточки)
            # Спрайт от меньшей стороны и по центру: при ограниченной высоте
            # карточки иначе силуэт вылезает за верх/низ карточки.
            sprite_size = int(min(shop_card_w, shop_card_h) * SPRITE_FILL_RATIO)
            sprite_x = x + shop_card_w // 2 - sprite_size // 2
            sprite_y = shop_y + (shop_card_h - sprite_size) // 2 - 14
            if name_key.startswith("ITEM:"):
                draw_item_icon(self.screen, x + shop_card_w // 2, shop_y + int(shop_card_h * 0.45),
                               sprite_size, item.get("type", "accessory"))
                # Цена предмета — тоже на подложке
                self.draw_text_overlay(
                    self.screen, f"${cost}", self.font_tiny,
                    x + SHOP_CARD_PADDING, shop_y + shop_card_h - 10,
                    shop_card_w - 2 * SHOP_CARD_PADDING, 16,
                    align="left",
                )
            else:
                draw_unit_sprite(
                    self.screen, sprite_x, sprite_y, sprite_size, sprite_size,
                    cls, unit_key=name_key, star=1,
                    race=ud.get("race", "human") if ud else "human",
                )

            # Стоимость в правом нижнем углу карточки (уже выведена через draw_text_overlay выше)

        # ── BENCH section (юниты в запасе, внизу) ──
        bench_panel_w = self.width // 3 - 40
        bench_cell_w = max(
            50,
            (bench_panel_w - 2 * BENCH_SIDE_PAD - (BENCH_COLS - 1) * BENCH_CELL_MARGIN) // BENCH_COLS,
        )
        bench_cell_h = bench_cell_w  # квадратные ячейки
        # Высота = только контент (заголовок + сетка + отступы), БЕЗ BENCH_Y0:
        # раньше Y0 прибавлялся к высоте и рамка уходила далеко за низ экрана.
        bench_panel_h = 40 + BENCH_ROWS * bench_cell_h + (BENCH_ROWS - 1) * BENCH_CELL_MARGIN + 10
        self.draw_textured_rect(self.screen, 10, BENCH_Y0,
                                bench_panel_w, bench_panel_h, texture_name="panel")
        # Только рамка поверх текстуры (заливка уже текстура)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER,
                         (10, BENCH_Y0, bench_panel_w, bench_panel_h),
                         width=2, border_radius=8)
        bench_title = self.font_small.render(f"BENCH ({len(player.reserve)}/{BENCH_MAX}) — D=place", True, (200, 200, 200))
        self.screen.blit(bench_title, (20, BENCH_Y0 + 8))

        # Рисуем пустые слоты скамейки (сетка 3×3)
        for i in range(BENCH_MAX):
            col = i % BENCH_COLS
            row = i // BENCH_COLS
            bx = BENCH_X0 + col * (bench_cell_w + BENCH_CELL_MARGIN)
            by = BENCH_Y0 + 30 + row * (bench_cell_h + BENCH_CELL_MARGIN)
            empty_rect = pygame.Rect(bx, by, bench_cell_w, bench_cell_h)
            # Пустая ячейка: темный квадрат с тонкой рамкой
            pygame.draw.rect(self.screen, COLOR_CELL_EMPTY, empty_rect, border_radius=4)
            pygame.draw.rect(self.screen, COLOR_CELL_EMPTY_BORDER, empty_rect,
                             width=1, border_radius=4)

        for i, unit_name in enumerate(player.reserve[:BENCH_MAX]):
            # Пропускаем юнт, которого сейчас тащат (рисуем его под курсором)
            if i == self.drag_bench_idx:
                continue
            col = i % BENCH_COLS
            row = i // BENCH_COLS
            x = BENCH_X0 + col * (bench_cell_w + BENCH_CELL_MARGIN)
            y = BENCH_Y0 + 30 + row * (bench_cell_h + BENCH_CELL_MARGIN)
            # Переводим английский ключ на русское имя
            base = base_name(unit_name)
            ru_name = self.all_units.get(base, {}).get("name", base)
            # Звёздность — через '*', иначе глиф '★' рисуется заглушкой
            suffix = self.star_suffix(unit_name)
            display_name = ru_name + (" " + suffix if suffix else "")
            # Подсветка выбранного bench slot — через цвет названия, а не рамку
            cell_rect = pygame.Rect(x, y, bench_cell_w, bench_cell_h)
            pygame.draw.rect(self.screen, slot_color, cell_rect, border_radius=4)
            # Силуэт юнита на скамейке (занимает ~70-80% от ячейки)
            sprite_size = int(bench_cell_w * SPRITE_FILL_RATIO)
            sprite_x = x + (bench_cell_w - sprite_size) // 2
            sprite_y = y + (bench_cell_h - sprite_size) // 2 - 4
            ud = self.all_units.get(base, {})
            draw_unit_sprite(
                self.screen, sprite_x, sprite_y, sprite_size, sprite_size,
                ud.get("class", "warrior"), unit_key=base,
                star=star_level(unit_name),
                race=ud.get("race", "human"),
            )
            # Названиеベンч цветом по редкости
            name_color = self.tier_color(display_name)
            if i == self.selected_bench_idx:
                name_color = (255, 255, 100)
            name_surf = self.font_micro.render(
                self.fit_text(display_name, bench_cell_w - 8, self.font_micro),
                True, name_color)
            self.screen.blit(name_surf, (x + 4, y + bench_cell_h - 16))

        # ── Корзина для продажи под панелью бенча (слева внизу) ──
        sell_rect = self._sell_bin_rect()
        if sell_rect.h >= 32:
            hover_sell = sell_rect.collidepoint(mx, my)
            bin_color = (120, 60, 60) if not hover_sell else (180, 80, 80)
            pygame.draw.rect(self.screen, bin_color, sell_rect, border_radius=6)
            pygame.draw.rect(
                self.screen, (255, 255, 255), sell_rect, width=2, border_radius=6
            )
            sell_text = self.font_tiny.render(
                "Продать — перетащи юнита сюда", True, (255, 255, 255)
            )
            self.screen.blit(
                sell_text,
                sell_text.get_rect(center=sell_rect.center),
            )

        # ── BOARD section — тактическое поле 5×5 ──
        field_x0 = self.width // 3 + 10
        field_y0 = BOARD_Y0
        # Ширина панели поля (одна треть экрана за вычетом отступов)
        field_panel_w = self.width // 3 - 20
        # Вычисляем размер ячейки так, чтобы 5 клеток вписывались в ширину панели
        board_cell_w = max(
            50,
            (field_panel_w - (BOARD_COLS - 1) * BOARD_CELL_MARGIN) // BOARD_COLS,
        )
        board_cell_h = board_cell_w  # квадратные ячейки
        field_w = BOARD_COLS * board_cell_w + (BOARD_COLS - 1) * BOARD_CELL_MARGIN
        # +60 (а не +40): запас под подсказку снизу, иначе она перекрывает
        # последний ряд клеток поля.
        field_h = BOARD_ROWS * board_cell_h + (BOARD_ROWS - 1) * BOARD_CELL_MARGIN + 60

        pygame.draw.rect(self.screen, (40, 70, 40),
                         (field_x0, field_y0, field_w, field_h), border_radius=8)
        # Заголовок поля с динамическим лимитом доски (зависит от уровня игрока)
        board_limit = player.level if hasattr(player, 'level') else 6
        board_title = self.font_small.render(
            f"ПОЛЕ ({len(player.board)}/{board_limit})",
            True, (200, 200, 200))
        self.screen.blit(board_title, (field_x0 + 5, field_y0 + 5))

        mx, my = pygame.mouse.get_pos()

        # Карта занятости клеток: (row, col) -> unit
        occupied = {}
        for unit in player.board:
            r = unit.get("row")
            c = unit.get("col")
            if r is not None and c is not None:
                occupied[(r, c)] = unit

        for r in range(BOARD_ROWS):
            for c in range(BOARD_COLS):
                cx = field_x0 + c * (board_cell_w + BOARD_CELL_MARGIN) + 2
                cy = field_y0 + 30 + r * (board_cell_h + BOARD_CELL_MARGIN) + 2
                cw = board_cell_w - 4
                ch = board_cell_h - 4
                cell_rect = pygame.Rect(cx, cy, cw, ch)
                hovered = cell_rect.collidepoint(mx, my)

                unit = occupied.get((r, c))
                if unit:
                    # Юнит стоит на клетке — без рамки, выделение через цвет названия
                    base = unit["name"].split("★")[0]
                    ud = self.all_units.get(base, {})
                    # Спрайт занимает ~70-80% от ячейки
                    sprite_size = int(board_cell_w * SPRITE_FILL_RATIO)
                    sprite_x = cx + (cw - sprite_size) // 2
                    sprite_y = cy + (ch - sprite_size) // 2 - 2
                    draw_unit_sprite(
                        self.screen, sprite_x, sprite_y, sprite_size, sprite_size,
                        ud.get("class", "warrior"), unit_key=base,
                        star=unit.get("star", 1),
                        race=ud.get("race", "human"),
                    )
                    # Название на поле цветом по редкости
                    base = base_name(unit["name"])
                    ru_name = self.all_units.get(base, {}).get("name", base)
                    suffix = self.star_suffix(unit["name"])
                    display_name = ru_name + (" " + suffix if suffix else "")
                    name_color = self.tier_color(display_name)
                    if (r, c) == self.selected_field_cell:
                        name_color = (255, 255, 100)
                    name_surf = self.font_micro.render(
                        self.fit_text(display_name, cw - 8, self.font_micro),
                        True, name_color)
                    self.screen.blit(name_surf, (cx + 4, cy + ch - 14))
                else:
                    # Пустая клетка — тёмный фон без цветной рамки
                    pygame.draw.rect(self.screen, (30, 50, 30),
                                     cell_rect, border_radius=3)

        # Подсказка под полем
        hint_surf = self.font_tiny.render(
            "Выберите юнта на бенче, затем клик по клетке поля",
            True, (150, 150, 150))
        self.screen.blit(hint_surf, (field_x0 + 5, field_y0 + field_h - 16))

        # Отрисовываем тащущегося юнита поверх всего (драг энд дроп)
        if self.drag_bench_idx is not None and self.drag_bench_idx < len(player.reserve):
            mx, my = pygame.mouse.get_pos()
            unit_name = player.reserve[self.drag_bench_idx]
            base = base_name(unit_name)
            ud = self.all_units.get(base, {})
            sprite_size = int(BENCH_CELL_SIZE * SPRITE_FILL_RATIO)
            draw_unit_sprite(
                self.screen, mx - sprite_size // 2, my - sprite_size // 2,
                sprite_size, sprite_size,
                ud.get("class", "warrior"), unit_key=base,
                tier_color=self.tier_color(unit_name),
                star=star_level(unit_name),
                race=ud.get("race", "human"),
            )

        # Отрисовываем тащущегося юнита с поля на новую клетку
        if self.drag_board_idx is not None and self.drag_board_data is not None:
            mx, my = pygame.mouse.get_pos()
            unit_name = self.drag_board_data.get("name", "?")
            base = base_name(unit_name)
            ud = self.all_units.get(base, {})
            sprite_size = int(BOARD_CELL_SIZE * SPRITE_FILL_RATIO)
            draw_unit_sprite(
                self.screen, mx - sprite_size // 2, my - sprite_size // 2,
                sprite_size, sprite_size,
                ud.get("class", "warrior"), unit_key=base,
                tier_color=self.tier_color(unit_name),
                star=star_level(unit_name),
                race=ud.get("race", "human"),
            )

        # ── Synergy info ────────────────────────────────────────────────
        syn_x = self.width // 3 * 2 + 10
        syn_title = self.font_small.render("SYNERGIES", True, (200, 200, 200))
        self.screen.blit(syn_title, (syn_x, BOARD_Y0 + 8))

        syn_entries = []
        # Классовые синергии (порог активации 2)
        for cls_name in ["warrior", "mage", "archer", "healer", "buffer", "assassin"]:
            try:
                count = player.get_synergy_count(cls_name, self.all_units)
            except TypeError:
                count = player.get_synergy_count(cls_name)
            if count >= 2:
                syn_entries.append((cls_name, count))
        # Расовые синергии (порог активации 2) — включая эльфов
        for race_name in ["human", "orc", "demon", "elf", "undead"]:
            count = player.get_race_count(race_name, self.all_units)
            if count >= 2:
                syn_entries.append((race_name, count))

        syn_hover_name = None  # имя записи синергии под курсором
        for idx, (name, count) in enumerate(syn_entries):
            syn_color = (100, 255, 100) if count >= 2 else (200, 200, 100)
            syn_text = self.font_tiny.render(f"{name}: {count}", True, syn_color)
            syn_rect = syn_text.get_rect(topleft=(syn_x, BOARD_Y0 + 21 + idx * 20))
            syn_rect = syn_rect.inflate(6, 4)
            self.screen.blit(syn_text, syn_rect)
            if syn_rect.collidepoint(mx, my):
                syn_hover_name = name

        # ── Inventory ───────────────────────────────────────────────────
        # Раньше метод _draw_items_section() не вызывался нигде, поэтому
        # купленные предметы было не видно.
        self._draw_items_section(player.items)

        # ── Кнопка начала раунда (клик мышью или Enter) ─────────────────
        start_rect = pygame.Rect(self.width // 2 - 100, self.height - 90, 200, 44)
        hover_start = start_rect.collidepoint(mx, my)
        # Эффект свечения (glow) при наведении
        if hover_start:
            glow_rect = pygame.Rect(start_rect.x - 4, start_rect.y - 4,
                                    start_rect.w + 8, start_rect.h + 8)
            pygame.draw.rect(self.screen, (100, 255, 100, 60), glow_rect, border_radius=10)
        # Основная кнопка с градиентом (темно-зеленый -> ярко-зеленый)
        btn_color = (40, 160, 40) if not hover_start else (60, 200, 60)
        self.draw_rounded_panel(
            self.screen, start_rect.x, start_rect.y, start_rect.w, start_rect.h,
            radius=9, bg_color=btn_color,
            border_color=(200, 230, 200), border_width=2,
        )
        # Градиентный блик сверху
        highlight = pygame.Surface((start_rect.w, start_rect.h // 2), pygame.SRCALPHA)
        highlight.fill((255, 255, 255, 30 if not hover_start else 60))
        self.screen.blit(highlight, (start_rect.x, start_rect.y))
        start_surf = self.font_small.render("Начать раунд (Enter)", True, (255, 255, 255))
        self.screen.blit(start_surf, start_surf.get_rect(center=start_rect.center))

        # ── Controls hint ───────────────────────────────────────────────
        controls = "W=Buy  S=Sell  D=Place  F=Remove  R=Roll  I=Item  A=Apply  Enter=Done  |  Клик: шоп/бенч/доска"
        ctrl_surf = self.font_tiny.render(controls, True, (150, 150, 150))
        self.screen.blit(ctrl_surf, (self.width // 2 - 310, self.height - 30))

        # Сообщение об ошибке магазина (ShopError): показываем ~2 секунды
        if self.draft_message is not None:
            msg_text, t0 = self.draft_message
            if pygame.time.get_ticks() - t0 < 2000:
                msg_surf = self.font_tiny.render(msg_text, True, (255, 80, 80))
                self.screen.blit(msg_surf, (SCREEN_MARGIN, self.height - 55))
            else:
                self.draft_message = None

        # Tooltip магазина рисуем ВСЕМИ остальными элементами, чтобы не
        # перекрывался фоном скамейки, полем и другими панелями.
        if shop_hover_tooltip is not None:
            x, name_key, name, cls, cost, ud, item = shop_hover_tooltip
            if name_key.startswith("ITEM:"):
                desc = item.get("description", "")
                stats = item.get("stats", {})
                stat_labels = {
                    "hp_bonus": "+{} HP",
                    "damage_bonus": "+{} урона",
                    "speed_bonus_pct": "+{}% скор. атаки",
                }
                stat_parts = [
                    stat_labels.get(k, k).format(v)
                    for k, v in stats.items()
                ]
                stats_text = " | ".join(stat_parts)
                tooltip = f"{name}\n${cost}"
                # Если характеристики уже выводятся из stats, description не дублируем
                # (иначе "+400 HP" aparece дважды: из description и из stats)
                if stats_text:
                    tooltip += f"\n{stats_text}"
                elif desc:
                    tooltip += f"\n{desc}"
            else:
                unit_desc = ud.get("description", "")
                lines = [f"{name}\n${cost}", f"Класс: {cls}"]
                if unit_desc:
                    lines.append(unit_desc)
                passive = ud.get("passive")
                if passive:
                    eff = passive.get("effect", {})
                    # Единый формат: +N% тип за союзника (берем из effect, а не из desc,
                    # чтобы не было дублей типа "+10% урона ... урон").
                    name = passive.get("name", "")
                    if "hp_bonus_pct_per_ally" in eff:
                        lines.append(
                            f"Пассивка: {name} — +{eff['hp_bonus_pct_per_ally']}% HP за союзника"
                        )
                    elif "damage_bonus_pct_per_ally" in eff:
                        lines.append(
                            f"Пассивка: {name} — +{eff['damage_bonus_pct_per_ally']}% урона за союзника"
                        )
                    elif "speed_bonus_pct_per_ally" in eff:
                        lines.append(
                            f"Пассивка: {name} — +{eff['speed_bonus_pct_per_ally']}% скорости за союзника"
                        )
                    elif "damage_reduction_pct_per_ally" in eff:
                        lines.append(
                            f"Пассивка: {name} — +{eff['damage_reduction_pct_per_ally']}% защиты за союзника"
                        )
                    else:
                        desc = passive.get("desc", "")
                        lines.append(f"Пассивка: {name} — {desc}")
                active = ud.get("active")
                if active:
                    cd = active.get("cooldown")
                    cd_text = f" (к/д {cd} сек)" if cd else ""
                    # Описание эффекта способности из effect
                    eff = active.get("effect", {})
                    eff_parts = []
                    if "damage" in eff:
                        eff_parts.append(f"урон {eff['damage']}")
                    if "shield" in eff:
                        eff_parts.append(f"щит {eff['shield']}")
                    if "heal" in eff:
                        eff_parts.append(f"исцеление {eff['heal']}")
                    if "damage_per_tick" in eff:
                        eff_parts.append(f"{eff['damage_per_tick']} урона/тик")
                    if "heal_per_tick" in eff:
                        eff_parts.append(f"{eff['heal_per_tick']} лечения/тик")
                    if "bonus_damage" in eff and eff["bonus_damage"] > 0:
                        eff_parts.append(f"+{eff['bonus_damage']} урона")
                    if "bonus_damage_per_ally" in eff:
                        eff_parts.append(f"+{eff['bonus_damage_per_ally']}% урона/союзник")
                    if "damage_bonus_pct" in eff:
                        eff_parts.append(f"+{eff['damage_bonus_pct']}% урона")
                    if "damage_reduction_pct" in eff:
                        eff_parts.append(f"-{eff['damage_reduction_pct']}% урона")
                    if "attack_speed_pct" in eff:
                        eff_parts.append(f"+{eff['attack_speed_pct']}% скорости")
                    if eff.get("targets") == "all_allies":
                        eff_parts.append("всем союзникам")
                    elif eff.get("targets") == "lowest_ally":
                        eff_parts.append("самому слабому союзнику")
                    if eff.get("radius"):
                        eff_parts.append(f"радиус {eff['radius']}")
                    eff_text = f": {', '.join(eff_parts)}" if eff_parts else ""
                    lines.append(
                        f"Активка: {active.get('name', '')}{eff_text}{cd_text}"
                    )
                tooltip = "\n".join(lines)
            draw_tooltip(self.screen, x, shop_y + shop_card_h + 18, tooltip, self.font_tiny)

        # Tooltip синергии — рисуется поверх всего, если курсор на записи
        if syn_hover_name is not None:
            syn_info = self._synergy_info_for(
                syn_hover_name, synergy_data, race_synergy_data
            )
            if syn_info is not None:
                count = player.get_synergy_count(syn_hover_name, self.all_units)
                if count == 0:
                    count = player.get_race_count(syn_hover_name, self.all_units)
                tooltip = self._format_synergy_tooltip(
                    syn_hover_name, count, syn_info, self.all_units
                )
                draw_tooltip(
                    self.screen,
                    syn_x - 280,
                    BOARD_Y0 + 21,
                    tooltip,
                    self.font_tiny,
                )

    def _synergy_info_for(
        self,
        name: str,
        synergy_data: dict,
        race_synergy_data: dict | None,
    ) -> dict | None:
        """Вернуть полную запись синергии (пороги + бонусы) по имени."""
        syn_info = synergy_data.get(name)
        if syn_info:
            return syn_info
        if race_synergy_data:
            return race_synergy_data.get(name)
        return None

    def _format_synergy_bonus(self, bonus: dict) -> str:
        """Единый форматтер бонусов синергии: ключ -> человекочитаемая строка."""
        parts: list[str] = []
        if "hp_bonus_pct" in bonus:
            parts.append(f"+{bonus['hp_bonus_pct']}% HP")
        if "damage_bonus_pct" in bonus:
            parts.append(f"+{bonus['damage_bonus_pct']}% урона")
        if "attack_speed_pct" in bonus:
            parts.append(f"+{bonus['attack_speed_pct']}% скорости атаки")
        if "crit_chance_bonus" in bonus:
            parts.append(f"+{bonus['crit_chance_bonus']}% шанс крита")
        if "mana_per_kill" in bonus:
            parts.append(f"к/д −{bonus['mana_per_kill']} сек за убийство")
        if "evasion_pct" in bonus:
            parts.append(f"уклонение {bonus['evasion_pct']}%")
        if "lifesteal_pct" in bonus:
            parts.append(f"вампиризм {bonus['lifesteal_pct']}%")
        if "damage_reduction_pct" in bonus:
            parts.append(f"−{bonus['damage_reduction_pct']}% получаемого урона")
        if "hp_regen_pct" in bonus:
            parts.append(f"реген {bonus['hp_regen_pct']}% HP")
        if "gold_bonus_pct" in bonus:
            parts.append(f"+{bonus['gold_bonus_pct']}% золота")
        if "unity_damage_pct" in bonus or "unity_hp_pct" in bonus:
            dmg = bonus.get("unity_damage_pct", 0)
            hp = bonus.get("unity_hp_pct", 0)
            parts.append(f"единство: +{dmg}% урона / +{hp}% HP за уникальный класс")
        if "berserker" in bonus:
            b = bonus["berserker"]
            parts.append(
                f"берсерк: +{b['damage_pct'][-1]}% урона/скорости при HP≤{b['hp_thresholds'][0]}%"
            )
        if "revive" in bonus:
            rv = bonus["revive"]
            parts.append(f"восстание: {rv['hp_pct']}% HP, до {rv['max_revives']} раз")
        # Неизвестные ключи — не падать
        for key, value in bonus.items():
            if key not in {
                "hp_bonus_pct",
                "damage_bonus_pct",
                "attack_speed_pct",
                "crit_chance_bonus",
                "mana_per_kill",
                "evasion_pct",
                "lifesteal_pct",
                "damage_reduction_pct",
                "hp_regen_pct",
                "gold_bonus_pct",
                "unity_damage_pct",
                "unity_hp_pct",
                "berserker",
                "revive",
            }:
                parts.append(f"{key}: {value}")
        return "; ".join(parts)

    def _format_synergy_tooltip(
        self, name: str, count: int, syn_info: dict, all_units: dict
    ) -> str:
        """Формирует текст тултипа синергии: имя, активный порог, следующий порог."""
        ud = all_units.get(name, {})
        ru_name = ud.get("name", name)
        lines: list[str] = [f"{ru_name}: {count} на доске"]

        thresholds = sorted(syn_info.get("thresholds", []))
        bonuses = syn_info.get("bonuses", {})

        # Находим активный порог (максимальный ≤ count) и следующий (минимум > count)
        active_key = None
        next_key = None
        for t in thresholds:
            t_str = str(t)
            if t <= count:
                active_key = t_str
            elif t > count and next_key is None:
                next_key = t_str

        if active_key and active_key in bonuses:
            lines.append(
                f"{active_key} (активно): {self._format_synergy_bonus(bonuses[active_key])}"
            )
        if next_key and next_key in bonuses:
            lines.append(
                f"{next_key} (следующий): {self._format_synergy_bonus(bonuses[next_key])}"
            )

        return "\n".join(lines)

    def _draw_items_section(self, items: list[dict]):
        """Draw inventory section with items."""
        if not items:
            return

        inv_x = self.width // 3 * 2 + 10
        inv_y = 260
        mx, my = pygame.mouse.get_pos()
        pygame.draw.rect(self.screen, (50, 40, 70), (inv_x - 10, inv_y - 5, self.width // 3 - 30, len(items) * 35 + 20), border_radius=8)

        inv_title = self.font_small.render("INVENTORY", True, (200, 150, 200))
        self.screen.blit(inv_title, (inv_x, inv_y))
        inv_y += 25

        for i, item in enumerate(items[:4]):
            x = inv_x
            y = inv_y + i * 35
            item_rect = pygame.Rect(x, y, 100, 28)
            hovered = item_rect.collidepoint(mx, my)
            if hovered:
                self.hover_item_idx = i
            # Фон предмета: выделенный или наведенный
            if i == self.selected_item_idx:
                bg_color = (140, 100, 180)
            elif hovered:
                bg_color = (110, 90, 130)
            else:
                bg_color = (80, 60, 100)
            pygame.draw.rect(self.screen, bg_color, item_rect, border_radius=4)

            # Иконка предмета
            item_type = item.get("type", "accessory")
            draw_item_icon(self.screen, x + 14, y + 14, 24, item_type)
            # Название без техпрефикса ITEM:
            raw_name = item.get("name", "?")
            name = raw_name[len("ITEM:"):] if raw_name.startswith("ITEM:") else raw_name
            name_surf = self.font_tiny.render(name, True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 38, y + 4))

            # Tooltip при наведении
            if hovered:
                tooltip = (f"{name}\n${item.get('cost', '?')}  {item_type}\n"
                           f"{item.get('description', '')}\n"
                           "Клик — выбрать, затем клик по юниту на доске")
                draw_tooltip(self.screen, x, y + 34, tooltip, self.font_tiny)

    def _mixed_roll(self, shop, count=5, item_count=3):
        """Смешанный ролл: юниты + предметы.

        Количество карточек юнитов определяется shop.shop_slots.
        """
        unit_items = shop.roll(count=count, player=self.player)
        try:
            item_items = shop.roll_items(count=item_count)
            # Добавляем префикс 'ITEM:' для предметов чтобы различать
        except Exception:
            item_items = []
        
        all_items = list(unit_items) + [
            {
                "name": f"ITEM:{i['name']}",
                "cost": i["cost"],
                "item_key": i.get("item_key", ""),
                "type": (getattr(self, "items_data", {}) or {}).get("items", {}).get(i.get("item_key", ""), {}).get("type", "accessory"),
                "stats": i.get("stats", {}),
                "description": i.get("description", ""),
            }
            for i in item_items
        ]
        return all_items

    def _run_interactive_draft(self, round_num, is_creep, synergy_data, seed, existing_units=None):
        """Run interactive draft phase. Returns (player_units_for_battle, gold_after) or None if user quits."""
        from game.core.shop import Shop
        from game.core.pool import Pool
        from game.core.draft import DraftPhase
        from game.core.player import Player
        import json

        project_root = Path(__file__).parent.parent.resolve()
        with open(project_root / "data" / "units.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Load items
        with open(project_root / "data" / "items.json", "r", encoding="utf-8") as f:
            items_data = json.load(f)

        all_units = data["units"]
        unit_costs = {name: info["cost"] for name, info in all_units.items()}
        self.items_data = items_data  # для типа предметов в _mixed_roll

        rng = random.Random(seed + round_num * 100)
        pool = Pool(unit_costs)
        shop = Shop(pool, unit_costs=unit_costs, item_data=items_data.get("items", {}), rng=rng)
        draft_phase = DraftPhase(shop, all_units)

        self.all_units = all_units  # Для отображения имён на русском в магазине
        self._rebuild_cost_index()
        self._name_to_unit_key = {}
        for key, ud in self.all_units.items():
            self._name_to_unit_key[ud.get("name", key)] = key

        gold = 5 if existing_units is None else existing_units.get("gold", 5)
        player_level = existing_units.get("level", 1) if existing_units else 1
        player_xp = existing_units.get("xp", 0) if existing_units else 0
        player = Player(gold=gold)
        player.level = player_level
        shop.level = player.level
        player.xp = player_xp
        player.xp_to_next_level = player.XP_TABLE.get(player.level, 999999)
        player.max_board = player.level
        player.win_streak = existing_units.get("win_streak", 0) if existing_units else 0
        player.loss_streak = existing_units.get("loss_streak", 0) if existing_units else 0
        self.player = player  # сохраняем для отображения уровня/XP в HUD

        if existing_units is None:
            # First round — игрок начинает без юнитов
            pass
        else:
            # Очищаем доску и скамейку перед восстановлением, иначе юниты
            # с предыдущего раунда остаются и накапливаются/дублируются.
            player.board.clear()
            player.reserve.clear()

            # Восстанавливаем купленных юнитов с ДОСКИ. Они хранятся в формате
            # доски: {"name":..., "star":..., "row":..., "col":...}. Возвращаем
            # их на доску с теми же координатами.
            # возвращаем их на доску. На бенч кладём только перелив, когда
            # доска полна, — иначе один и тот же юнит существует дважды
            # (и на бенче, и на доске) и игрок видит «клоны из ниоткуда».
            units = existing_units.get("units", [])
            for u in units:
                name = u.get("name", "warrior_freshman")
                star = u.get("star", 1)
                # Формат имени внутренний: 'warrior_knight★2' (Shop так парсит).
                # Повторение '★★' без цифры звёздность теряет.
                if star > 1 and "★" not in name:
                    name = f"{name}★{star}"
                name_base = name.split("★")[0]
                unit_data = {"name": name, "star": star}
                if u.get("row") is not None:
                    unit_data["row"] = u.get("row")
                if u.get("col") is not None:
                    unit_data["col"] = u.get("col")
                # Восстанавливаем предметы с юнита, чтобы они не исчезали между раундами
                saved_items = u.get("items", [])
                if saved_items:
                    unit_data["items"] = [dict(it) for it in saved_items]
                # Юнит без позиции на поле — он был на скамейке, кладем туда.
                if u.get("row") is None or u.get("col") is None:
                    player.reserve.append(name)
                elif len(player.board) < player.max_board:
                    player.board.append(unit_data)
                    # Переносим базовые статы, чтобы предметы и бонусы применялись корректно
                    idx = len(player.board) - 1
                    ud = all_units.get(name_base)
                    shop.set_base_stats(
                        player, idx,
                        u.get("hp", ud.get("hp", 100) if ud else 100),
                        u.get("damage", ud.get("damage", 10) if ud else 10),
                        u.get("attack_speed", ud.get("attack_speed", 1.0) if ud else 1.0),
                    )
                    # Пересчитываем бонусы предметов из сохранённых items.
                    # Единая точка accumulate_item_bonuses кладёт ВСЕ статы
                    # (включая speed_bonus_pct) в item_bonuses — их применит
                    # build_combat_team. Раньше скорость писалась в attack_speed
                    # напрямую и в бой не попадала.
                    board_unit = player.board[idx]
                    for it in board_unit.get("items", []):
                        accumulate_item_bonuses(board_unit, it.get("stats", {}))
                else:
                    player.reserve.append(name)

            # Восстанавливаем скамейку (юниты без позиции на поле) между раундами.
            saved_reserve = existing_units.get("reserve", [])
            for name in saved_reserve:
                player.reserve.append(name)

            # Восстанавливаем предметы между раундами (иначе пропадают после каждого боя)
            saved_items = existing_units.get("items", [])
            if saved_items:
                player.items = [dict(it) for it in saved_items]

        # Mixed shop: units + items
        shop_items = self._mixed_roll(shop, count=5, item_count=3)

        while True:
            done_draft = False
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return None

                elif event.type == pygame.KEYDOWN:
                    key = event.key

                    if key == pygame.K_RETURN:
                        # Player done with draft — exit both the event loop and while True
                        done_draft = True
                        break

                    elif key == pygame.K_r:
                        if player.gold >= ROLL_COST:
                            try:
                                # роллим и юнитов, и предметы — иначе после
                                # нажатия R из магазина пропадали предметы
                                new_items = self._mixed_roll(
                                    shop, count=5, item_count=3)
                            except Exception:
                                pass  # ролл не удался — золото НЕ списываем
                            else:
                                player.gold -= ROLL_COST
                                shop_items = new_items

                    elif key == pygame.K_n:
                        try:
                            shop_items = self._mixed_roll(
                                shop, count=5, item_count=3)
                        except Exception:
                            pass

                    elif key == pygame.K_u:
                        # Апгрейд магазина отключен — уровень привязан к игроку.
                        pass

                    elif key == pygame.K_w:
                        # Shop.buy() уже списывает золото — второй раз не вычитаем
                        try:
                            if self.selected_shop_idx is not None and self.selected_shop_idx < len(shop_items):
                                item = shop_items[self.selected_shop_idx]
                                if item is not None and not item.get("name", "").startswith("ITEM:"):
                                    draft_phase.buy_unit(player, item["name"])
                                    self.play_sound("buy")
                                    shop_items[self.selected_shop_idx] = None
                                    self.selected_shop_idx = None
                        except ShopError as e:
                            self.draft_message = (str(e), pygame.time.get_ticks())

                    elif key == pygame.K_s:
                        if player.reserve:
                            try:
                                sold = draft_phase.sell_unit(
                                    player, len(player.reserve) - 1)
                                # Возвращаем цену юнита, а не всегда 1
                                player.gold += self.all_units.get(
                                    sold.split("★")[0], {}).get("cost", 1)
                            except Exception:
                                pass

                    elif key == pygame.K_d:
                        if player.reserve and len(player.board) < player.max_board:
                            try:
                                unit = draft_phase.place_on_board(player, len(player.reserve) - 1)
                                # Найти первую свободную клетку на тактическом поле 5×5
                                occupied = {
                                    (u.get("row"), u.get("col"))
                                    for u in player.board
                                    if u.get("row") is not None and u.get("col") is not None
                                }
                                for r in range(5):
                                    for c in range(5):
                                        if (r, c) not in occupied:
                                            unit["row"] = r
                                            unit["col"] = c
                                            occupied.add((r, c))
                                            break
                                    else:
                                        continue
                                    break
                                # Set base stats for item bonus calculation
                                name_base = unit["name"].split("★")[0]
                                if name_base in all_units:
                                    ud = all_units[name_base]
                                    shop.set_base_stats(player, len(player.board) - 1, 
                                                       int(ud["hp"] * (star_multiplier(unit.get("star", 1)))),
                                                       int(ud["damage"] * (star_multiplier(unit.get("star", 1)))),
                                                       ud["attack_speed"])
                            except Exception:
                                pass

                    elif key == pygame.K_f:
                        if player.board:
                            try:
                                draft_phase.remove_from_board(player, len(player.board) - 1)
                            except Exception:
                                pass

                    elif key == pygame.K_i:
                        # Buy cheapest item (cost ~3)
                        try:
                            available_items = shop.get_available_items()
                            if available_items:
                                # Find cheapest item
                                cheapest = min(available_items, key=lambda k: items_data["items"][k]["cost"])
                                item_info = items_data["items"][cheapest]
                                if player.gold >= item_info["cost"]:
                                    shop.buy_item(player, cheapest)
                        except Exception:
                            pass

                    elif key == pygame.K_a:
                        # Apply last item to last board unit
                        if player.items and player.board:
                            try:
                                shop.apply_item_to_unit(player, len(player.items) - 1, len(player.board) - 1)
                            except Exception:
                                pass

                    elif key == KEY_LEADERBOARD:
                        # Tab — открыть/закрыть сводную таблицу
                        self.leaderboard_open = not self.leaderboard_open
                        self.viewing_board = None

                    elif key == pygame.K_ESCAPE:
                        # Esc — закрыть таблицу или просмотр доски
                        if self.leaderboard_open:
                            self.leaderboard_open = False
                        elif self.viewing_board is not None:
                            self.viewing_board = None

                elif event.type == pygame.MOUSEMOTION:
                    pass  # позиция мыши берется напрямую при отрисовке

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    # ── Панель участников: клик по участнику открывает его доску ──
                    if self.handle_player_list_click(mx, my):
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # Закрыть окно просмотра доски: клик по кнопке «Закрыть» или вне окна
                    if self.viewing_board is not None:
                        if getattr(self, "board_close_rect", None) and self.board_close_rect.collidepoint(mx, my):
                            self.viewing_board = None
                            self.selected_shop_idx = None
                            self.selected_bench_idx = None
                            break
                        elif getattr(self, "board_view_rect", None) and not self.board_view_rect.collidepoint(mx, my):
                            self.viewing_board = None
                            self.selected_shop_idx = None
                            self.selected_bench_idx = None
                            break
                    # ── Кнопка реролла магазина (клик мышью) ──
                    reroll_rect = pygame.Rect(self.width - 120, 93, 95, 26)
                    if reroll_rect.collidepoint(mx, my):
                        if player.gold >= ROLL_COST:
                            player.gold -= ROLL_COST
                            try:
                                shop_items = self._mixed_roll(
                                    shop, count=5, item_count=3)
                                self.play_sound("click")
                            except Exception:
                                pass
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # ── Кнопка покупки опыта (Level Up) ──
                    if (self.lvlup_rect
                            and self.lvlup_rect.collidepoint(mx, my)
                            and shop is not None
                            and self.player is not None):
                        if self.player.buy_xp():
                            # Уровень магазина привязан к уровню игрока: после
                            # покупки опыта синхронизируем shop.level, иначе
                            # ролл идёт по старым шансам до следующего раунда.
                            shop.level = self.player.level
                            self.play_sound("gold")
                            try:
                                shop_items = self._mixed_roll(
                                    shop)
                            except Exception:
                                pass
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # Иконка уровня магазина — клик не ведет к апгрейду (уровень привязан к игроку).
                    if (self.lvl_icon_rect
                            and self.lvl_icon_rect.collidepoint(mx, my)
                            and shop is not None):
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # ── Кнопка начала раунда ──
                    start_rect = pygame.Rect(self.width // 2 - 100,
                                             self.height - 90, 200, 44)
                    if start_rect.collidepoint(mx, my):
                        done_draft = True
                        break
                    # ── Инвентарь: выбрать предмет для применения к юниту ──
                    inv_x = self.width // 3 * 2 + 10
                    inv_y = 285  # 260 + 25 (заголовок)
                    for i in range(min(len(player.items), 4)):
                        item_rect = pygame.Rect(inv_x, inv_y + i * 35, 100, 28)
                        if item_rect.collidepoint(mx, my):
                            self.selected_item_idx = i \
                                if self.selected_item_idx != i else None
                            self.selected_shop_idx = None
                            self.selected_bench_idx = None
                            break
                    else:
                        # ── SHOP items ──
                        for i, item in enumerate(shop_items[:SHOP_CARD_COUNT]):
                            if item is None:
                                continue
                            # Пересчитываем те же размеры карточек, что в отрисовке
                            shop_y = SHOP_Y0
                            shop_area_right = self.width - SCREEN_MARGIN - 130
                            available_shop_width = shop_area_right - SCREEN_MARGIN
                            shop_card_w = max(
                                100,
                                (available_shop_width - (SHOP_CARD_COUNT - 1) * SHOP_CARD_MARGIN)
                                // SHOP_CARD_COUNT,
                            )
                            shop_card_h = min(int(shop_card_w * SHOP_CARD_ASPECT),
                                              BENCH_Y0 - SHOP_Y0 - 12)
                            shop_step = shop_card_w + SHOP_CARD_MARGIN
                            sx = SCREEN_MARGIN + i * shop_step
                            if sx + shop_card_w > self.width - 130:
                                break
                            rect = pygame.Rect(sx, shop_y, shop_card_w, shop_card_h)
                            if rect.collidepoint(mx, my):
                                name = item.get("name", "")
                                if name.startswith("ITEM:"):
                                    # Предмет
                                    item_key = item.get("item_key", "")
                                    try:
                                        shop.buy_item(player, item_key)
                                        shop_items[i] = None  # слот очищается после покупки предмета
                                    except ShopError as e:
                                        self.draft_message = (str(e), pygame.time.get_ticks())
                                else:
                                    # Юнит
                                    try:
                                        draft_phase.buy_unit(player, name)
                                        self.play_sound("buy")
                                        shop_items[i] = None  # слот очищается после покупки
                                        self.selected_shop_idx = None
                                    except ShopError as e:
                                        self.draft_message = (str(e), pygame.time.get_ticks())
                                self.selected_bench_idx = None
                                break
                        else:
                            # ── BENCH — начать перетаскивание (драг энд дроп) ──
                            bench_clicked = False
                            bench_panel_w = self.width // 3 - 40
                            bench_cell_w = max(
                                50,
                                (bench_panel_w - 2 * BENCH_SIDE_PAD - (BENCH_COLS - 1) * BENCH_CELL_MARGIN) // BENCH_COLS,
                            )
                            bench_cell_h = bench_cell_w
                            for i in range(min(len(player.reserve), BENCH_MAX)):
                                col = i % BENCH_COLS
                                row = i // BENCH_COLS
                                bx = BENCH_X0 + col * (bench_cell_w + BENCH_CELL_MARGIN)
                                by = BENCH_Y0 + 30 + row * (bench_cell_h + BENCH_CELL_MARGIN)
                                rect = pygame.Rect(bx, by, bench_cell_w, bench_cell_h)
                                if rect.collidepoint(mx, my):
                                    self.drag_bench_idx = i
                                    self.selected_shop_idx = None
                                    self.selected_field_cell = None
                                    bench_clicked = True
                                    break
                            if not bench_clicked:
                                # ── Тактическое поле 5×5 ──
                                field_x0 = self.width // 3 + 10
                                field_y0 = BOARD_Y0
                                field_panel_w = self.width // 3 - 20
                                board_cell_w = max(
                                    50,
                                    (field_panel_w - (BOARD_COLS - 1) * BOARD_CELL_MARGIN) // BOARD_COLS,
                                )
                                board_cell_h = board_cell_w

                                # Пропускаем заголовок поля (первые 30 пикселей по Y)
                                if my < field_y0 + 30:
                                    pass
                                else:
                                    # Вычисляем ячейку через collidepoint с теми же rect, что и в отрисовке
                                    click_r = click_c = None
                                    for r in range(BOARD_ROWS):
                                        for c in range(BOARD_COLS):
                                            cell_left = field_x0 + c * (board_cell_w + BOARD_CELL_MARGIN) + 2
                                            cell_top = field_y0 + 30 + r * (board_cell_h + BOARD_CELL_MARGIN) + 2
                                            cell_rect = pygame.Rect(
                                                cell_left, cell_top, board_cell_w - 4, board_cell_h - 4
                                            )
                                            if cell_rect.collidepoint(mx, my):
                                                click_r, click_c = r, c
                                                break
                                        if click_r is not None:
                                            break
                                    if click_r is not None:
                                        cell_key = (click_r, click_c)
                                        # Найдём юнит на этой клетке
                                        unit_on_cell = None
                                        unit_idx = None
                                        for i, u in enumerate(player.board):
                                            if u.get("row") == click_r and u.get("col") == click_c:
                                                unit_on_cell = u
                                                unit_idx = i
                                                break

                                        if unit_on_cell is not None:
                                            # На клетке есть юнит
                                            if (self.selected_item_idx is not None
                                                    and self.selected_item_idx < len(player.items)):
                                                # Применить выбранный предмет к юниту
                                                try:
                                                    shop.apply_item_to_unit(
                                                        player, self.selected_item_idx, unit_idx)
                                                    self.play_sound("click")
                                                    self.selected_item_idx = None
                                                except Exception:
                                                    pass
                                            else:
                                                # Начать перетаскивание юнта с этой клетки поля на другую
                                                self.drag_board_idx = unit_idx
                                                self.drag_board_orig = (unit_on_cell.get("row"),
                                                                        unit_on_cell.get("col"))
                                                self.drag_board_data = dict(unit_on_cell)
                                                # Временно убираем с поля (вернём в MOUSEBUTTONUP, если не разместим)
                                                player.board.pop(unit_idx)
                                                self.play_sound("click")
                                            self.selected_bench_idx = None
                                            self.selected_shop_idx = None
                                            self.selected_field_cell = None
                                        else:
                                            # Пустая клетка
                                            if self.selected_bench_idx is not None \
                                                    and self.selected_bench_idx < len(player.reserve) \
                                                    and len(player.board) < player.max_board:
                                                # Поставить выбранного юнита с бенча на клетку
                                                bench_idx = self.selected_bench_idx
                                                unit_name = player.reserve[bench_idx]
                                                # Удалим из бенча
                                                player.reserve.pop(bench_idx)
                                                # Добавим на поле с координатами
                                                new_unit = {
                                                    "name": unit_name,
                                                    "star": star_level(unit_name),
                                                    "row": click_r,
                                                    "col": click_c,
                                                }
                                                name_base = base_name(unit_name)
                                                if name_base in all_units:
                                                    ud = all_units[name_base]
                                                    player.board.append(new_unit)
                                                    shop.set_base_stats(
                                                        player, len(player.board) - 1,
                                                        int(ud["hp"] * (star_multiplier(new_unit.get("star", 1)))),
                                                        int(ud["damage"] * (star_multiplier(new_unit.get("star", 1)))),
                                                        ud["attack_speed"])
                                                self.play_sound("click")
                                            self.selected_field_cell = cell_key
                                            self.selected_bench_idx = None
                                            self.selected_shop_idx = None

                elif event.type == pygame.MOUSEBUTTONUP:
                    mx, my = event.pos
                    # ── Если тащили юнт с벤ча — разместить на клетке поля ──
                    if self.drag_bench_idx is not None:
                        placed = False
                        field_x0 = self.width // 3 + 10
                        field_y0 = BOARD_Y0
                        field_panel_w = self.width // 3 - 20
                        board_cell_w = max(
                            50,
                            (field_panel_w - (BOARD_COLS - 1) * BOARD_CELL_MARGIN) // BOARD_COLS,
                        )
                        board_cell_h = board_cell_w
                        if my >= field_y0 + 30:
                            click_r = click_c = None
                            for r in range(BOARD_ROWS):
                                for c in range(BOARD_COLS):
                                    cell_left = field_x0 + c * (board_cell_w + BOARD_CELL_MARGIN) + 2
                                    cell_top = field_y0 + 30 + r * (board_cell_h + BOARD_CELL_MARGIN) + 2
                                    cell_rect = pygame.Rect(
                                        cell_left, cell_top, board_cell_w - 4, board_cell_h - 4
                                    )
                                    if cell_rect.collidepoint(mx, my):
                                        click_r, click_c = r, c
                                        break
                                if click_r is not None:
                                    break
                            if click_r is not None:
                                occupied = any(
                                    u.get("row") == click_r and u.get("col") == click_c
                                    for u in player.board
                                )
                                if not occupied:
                                    if len(player.board) >= player.max_board:
                                        # Доска полна — юнт остаётся наベンче
                                        pass
                                    else:
                                        bench_idx = self.drag_bench_idx
                                        if bench_idx < len(player.reserve):
                                            unit_name = player.reserve[bench_idx]
                                            player.reserve.pop(bench_idx)
                                            new_unit = {
                                                "name": unit_name,
                                                "star": star_level(unit_name),
                                                "row": click_r,
                                                "col": click_c,
                                            }
                                            name_base = base_name(unit_name)
                                            if name_base in all_units:
                                                ud = all_units[name_base]
                                                player.board.append(new_unit)
                                                shop.set_base_stats(
                                                    player, len(player.board) - 1,
                                                    int(ud["hp"] * (star_multiplier(new_unit.get("star", 1)))),
                                                    int(ud["damage"] * (star_multiplier(new_unit.get("star", 1)))),
                                                    ud["attack_speed"])
                                                self.play_sound("click")
                                                placed = True
                        # Продажа перетаскиванием в корзину (если не разместили на поле)
                        if not placed and self._sell_bin_rect().collidepoint(mx, my):
                            bench_idx = self.drag_bench_idx
                            if bench_idx < len(player.reserve):
                                unit_name = player.reserve[bench_idx]
                                base = base_name(unit_name)
                                cost = self.all_units.get(base, {}).get("cost", 1)
                                try:
                                    draft_phase.sell_unit(player, bench_idx)
                                    player.gold += cost
                                    self.play_sound("gold")
                                except ShopError as e:
                                    self.draft_message = (str(e), pygame.time.get_ticks())
                        self.drag_bench_idx = None

                    # ── Если тащили юнт с клетки поля — разместить на новой клетке ──
                    elif self.drag_board_idx is not None:
                        field_x0 = self.width // 3 + 10
                        field_y0 = BOARD_Y0
                        field_panel_w = self.width // 3 - 20
                        board_cell_w = max(
                            50,
                            (field_panel_w - (BOARD_COLS - 1) * BOARD_CELL_MARGIN) // BOARD_COLS,
                        )
                        board_cell_h = board_cell_w
                        placed = False
                        if my >= field_y0 + 30:
                            click_r = click_c = None
                            for r in range(BOARD_ROWS):
                                for c in range(BOARD_COLS):
                                    cell_left = field_x0 + c * (board_cell_w + BOARD_CELL_MARGIN) + 2
                                    cell_top = field_y0 + 30 + r * (board_cell_h + BOARD_CELL_MARGIN) + 2
                                    cell_rect = pygame.Rect(
                                        cell_left, cell_top, board_cell_w - 4, board_cell_h - 4
                                    )
                                    if cell_rect.collidepoint(mx, my):
                                        click_r, click_c = r, c
                                        break
                                if click_r is not None:
                                    break
                            if click_r is not None:
                                occupied = any(
                                    u.get("row") == click_r and u.get("col") == click_c
                                    for u in player.board
                                )
                                if not occupied:
                                    # Размещаем юнта на новой клетке
                                    unit_data = dict(self.drag_board_data)
                                    unit_data["row"] = click_r
                                    unit_data["col"] = click_c
                                    player.board.append(unit_data)
                                    # Пересчитать статы для нового индекса
                                    idx = len(player.board) - 1
                                    name_base = base_name(unit_data["name"])
                                    if name_base in all_units:
                                        ud = all_units[name_base]
                                        shop.set_base_stats(
                                            player, idx,
                                            int(ud["hp"] * (star_multiplier(unit_data.get("star", 1)))),
                                            int(ud["damage"] * (star_multiplier(unit_data.get("star", 1)))),
                                            ud["attack_speed"])
                                    self.play_sound("click")
                                    placed = True
                        if not placed:
                            # Продажа перетаскиванием в корзину с доски
                            if self._sell_bin_rect().collidepoint(mx, my):
                                idx = self.drag_board_idx
                                if 0 <= idx < len(player.board):
                                    unit_data = player.board[idx]
                                    base = base_name(unit_data.get("name", ""))
                                    cost = self.all_units.get(base, {}).get("cost", 1)
                                    try:
                                        draft_phase.sell_unit(
                                            player, idx, from_board=True
                                        )
                                        player.gold += cost
                                        self.play_sound("gold")
                                    except ShopError as e:
                                        self.draft_message = (
                                            str(e), pygame.time.get_ticks()
                                        )
                                self.drag_board_idx = None
                                self.drag_board_orig = None
                                self.drag_board_data = None
                            else:
                                # Клик на скамейке — вернуть юнта на скамейку (не на доску)
                                bench_cell_w = max(
                                    50,
                                    ((self.width // 3 - 40) - 2 * BENCH_SIDE_PAD
                                     - (BENCH_COLS - 1) * BENCH_CELL_MARGIN)
                                    // BENCH_COLS,
                                )
                                bench_cell_h = bench_cell_w
                                bench_x0 = BENCH_X0
                                bench_y0 = BENCH_Y0 + 30
                                bench_x1 = bench_x0 + BENCH_COLS * bench_cell_w + (BENCH_COLS - 1) * BENCH_CELL_MARGIN
                                bench_y1 = bench_y0 + BENCH_ROWS * bench_cell_h + (BENCH_ROWS - 1) * BENCH_CELL_MARGIN
                                on_bench = (
                                    bench_x0 <= mx <= bench_x1
                                    and bench_y0 <= my <= bench_y1
                                    and len(player.reserve) < player.max_bench
                                )
                                if on_bench:
                                    # Возвращаем на скамейку
                                    unit_name = self.drag_board_data.get("name", "warrior_freshman")
                                    star = self.drag_board_data.get("star", 1)
                                    base = base_name(unit_name)
                                    name_with_star = f"{base}★{star}" if star > 1 else base
                                    # Возвращаем предметы с юнита в инвентарь, иначе они исчезнут
                                    for item in self.drag_board_data.get("items", []):
                                        player.items.append(dict(item))
                                    player.reserve.append(name_with_star)
                                    self.play_sound("click")
                                else:
                                    # Клетка занята или клик вне поля — вернуть на исходную позицию
                                    orig_r, orig_c = self.drag_board_orig or (0, 0)
                                    unit_data = dict(self.drag_board_data)
                                    unit_data["row"] = orig_r
                                    unit_data["col"] = orig_c
                                    player.board.append(unit_data)
                                    idx = len(player.board) - 1
                                    name_base = base_name(unit_data["name"])
                                    if name_base in all_units:
                                        ud = all_units[name_base]
                                        shop.set_base_stats(
                                            player, idx,
                                            int(ud["hp"] * (star_multiplier(unit_data.get("star", 1)))),
                                            int(ud["damage"] * (star_multiplier(unit_data.get("star", 1)))),
                                            ud["attack_speed"])
                        self.drag_board_idx = None
                        self.drag_board_orig = None
                        self.drag_board_data = None

            # Check if player pressed Enter to exit draft
            if done_draft:
                break

            # Draw current state
            self._draw_interactive_draft(
                player=player,
                shop_items=shop_items,
                gold=player.gold,
                round_num=round_num,
                is_creep=is_creep,
                synergy_data=synergy_data,
                race_synergy_data=data.get("race_synergies", {}),
                shop=shop,
            )

            # ── Панель участников (всегда видима в драфте) ──
            participants = self._gather_participants()
            self.draw_player_list_panel(participants)

            # Модальные оверлеи поверх всего
            if self.leaderboard_open:
                self.draw_leaderboard(participants)
            elif self.viewing_board is not None:
                view = self._find_participant(participants)
                if view is not None:
                    self.draw_board_view(view)

            pygame.display.flip()
            self.clock.tick(30)

        # Драфт мог завершиться (Enter/кнопка «Начать раунд») прямо во время
        # перетаскивания юнита с поля: он временно убран с доски. Возвращаем на
        # исходную клетку, иначе юнит потеряется при сборке board_format. Бенч-юнит
        # при драге из reserve не удаляется — просто сбрасываем состояние драга.
        if self.drag_board_idx is not None and self.drag_board_data is not None:
            orig_r, orig_c = self.drag_board_orig or (0, 0)
            unit_data = dict(self.drag_board_data)
            unit_data["row"] = orig_r
            unit_data["col"] = orig_c
            player.board.append(unit_data)
        self.drag_board_idx = None
        self.drag_board_orig = None
        self.drag_board_data = None
        self.drag_bench_idx = None

        # Convert board to battle format — единая сборка через build_combat_team.
        # Вся доска (лимит = player.max_board = уровень игрока), а не первые 6 —
        # иначе на уровнях 7+ юниты сверх шести не участвовали в бою.
        player_units = build_combat_team(
            player.board,
            all_units,
            synergy_data=synergy_data,
            race_synergy_data=data.get("race_synergies", {}),
            race_data=data.get("races", {}),
        )

        # Юниты со скамейки (reserve) НЕ идут в бой — они ждут своей очереди на доске.
        # Только player.board (до 6 юнитов) участвует в синергиях и симуляции.

        if not player_units:
            # Нет юнитов — в бой выходит пустая команда
            player_units = []

        # Возвращаем также резерв (скамейку) и формат доски (для хранения
        # между раундами — иначе статы боя перезапишут composición доски).
        # board_format — это {"name":..., "star":..., "row":..., "col":...}
        # без усиленных статов боя, пригодный для восстановления следующим раундом.
        board_format = [
            {
                "name": u["name"],
                "star": u.get("star", 1),
                "row": u.get("row"),
                "col": u.get("col"),
                # Храним предметы с юнита, иначе они исчезнут при переходе в следующий раунд
                "items": [dict(it) for it in u.get("items", [])],
            }
            for u in player.board
        ]
        return player_units, player.gold, player.items, list(player.reserve), board_format, player.level, player.xp, player.win_streak, player.loss_streak

    def _sell_bin_rect(self) -> pygame.Rect:
        """Геометрия полосы продажи под панелью бенча (левый край, под панелью).

        Вычисление одно и то же для отрисовки и для хит-теста в обработчике дропа.
        """
        bench_panel_w = self.width // 3 - 40
        bench_cell_w = max(
            50,
            (bench_panel_w - 2 * BENCH_SIDE_PAD - (BENCH_COLS - 1) * BENCH_CELL_MARGIN)
            // BENCH_COLS,
        )
        bench_cell_h = bench_cell_w
        bench_panel_h = (
            40
            + BENCH_ROWS * bench_cell_h
            + (BENCH_ROWS - 1) * BENCH_CELL_MARGIN
            + 10
        )
        y = BENCH_Y0 + bench_panel_h + 6
        w = bench_panel_w
        h = min(44, (self.height - 90) - y - 6)
        return pygame.Rect(10, y, w, h)

    def _get_unit_positions(self, player_units, enemy_units):
        """Позиции на едином тактическом поле 10×5: игрок cols 0-4, враг cols 5-9."""
        cell_w = 100
        cell_h = 80
        offset_x = 60
        offset_y = 100
        positions = {}

        for u in player_units:
            x = offset_x + u.col * cell_w
            y = offset_y + u.row * cell_h
            positions[u] = (x + cell_w // 2, y + cell_h // 2)

        for u in enemy_units:
            # Враг occupeт колонки 5-9 на той же единой сетке
            x = offset_x + u.col * cell_w
            y = offset_y + u.row * cell_h
            positions[u] = (x + cell_w // 2, y + cell_h // 2)

        return positions

    def _draw_battle_scene(self, sim, effects, frame_idx=0, target=None):
        """Draw the current state of a battle with visual effects.

        Args:
            sim: BattleSimulator instance
            effects: dict with visual effect lists (populated during drawing)
            frame_idx: index into sim._tick_history (0 = initial state)
            target: surface to draw on (default self.screen). Нужен для тряски.
        """
        PLAYER_COLOR = (40, 80, 160)
        ENEMY_COLOR = (160, 50, 50)
        surf = target if target is not None else self.screen

        # Лениво перестроим карту имён → ключей, если all_units уже загружен,
        # а карта ещё пуста (init() может вызван до установки all_units).
        if not self._name_to_unit_key and self.all_units:
            self._name_to_unit_key = {}
            for key, ud in self.all_units.items():
                self._name_to_unit_key[ud.get("name", key)] = key

        # Restore state from snapshot at the given frame index
        if frame_idx > 0 and frame_idx <= len(sim._tick_history):
            sim.restore_from_snapshot(sim._tick_history[frame_idx - 1])

        player_units = list(sim.teams.values())[0] if sim.teams else []
        enemy_units = list(sim.teams.values())[1] if len(sim.teams) > 1 else []

        # Get positions for each unit
        positions = self._get_unit_positions(player_units, enemy_units)

        # Размеры ячейки поля боя (единая сетка 10×5)
        cell_w = 100
        cell_h = 80
        offset_x = 60
        offset_y = 100

        # Разделительная линия и VS на стыке между сетками (между col 4 и col 5)
        vs_x = offset_x + 5 * cell_w
        self.draw_vs(vs_x, offset_y + cell_h // 2, target=surf)

        # Бейдж активной расовой синергии для каждой команды
        for team_idx, (team_name, team_units) in enumerate(sim.teams.items()):
            race_counts = {}
            for u in team_units:
                r = getattr(u, "race", "")
                race_counts[r] = race_counts.get(r, 0) + 1
            # Найти расу с максимальным числом и активный порог
            best_race = None
            best_count = 0
            for r, c in race_counts.items():
                if c > best_count:
                    best_count = c
                    best_race = r
            if best_race and best_count >= 2:
                syn_info = sim.race_synergy_data.get(best_race, {})
                thresholds = syn_info.get("thresholds", [])
                bonuses = syn_info.get("bonuses", {})
                active_level = None
                for th in sorted(thresholds):
                    if best_count >= th:
                        active_level = th
                if active_level:
                    bonus = bonuses.get(str(active_level), {})
                    desc_parts = []
                    if "evasion_pct" in bonus:
                        desc_parts.append(f"Уклонение {bonus['evasion_pct']}%")
                    if "lifesteal_pct" in bonus:
                        desc_parts.append(f"Вампиризм {bonus['lifesteal_pct']}%")
                    if "berserker" in bonus:
                        b = bonus["berserker"]
                        desc_parts.append(f"Берсерк {b['damage_pct'][-1]}% урона")
                    if "revive" in bonus:
                        rv = bonus["revive"]
                        desc_parts.append(f"Восстание {rv['hp_pct']}%/{rv['max_revives']}")
                    if "unity_damage_pct" in bonus:
                        desc_parts.append(f"Единство +{bonus['unity_damage_pct']}% урон/HP")
                    if desc_parts:
                        badge_text = f"{best_race.upper()} {active_level}: " + ", ".join(desc_parts)
                        badge_y = offset_y - 28 - team_idx * 20
                        badge_x = vs_x + (team_idx - 0) * 200
                        self.draw_text_overlay(
                            surf, badge_text, self.font_tiny,
                            badge_x, badge_y, 300, 14,
                            align="center", text_color=(255, 215, 0),
                        )


        # Фон игрового поля — единая текстура камня на всю ширину (10 колонок)
        board_w = 10 * cell_w
        board_h = 5 * cell_h
        self.draw_textured_rect(surf, offset_x, offset_y, board_w, board_h, texture_name="board")

        # Draw attack lines first (behind units)
        for line in list(effects.get("lines", [])):
            if line.update():
                line.draw(surf)
            else:
                effects["lines"].remove(line)

        # Draw 10×5 grid lines for the unified tactical field
        grid_color = (60, 60, 80)
        # 11 вертикальных линий (cols 0-10)
        for c in range(11):
            x = offset_x + c * cell_w
            pygame.draw.line(surf, grid_color, (x, offset_y), (x, offset_y + 5 * cell_h), 1)
        # 6 горизонтальных линий (rows 0-5)
        for r in range(6):
            y = offset_y + r * cell_h
            pygame.draw.line(surf, grid_color, (offset_x, y), (offset_x + 10 * cell_w, y), 1)

        # Draw each unit
        for unit in player_units:
            if not unit.alive:
                continue  # dead units are drawn as faded
            try:
                x, y = positions[unit]
            except KeyError:
                continue  # юнит не найден в позициях (погиб в этой же тике)
            cls_name = getattr(unit, "unit_class", "warrior")
            base_name = unit.name.split("★")[0] if hasattr(unit, "name") else None
            unit_key = self._name_to_unit_key.get(base_name, base_name) if base_name else None
            # Вёрстка внутри ячейки: имя сверху, спрайт по центру, HP-бар внизу.
            sprite_size = 46
            cell_x = x - cell_w // 2
            cell_y = y - cell_h // 2
            # Имя юнита в самом верху ячейки
            name_text = self.display_name(unit.name)
            self.draw_text_overlay(
                surf, name_text, self.font_tiny,
                cell_x + 2, cell_y + 2, cell_w - 4, 16,
                align="center",
            )
            # Спрайт центрирован по горизонтали, размещён в верхней-середине ячейки
            sprite_x = cell_x + (cell_w - sprite_size) // 2
            sprite_y = cell_y + 20
            draw_unit_sprite(
                surf, sprite_x, sprite_y, sprite_size, sprite_size,
                cls_name, unit_key=unit_key,
                star=getattr(unit, "star", 1),
                race=getattr(unit, "race", "human"),
            )
            # Полоска здоровья в самом низу ячейки
            try:
                hp_pct = unit.hp / max(unit.max_hp, 1)
            except Exception:
                hp_pct = 0.0
            bar_w = 56
            bar_h = 4
            bar_x = x - bar_w // 2
            bar_y = cell_y + cell_h - 10
            self.draw_hp_bar(surf, bar_x, bar_y, bar_w, bar_h, hp_pct,
                             fill_color=(60, 200, 60))
            # Текст HP над полоской
            hp_text = f"{int(unit.hp)}/{int(unit.max_hp)}"
            self.draw_text_overlay(
                surf, hp_text, self.font_tiny,
                bar_x, bar_y - 10, bar_w, 10,
                align="center",
            )
            # Берсерк (орки): иконка ярости при HP≤порога
            berserker = getattr(unit, "berserker", None)
            if berserker:
                hp_pct_now = unit.hp / max(unit.max_hp, 1) * 100.0
                thresholds = sorted(berserker.get("hp_thresholds", []))
                if thresholds and hp_pct_now <= thresholds[-1]:
                    self.draw_text_overlay(
                        surf, "ЯРОСТЬ", self.font_tiny,
                        cell_x + 2, cell_y + cell_h - 34, cell_w - 4, 10,
                        align="center", text_color=(255, 80, 80),
                    )

        for unit in enemy_units:
            if not unit.alive:
                continue
            try:
                x, y = positions[unit]
            except KeyError:
                continue
            cls_name = getattr(unit, "unit_class", "warrior")
            base_name = unit.name.split("★")[0] if hasattr(unit, "name") else None
            unit_key = self._name_to_unit_key.get(base_name, base_name) if base_name else None
            # Вёрстка внутри ячейки: имя сверху, спрайт по центру, HP-бар внизу.
            sprite_size = 46
            cell_x = x - cell_w // 2
            cell_y = y - cell_h // 2
            # Имя юнита в самом верху ячейки
            name_text = self.display_name(unit.name)
            self.draw_text_overlay(
                surf, name_text, self.font_tiny,
                cell_x + 2, cell_y + 2, cell_w - 4, 16,
                align="center",
            )
            # Спрайт центрирован по горизонтали, размещён в верхней-середине ячейки
            sprite_x = cell_x + (cell_w - sprite_size) // 2
            sprite_y = cell_y + 20
            draw_unit_sprite(
                surf, sprite_x, sprite_y, sprite_size, sprite_size,
                cls_name, unit_key=unit_key,
                star=getattr(unit, "star", 1),
                race=getattr(unit, "race", "human"),
            )
            # Полоска здоровья в самом низу ячейки
            try:
                hp_pct = unit.hp / max(unit.max_hp, 1)
            except Exception:
                hp_pct = 0.0
            bar_w = 56
            bar_h = 4
            bar_x = x - bar_w // 2
            bar_y = cell_y + cell_h - 10
            self.draw_hp_bar(surf, bar_x, bar_y, bar_w, bar_h, hp_pct,
                             fill_color=(200, 60, 60))
            # Текст HP над полоской
            hp_text = f"{int(unit.hp)}/{int(unit.max_hp)}"
            self.draw_text_overlay(
                surf, hp_text, self.font_tiny,
                bar_x, bar_y - 10, bar_w, 10,
                align="center",
            )
            # Берсерк (орки): иконка ярости при HP≤порога
            berserker = getattr(unit, "berserker", None)
            if berserker:
                hp_pct_now = unit.hp / max(unit.max_hp, 1) * 100.0
                thresholds = sorted(berserker.get("hp_thresholds", []))
                if thresholds and hp_pct_now <= thresholds[-1]:
                    self.draw_text_overlay(
                        surf, "ЯРОСТЬ", self.font_tiny,
                        cell_x + 2, cell_y + cell_h - 34, cell_w - 4, 10,
                        align="center", text_color=(255, 80, 80),
                    )

        # Draw dead units (faded)
        for unit in player_units + enemy_units:
            if unit.alive:
                continue
            try:
                x, y = positions[unit]
            except KeyError:
                continue
            cls_name = getattr(unit, "unit_class", "warrior")
            base_name = unit.name.split("★")[0] if hasattr(unit, "name") else None
            unit_key = self._name_to_unit_key.get(base_name, base_name) if base_name else None
            # Вёрстка внутри ячейки (мертвый юнит): имя сверху, спрайт посередине, HP внизу.
            sprite_size = 46
            cell_x = x - cell_w // 2
            cell_y = y - cell_h // 2
            # Имя юнита в самом верху ячейки
            name_text = self.display_name(unit.name)
            self.draw_text_overlay(
                surf, name_text, self.font_tiny,
                cell_x + 2, cell_y + 2, cell_w - 4, 16,
                align="center",
            )
            # Спрайт с затемнением
            sprite_x = cell_x + (cell_w - sprite_size) // 2
            sprite_y = cell_y + 20
            draw_unit_sprite(
                surf, sprite_x, sprite_y, sprite_size, sprite_size,
                cls_name, unit_key=unit_key,
                tier_color=(60, 60, 70),
                star=getattr(unit, "star", 1),
                race=getattr(unit, "race", "human"),
            )
            # Затемняющий оверлей
            dead_overlay = pygame.Surface((sprite_size, sprite_size), pygame.SRCALPHA)
            dead_overlay.fill((0, 0, 0, 160))
            surf.blit(dead_overlay, (sprite_x, sprite_y))
            # HP bar пустая внизу ячейки
            hp_pct = 0.0
            bar_w = 56
            bar_h = 4
            bar_x = x - bar_w // 2
            bar_y = cell_y + cell_h - 10
            self.draw_hp_bar(surf, bar_x, bar_y, bar_w, bar_h, hp_pct,
                             fill_color=(100, 100, 100))

        # Draw damage numbers on top of everything
        for dn in list(effects.get("damage_numbers", [])):
            if dn.update():
                dn.draw(surf, self.font_tiny)
            else:
                effects["damage_numbers"].remove(dn)

        # Draw death effects
        for de in list(effects.get("death_effects", [])):
            if de.update():
                de.draw(surf)
            else:
                effects["death_effects"].remove(de)

        # Draw ability effects (expanding rings + particles)
        for ae in list(effects.get("ability_effects", [])):
            if ae.update():
                ae.draw(surf)
            else:
                effects["ability_effects"].remove(ae)

        # Draw hit impact particles
        for hp in list(effects.get("hit_particles", [])):
            if hp.update():
                hp.draw(surf)
            else:
                effects["hit_particles"].remove(hp)

        # Draw critical hit flash + enlarged number
        for ce in list(effects.get("critical_effects", [])):
            if ce.update():
                ce.draw(surf, self.font_tiny)
            else:
                effects["critical_effects"].remove(ce)

    def _generate_battle_effects(self, sim, tick_count, last_processed_tick, effects):
        """Создать визуальные эффекты для событий, произошедших между кадрами.

        Единая реализация для run() и _animate_battle(): раньше логика была
        скопирована дважды, и в копии для _animate_battle не было частиц
        от попаданий и крит-вспышек — в игре они не появлялись.

        Args:
            sim: BattleSimulator
            tick_count: текущий тик анимации
            last_processed_tick: последний обработанный тик (-1 в начале)
            effects: dict со списками эффектов (мутируется)
        """
        # Движок допускает любые имена команд, поэтому берём первые две
        # по порядку: первая — слева, вторая — справа.
        # (Раньше здесь был хардкод "player"/"enemy", который молча ломался
        # на симуляторах с другими именами.)
        teams = [u for u in sim.teams.values()]
        player_units = list(teams[0]) if len(teams) > 0 else []
        enemy_units = list(teams[1]) if len(teams) > 1 else []
        positions = self._get_unit_positions(player_units, enemy_units)

        def find_unit(uid):
            for u in player_units + enemy_units:
                if u.unit_id == uid:
                    return u
            return None

        # ── Линии атак: только события, новые с прошлого кадра ──────────
        for evt in sim.get_attack_events(up_to_tick=tick_count):
            if not (last_processed_tick < evt.get("tick", 0) <= tick_count):
                continue
            attacker = find_unit(evt.get("attacker_id"))
            if not attacker:
                continue
            for target_id in evt.get("targets", []):
                target = find_unit(target_id)
                if not target:
                    continue
                a_pos = positions.get(attacker)
                t_pos = positions.get(target)
                if a_pos and t_pos:
                    line_color = (255, 220, 60) if evt.get("is_critical") else (200, 200, 200)
                    effects["lines"].append(
                        AttackLine(a_pos[0], a_pos[1], t_pos[0], t_pos[1], line_color))

        # ── Урон / смерть / способности за эти тики ─────────────────────
        for event in sim.log:
            if not (last_processed_tick < event.get("tick", 0) <= tick_count):
                continue

            etype = event.get("type", "")

            # Попадание / исцеление / смерть / способности за эти тики
            if etype in ("hit", "kill", "ability_hit", "ability_kill", "ability_heal"):
                target = find_unit(event.get("target_id"))
                if target is None:
                    continue
                t_pos = positions.get(target)
                if t_pos is None:
                    continue
                dmg = event.get("damage", 0)
                heal = event.get("heal", 0)
                is_kill = etype in ("kill", "ability_kill")
                is_crit = bool(event.get("is_critical"))
                is_heal = etype == "ability_heal"
                if is_heal:
                    dmg_color = (100, 255, 100)  # зелёное число — исцеление
                    show_amount = f"+{heal:.0f}"
                else:
                    dmg_color = (255, 50, 50) if is_kill else (255, 100, 50)
                    show_amount = dmg
                effects["damage_numbers"].append(
                    DamageNumber(t_pos[0], t_pos[1] - 30, show_amount, dmg_color))
                if not is_heal:
                    effects["hit_particles"].append(
                        HitParticles(t_pos[0], t_pos[1], is_critical=is_crit))
                if is_crit:
                    effects["critical_effects"].append(
                        CriticalEffect(t_pos[0], t_pos[1], dmg))
                    self.add_shake(3.5)          # крит трясёт
                if is_kill:
                    effects["death_effects"].append(DeathEffect(t_pos[0], t_pos[1]))
                    self.add_shake(2.0)

                # Звук: крит звонче, смерть ниже, исцеление — светлый хлопок, обычный удар — хлопок
                if is_kill:
                    self.play_sound("kill")
                elif is_crit:
                    self.play_sound("crit")
                elif is_heal:
                    self.play_sound("ability", 0.7)
                else:
                    self.play_sound("hit", 0.7)

            # Промах от уклонения (эльфы)
            if etype == "miss":
                target = find_unit(event.get("target_id"))
                if target:
                    t_pos = positions.get(target)
                    if t_pos:
                        effects["damage_numbers"].append(
                            DamageNumber(t_pos[0], t_pos[1] - 30, "MISS", (180, 180, 180)))

            # Вампиризм (демоны): зелёное число хила над атакующим
            if etype == "lifesteal":
                attacker = find_unit(event.get("attacker_id"))
                if attacker:
                    a_pos = positions.get(attacker)
                    if a_pos:
                        heal = event.get("heal", 0)
                        effects["damage_numbers"].append(
                            DamageNumber(a_pos[0], a_pos[1] - 30, f"+{heal:.0f}", (100, 255, 100)))
                        self.play_sound("ability", 0.6)

            # Восстание (нежить): визуал подъёма над юнитом
            if etype == "revive":
                target = find_unit(event.get("target_id"))
                if target:
                    t_pos = positions.get(target)
                    if t_pos:
                        effects["damage_numbers"].append(
                            DamageNumber(t_pos[0], t_pos[1] - 30, "REVIVE", (200, 200, 100)))
                        effects["death_effects"].append(DeathEffect(t_pos[0], t_pos[1]))
                        self.add_shake(2.0)

            # Способность: расширяющееся кольцо с названием
            if (etype.startswith("ability") or "ability_name" in event
                    or "caster_id" in event):
                try:
                    caster = find_unit(event.get("caster_id"))
                    if caster is not None and caster.alive:
                        c_pos = positions.get(caster)
                        if c_pos is not None:
                            ability_name = event.get("ability_name", "Ability")
                            # Тип берём из данных движка, а не угадываем по имени
                            effect_type = event.get("ability_type") or "aoe_damage"
                            effects["ability_effects"].append(
                                AbilityEffect(c_pos[0], c_pos[1],
                                              ability_name, effect_type))
                            self.play_sound("ability")
                            self.add_shake(2.5)
                except Exception:
                    pass

    def wait_for_input(self):
        """Ждёт нажатия клавиши или клика мыши перед переходом к следующей фазе."""
        pygame.event.get()  # очистить очередь
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    return False
                elif event.type == pygame.KEYDOWN or event.type == pygame.MOUSEBUTTONDOWN:
                    return True
            self.clock.tick(30)
        return False

    def run(self, game_instance):
        """Run UI with real-time battle animation.

        Each round plays out tick-by-tick from its stored simulator.
        Press SPACE to pause/resume, +/- to change speed.
        """
        self.init()
        self.running = True
        self._game_instance = game_instance

        BG_COLOR = (20, 20, 30)

        history = game_instance.history
        if not history:
            print("No rounds to display.")
            pygame.quit()
            return

        # State machine for animation — NO WAITING between phases!
        phase = "intro"  # intro -> draft -> round_title -> battle -> round_end -> done
        current_round_idx = 0
        tick_count = 0
        paused = False
        # Последний обработанный тик для генератора эффектов.
        # Без этого run() падал с NameError на первом же кадре боя.
        last_processed_tick = -1

        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                
                elif event.type == pygame.KEYDOWN:
                    # Handle global hotkeys
                    if event.key == KEY_LEADERBOARD:
                        self.leaderboard_open = not self.leaderboard_open
                        self.viewing_board = None
                    elif event.key == pygame.K_ESCAPE:
                        if self.leaderboard_open:
                            self.leaderboard_open = False
                        elif self.viewing_board is not None:
                            self.viewing_board = None
                        else:
                            self.running = False
                    elif event.key == pygame.K_SPACE:
                        paused = not paused
                    elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, getattr(pygame, 'K_KP_PLUS', None)):
                        self.ticks_per_frame = min(20, self.ticks_per_frame + 1)
                        self.speed_display_timer = 60  # показывать 2 секунды
                    elif event.key in (pygame.K_MINUS, getattr(pygame, 'K_KP_MINUS', None)):
                        self.ticks_per_frame = max(1, self.ticks_per_frame - 1)
                        self.speed_display_timer = 60  # показывать 2 секунды
            
            # Phase transitions — use time.sleep() for visible pauses
            if phase == "intro":
                self.screen.fill(BG_COLOR)
                surf = self.font_large.render("AUTOBATTLER MVP", True, (255, 255, 100))
                r = surf.get_rect(center=(self.width // 2, self.height // 3))
                self.screen.blit(surf, r)
                sub = self.font_small.render("Нажмите любую клавишу...", True, (200, 200, 200))
                r2 = sub.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(sub, r2)
                pygame.display.flip()
                
                # Wait for any keypress to start (user must click window first)
                started = False
                while not started and self.running:
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            self.running = False
                            break
                        elif event.type == pygame.KEYDOWN:
                            started = True
                    
                    # If no key pressed yet, just keep the screen visible
                    if not started:
                        time.sleep(0.05)
                
                phase = "draft"
                current_round_idx = 0
                tick_count = 0
                paused = False
            
            elif phase == "draft":
                # Auto-skip ALL drafts — use pre-built teams from game_instance
                state = history[current_round_idx]
                
                self.screen.fill((20, 30, 40))
                title = f"ROUND {state.round_number}"
                if state.is_creep:
                    title += " (CREEP)"
                else:
                    title += " (PvP)"
                self.draw_round_title(title)
                sub = self.font_small.render("Нажмите любую клавишу или кликните мышью...", True, (200, 200, 200))
                r = sub.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(sub, r)
                pygame.display.flip()
                
                if not self.wait_for_input():
                    return
                
                phase = "round_title"
            
            elif phase == "round_title":
                # Show round title briefly then move to battle immediately
                state = history[current_round_idx]
                self.screen.fill(BG_COLOR)
                is_creep = state.is_creep
                title = f"ROUND {state.round_number} - CREEP BATTLE" if is_creep else f"ROUND {state.round_number} - PvP"
                self.draw_round_title(title)
                sub = self.font_small.render("Нажмите любую клавишу или кликните мышью...", True, (200, 200, 200))
                r = sub.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(sub, r)
                pygame.display.flip()

                if not self.wait_for_input():
                    return
                
                # Move to battle immediately — no waiting!
                phase = "battle"
                tick_count = 0

            elif phase == "battle":
                state = history[current_round_idx]
                sim = game_instance.all_sims.get(state.round_number)

                if not sim:
                    # No simulator for this round - skip
                    current_round_idx += 1
                    if current_round_idx >= len(history):
                        phase = "done"
                    else:
                        phase = "round_title"
                    continue

                if paused:
                    self.clock.tick(30)
                    continue

                total_ticks_final = state.total_ticks if hasattr(state, 'total_ticks') else sim.get_total_ticks()
                
                # Accumulate effects across frames (don't reset each frame)
                # This allows attack lines and damage numbers to animate smoothly
                if tick_count == 0:  # Initialize on first frame only
                    effects = {
                        "damage_numbers": [],
                        "death_effects": [],
                        "lines": [],
                        "ability_effects": [],
                        "hit_particles": [],
                        "critical_effects": [],
                    }
                
                # Restore state from snapshot at the current frame
                self.screen.fill(BG_COLOR)
                self._draw_battle_scene(sim, effects, tick_count)

                # Визуальные эффекты: единая реализация на run() и _animate_battle()
                self._generate_battle_effects(
                    sim, tick_count, last_processed_tick, effects)

                # Header for this round
                self.draw_header(state.round_number, state.total_gold_after, state.is_creep, player=self.player)

                # Battle log (last events)
                if sim.log:
                    self.draw_battle_log(sim.log)

                # Tick counter
                tick_surf = self.font_tiny.render(
                    f"Tick: {tick_count}/{total_ticks_final}", True, (150, 150, 255))
                self.screen.blit(tick_surf, (self.width // 2 - 40, 380))

                # Speed indicator badge
                if self.speed_display_timer > 0:
                    self.speed_display_timer -= 1
                    alpha = min(self.speed_display_timer / 30, (60 - self.speed_display_timer) / 30)
                    if alpha > 0:
                        speed_level = self.ticks_per_frame
                        label = "x1" if speed_level <= 1 else f"x{speed_level}"
                        badge_text = f"Speed: {label}"
                        badge_surf = self.font_tiny.render(badge_text, True, (255, 255, 100))
                        badge_rect = badge_surf.get_rect(center=(self.width // 2 - 40, 398))
                        pygame.draw.rect(self.screen, (40, 40, 60),
                                        (badge_rect.x - 4, badge_rect.y - 2, badge_rect.w + 8, badge_rect.h + 4),
                                        border_radius=4)
                        pygame.draw.rect(self.screen, (150, 150, 100),
                                        (badge_rect.x - 4, badge_rect.y - 2, badge_rect.w + 8, badge_rect.h + 4),
                                        width=1, border_radius=4)
                        self.screen.blit(badge_surf, badge_rect)

                # Round progress dots
                completed = current_round_idx if tick_count > 0 else -1
                self.draw_round_progress(completed, len(history))

                # ── Панель участников (всегда видима в бою) ──
                participants = self._gather_participants()
                self.draw_player_list_panel(participants)
                if self.leaderboard_open:
                    self.draw_leaderboard(participants)
                elif self.viewing_board is not None:
                    view = self._find_participant(participants)
                    if view is not None:
                        self.draw_board_view(view)

                last_processed_tick = tick_count
                tick_count += self.ticks_per_frame

                # Check if round is over (show final frame before ending)
                if tick_count >= total_ticks_final:
                    phase = "round_end"

            elif phase == "round_end":
                # Show round result briefly then move on
                state = history[current_round_idx]
                sim = game_instance.all_sims.get(state.round_number)
                self.screen.fill(BG_COLOR)
                # Restore final state from last snapshot
                if sim and sim._tick_history:
                    sim.restore_from_snapshot(sim._tick_history[-1])
                self._draw_battle_scene(
                    sim,
                    {"damage_numbers": [], "death_effects": [], "lines": []}
                )
                # ── Панель участников (всегда видима в бою) ──
                participants = self._gather_participants()
                self.draw_player_list_panel(participants)
                if self.leaderboard_open:
                    self.draw_leaderboard(participants)
                elif self.viewing_board is not None:
                    view = self._find_participant(participants)
                    if view is not None:
                        self.draw_board_view(view)

                winner = state.battle_result["winner"] if state.battle_result else "?"
                ticks = state.battle_result.get("ticks", "?") if state.battle_result else "?"
                is_creep = state.is_creep

                result_text = f"ROUND {state.round_number} COMPLETE"
                self.draw_round_title(result_text)

                winner_surf = self.font_small.render(
                    f"{winner.upper()} wins ({ticks} ticks)", True, (255, 200, 100))
                r = winner_surf.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(winner_surf, r)

                # Gold earned
                gold_text = f"+{state.gold_earned} gold (+{state.interest_earned}% interest)"
                gold_surf = self.font_tiny.render(gold_text, True, (150, 255, 150))
                r = gold_surf.get_rect(center=(self.width // 2, self.height // 2 + 70))
                self.screen.blit(gold_surf, r)

                sub = self.font_small.render("Нажмите любую клавишу или кликните мышью...", True, (200, 200, 200))
                r = sub.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(sub, r)
                pygame.display.flip()

                if not self.wait_for_input():
                    return
                
                # Move to next phase immediately — no waiting!
                current_round_idx += 1
                tick_count = 0
                
                # Начисляем опыт за завершённый раунд
                if self.player is not None:
                    leveled_up = self.player.add_round_xp()
                    if leveled_up:
                        self.play_sound("gold")
                
                if current_round_idx >= len(history):
                    phase = "done"
                else:
                    phase = "draft"

            elif phase == "done":
                # Show final match result
                self.screen.fill(BG_COLOR)
                self.draw_result(game_instance.winner or "?", "?")

                summary_surf = self.font_small.render(
                    f"You won {sum(1 for s in history if s.battle_result and s.battle_result['winner'] == 'player')} rounds",
                    True, (200, 200, 200))
                r = summary_surf.get_rect(center=(self.width // 2, self.height // 2 + 50))
                self.screen.blit(summary_surf, r)

                restart_surf = self.font_tiny.render(
                    "Press ESC to quit", True, (150, 150, 150))
                r = restart_surf.get_rect(center=(self.width // 2, self.height - 40))
                self.screen.blit(restart_surf, r)

                pygame.display.flip()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        self.running = False

            else:
                phase = "done"

            # Draw controls on every frame (except intro)
            if phase != "intro":
                self.draw_controls()

            pygame.display.flip()
            self.clock.tick(60)

        pygame.quit()

    def run_interactive_match(self, seed=None, enemy_bot="balanced"):
        """Run a fully interactive match with draft phases.
        
        For PvP rounds (5+), player can buy/sell/place/remove units from shop.
        For creep rounds (1-4), auto-fills with default units.
        
        Keys during draft: W=Buy(1g) S=Sell-last D=Place F=Remove R=Roll N=Next Enter=Done
        During battle: SPACE=Pause +/-=Speed ESC=Quit
        
        Args:
            seed: Random seed for battle determinism. If None, generates a random seed
                  so that each run has different shop rolls and battle outcomes.
            enemy_bot: Bot preset for PvP rounds.
        """
        import random as _random
        if seed is None:
            seed = _random.randint(0, 2 ** 31 - 1)
        from game.core.round import Game, load_game_data, build_creep_units
        from game.core.shop import Shop
        from game.core.pool import Pool
        from game.core.draft import DraftPhase
        from game.core.player import Player
        from game.core.bots import create_bot
        from game.core.economy import round_economy, START_HP
        from game.core.synergies import (
            calculate_synergy_bonuses, apply_synergy_bonuses,
            calculate_passive_bonuses, apply_passive_bonuses,
        )
        from game.battle.engine import BattleSimulator
        
        self.init()
        self.running = True
        
        project_root = Path(__file__).parent.parent.resolve()
        data = load_game_data(project_root / "data" / "units.json")
        all_units = data["units"]
        # Доступно и для крип-раундов, где драфт не вызывается
        self.all_units = all_units
        self._rebuild_cost_index()
        # Перестроим карту имён -> ключей после загрузки данных юнитов
        self._name_to_unit_key = {}
        for key, ud in self.all_units.items():
            self._name_to_unit_key[ud.get("name", key)] = key
        unit_costs = {name: info["cost"] for name, info in all_units.items()}
        
        BG_COLOR = (20, 20, 30)

        gold = 5
        player_level = 1
        player_xp = 0
        self.player = None
        self.player_hp = START_HP
        # 7 постоянных ботов (соперники по очереди), чтобы показать 8 участников матча.
        self.match_bots = []
        bot_presets = ["balanced", "aggressive", "casual", "saver", "synergy_focus", "random", "balanced"]
        for i in range(7):
            self.match_bots.append({
                "name": f"Bot {i+1}",
                "preset": bot_presets[i],
                "hp": START_HP,
                "level": 1,
                "gold": 20,
                "board_units": [],      # купленные юниты, сохраняются между раундами
                "dead": False,
                "seed_base": 1000 + i,
            })
        self.pvp_round_index = 0
        history = []  # list of round result dicts
        all_sims = {}  # round_num -> BattleSimulator
        # Купленные юниты, предметы и скамейка между раундами.
        # Крип-раунды их не сбрасывают — состав переносится на следующий раунд.
        stored_player_units = None   # формат доски: [{"name":..., "star":..., "row":..., "col":...}, ...]
        stored_player_items = None
        stored_player_reserve = None  # имена с ★N: ["warrior_freshman", "archer_scout★2", ...]

        round_num = 0
        while True:
            round_num += 1
            # Раунды 1-3 — крипы, потом каждый третий (6, 9, ...) — крип, остальные — PvP
            is_creep = round_num <= 3 or round_num % 3 == 0
            bot_data = None  # соперник этого раунда (PvP); None для крип-раундов

            # ── Драфт игрока. С ПЕРВОГО раунда. ────────────────────────────
            # Раньше крип-раунды шли с захардкоженным составом, то есть три
            # раунда из восьми были кат-сценой без единого решения игрока.
            existing = {
                "units": stored_player_units,
                "gold": gold,
                "items": stored_player_items,
                "reserve": stored_player_reserve,
                "level": player_level,
                "xp": player_xp,
                "win_streak": self.player.win_streak if self.player is not None else 0,
                "loss_streak": self.player.loss_streak if self.player is not None else 0,
            } if stored_player_units is not None else None
            result = self._run_interactive_draft(
                round_num=round_num,
                is_creep=is_creep,
                synergy_data=data["synergies"],
                seed=seed,
                existing_units=existing,
            )
            if result is None:
                return  # user quit
            player_units, gold, stored_items, stored_player_reserve, stored_player_units, player_level, player_xp, player_win_streak, player_loss_streak = result
            # stored_player_units теперь формат доски (name/star/row/col),
            # а не боевой формат (hp/damage/...) — пригоден для восстановления
            stored_player_items = stored_items

            if is_creep:
                # Крипы: волна растёт с номером раунда (раньше была одинаковой),
                # количество подстраивается под размер доски игрока
                enemy_units = build_creep_units(
                    round_num, all_units, player_units,
                    synergy_data=data["synergies"],
                    race_synergy_data=data.get("race_synergies", {}),
                    race_data=data.get("races", {}),
                )
                # Бой игрока с волной крипов
                sim = BattleSimulator(
                    seed=seed + round_num,
                    race_data=data["races"],
                    race_synergy_data=data["race_synergies"],
                )
                sim.add_team("Игрок", player_units)
                sim.add_team("Крипы", enemy_units)
                battle_result = sim.run()
                total_ticks = sim.get_total_ticks()
                # Стандартизируем winner для совместимости с отчётом
                if battle_result["winner"] == "Игрок":
                    battle_result["winner"] = "player"
                    pvp_win = False
                    creep_win = True
                else:
                    battle_result["winner"] = "enemy"
                    pvp_win = False
                    creep_win = False
                hp_lost = 0
                eliminated = self.player_hp <= 0
                player_opponent_name = None
                # Золото и киллы для крип-раундов
                kills = sum(1 for e in sim.log
                            if e.get("type") in ("kill", "ability_kill")
                            and e.get("killer_team") == "Игрок")
                kill_gold = KILL_GOLD_PER_UNIT * kills
                surviving_enemies = 0
                surviving_players = sum(1 for u in sim.teams.get("Игрок", []) if u.alive)
                econ = round_economy(
                    gold=gold, pvp_win=False, creep_win=creep_win,
                    is_creep=True,
                    surviving_enemy_units=0,
                    win_streak=self.player.win_streak,
                    loss_streak=self.player.loss_streak,
                )
                gold = econ["gold_after"] + kill_gold
            else:
                # PvP-раунд: все живые участники делятся на пары (все против всех).
                # Пары: (1-й со 2-м), (3-й с 4-м), … с ротацией через порядок в living_names.
                # При нечётном числе живых — первый участник сражается с копией себя.

                living_bots = [b for b in self.match_bots if b["hp"] > 0]

                # Состав каждой команды на этот раунд
                units_by_name: dict[str, list[dict]] = {"Игрок": player_units}

                # Каждый живой бот покупает/докупает юнитов (экономика переносится между раундами)
                for bot_data in living_bots:
                    bot_gold = bot_data["gold"]
                    bot = create_bot(
                        preset=bot_data["preset"],
                        seed=seed + round_num + bot_data["seed_base"],
                    )
                    rng = random.Random(seed + round_num * 100 + bot_data["seed_base"])
                    pool = Pool(unit_costs)
                    shop = Shop(pool, unit_costs=unit_costs, rng=rng)
                    draft_phase_bot = DraftPhase(shop, all_units)
                    enemy_player = Player(gold=bot_gold)

                    draft_decision = bot.decide_draft(
                        available_units=all_units, gold=bot_gold, current_team=[],
                        synergy_data=data["synergies"],
                    )

                    purchased = []
                    for unit_info in draft_decision:
                        name = unit_info["name"]
                        cost = unit_info.get("cost", 1)
                        if enemy_player.gold >= cost:
                            try:
                                merged_name = draft_phase_bot.buy_unit(enemy_player, name)
                                purchased.append(merged_name)
                            except ShopError:
                                pass  # не хватило пула или резерв полон
                    bot_data["gold"] = enemy_player.gold  # экономика бота между раундами

                    # Сохраняем composition для панели участников
                    bot_board = []
                    for pu in purchased[:6]:
                        base = base_name(pu)
                        star = star_level(pu)
                        ud = all_units.get(base, {})
                        bot_board.append({
                            "name": self.display_name(pu),
                            "key": base,
                            "star": star,
                            "cls": ud.get("class", "warrior"),
                            "cost": ud.get("cost", 1),
                            "race": ud.get("race", "human"),
                        })
                    bot_data["board_units"] = bot_board
                    bot_data["level"] = Game._bot_level_for_round(round_num)

                    # Боевой состав через build_combat_team
                    bot_units_data = [
                        {"name": pu, "star": star_level(pu)}
                        for pu in purchased[:6]
                    ]
                    bot_team = build_combat_team(
                        bot_units_data, all_units,
                        synergy_data=data["synergies"],
                        race_synergy_data=data.get("race_synergies", {}),
                        race_data=data.get("races", {}),
                    )
                    if not bot_team:
                        bot_team = [
                            {"name": "warrior_freshman", "hp": 500, "damage": 40,
                             "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                        ]
                    units_by_name[bot_data["name"]] = bot_team

                # Живые участники: игрок + живые боты
                living_names = ["Игрок"] + [b["name"] for b in living_bots]

                # Нечётное → копия первого участника
                copy_name = None
                if len(living_names) % 2 == 1:
                    copy_name = living_names[0] + " (копия)"
                    units_by_name[copy_name] = [dict(u) for u in units_by_name[living_names[0]]]
                    living_names.append(copy_name)

                # Проводим все парные бои
                pair_results = []  # (name_a, name_b, sim, battle_result, winner, loser, dmg)

                for i in range(0, len(living_names), 2):
                    name_a, name_b = living_names[i], living_names[i + 1]
                    team_a = units_by_name.get(name_a, [])
                    team_b = units_by_name.get(name_b, [])

                    sim = BattleSimulator(
                        seed=seed + round_num + i,
                        race_data=data["races"],
                        race_synergy_data=data["race_synergies"],
                    )

                    # Активные способности, критики, класс — из JSON
                    for team in (team_a, team_b):
                        for u in team:
                            nb = base_name(u.get("name", ""))
                            if nb in all_units:
                                ud = all_units[nb]
                                if ud.get("active"):
                                    u["active"] = dict(ud["active"])
                                u.setdefault("crit_chance", ud.get("crit_chance", 0))
                                u.setdefault("unit_class", ud.get("class", ""))

                    sim.add_team(name_a, team_a)
                    sim.add_team(name_b, team_b)
                    br = sim.run()

                    winner = br["winner"]  # name_a или name_b
                    loser = name_b if winner == name_a else name_a

                    dmg = 0
                    if not is_creep:
                        surv_winner = sum(1 for u in sim.teams[winner] if u.alive)
                        dmg = pvp_round_damage(round_num, surv_winner)

                        # Урон проигравшему
                        if loser == "Игрок":
                            self.player_hp = max(0, self.player_hp - dmg)
                            hp_lost = dmg
                        else:
                            for b in self.match_bots:
                                if b["name"] == loser:
                                    b["hp"] = max(0, b["hp"] - dmg)
                                    if b["hp"] <= 0:
                                        b["dead"] = True
                                    break
                            hp_lost = 0  # для игрока урон нанёс бот, а не наоборот

                        # Серии побед/поражений игрока
                        if name_a == "Игрок":
                            if winner == "Игрок":
                                self.player.record_win()
                            else:
                                self.player.record_loss()
                        elif name_b == "Игрок":
                            if winner == "Игрок":
                                self.player.record_win()
                            else:
                                self.player.record_loss()

                    pair_results.append(
                        (name_a, name_b, sim, br, winner, loser, dmg)
                    )

                # Результат для отображения: пара, в которой участвовал игрок
                player_pair = None
                for pr in pair_results:
                    if pr[0] == "Игрок" or pr[1] == "Игрок":
                        player_pair = pr
                        break

                if player_pair:
                    name_a, name_b, sim, battle_result, winner, loser, dmg = player_pair
                    total_ticks = sim.get_total_ticks()
                    pvp_win = winner == "Игрок"
                    creep_win = False
                    # Стандартизируем winner для итогового отчёта
                    battle_result["winner"] = "player" if pvp_win else "enemy"
                    if pvp_win:
                        hp_lost = 0
                    else:
                        hp_lost = dmg
                    # Выжившие для статистики
                    enemy_name = name_b if name_a == "Игрок" else name_a
                    player_opponent_name = enemy_name
                    surviving_enemies = sum(
                        1 for u in sim.teams.get(enemy_name, []) if u.alive)
                    surviving_players = sum(
                        1 for u in sim.teams.get("Игрок", []) if u.alive)
                else:
                    # Игрок не участвовал в этой паре (не должно быть, но на всякий)
                    battle_result = {"winner": "player", "reason": "no_fight"}
                    total_ticks = 0
                    pvp_win = True
                    creep_win = False
                    surviving_enemies = 0
                    surviving_players = 0
                    hp_lost = 0
                    player_opponent_name = None
                    sim = BattleSimulator(
                        seed=seed + round_num,
                        race_data=data["races"],
                        race_synergy_data=data["race_synergies"],
                    )

                # Золото и киллы игрока (с его боя)
                kills = sum(1 for e in sim.log
                            if e.get("type") in ("kill", "ability_kill")
                            and e.get("killer_team") == "Игрок")
                kill_gold = KILL_GOLD_PER_UNIT * kills
                econ = round_economy(
                    gold=gold, pvp_win=pvp_win, creep_win=creep_win,
                    is_creep=is_creep,
                    surviving_enemy_units=surviving_enemies,
                    win_streak=self.player.win_streak,
                    loss_streak=self.player.loss_streak,
                )
                gold = econ["gold_after"] + kill_gold
                eliminated = self.player_hp <= 0

            # ── Детальная статистика боя ───────────────────────────────────
            # Урон, киллы и топ юнитов из sim.log
            dmg_by_team = {}
            kills_by_team = {}
            dmg_by_unit = {}   # attacker_id -> damage
            kills_by_unit = {} # attacker_id -> kills
            heal_by_unit = {}  # caster_id -> heal amount
            unit_names = {}    # unit_id -> (name, team, star)
            for team_name, units in sim.teams.items():
                dmg_by_team[team_name] = 0
                kills_by_team[team_name] = 0
                for u in units:
                    unit_names[u.unit_id] = (self.display_name(u.name), team_name, getattr(u, "star", 1))

            for e in sim.log:
                etype = e.get("type")
                if etype in ("hit", "ability_hit"):
                    dmg = e.get("damage", 0)
                    attacker_id = e.get("attacker_id") or e.get("caster_id")
                    if attacker_id in unit_names:
                        _, team, _ = unit_names[attacker_id]
                        dmg_by_team[team] = dmg_by_team.get(team, 0) + dmg
                        dmg_by_unit[attacker_id] = dmg_by_unit.get(attacker_id, 0) + dmg
                elif etype in ("kill", "ability_kill"):
                    attacker_id = e.get("attacker_id") or e.get("caster_id")
                    killer_team = e.get("killer_team")
                    if killer_team in kills_by_team:
                        kills_by_team[killer_team] += 1
                    if attacker_id in unit_names:
                        kills_by_unit[attacker_id] = kills_by_unit.get(attacker_id, 0) + 1
                elif etype == "ability_heal":
                    heal_amount = e.get("heal", 0)
                    caster_id = e.get("caster_id")
                    if caster_id in unit_names:
                        heal_by_unit[caster_id] = heal_by_unit.get(caster_id, 0) + heal_amount

            # Топ по урону и киллам
            top_damage = sorted(
                ((unit_names[uid][0], dmg, unit_names[uid][1], unit_names[uid][2])
                 for uid, dmg in dmg_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_kills = sorted(
                ((unit_names[uid][0], k, unit_names[uid][1], unit_names[uid][2])
                 for uid, k in kills_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_heal = sorted(
                ((unit_names[uid][0], h, unit_names[uid][1], unit_names[uid][2])
                 for uid, h in heal_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]

            state = {
                "round_number": round_num,
                "is_creep": is_creep,
                "gold_earned": econ["income"],
                "interest_earned": econ["interest"],
                "kill_gold": kill_gold,
                "total_gold_after": gold,
                "hp": self.player_hp,
                "hp_lost": hp_lost,
                "eliminated": eliminated,
                "battle_result": battle_result,
                "total_ticks": total_ticks,
                # Детальная статистика
                "dmg_by_team": dmg_by_team,
                "kills_by_team": kills_by_team,
                "top_damage": top_damage,
                "top_kills": top_kills,
                "top_heal": top_heal,
                # HP оппонента игрока в его паре (или первого живого бота)
                "bot_hp": (next((b["hp"] for b in self.match_bots
                                 if b["name"] == player_opponent_name), 0)
                           if player_opponent_name
                           else (self.match_bots[0]["hp"] if self.match_bots else START_HP)),
                "player_hp": self.player_hp,
            }
            history.append(state)
            all_sims[round_num] = sim
            
            # Проверяем конец игры по HP (игрок или все 7 ботов)
            if self.player_hp <= 0 or all(b["hp"] <= 0 for b in self.match_bots):
                break
            
            # ── Battle animation phase (auto-start, no wait screen) ────────────
            try:
                result = self._animate_battle(sim, state, all_sims, BG_COLOR)
                if not result:
                    return  # user quit
            except Exception as e:
                print(f"ERROR in round {state['round_number']}: {e}")
                import traceback
                traceback.print_exc()
                return  # user quit
            
            # ── Pause between rounds so user can see results ────────────
            # Звук итога раунда: золото всегда, вылет — своей темой
            self.play_sound("gold")
            if eliminated:
                self.play_sound("lose")
            for _ in range(90):  # ~3 seconds at 30fps
                if not self.running:
                    return
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        return
                    if event.type == pygame.KEYDOWN:
                        if event.key == KEY_LEADERBOARD:
                            self.leaderboard_open = not self.leaderboard_open
                            self.viewing_board = None
                        elif event.key == pygame.K_ESCAPE:
                            if self.leaderboard_open:
                                self.leaderboard_open = False
                            elif self.viewing_board is not None:
                                self.viewing_board = None
                        else:
                            break  # любая другая клавиша пропускает паузу
                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        break  # клик пропускает паузу
                else:
                    self.clock.tick(30)
                    # Рисуем статистику боя поверх анимации
                    self.screen.fill(BG_COLOR)
                    self.draw_battle_stats(state)
                    # Панель участников + оверлеи (таблица/доска) поверх статистики
                    participants = self._gather_participants()
                    self.draw_player_list_panel(participants)
                    if self.leaderboard_open:
                        self.draw_leaderboard(participants)
                    elif self.viewing_board is not None:
                        view = self._find_participant(participants)
                        if view is not None:
                            self.draw_board_view(view)
                    pygame.display.flip()
                    continue
                break

            # Здоровье кончилось — матч проигран
            if eliminated:
                break

        # ── Final result ────────────────────────────────────────────────
        self.screen.fill(BG_COLOR)

        player_wins = sum(1 for s in history if s["battle_result"]["winner"] == "player")
        living_bots = sum(1 for b in self.match_bots if b["hp"] > 0)
        if self.player_hp <= 0:
            winner = "enemy"
            verdict = "ПОРАЖЕНИЕ"
            place = living_bots + 1  # место по числу живых ботов + игрок
        elif all(b["hp"] <= 0 for b in self.match_bots):
            winner = "player"
            verdict = "ПОБЕДА"
            place = 1
        else:
            winner = "player" if player_wins > len(history) - player_wins else "enemy"
            verdict = "ПОБЕДА" if winner == "player" else "ПОРАЖЕНИЕ"
            place = 1 if winner == "player" else living_bots + 1

        self.draw_result(verdict, "?")
        self.play_sound("win" if winner == "player" else "lose")
        if self.player_hp <= 0:
            self.add_shake(10.0)      # проигрыш бьёт по нервам

        summary_surf = self.font_small.render(
            f"Раундов сыграно: {len(history)}   |   HP игрока: {self.player_hp}   |   Ботов живых: {living_bots}/7",
            True, (200, 200, 200))
        r = summary_surf.get_rect(center=(self.width // 2, self.height // 2 + 50))
        self.screen.blit(summary_surf, r)

        place_surf = self.font_small.render(
            f"Занятое место: {place}", True, (200, 200, 200))
        r = place_surf.get_rect(center=(self.width // 2, self.height // 2 + 80))
        self.screen.blit(place_surf, r)

        # Итоговая статистика по всему матчу
        # Определяем имя команды игрока из первого состояния
        player_team = "player"
        if history:
            for t in history[0].get("dmg_by_team", {}):
                if t != "enemy":
                    player_team = t
                    break

        total_dmg = sum(s.get("dmg_by_team", {}).get(player_team, 0) for s in history)
        total_kills = sum(s.get("kills_by_team", {}).get(player_team, 0) for s in history)
        total_gold_earned = sum(s.get("gold_earned", 0) for s in history)
        total_kill_gold = sum(s.get("kill_gold", 0) for s in history)

        stats_lines = [
            f"Всего урона: {total_dmg:.1f}   |   Всего киллов: {total_kills}",
            f"Золота за раунды: {total_gold_earned}   |   Золота за киллы: {total_kill_gold}",
        ]
        for i, line in enumerate(stats_lines):
            surf = self.font_tiny.render(line, True, (180, 180, 180))
            r = surf.get_rect(center=(self.width // 2, self.height // 2 + 80 + i * 20))
            self.screen.blit(surf, r)
        
        restart_surf = self.font_tiny.render("Press ESC to quit", True, (150, 150, 150))
        r = restart_surf.get_rect(center=(self.width // 2, self.height - 40))
        self.screen.blit(restart_surf, r)
        
        pygame.display.flip()
        
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self.running = False
        
        pygame.quit()

    def run_bot_vs_bot_match(self, bot1_preset="balanced", bot2_preset="aggressive",
                             seed=42, rounds=8):
        """Режим «бот против бота» без участия игрока.

        Два бота с собственными экономиками закупаются через decide_draft,
        сражаются на BattleSimulator, зарабатывают золото и теряют HP за
        проигранные PvP-раунды. Возвращает статистику матча.

        Args:
            bot1_preset: preset первого бота (из BOT_PRESETS)
            bot2_preset: preset второго бота
            seed: базовый seed для RNG
            rounds: количество раундов матча (1-8)

        Returns:
            dict с ключами: bot1_wins, bot2_wins, draws, rounds_played,
            bot1_hp, bot2_hp, winner ("bot1"/"bot2"/"draw"), history
        """
        project_root = Path(__file__).parent.parent.resolve()
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from game.core.bots import create_bot
        from game.core.shop import Shop
        from game.core.pool import Pool
        from game.core.draft import DraftPhase
        from game.core.player import Player
        from game.battle.engine import BattleSimulator
        from game.core.synergies import (
            calculate_synergy_bonuses, apply_synergy_bonuses,
            calculate_passive_bonuses, apply_passive_bonuses,
        )
        from game.core.economy import round_economy, START_HP
        from game.core.round import load_game_data

        data = load_game_data(project_root / "data" / "units.json")
        all_units = data["units"]
        unit_costs = {name: info["cost"] for name, info in all_units.items()}

        bot1 = create_bot(preset=bot1_preset, seed=seed)
        bot2 = create_bot(preset=bot2_preset, seed=seed + 1000)

        gold1 = 5
        gold2 = 5
        hp1 = START_HP
        hp2 = START_HP

        history = []

        for round_num in range(1, rounds + 1):
            is_creep = round_num <= 3 or round_num % 3 == 0

            # ── Бот 1 закупается ───────────────────────────────────────────
            player1 = Player(gold=gold1)
            rng1 = random.Random(seed + round_num * 100)
            pool1 = Pool(unit_costs)
            shop1 = Shop(pool1, unit_costs=unit_costs, rng=rng1)
            draft1 = DraftPhase(shop1, all_units)
            draft_decision1 = bot1.decide_draft(
                available_units=all_units, gold=gold1,
                current_team=[], synergy_data=data["synergies"])

            purchased1 = []
            for unit_info in draft_decision1:
                name = unit_info["name"]
                cost = unit_info.get("cost", 1)
                if player1.gold >= cost:
                    try:
                        merged = draft1.buy_unit(player1, name)
                        purchased1.append(merged)
                    except ShopError:
                        pass
            gold1 = player1.gold

            # ── Бот 2 закупается ───────────────────────────────────────────
            player2 = Player(gold=gold2)
            rng2 = random.Random(seed + round_num * 100 + 1)
            pool2 = Pool(unit_costs)
            shop2 = Shop(pool2, unit_costs=unit_costs, rng=rng2)
            draft2 = DraftPhase(shop2, all_units)
            draft_decision2 = bot2.decide_draft(
                available_units=all_units, gold=gold2,
                current_team=[], synergy_data=data["synergies"])

            purchased2 = []
            for unit_info in draft_decision2:
                name = unit_info["name"]
                cost = unit_info.get("cost", 1)
                if player2.gold >= cost:
                    try:
                        merged = draft2.buy_unit(player2, name)
                        purchased2.append(merged)
                    except ShopError:
                        pass
            gold2 = player2.gold

            # ── Формируем боевые составы ──────────────────────────────────
            def make_battle_units(purchased, all_units):
                units = []
                for pu in purchased[:6]:
                    name = base_name(pu)
                    if name in all_units:
                        ud = all_units[name]
                        mult = star_multiplier(star_level(pu))
                        eu = {
                            "name": name,
                            "hp": int(ud["hp"] * mult),
                            "damage": int(ud["damage"] * mult),
                            "attack_speed": ud["attack_speed"],
                            "range_": ud["range"],
                            "class": ud["class"],
                            "race": ud.get("race", "human"),
                            "crit_chance": ud.get("crit_chance", 0),
                        }
                        if ud.get("active"):
                            eu["active"] = dict(ud["active"])
                        units.append(eu)
                return units

            team1 = make_battle_units(purchased1, all_units)
            team2 = make_battle_units(purchased2, all_units)

            if not team1:
                team1 = [{"name": "warrior_freshman", "hp": 500, "damage": 40,
                          "attack_speed": 1.2, "range_": 1, "class": "warrior"}]
            if not team2:
                team2 = [{"name": "warrior_freshman", "hp": 500, "damage": 40,
                          "attack_speed": 1.2, "range_": 1, "class": "warrior"}]

            # Симметрично применяем синергии и пассивки обеим сторонам
            team1 = apply_synergy_bonuses(
                team1, calculate_synergy_bonuses(team1, data["synergies"]))
            team2 = apply_synergy_bonuses(
                team2, calculate_synergy_bonuses(team2, data["synergies"]))
            if self.all_units:
                passive1 = calculate_passive_bonuses(team1, self.all_units)
                team1 = apply_passive_bonuses(team1, passive1)
                passive2 = calculate_passive_bonuses(team2, self.all_units)
                team2 = apply_passive_bonuses(team2, passive2)

            # ── Бой ────────────────────────────────────────────────────────
            sim = BattleSimulator(seed=seed + round_num * 50, race_data=data["races"], race_synergy_data=data["race_synergies"])
            sim.add_team("bot1", team1)
            sim.add_team("bot2", team2)
            battle_result = sim.run()

            # ── Экономика и HP ─────────────────────────────────────────────
            bot1_won = battle_result["winner"] == "bot1"
            bot2_won = battle_result["winner"] == "bot2"
            surviving1 = sum(1 for u in sim.teams.get("bot1", []) if u.alive)
            surviving2 = sum(1 for u in sim.teams.get("bot2", []) if u.alive)

            econ1 = round_economy(
                gold=gold1, pvp_win=bot1_won, creep_win=False,
                hp=hp1, is_creep=is_creep,
                surviving_enemy_units=surviving2)
            econ2 = round_economy(
                gold=gold2, pvp_win=bot2_won, creep_win=False,
                hp=hp2, is_creep=is_creep,
                surviving_enemy_units=surviving1)

            gold1 = econ1["gold_after"]
            gold2 = econ2["gold_after"]
            hp1 = econ1["hp_after"]
            hp2 = econ2["hp_after"]

            # ── Детальная статистика боя (бот vs бот) ──────────────────────
            dmg_by_team = {}
            kills_by_team = {}
            dmg_by_unit = {}
            kills_by_unit = {}
            heal_by_unit = {}
            unit_names = {}
            for team_name, units in sim.teams.items():
                dmg_by_team[team_name] = 0
                kills_by_team[team_name] = 0
                for u in units:
                    unit_names[u.unit_id] = (self.display_name(u.name), team_name, getattr(u, "star", 1))

            for e in sim.log:
                etype = e.get("type")
                if etype in ("hit", "ability_hit"):
                    dmg = e.get("damage", 0)
                    attacker_id = e.get("attacker_id") or e.get("caster_id")
                    if attacker_id in unit_names:
                        _, team, _ = unit_names[attacker_id]
                        dmg_by_team[team] = dmg_by_team.get(team, 0) + dmg
                        dmg_by_unit[attacker_id] = dmg_by_unit.get(attacker_id, 0) + dmg
                elif etype in ("kill", "ability_kill"):
                    attacker_id = e.get("attacker_id") or e.get("caster_id")
                    killer_team = e.get("killer_team")
                    if killer_team in kills_by_team:
                        kills_by_team[killer_team] += 1
                    if attacker_id in unit_names:
                        kills_by_unit[attacker_id] = kills_by_unit.get(attacker_id, 0) + 1
                elif etype == "ability_heal":
                    heal_amount = e.get("heal", 0)
                    caster_id = e.get("caster_id")
                    if caster_id in unit_names:
                        heal_by_unit[caster_id] = heal_by_unit.get(caster_id, 0) + heal_amount
                elif etype == "ability_heal":
                    heal_amount = e.get("heal", 0)
                    caster_id = e.get("caster_id")
                    if caster_id in unit_names:
                        heal_by_unit[caster_id] = heal_by_unit.get(caster_id, 0) + heal_amount

            top_damage = sorted(
                ((unit_names[uid][0], dmg, unit_names[uid][1], unit_names[uid][2])
                 for uid, dmg in dmg_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_kills = sorted(
                ((unit_names[uid][0], k, unit_names[uid][1], unit_names[uid][2])
                 for uid, k in kills_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_heal = sorted(
                ((unit_names[uid][0], h, unit_names[uid][1], unit_names[uid][2])
                 for uid, h in heal_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]

            history.append({
                "round": round_num,
                "is_creep": is_creep,
                "winner": battle_result["winner"],
                "total_ticks": sim.get_total_ticks(),
                "bot1_units": surviving1,
                "bot2_units": surviving2,
                "bot1_gold": gold1,
                "bot2_gold": gold2,
                "bot1_hp": hp1,
                "bot2_hp": hp2,
                "dmg_by_team": dmg_by_team,
                "kills_by_team": kills_by_team,
                "top_damage": top_damage,
                "top_kills": top_kills,
                "top_heal": top_heal,
            })

            if hp1 <= 0 or hp2 <= 0:
                break

        bot1_wins = sum(1 for s in history if s["winner"] == "bot1")
        bot2_wins = sum(1 for s in history if s["winner"] == "bot2")
        draws = len(history) - bot1_wins - bot2_wins

        if hp1 <= 0 and hp2 <= 0:
            winner = "draw"
        elif hp1 <= 0:
            winner = "bot2"
        elif hp2 <= 0:
            winner = "bot1"
        else:
            winner = "bot1" if bot1_wins > bot2_wins else "bot2" if bot2_wins > bot1_wins else "draw"

        return {
            "bot1": bot1.name,
            "bot2": bot2.name,
            "bot1_wins": bot1_wins,
            "bot2_wins": bot2_wins,
            "draws": draws,
            "rounds_played": len(history),
            "bot1_hp": hp1,
            "bot2_hp": hp2,
            "winner": winner,
            "history": history,
        }

    def _animate_battle(self, sim, state, all_sims, BG_COLOR):
        """Animate a single battle round. Returns True if user stayed."""
        paused = False
        tick_count = 0
        last_processed_tick = -1
        total_ticks_final = state["total_ticks"]
        
        # ── Визуальный индикатор скорости ────────────────────────────────
        # speed_display_timer и ticks_per_frame берутся из self (сохраняются между раундами)
        
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [], "critical_effects": []}

        while self.running:
            # ── ОБРАБОТКА СОБЫТИЙ — ОДИН РАЗ ЗА ИТЕРАЦИЮ! ─────────────────
            # pygame.event.get() очищает очередь, поэтому вызываем только один раз.
            # Все последующие проверки используют сохранённые события.
            
            events = pygame.event.get()

            for event in events:
                if event.type == pygame.QUIT:
                    return False
                elif event.type == pygame.KEYDOWN:
                    key = event.key
                    if key == KEY_LEADERBOARD:
                        self.leaderboard_open = not self.leaderboard_open
                        self.viewing_board = None
                    elif key == pygame.K_ESCAPE:
                        if self.leaderboard_open:
                            self.leaderboard_open = False
                        elif self.viewing_board is not None:
                            self.viewing_board = None
                        else:
                            return False
                    elif key == pygame.K_SPACE:
                        paused = not paused
                    elif key in (pygame.K_PLUS, pygame.K_EQUALS,
                                 getattr(pygame, 'K_KP_PLUS', None)):
                        self.ticks_per_frame = min(20, self.ticks_per_frame + 1)
                        self.speed_display_timer = 60  # показывать 2 секунды
                    elif key in (pygame.K_MINUS, getattr(pygame, 'K_KP_MINUS', None)):
                        self.ticks_per_frame = max(1, self.ticks_per_frame - 1)
                        self.speed_display_timer = 60  # показывать 2 секунды

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    clicked_participant = self.handle_player_list_click(mx, my)
                    if self.viewing_board is not None and not clicked_participant:
                        if getattr(self, "board_close_rect", None) and self.board_close_rect.collidepoint(mx, my):
                            self.viewing_board = None
                        elif getattr(self, "board_view_rect", None) and not self.board_view_rect.collidepoint(mx, my):
                            self.viewing_board = None
            
            if paused:
                self.clock.tick(30)
                continue
            
            self.screen.fill(BG_COLOR)

            # Визуальные эффекты: единая реализация на run() и _animate_battle()
            self._generate_battle_effects(
                sim, tick_count, last_processed_tick, effects)

            # Тряска экрана: бой рисуем на отдельный слой и блитим со смещением.
            # Иначе пришлось бы протаскивать offset во все вызовы draw_*.
            if self.shake > 0.3:
                surf = self.battle_surface
                surf.fill(BG_COLOR)
                self._draw_battle_scene(sim, effects, tick_count, target=surf)
                ox = int(self.shake * (self.rng_shake() * 2 - 1))
                oy = int(self.shake * (self.rng_shake() * 2 - 1))
                self.screen.blit(surf, (ox, oy))
                self.shake *= 0.86            # затухание
            else:
                self.shake = 0
                self._draw_battle_scene(sim, effects, tick_count)
            
            # Header
            is_creep = state["is_creep"]
            self.draw_header(state["round_number"], state["total_gold_after"],
                         is_creep, hp=state.get("hp"), player=self.player)
            
            # Battle log
            if sim.log:
                self.draw_battle_log(sim.log)
            
            # Tick counter
            tick_surf = self.font_tiny.render(
                f"Tick: {tick_count}/{total_ticks_final}", True, (150, 150, 255))
            self.screen.blit(tick_surf, (self.width // 2 - 40, 380))
            
            # ── Визуальный индикатор скорости ────────────────────────────
            if self.speed_display_timer > 0:
                self.speed_display_timer -= 1
                # Масштаб от 0→1→0 за время показа (плавное появление/исчезновение)
                alpha = min(self.speed_display_timer / 30, (60 - self.speed_display_timer) / 30)
                if alpha > 0:
                    speed_level = self.ticks_per_frame
                    label = "x1" if speed_level <= 1 else f"x{speed_level}"
                    
                    # Бейдж с фоном
                    badge_text = f"Speed: {label}"
                    badge_surf = self.font_tiny.render(badge_text, True, (255, 255, 100))
                    badge_rect = badge_surf.get_rect(center=(self.width // 2 - 40, 398))
                    
                    # Фон бейджа
                    pygame.draw.rect(self.screen, (40, 40, 60), 
                                    (badge_rect.x - 4, badge_rect.y - 2, badge_rect.w + 8, badge_rect.h + 4), 
                                    border_radius=4)
                    pygame.draw.rect(self.screen, (150, 150, 100),
                                    (badge_rect.x - 4, badge_rect.y - 2, badge_rect.w + 8, badge_rect.h + 4),
                                    width=1, border_radius=4)
                    self.screen.blit(badge_surf, badge_rect)
            
            # ── Панель участников (всегда видима в бою) ──
            participants = self._gather_participants()
            self.draw_player_list_panel(participants)
            # Модальные оверлеи поверх боя
            if self.leaderboard_open:
                self.draw_leaderboard(participants)
            elif self.viewing_board is not None:
                view = self._find_participant(participants)
                if view is not None:
                    self.draw_board_view(view)

            pygame.display.flip()
            
            # Process 1 tick per frame for visible battle animation
            if tick_count < total_ticks_final:
                last_processed_tick = tick_count
                tick_count += self.ticks_per_frame
            
            # Check if we've finished the round
            if tick_count >= total_ticks_final:
                # Show result briefly.
                # Раньше здесь был `tick_count - 1` — экран результата
                # перерисовывался предПОСЛЕДНЬ кадром, поэтому поверженный
                # враг выглядел живым с полной зеленой полоской HP.
                # total_ticks_final == числу снапшотов, т.е. это финальное
                # состояние, где проигравшие уже мертвы.
                self.screen.fill(BG_COLOR)
                self._draw_battle_scene(
                    sim,
                    {"damage_numbers": [], "death_effects": [], "lines": []},
                    total_ticks_final,
                )
                
                # ── Панель участников (всегда видима в бою) ──
                participants = self._gather_participants()
                self.draw_player_list_panel(participants)
                # Модальные оверлеи поверх экрана завершения раунда
                if self.leaderboard_open:
                    self.draw_leaderboard(participants)
                elif self.viewing_board is not None:
                    view = self._find_participant(participants)
                    if view is not None:
                        self.draw_board_view(view)
                
                winner = state["battle_result"]["winner"]
                ticks = state["battle_result"].get("ticks", "?")
                result_text = f"ROUND {state['round_number']} COMPLETE"
                self.draw_round_title(result_text)
                
                winner_surf = self.font_small.render(
                    f"{winner.upper()} wins ({ticks} ticks)", True, (255, 200, 100))
                r = winner_surf.get_rect(center=(self.width // 2, self.height // 2 + 40))
                self.screen.blit(winner_surf, r)
                
                gold_text = f"+{state['gold_earned']} gold (+{state['interest_earned']}% interest)"
                gold_surf = self.font_tiny.render(gold_text, True, (150, 255, 150))
                r = gold_surf.get_rect(center=(self.width // 2, self.height // 2 + 70))
                self.screen.blit(gold_surf, r)

                # Потеря здоровья — важнее золота, показываем отдельно
                hp_lost = state.get("hp_lost", 0)
                if hp_lost:
                    hp_text = f"-{hp_lost} HP  (осталось {state.get('hp', '?')})"
                    hp_color = (255, 90, 90) if state.get("hp", 100) <= 30 else (255, 180, 90)
                    hp_surf = self.font_small.render(hp_text, True, hp_color)
                    r = hp_surf.get_rect(center=(self.width // 2, self.height // 2 + 95))
                    self.screen.blit(hp_surf, r)

                pygame.display.flip()
                for _ in range(90):
                    if not self.running: return False
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT: return False
                        if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                            break  # клик или клавиша пропускают паузу
                    else:
                        self.clock.tick(30)
                        continue
                    break
                
                return True
            
            # Process 30fps for battle animation
            self.clock.tick(30)
        
        return False


def main():
    """Entry point for the UI."""
    from game.core.round import run_match

    print("Running match...")
    game = run_match(seed=42, verbose=False)
    print(game.get_summary())

    ui = GameUI(width=1200, height=800)
    ui.run(game)


if __name__ == "__main__":
    main()
