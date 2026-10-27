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
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from ui.sprites import draw_unit_sprite, draw_item_icon, draw_tooltip

# ── Раскладка фазы драфта (одна True на отрисовку и на клики мышью) ──────────
# Хитбоксы и рисование обязаны использовать одни и те же числа, иначе
# «невидимые» слоты остаются кликабельными, а видимые — нет.
SHOP_X0, SHOP_Y0, SHOP_W, SHOP_H, SHOP_STEP = 20, 85, 95, 105, 100

BENCH_X0, BENCH_Y0, BENCH_W, BENCH_H = 20, 268, 85, 26
BENCH_COLS, BENCH_ROW_H, BENCH_MAX = 5, 32, 10

BOARD_X0, BOARD_Y0, BOARD_W, BOARD_H = 20, 268, 85, 30   # BOARD_X0 += width // 3
BOARD_COLS, BOARD_ROW_H = 3, 35

# Цвет рамки по цене юнита — как в TFT/Underlords: сразу видно, что дорого.
# Ключ — цена из data/units.json.
TIER_COLORS = {
    1: (150, 150, 150),   # обычный
    2: (90, 200, 120),    # необычный
    3: (90, 150, 255),    # редкий
    5: (200, 120, 255),   # легендарный
}
TIER_COLOR_DEFAULT = (150, 150, 150)

# Символ звезды. '★' (U+2605) отсутствует в стандартных шрифтах pygame и
# рисуется квадратом-заглушкой, поэтому используем '*'.
STAR_CHAR = "*"

# Килл-бонус: золото за каждого убитого врага (экономика «фарм на боях»).
KILL_GOLD_PER_UNIT = 1


# ── Visual effects system ────────────────────────────────────────────────

class DamageNumber:
    """Floating damage number that appears on a unit."""
    def __init__(self, x, y, amount, color=(255, 100, 50)):
        self.x = x
        self.y = y
        self.amount = int(amount)
        self.color = color
        self.life = 40  # frames to live
        self.max_life = 40

    def update(self):
        self.y -= 1.5
        self.life -= 1
        return self.life > 0

    def draw(self, screen, font):
        surf = font.render(f"-{self.amount}", True, self.color)
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
            try:
                _font = pygame.font.SysFont("arial", 16, bold=True)
            except Exception:
                _font = pygame.font.Font(None, 16)
            name_surf = _font.render(self.ability_name.upper(), True, 
                                  self.COLORS.get(self.effect_type, ((255, 255, 0)))[1])
            r = name_surf.get_rect(center=(int(self.x), int(self.y) - self.ring_radius - 15))
            screen.blit(name_surf, r)

    def _font_render(self, text, bold, color):
        try:
            return pygame.font.SysFont("arial", 16, bold=bold).render(text, True, color)
        except Exception:
            return pygame.font.Font(None, 16).render(text, True, color)


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

    def draw_unit(self, unit_dict, x, y, team_color, target=None,
                  ability_name=None, ability_cooldown=0, ability_cooldown_max=0,
                  tier_color=None, unit_class=None, star=1, race=None):
        """Draw a unit with HP bar and ability cooldown indicator.

        target=None рисует на главный экран (драфт, результаты);
        при тряске бой рисуется на отдельный слой.
        tier_color — цвет рамки по цене юнита (см. TIER_COLORS).
        unit_class — класс юнита для процедурного силуэта (warrior/mage/archer).
        star — звёздность 1..3 (рисуются звёздочки в углу).
        race — раса юнита для окраски силуэта (human/orc/demon/elf/undead).
        """
        surf = target if target is not None else self.screen
        name = unit_dict.get("name", "?")
        hp = unit_dict.get("hp", 0)
        max_hp = unit_dict.get("_base_hp", unit_dict.get("hp", 100))

        rect_w, rect_h = 140, 50
        # Фон карточки — цвет команды
        pygame.draw.rect(surf, team_color, (x, y, rect_w, rect_h), border_radius=6)
        # Процедурный силуэт юнита по классу + цвет тира + звёзды
        cls = unit_class or unit_dict.get("class", "warrior")
        unit_race = race or unit_dict.get("race", "human")
        draw_unit_sprite(
            surf, x + 6, y + 8, rect_w - 12, rect_h - 20,
            cls, tier_color=tier_color, star=star, race=unit_race,
        )

        # HP bar
        hp_pct = max(0, min(1.0, hp / max(max_hp, 1)) if max_hp > 0 else 0)
        bar_w = int((rect_w - 8) * hp_pct)
        if hp_pct > 0.5:
            bar_color = (60, 200, 60)
        elif hp_pct > 0.25:
            bar_color = (220, 180, 40)
        else:
            bar_color = (200, 40, 40)

        if bar_w > 0:
            pygame.draw.rect(surf, bar_color,
                           (x + 4, y + rect_h - 10, bar_w, 6), border_radius=3)

        # Unit name
        name_surf = self.font_tiny.render(name, True, (255, 255, 255))
        surf.blit(name_surf, (x + 4, y + 6))

        # Ability name + cooldown indicator
        if ability_name:
            ready = ability_cooldown <= 0
            ability_color = (100, 255, 100) if ready else (255, 220, 50)
            ability_surf = self.font_tiny.render(ability_name, True, ability_color)
            surf.blit(ability_surf, (x + 4, y + 22))

            # Cooldown progress ring (right side of unit card)
            ring_cx = x + rect_w - 20
            ring_cy = y + rect_h // 2
            ring_r = 12
            ring_w = 3
            # Background ring
            pygame.draw.circle(surf, (60, 60, 60), (ring_cx, ring_cy), ring_r, ring_w)
            if not ready and ability_cooldown_max > 0:
                # Filled arc showing remaining cooldown
                progress = 1.0 - (ability_cooldown / ability_cooldown_max)
                end_angle = -90 + progress * 360
                # Draw arc as series of lines
                for angle in range(-90, int(end_angle)):
                    rad = math.radians(angle)
                    px = ring_cx + int(math.cos(rad) * ring_r)
                    py = ring_cy + int(math.sin(rad) * ring_r)
                    pygame.draw.circle(surf, ability_color, (px, py), 2)
            else:
                # Ready — solid fill
                pygame.draw.circle(surf, (100, 255, 100), (ring_cx, ring_cy), ring_r - 1)

        # HP text
        hp_text = f"{int(hp)}/{max_hp}"
        hp_surf = self.font_tiny.render(hp_text, True, (200, 200, 200))
        surf.blit(hp_surf, (x + 4, y + rect_h - 8))

    def play_sound(self, name: str, volume: float = 1.0):
        """Проиграть звук, если звук включён."""
        if self.sound is None:
            return
        self.sound.play(name, volume)

    def add_shake(self, amount: float):
        """Добавить тряску экрана (в пикселях, максимум 14)."""
        self.shake = min(14.0, self.shake + amount)

    def draw_header(self, round_num, gold, is_creep, hp=None):
        """Draw header with round info and player's match HP."""
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

    def draw_battle_log(self, log, max_lines=6):
        """Draw battle event log on the right side."""
        y_start = self.height - (max_lines * 20)
        for i, event in enumerate(log[-max_lines:]):
            if event.get("type") == "kill":
                text = f"KILL tick {event.get('tick', '?')}"
                color = (255, 100, 100)
            else:
                dmg = event.get("damage", 0)
                text = f"[{event.get('tick', '?')}] hit: {dmg:.0f} dmg"
                color = (200, 200, 200)

            surf = self.font_tiny.render(text, True, color)
            self.screen.blit(surf, (self.width - 350, y_start + i * 20))

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
        """Draw detailed post-battle statistics: damage, kills, stars."""
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        cx = self.width // 2
        y = self.height // 2 - 110

        # Заголовок
        title = self.font_large.render("ИТОГ БОЯ", True, (255, 215, 0))
        self.screen.blit(title, title.get_rect(center=(cx, y)))
        y += 35

        # Урон и киллы по командам
        dmg = state.get("dmg_by_team", {})
        kills = state.get("kills_by_team", {})

        # Определяем имена команд из ключей (player/enemy или bot1/bot2)
        teams = list(dmg.keys())
        if len(teams) >= 2:
            t1, t2 = teams[0], teams[1]
        else:
            t1, t2 = "player", "enemy"

        t1_dmg = dmg.get(t1, 0)
        t2_dmg = dmg.get(t2, 0)
        t1_k = kills.get(t1, 0)
        t2_k = kills.get(t2, 0)

        # Русифицируем названия команд для отображения
        t1_label = "Игрок" if t1 == "player" else t1
        t2_label = "Враг" if t2 == "enemy" else t2

        line = f"Урон:  {t1_label} {t1_dmg}   {t2_label} {t2_dmg}"
        surf = self.font_small.render(line, True, (200, 200, 200))
        self.screen.blit(surf, surf.get_rect(center=(cx, y)))
        y += 22

        line = f"Киллы: {t1_label} {t1_k}   {t2_label} {t2_k}"
        surf = self.font_small.render(line, True, (200, 200, 200))
        self.screen.blit(surf, surf.get_rect(center=(cx, y)))
        y += 35

        # Топ по урону
        top_d = state.get("top_damage", [])
        if top_d:
            surf = self.font_small.render("Топ урона:", True, (255, 215, 0))
            self.screen.blit(surf, (cx - 150, y))
            y += 22
            for name, dmg_val, team, star in top_d:
                star_str = "★" * star if star > 1 else ""
                line = f"  {name}{star_str}  {dmg_val}"
                surf = self.font_tiny.render(line, True, (180, 180, 180))
                self.screen.blit(surf, (cx - 150, y))
                y += 18
            y += 12

        # Топ по киллам
        top_k = state.get("top_kills", [])
        if top_k:
            surf = self.font_small.render("Топ киллов:", True, (255, 215, 0))
            self.screen.blit(surf, (cx - 150, y))
            y += 22
            for name, k, team, star in top_k:
                star_str = "★" * star if star > 1 else ""
                line = f"  {name}{star_str}  {k}x"
                surf = self.font_tiny.render(line, True, (180, 180, 180))
                self.screen.blit(surf, (cx - 150, y))
                y += 18

        # Подсказка
        hint = self.font_tiny.render("Клик или клавиша — продолжить", True, (120, 120, 120))
        self.screen.blit(hint, hint.get_rect(center=(cx, self.height - 40)))

    def draw_controls(self):
        """Draw control hints at bottom."""
        text = "SPACE=Pause  +/-=Speed  ESC=Quit"
        surf = self.font_tiny.render(text, True, (150, 150, 150))
        self.screen.blit(surf, (self.width // 2 - 200, self.height - 16))

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

    def draw_draft_phase(self, player, shop_items: list[dict], gold: int, 
                         round_num: int, is_creep: bool, synergy_data: dict):
        """Draw draft phase UI with shop items, bench, and board."""
        self.screen.fill((20, 30, 40))

        # Header
        status = "CREEP" if is_creep else "PvP"
        header = f"ROUND {round_num} - DRAFT [{status}]"
        surf = self.font_large.render(header, True, (255, 255, 100))
        r = surf.get_rect(center=(self.width // 2, 40))
        self.screen.blit(surf, r)

        # Gold display
        gold_surf = self.font_small.render(f"Gold: {gold}", True, (255, 215, 0))
        self.screen.blit(gold_surf, (self.width - 150, 8))

        # Draw shop items (top section)
        pygame.draw.rect(self.screen, (40, 60, 80), (10, 70, self.width - 20, 120), border_radius=8)
        shop_title = self.font_small.render("SHOP (N=Next roll)", True, (200, 200, 200))
        self.screen.blit(shop_title, (20, 80))

        item_x = 20
        for i, item in enumerate(shop_items[:10]):
            x = item_x + i * 110
            if x > self.width - 120:
                break
            # Item card
            color = (60, 80, 100)
            name = item.get("name", "?")
            cost = item.get("cost", 1)

            # Background
            pygame.draw.rect(self.screen, color, (x, 100, 100, 85), border_radius=6)
            pygame.draw.rect(self.screen, (100, 150, 200), (x, 100, 100, 85), width=1, border_radius=6)

            # Name
            name_surf = self.font_tiny.render(name, True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 5, 105))

            # Cost
            cost_surf = self.font_tiny.render(f"${cost}", True, (255, 215, 0))
            self.screen.blit(cost_surf, (x + 5, 125))

        # Draw bench (left section)
        pygame.draw.rect(self.screen, (30, 50, 70), (10, 200, self.width // 3 - 20, 200), border_radius=8)
        bench_title = self.font_small.render("BENCH (Click to place)", True, (200, 200, 200))
        self.screen.blit(bench_title, (20, 210))

        bench_y = 240
        for i, unit_name in enumerate(player.reserve[:10]):
            x = 20 + (i % 5) * ((self.width // 3 - 40) // 5)
            y = bench_y + (i // 5) * 35
            color = (80, 100, 120) if "★" not in unit_name else (120, 80, 160)
            pygame.draw.rect(self.screen, color, (x, y, 90, 28), border_radius=4)
            name_surf = self.font_tiny.render(unit_name, True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 5, y + 5))

        # Draw board (right section)
        pygame.draw.rect(self.screen, (40, 70, 40), (self.width // 3 + 10, 200, self.width // 3 - 20, 200), border_radius=8)
        board_title = self.font_small.render("BOARD (Click to remove)", True, (200, 200, 200))
        self.screen.blit(board_title, (self.width // 3 + 20, 210))

        for i, unit in enumerate(player.board[:6]):
            x = self.width // 3 + 20 + (i % 3) * ((self.width // 3 - 40) // 3)
            y = 250 + (i // 3) * 40
            color = (100, 160, 100) if unit.get("star", 1) == 1 else (160, 100, 160)
            pygame.draw.rect(self.screen, color, (x, y, 90, 32), border_radius=4)
            name_surf = self.font_tiny.render(unit.get("name", "?"), True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 5, y + 5))

        # Synergy info
        synergy_counts = player.get_synergy_count
        syn_x = self.width // 3 * 2 + 10
        for cls_name in ["warrior", "mage", "archer"]:
            count = synergy_counts(cls_name)
            if count > 0:
                color = (100, 255, 100) if count >= 2 else (200, 200, 100)
                syn_text = self.font_tiny.render(f"{cls_name}: {count}", True, color)
                self.screen.blit(syn_text, (syn_x, 230 + list(["warrior", "mage", "archer"]).index(cls_name)) * 25)

        # Controls hint
        controls = "W=Buy(1) S=Sell D=Place F=Remove R=Roll"
        ctrl_surf = self.font_tiny.render(controls, True, (150, 150, 150))
        self.screen.blit(ctrl_surf, (self.width // 2 - 200, self.height - 40))

    def _draw_interactive_draft(self, player, shop_items: list[dict], gold: int,
                                 round_num: int, is_creep: bool, synergy_data: dict,
                                 shop=None):
        """Draw interactive draft phase with keyboard controls."""
        self.screen.fill((20, 30, 40))

        # Header
        status = "CREEP" if is_creep else "PvP"
        header = f"ROUND {round_num} - DRAFT [{status}]"
        surf = self.font_large.render(header, True, (255, 255, 100))
        r = surf.get_rect(center=(self.width // 2, 30))
        self.screen.blit(surf, r)

        # Gold display
        gold_surf = self.font_small.render(f"Gold: {gold}", True, (255, 215, 0))
        self.screen.blit(gold_surf, (self.width - 150, 8))

        # ── SHOP section (карточки с именем + силуэт + стоимость + звёзды + синергии) ──
        mx, my = pygame.mouse.get_pos()
        shop_y = 85
        SHOP_H = 105
        SHOP_W = 95
        SHOP_STEP = 100
        item_x = SHOP_X0
        slot_color = (60, 80, 100)
        max_shop_slots = min(len(shop_items), 10)

        # Правая вертикальная панель: реролл + апгрейд уровня
        right_panel_x = self.width - 130
        right_panel_y = shop_y
        right_panel_w = 115
        right_panel_h = SHOP_H
        pygame.draw.rect(self.screen, (40, 60, 80),
                         (right_panel_x, right_panel_y, right_panel_w, right_panel_h), border_radius=6)

        # Кнопка реролла магазина (клик мышью)
        reroll_rect = pygame.Rect(right_panel_x + 10, right_panel_y + 8, right_panel_w - 20, 26)
        hover_reroll = reroll_rect.collidepoint(mx, my)
        pygame.draw.rect(self.screen, (80, 120, 160) if not hover_reroll else (120, 160, 200),
                         reroll_rect, border_radius=4)
        rr_surf = self.font_tiny.render("Reroll ($1)", True, (255, 255, 255))
        self.screen.blit(rr_surf, rr_surf.get_rect(center=reroll_rect.center))
        if hover_reroll:
            draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                         "Перебросить витрину магазина\nза 1 золото (клавиша R)", self.font_tiny)

        # Уровень магазина: иконка + текст + клик по иконке — апгрейд за золото
        if shop is not None:
            lvl = shop.level
            up_cost = shop.upgrade_cost
            up_text = f"upgrade(${up_cost})" if up_cost else "max"
            max_cost = shop.MAX_COST_BY_LEVEL.get(lvl, 1)
            unit_candidates = [u for u, c in shop.unit_costs.items()
                               if c <= max_cost and shop.pool.available(u) > 0]
            unit_chance_pct = int(100 / len(unit_candidates)) if unit_candidates else 0
            item_chance_pct = int(100 / len(shop.item_data)) if shop.item_data else 0
        else:
            lvl = 1
            up_cost = None
            up_text = "max"
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

        # Иконка уровня магазина — круг с цифрой (ниже кнопки реролла)
        icon_r = 14
        icon_cx = right_panel_x + right_panel_w // 2
        icon_cy = right_panel_y + 68
        self.lvl_icon_rect = pygame.Rect(icon_cx - icon_r, icon_cy - icon_r,
                                         icon_r * 2, icon_r * 2)
        hover_lvl = self.lvl_icon_rect.collidepoint(mx, my)
        pygame.draw.circle(self.screen, lvl_color, (icon_cx, icon_cy), icon_r)
        pygame.draw.circle(self.screen, (255, 255, 255), (icon_cx, icon_cy), icon_r, width=2)
        lvl_digit = self.font_tiny.render(str(lvl), True, (30, 30, 40))
        self.screen.blit(lvl_digit, lvl_digit.get_rect(center=(icon_cx, icon_cy)))

        # Текст уровня под иконкой
        lvl_text = self.font_tiny.render(f"lvl {lvl}", True, lvl_color)
        self.screen.blit(lvl_text, lvl_text.get_rect(center=(icon_cx, icon_cy + 18)))
        up_surf = self.font_tiny.render(up_text, True, (200, 200, 100))
        self.screen.blit(up_surf, up_surf.get_rect(center=(icon_cx, icon_cy + 32)))

        if hover_lvl:
            tip = f"Уровень магазина {lvl}\nШанс юнита: {unit_chance_pct}%\n"
            if up_cost is not None:
                tip += f"Апгрейд: ${up_cost} (клик)\n"
            else:
                tip += "Макс. уровень\n"
            tip += f"Шанс предмета: {item_chance_pct}%"
            draw_tooltip(self.screen, right_panel_x, right_panel_y + right_panel_h + 4,
                         tip, self.font_tiny)

        # Карточки юнитов в витрине магазина
        for i in range(max_shop_slots):
            item = shop_items[i]
            x = item_x + i * SHOP_STEP
            name_key = item.get("name", "?")
            if not name_key.startswith("ITEM:"):
                name = self.all_units.get(name_key, {}).get("name", name_key)
                cls = self.all_units.get(name_key, {}).get("class", "warrior")
                cost = self.all_units.get(name_key, {}).get("cost", 1)
            else:
                name = name_key[len("ITEM:"):]
                cls = None
                cost = item.get("cost", 1)

            # Наведение на shop slot
            slot_rect = pygame.Rect(x, shop_y, SHOP_W, SHOP_H)
            hovered = slot_rect.collidepoint(mx, my)
            if hovered:
                self.hover_shop_idx = i

            border_color = (255, 255, 100) if i == self.selected_shop_idx else (100, 150, 200)
            border_width = 3 if i == self.selected_shop_idx else 1
            if hovered:
                border_color = (255, 215, 0)
                border_width = 2
            pygame.draw.rect(self.screen, (60, 80, 100), slot_rect, border_radius=6)
            pygame.draw.rect(self.screen, border_color, slot_rect, width=border_width, border_radius=6)

            # Имя юнита над картинкой
            name_surf = self.font_tiny.render(
                self.fit_text(name, SHOP_W - 6), True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 3, shop_y + 4))

            # Силуэт юнита в центре карточки
            if name_key.startswith("ITEM:"):
                draw_item_icon(self.screen, x + SHOP_W // 2, shop_y + 42, 34,
                               item.get("type", "accessory"))
            else:
                ud = self.all_units.get(name_key, {})
                draw_unit_sprite(
                    self.screen, x + 12, shop_y + 16, SHOP_W - 24, 46,
                    cls, tier_color=self.tier_color(name), star=1,
                    race=ud.get("race", "human"),
                )

            # Стоимость в правом верхнем углу карточки
            cost_surf = self.font_tiny.render(f"${cost}", True, (255, 215, 0))
            self.screen.blit(cost_surf, (x + SHOP_W - cost_surf.get_width() - 4,
                                         shop_y + SHOP_H - 18))

            # Tooltip при наведении
            if hovered:
                if name_key.startswith("ITEM:"):
                    # Предмет: что он делает (описание + статы), без шанса
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
                    if desc:
                        tooltip += f"\n{desc}"
                    if stats_text:
                        tooltip += f"\n{stats_text}"
                else:
                    # Юнит: способности (пассивка + активка), класс, без шанса
                    ud = self.all_units.get(name_key, {})
                    unit_desc = ud.get("description", "")
                    lines = [f"{name}\n${cost}", f"Класс: {cls}"]
                    if unit_desc:
                        lines.append(unit_desc)
                    passive = ud.get("passive")
                    if passive:
                        lines.append(
                            f"Пассивка: {passive.get('name', '')} — {passive.get('desc', '')}"
                        )
                    active = ud.get("active")
                    if active:
                        cd = active.get("cooldown")
                        cd_text = f" (к/д {cd} тиков)" if cd else ""
                        lines.append(
                            f"Активка: {active.get('name', '')} — {active.get('desc', '')}{cd_text}"
                        )
                    tooltip = "\n".join(lines)
                draw_tooltip(self.screen, x, shop_y + SHOP_H + 18, tooltip, self.font_tiny)

        # ── BENCH section (юниты в запасе, внизу) ──
        pygame.draw.rect(self.screen, (30, 50, 70), (10, BENCH_Y0, self.width // 3 - 20, 180), border_radius=8)
        bench_title = self.font_small.render(f"BENCH ({len(player.reserve)}) — D=place", True, (200, 200, 200))
        self.screen.blit(bench_title, (20, BENCH_Y0 + 8))

        for i, unit_name in enumerate(player.reserve[:BENCH_MAX]):
            # Пропускаем юнт, которого сейчас тащат (рисуем его под курсором)
            if i == self.drag_bench_idx:
                continue
            x = BENCH_X0 + (i % BENCH_COLS) * ((self.width // 3 - 40) // BENCH_COLS)
            y = BENCH_Y0 + (i // BENCH_COLS) * BENCH_ROW_H
            # Переводим английский ключ на русское имя
            base = unit_name.split("★")[0]
            ru_name = self.all_units.get(base, {}).get("name", base)
            # Звёздность — через '*', иначе глиф '★' рисуется заглушкой
            display_name = ru_name + self.star_suffix(unit_name)
            # Подсветка выбранного bench slot
            if i == self.selected_bench_idx:
                border_color = (255, 255, 100)
            else:
                border_color = self.tier_color(display_name)
            border_width = 3 if i == self.selected_bench_idx else 1
            pygame.draw.rect(self.screen, slot_color, (x, y, BENCH_W, BENCH_H), border_radius=4)
            pygame.draw.rect(self.screen, border_color, (x, y, BENCH_W, BENCH_H), width=border_width, border_radius=4)
            # Силуэт юнита наベンче
            ud = self.all_units.get(base, {})
            draw_unit_sprite(
                self.screen, x + 4, y + 2, 24, 14,
                ud.get("class", "warrior"),
                tier_color=border_color,
                star=int(unit_name.split("★")[1]) if "★" in unit_name else 1,
                race=ud.get("race", "human"),
            )
            name_surf = self.font_micro.render(
                self.fit_text(display_name, BENCH_W - 8, self.font_micro),
                True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 3, y + 18))

        # ── BOARD section — тактическое поле 5×5 ──
        field_x0 = self.width // 3 + 10
        field_y0 = BOARD_Y0
        field_w = max(BOARD_W * 5, self.width // 3 - 20)  # минимум 5 слотов по BOARD_W
        field_h = max(BOARD_H * 6, 180)                    # минимум 6 слотов по BOARD_H
        cell_w = field_w // 5
        cell_h = field_h // 5

        pygame.draw.rect(self.screen, (40, 70, 40),
                         (field_x0, field_y0, field_w, field_h), border_radius=8)
        board_title = self.font_small.render(
            f"ПОЛЕ 5×5 ({len(player.board)}/6) — клик: поставить/убрать",
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

        for r in range(5):
            for c in range(5):
                cx = field_x0 + c * cell_w + 2
                cy = field_y0 + 30 + r * cell_h + 2
                cw = cell_w - 4
                ch = cell_h - 4
                cell_rect = pygame.Rect(cx, cy, cw, ch)
                hovered = cell_rect.collidepoint(mx, my)

                unit = occupied.get((r, c))
                if unit:
                    # Юнит стоит на клетке
                    border_color = (255, 255, 100) \
                        if (r, c) == self.selected_field_cell else (100, 200, 100)
                    pygame.draw.rect(self.screen, (60, 100, 60),
                                     cell_rect, border_radius=3)
                    pygame.draw.rect(self.screen, border_color,
                                     cell_rect, width=2, border_radius=3)

                    base = unit["name"].split("★")[0]
                    ud = self.all_units.get(base, {})
                    draw_unit_sprite(
                        self.screen, cx + 4, cy + 2, 28, 18,
                        ud.get("class", "warrior"),
                        tier_color=self.tier_color(unit.get("name", "?")),
                        star=unit.get("star", 1),
                        race=ud.get("race", "human"),
                    )
                    name_surf = self.font_micro.render(
                        self.fit_text(ud.get("name", base), cw - 8, self.font_micro),
                        True, (255, 255, 255))
                    self.screen.blit(name_surf, (cx + 4, cy + 20))
                else:
                    # Пустая клетка
                    border_color = (80, 100, 80) if not hovered else (120, 150, 120)
                    if (r, c) == self.selected_field_cell:
                        border_color = (255, 255, 100)
                    pygame.draw.rect(self.screen, (30, 50, 30),
                                     cell_rect, border_radius=3)
                    pygame.draw.rect(self.screen, border_color,
                                     cell_rect, width=1, border_radius=3)

        # Подсказка под полем
        hint_surf = self.font_tiny.render(
            "Выберите юнта на бенче, затем клик по клетке поля",
            True, (150, 150, 150))
        self.screen.blit(hint_surf, (field_x0 + 5, field_y0 + field_h - 16))

        # Отрисовываем тащущегося юнита поверх всего (драг энд дроп)
        if self.drag_bench_idx is not None and self.drag_bench_idx < len(player.reserve):
            mx, my = pygame.mouse.get_pos()
            unit_name = player.reserve[self.drag_bench_idx]
            base = unit_name.split("★")[0]
            ud = self.all_units.get(base, {})
            draw_unit_sprite(
                self.screen, mx - 14, my - 9,
                28, 18,
                ud.get("class", "warrior"),
                tier_color=self.tier_color(unit_name),
                star=int(unit_name.split("★")[1]) if "★" in unit_name else 1,
                race=ud.get("race", "human"),
            )

        # Отрисовываем тащущегося юнита с поля на новую клетку
        if self.drag_board_idx is not None and self.drag_board_data is not None:
            mx, my = pygame.mouse.get_pos()
            unit_name = self.drag_board_data.get("name", "?")
            base = unit_name.split("★")[0]
            ud = self.all_units.get(base, {})
            draw_unit_sprite(
                self.screen, mx - 14, my - 9,
                28, 18,
                ud.get("class", "warrior"),
                tier_color=self.tier_color(unit_name),
                star=int(unit_name.split("★")[1]) if "★" in unit_name else 1,
                race=ud.get("race", "human"),
            )

        # ── Synergy info ────────────────────────────────────────────────
        syn_x = self.width // 3 * 2 + 10
        syn_title = self.font_small.render("SYNERGIES", True, (200, 200, 200))
        self.screen.blit(syn_title, (syn_x, BOARD_Y0 + 8))
        for idx, cls_name in enumerate(["warrior", "mage", "archer"]):
            count = player.get_synergy_count(cls_name)
            if count > 0:
                syn_color = (100, 255, 100) if count >= 2 else (200, 200, 100)
                syn_text = self.font_tiny.render(f"{cls_name}: {count}", True, syn_color)
                self.screen.blit(syn_text, (syn_x, BOARD_Y0 + 21 + idx * 20))

        # ── Inventory ───────────────────────────────────────────────────
        # Раньше метод _draw_items_section() не вызывался нигде, поэтому
        # купленные предметы было не видно.
        self._draw_items_section(player.items)

        # ── Кнопка начала раунда (клик мышью или Enter) ─────────────────
        start_rect = pygame.Rect(self.width // 2 - 75, self.height - 90, 150, 30)
        hover_start = start_rect.collidepoint(mx, my)
        pygame.draw.rect(self.screen, (60, 140, 60) if not hover_start else (90, 180, 90),
                         start_rect, border_radius=6)
        pygame.draw.rect(self.screen, (200, 200, 100), start_rect, width=1, border_radius=6)
        start_surf = self.font_small.render("Начать раунд (Enter)", True, (255, 255, 255))
        self.screen.blit(start_surf, start_surf.get_rect(center=start_rect.center))

        # ── Controls hint ───────────────────────────────────────────────
        controls = "W=Buy  S=Sell  D=Place  F=Remove  R=Roll  I=Item  A=Apply  Enter=Done  |  Клик: шоп/бенч/доска"
        ctrl_surf = self.font_tiny.render(controls, True, (150, 150, 150))
        self.screen.blit(ctrl_surf, (self.width // 2 - 310, self.height - 30))

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
                stats = item.get("stats", {})
                stat_text = ", ".join(f"{k}: {v}" for k, v in stats.items()) if stats else ""
                tooltip = (f"{name}\n${item.get('cost', '?')}  {item_type}\n"
                           f"{stat_text}\n{item.get('description', '')}\n"
                           "Клик — выбрать, затем клик по юниту на доске")
                draw_tooltip(self.screen, x, y + 34, tooltip, self.font_tiny)

    def _mixed_roll(self, shop, count=7, item_count=3):
        """Смешанный ролл: юниты + предметы."""
        unit_items = shop.roll(count=count)
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

        # Уровень магазина переживает раунды: авто-рост каждый раунд
        # (кроме первого) + докупка за золото клавишей U
        if not hasattr(self, "shop_level"):
            self.shop_level = 1
        if round_num > 1:
            # авто-рост: каждый новый раунд магазин подрастает (макс. 6)
            self.shop_level = min(6, self.shop_level + 1)
        shop.level = self.shop_level
        draft_phase = DraftPhase(shop, all_units)

        self.all_units = all_units  # Для отображения имён на русском в магазине
        self._rebuild_cost_index()

        gold = 10 if existing_units is None else existing_units.get("gold", 10)
        player = Player(gold=gold)

        if existing_units is None:
            # First round — buy starting warrior (Shop сам списывает золото)
            try:
                shop.buy(player, "warrior_freshman", cost=1)
            except Exception:
                pass
        else:
            # Восстанавливаем купленных юнитов. Они хранились с ДОСКИ, поэтому
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
                # Восстанавливаем юнта на доске с его позицией на тактическом поле.
                # row/col хранятся на верхнем уровне unit_data, а не внутри stats.
                name_base = name.split("★")[0]
                unit_data = {"name": name, "star": star}
                if u.get("row") is not None:
                    unit_data["row"] = u.get("row")
                if u.get("col") is not None:
                    unit_data["col"] = u.get("col")
                if len(player.board) < 6:
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
                else:
                    player.reserve.append(name)

            # Восстанавливаем предметы между раундами (иначе пропадают после каждого боя)
            saved_items = existing_units.get("items", [])
            if saved_items:
                player.items = [dict(it) for it in saved_items]

        # Mixed shop: units + items
        shop_items = self._mixed_roll(shop, count=7, item_count=3)

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
                        if player.gold >= 1:
                            player.gold -= 1
                            try:
                                # роллим и юнитов, и предметы — иначе после
                                # нажатия R из магазина пропадали предметы
                                shop_items = self._mixed_roll(
                                    shop, count=7, item_count=3)
                            except Exception:
                                pass

                    elif key == pygame.K_n:
                        try:
                            shop_items = self._mixed_roll(
                                shop, count=7, item_count=3)
                        except Exception:
                            pass

                    elif key == pygame.K_u:
                        # Апгрейд магазина за золото (механика прокачки)
                        if shop.upgrade(player):
                            self.shop_level = shop.level
                            self.play_sound("gold")
                            try:
                                shop_items = self._mixed_roll(
                                    shop, count=7, item_count=3)
                            except Exception:
                                pass

                    elif key == pygame.K_w:
                        # Shop.buy() уже списывает золото — второй раз не вычитаем
                        try:
                            draft_phase.buy_unit(player, "warrior_freshman")
                        except Exception:
                            pass

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
                        if player.reserve and len(player.board) < 6:
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
                                                       int(ud["hp"] * (1.5 if unit.get("star", 1) == 2 else 2.0 if unit.get("star", 1) == 3 else 1)),
                                                       int(ud["damage"] * (1.5 if unit.get("star", 1) == 2 else 2.0 if unit.get("star", 1) == 3 else 1)),
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

                elif event.type == pygame.MOUSEMOTION:
                    pass  # позиция мыши берется напрямую при отрисовке

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
                    # ── Кнопка реролла магазина (клик мышью) ──
                    reroll_rect = pygame.Rect(self.width - 120, 93, 95, 26)
                    if reroll_rect.collidepoint(mx, my):
                        if player.gold >= 1:
                            player.gold -= 1
                            try:
                                shop_items = self._mixed_roll(
                                    shop, count=7, item_count=3)
                                self.play_sound("click")
                            except Exception:
                                pass
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # ── Иконка уровня магазина: клик — апгрейд за золото ──
                    if (self.lvl_icon_rect
                            and self.lvl_icon_rect.collidepoint(mx, my)
                            and shop is not None):
                        if shop.upgrade(player):
                            self.shop_level = shop.level
                            self.play_sound("gold")
                            try:
                                shop_items = self._mixed_roll(
                                    shop, count=7, item_count=3)
                            except Exception:
                                pass
                        self.selected_shop_idx = None
                        self.selected_bench_idx = None
                        break
                    # ── Кнопка начала раунда ──
                    start_rect = pygame.Rect(self.width // 2 - 75,
                                             self.height - 90, 150, 30)
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
                        for i, item in enumerate(shop_items[:10]):
                            sx = SHOP_X0 + i * SHOP_STEP
                            if sx > self.width - 120:
                                break
                            rect = pygame.Rect(sx, SHOP_Y0, SHOP_W, SHOP_H)
                            if rect.collidepoint(mx, my):
                                name = item.get("name", "")
                                if name.startswith("ITEM:"):
                                    # Предмет
                                    item_key = item.get("item_key", "")
                                    try:
                                        shop.buy_item(player, item_key)
                                    except Exception:
                                        pass
                                else:
                                    # Юнит
                                    try:
                                        draft_phase.buy_unit(player, name)
                                        self.play_sound("buy")
                                    except Exception:
                                        pass
                                self.selected_shop_idx = i
                                self.selected_bench_idx = None
                                break
                        else:
                            # ── BENCH — начать перетаскивание (драг энд дроп) ──
                            bench_clicked = False
                            cell_w = (self.width // 3 - 40) // BENCH_COLS
                            for i in range(min(len(player.reserve), BENCH_MAX)):
                                bx = BENCH_X0 + (i % BENCH_COLS) * cell_w
                                by = BENCH_Y0 + (i // BENCH_COLS) * BENCH_ROW_H
                                rect = pygame.Rect(bx, by, BENCH_W, BENCH_H)
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
                                field_w = self.width // 3 - 20
                                field_h = 180
                                cell_w = field_w // 5
                                cell_h = field_h // 5

                                # Пропускаем заголовок поля (первые 30 пикселей по Y)
                                if my < field_y0 + 30:
                                    pass
                                else:
                                    click_r = (my - field_y0 - 30) // cell_h
                                    click_c = (mx - field_x0) // cell_w
                                    if 0 <= click_r < 5 and 0 <= click_c < 5:
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
                                                # Начать перетаскивание юнта с клетки поля на другую клетку
                                                self.drag_board_idx = unit_idx
                                                self.drag_board_orig = (unit_on_cell.get("row"),
                                                                       unit_on_cell.get("col"))
                                                self.drag_board_data = dict(unit_on_cell)
                                                # Временно убираем с поля (вернём в MOUSEBUTTONUP, если клетка занята)
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
                                                    "star": int(unit_name.split("★")[1]) if "★" in unit_name else 1,
                                                    "row": click_r,
                                                    "col": click_c,
                                                }
                                                name_base = unit_name.split("★")[0]
                                                if name_base in all_units:
                                                    ud = all_units[name_base]
                                                    player.board.append(new_unit)
                                                    shop.set_base_stats(
                                                        player, len(player.board) - 1,
                                                        int(ud["hp"] * (1.5 if new_unit.get("star", 1) == 2 else 2.0 if new_unit.get("star", 1) == 3 else 1)),
                                                        int(ud["damage"] * (1.5 if new_unit.get("star", 1) == 2 else 2.0 if new_unit.get("star", 1) == 3 else 1)),
                                                        ud["attack_speed"])
                                                self.play_sound("click")
                                            self.selected_field_cell = cell_key
                                            self.selected_bench_idx = None
                                            self.selected_shop_idx = None

                elif event.type == pygame.MOUSEBUTTONUP:
                    mx, my = event.pos
                    # ── Если тащили юнт сベンча — разместить на клетке поля ──
                    if self.drag_bench_idx is not None:
                        field_x0 = self.width // 3 + 10
                        field_y0 = BOARD_Y0
                        field_w = max(BOARD_W * 5, self.width // 3 - 20)
                        field_h = max(BOARD_H * 6, 180)
                        cell_w_f = field_w // 5
                        cell_h_f = field_h // 5
                        if my >= field_y0 + 30:
                            click_r = (my - field_y0 - 30) // cell_h_f
                            click_c = (mx - field_x0) // cell_w_f
                            if 0 <= click_r < 5 and 0 <= click_c < 5:
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
                                                "star": int(unit_name.split("★")[1]) if "★" in unit_name else 1,
                                                "row": click_r,
                                                "col": click_c,
                                            }
                                            name_base = unit_name.split("★")[0]
                                            if name_base in all_units:
                                                ud = all_units[name_base]
                                                player.board.append(new_unit)
                                                shop.set_base_stats(
                                                    player, len(player.board) - 1,
                                                    int(ud["hp"] * (1.5 if new_unit.get("star", 1) == 2 else 2.0 if new_unit.get("star", 1) == 3 else 1)),
                                                    int(ud["damage"] * (1.5 if new_unit.get("star", 1) == 2 else 2.0 if new_unit.get("star", 1) == 3 else 1)),
                                                    ud["attack_speed"])
                                                self.play_sound("click")
                        self.drag_bench_idx = None

                    # ── Если тащили юнт с клетки поля — разместить на новой клетке ──
                    elif self.drag_board_idx is not None:
                        field_x0 = self.width // 3 + 10
                        field_y0 = BOARD_Y0
                        field_w = max(BOARD_W * 5, self.width // 3 - 20)
                        field_h = max(BOARD_H * 6, 180)
                        cell_w_f = field_w // 5
                        cell_h_f = field_h // 5
                        placed = False
                        if my >= field_y0 + 30:
                            click_r = (my - field_y0 - 30) // cell_h_f
                            click_c = (mx - field_x0) // cell_w_f
                            if 0 <= click_r < 5 and 0 <= click_c < 5:
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
                                    name_base = unit_data["name"].split("★")[0]
                                    if name_base in all_units:
                                        ud = all_units[name_base]
                                        shop.set_base_stats(
                                            player, idx,
                                            int(ud["hp"] * (1.5 if unit_data.get("star", 1) == 2 else 2.0 if unit_data.get("star", 1) == 3 else 1)),
                                            int(ud["damage"] * (1.5 if unit_data.get("star", 1) == 2 else 2.0 if unit_data.get("star", 1) == 3 else 1)),
                                            ud["attack_speed"])
                                    self.play_sound("click")
                                    placed = True
                        if not placed:
                            # Клик на скамейке — вернуть юнта на скамейку (не на доску)
                            bench_x0 = BENCH_X0
                            bench_y0 = BENCH_Y0
                            bench_x1 = bench_x0 + (self.width // 3 - 40)
                            bench_y1 = bench_y0 + BENCH_ROW_H * 2  # до 2 рядов скамейки
                            on_bench = (
                                bench_x0 <= mx <= bench_x1
                                and bench_y0 <= my <= bench_y1
                                and len(player.reserve) < player.max_bench
                            )
                            if on_bench:
                                # Возвращаем на скамейку
                                unit_name = self.drag_board_data.get("name", "warrior_freshman")
                                star = self.drag_board_data.get("star", 1)
                                base = unit_name.split("★")[0]
                                name_with_star = f"{base}★{star}" if star > 1 else base
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
                                name_base = unit_data["name"].split("★")[0]
                                if name_base in all_units:
                                    ud = all_units[name_base]
                                    shop.set_base_stats(
                                        player, idx,
                                        int(ud["hp"] * (1.5 if unit_data.get("star", 1) == 2 else 2.0 if unit_data.get("star", 1) == 3 else 1)),
                                        int(ud["damage"] * (1.5 if unit_data.get("star", 1) == 2 else 2.0 if unit_data.get("star", 1) == 3 else 1)),
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
                shop=shop,
            )

            pygame.display.flip()
            self.clock.tick(30)

        # Convert board to battle format (with item bonuses)
        player_units = []
        for unit in player.board[:6]:
            name_base = unit["name"].split("★")[0]
            if name_base in all_units:
                ud = all_units[name_base]
                star = unit.get("star", 1)
                hp_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                dmg_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                
                # Start with base stats + star bonuses
                unit_data = {
                    # Имя с ★N: display_name в бою покажет звёзды, а
                    # restore следующего раунда прочитает star из поля.
                    # Раньше сюда писался чистый ключ и star вообще не
                    # сохранялся — скауты теряли звёзды каждый раунд.
                    "name": f"{name_base}★{star}" if star > 1 else name_base,
                    "star": star,
                    "hp": int(ud["hp"] * hp_mult),
                    "damage": int(ud["damage"] * dmg_mult),
                    "attack_speed": ud["attack_speed"],
                    "range_": ud["range"],
                    "class": ud["class"],
                    "race": ud.get("race", "human"),
                    "crit_chance": ud.get("crit_chance", 0),
                    # Позиция на тактическом поле 5×5 (если игрок поставил вручную)
                    "row": unit.get("row"),
                    "col": unit.get("col"),
                }

                # Add active ability if unit has one
                if ud.get("active"):
                    unit_data["active"] = dict(ud["active"])

                # Check if this unit has item bonuses stored
                if "item_bonuses" in unit:
                    unit_data["item_bonuses"] = unit["item_bonuses"]

                player_units.append(unit_data)

        if not player_units:
            player_units = [
                {"name": "warrior_freshman", "hp": 500, "damage": 40,
                 "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                {"name": "mage_acolyte", "hp": 300, "damage": 65,
                 "attack_speed": 1.0, "range_": 4, "class": "mage"},
            ]

        return player_units, player.gold, player.items

    def _get_unit_positions(self, player_units, enemy_units):
        """Позиции на тактическом поле 5×5: игрок слева (колонки 0-4),
        враг справа (колонки 5-9)."""
        cell_w = 100
        cell_h = 70
        offset_x = 60
        offset_y = 100
        enemy_offset_x = 600
        positions = {}

        for u in player_units:
            x = offset_x + u.col * cell_w
            y = offset_y + u.row * cell_h
            positions[u] = (x + cell_w // 2, y + cell_h // 2)

        for u in enemy_units:
            # Вражеские колонки 5-9 → сдвигаем на 5, чтобы получить 0-4 внутри правой половины
            x = offset_x + enemy_offset_x + (u.col - 5) * cell_w
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

        # Restore state from snapshot at the given frame index
        if frame_idx > 0 and frame_idx <= len(sim._tick_history):
            sim.restore_from_snapshot(sim._tick_history[frame_idx - 1])

        player_units = [u for u in sim.teams.get("player", [])]
        enemy_units = [u for u in sim.teams.get("enemy", [])]

        # Get positions for each unit
        positions = self._get_unit_positions(player_units, enemy_units)

        # Draw VS separator
        self.draw_vs(self.width // 2, 100, target=surf)

        # Draw attack lines first (behind units)
        for line in list(effects.get("lines", [])):
            if line.update():
                line.draw(surf)
            else:
                effects["lines"].remove(line)

        # Draw 5×5 grid lines for both sides so the tactical field is visible
        cell_w = 100
        cell_h = 70
        offset_x = 60
        offset_y = 100
        enemy_offset_x = 600
        grid_color = (60, 60, 80)
        # Player side: cols 0-4
        for c in range(6):
            x = offset_x + c * cell_w
            pygame.draw.line(surf, grid_color, (x, offset_y), (x, offset_y + 5 * cell_h), 1)
        for r in range(6):
            y = offset_y + r * cell_h
            pygame.draw.line(surf, grid_color, (offset_x, y), (offset_x + 5 * cell_w, y), 1)
        # Enemy side: cols 5-9 → local 0-4
        ex0 = offset_x + enemy_offset_x
        for c in range(6):
            x = ex0 + c * cell_w
            pygame.draw.line(surf, grid_color, (x, offset_y), (x, offset_y + 5 * cell_h), 1)
        for r in range(6):
            y = offset_y + r * cell_h
            pygame.draw.line(surf, grid_color, (ex0, y), (ex0 + 5 * cell_w, y), 1)

        # Draw each unit
        for unit in player_units:
            if not unit.alive:
                continue  # dead units are drawn as faded
            x, y = positions[unit]
            rect_x = x - 70
            rect_y = y - 25
            ability_name = unit.active_ability.get("name", "") if unit.active_ability else None
            ability_cooldown = unit.ability_cooldown
            ability_cooldown_max = unit.active_ability.get("cooldown", 0) if unit.active_ability else 0
            self.draw_unit(
                {"name": self.display_name(unit.name), "hp": unit.hp, "_base_hp": unit.max_hp},
                rect_x, rect_y, PLAYER_COLOR, target=surf,
                ability_name=ability_name,
                ability_cooldown=ability_cooldown,
                ability_cooldown_max=ability_cooldown_max,
                tier_color=self.tier_color(self.display_name(unit.name)),
                unit_class=getattr(unit, "unit_class", "warrior"),
                star=getattr(unit, "star", 1),
                race=getattr(unit, "race", "human"),
            )

        for unit in enemy_units:
            if not unit.alive:
                continue
            x, y = positions[unit]
            rect_x = x - 70
            rect_y = y - 25
            ability_name = unit.active_ability.get("name", "") if unit.active_ability else None
            ability_cooldown = unit.ability_cooldown
            ability_cooldown_max = unit.active_ability.get("cooldown", 0) if unit.active_ability else 0
            self.draw_unit(
                {"name": self.display_name(unit.name), "hp": unit.hp, "_base_hp": unit.max_hp},
                rect_x, rect_y, ENEMY_COLOR, target=surf,
                ability_name=ability_name,
                ability_cooldown=ability_cooldown,
                ability_cooldown_max=ability_cooldown_max,
                tier_color=self.tier_color(self.display_name(unit.name)),
                unit_class=getattr(unit, "unit_class", "warrior"),
                star=getattr(unit, "star", 1),
                race=getattr(unit, "race", "human"),
            )

        # Draw dead units (faded)
        # set_alpha на главной поверхности pygame не работает — прозрачность
        # делаем затемнённым цветом карточки.
        for unit in player_units:
            if not unit.alive:
                x, y = positions[unit]
                self.draw_unit(
                    {"name": self.display_name(unit.name), "hp": 0, "_base_hp": unit.max_hp},
                    x - 70, y - 25, (45, 45, 55), target=surf,
                    unit_class=getattr(unit, "unit_class", "warrior"),
                    star=getattr(unit, "star", 1),
                    race=getattr(unit, "race", "human"),
                )

        for unit in enemy_units:
            if not unit.alive:
                x, y = positions[unit]
                self.draw_unit(
                    {"name": self.display_name(unit.name), "hp": 0, "_base_hp": unit.max_hp},
                    x - 70, y - 25, (45, 45, 55), target=surf,
                    unit_class=getattr(unit, "unit_class", "warrior"),
                    star=getattr(unit, "star", 1),
                    race=getattr(unit, "race", "human"),
                )

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

            # Попадание: цифра урона + частицы (+ вспышка на крите)
            if etype in ("hit", "kill", "ability_hit", "ability_kill"):
                target = find_unit(event.get("target_id"))
                if target is None:
                    continue
                t_pos = positions.get(target)
                if t_pos is None:
                    continue
                dmg = event.get("damage", 0)
                is_kill = etype in ("kill", "ability_kill")
                is_crit = bool(event.get("is_critical"))
                dmg_color = (255, 50, 50) if is_kill else (255, 100, 50)
                effects["damage_numbers"].append(
                    DamageNumber(t_pos[0], t_pos[1] - 30, dmg, dmg_color))
                effects["hit_particles"].append(
                    HitParticles(t_pos[0], t_pos[1], is_critical=is_crit))
                if is_crit:
                    effects["critical_effects"].append(
                        CriticalEffect(t_pos[0], t_pos[1], dmg))
                    self.add_shake(3.5)          # крит трясёт
                if is_kill:
                    effects["death_effects"].append(DeathEffect(t_pos[0], t_pos[1]))
                    self.add_shake(2.0)

                # Звук: крит звонче, смерть ниже, обычный удар — хлопок
                if is_kill:
                    self.play_sound("kill")
                elif is_crit:
                    self.play_sound("crit")
                else:
                    self.play_sound("hit", 0.7)

            # Способность: расширяющееся кольцо с названием
            if (etype.startswith("ability") or "ability_name" in event
                    or "caster_id" in event):
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
                    if event.key == pygame.K_ESCAPE:
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
                self.draw_header(state.round_number, state.total_gold_after, state.is_creep)

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

    def run_interactive_match(self, seed=42, enemy_bot="balanced"):
        """Run a fully interactive match with draft phases.
        
        For PvP rounds (5+), player can buy/sell/place/remove units from shop.
        For creep rounds (1-4), auto-fills with default units.
        
        Keys during draft: W=Buy(1g) S=Sell-last D=Place F=Remove R=Roll N=Next Enter=Done
        During battle: SPACE=Pause +/-=Speed ESC=Quit
        """
        from game.core.round import load_game_data, build_creep_units
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
        unit_costs = {name: info["cost"] for name, info in all_units.items()}
        
        BG_COLOR = (20, 20, 30)

        gold = 10
        hp = START_HP
        history = []  # list of round result dicts
        all_sims = {}  # round_num -> BattleSimulator
        # Купленные юниты и предметы между раундами. Крип-раунды их не сбрасывают.
        stored_player_units = None
        stored_player_items = None

        for round_num in range(1, 9):
            # Раунды 1-3 — крипы, потом каждый третий (6, 9, ...) — крип, остальные — PvP
            is_creep = round_num <= 3 or round_num % 3 == 0

            # ── Драфт игрока. С ПЕРВОГО раунда. ────────────────────────────
            # Раньше крип-раунды шли с захардкоженным составом, то есть три
            # раунда из восьми были кат-сценой без единого решения игрока.
            existing = {
                "units": stored_player_units,
                "gold": gold,
                "items": stored_player_items,
            } if stored_player_units else None
            result = self._run_interactive_draft(
                round_num=round_num,
                is_creep=is_creep,
                synergy_data=data["synergies"],
                seed=seed,
                existing_units=existing,
            )
            if result is None:
                return  # user quit
            player_units, gold, stored_items = result
            stored_player_units = player_units
            stored_player_items = stored_items

            if is_creep:
                # Крипы: волна растёт с номером раунда (раньше была одинаковой),
                # количество подстраивается под размер доски игрока
                enemy_units = build_creep_units(round_num, all_units, player_units)
            else:
                # Bot drafts enemy units via shop — bot has its own economy (independent from player)
                bot_gold = 20  # bot economy — enough for a full board
                bot = create_bot(preset=enemy_bot, seed=seed + round_num)
                rng = random.Random(seed + round_num * 100)
                pool = Pool(unit_costs)
                shop = Shop(pool, unit_costs=unit_costs, rng=rng)
                draft_phase = DraftPhase(shop, all_units)
                enemy_player = Player(gold=bot_gold)
                
                # Bot decides what to buy with its own gold.
                # synergy_data раньше передавался пустым — из-за этого
                # синергийная логика MEDIUM-бота не работала никогда.
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
                            # buy_unit -> Shop.buy уже списывает золото
                            merged_name = draft_phase.buy_unit(enemy_player, name)
                            purchased.append(merged_name)
                        except Exception:
                            pass
                
                # Convert to battle format — use actually purchased units
                enemy_units = []
                for pu in purchased[:6]:
                    name = pu.split("★")[0]  # base name without star
                    if name in all_units:
                        ud = all_units[name]
                        star = 1
                        if "★" in pu:
                            star = int(pu.split("★")[1][1:])
                        hp_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                        dmg_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                        eu = {
                            "name": name,
                            "hp": int(ud["hp"] * hp_mult),
                            "damage": int(ud["damage"] * dmg_mult),
                            "attack_speed": ud["attack_speed"],
                            "range_": ud["range"],
                            "class": ud["class"],
                            "crit_chance": ud.get("crit_chance", 0),
                        }
                        if ud.get("active"):
                            eu["active"] = dict(ud["active"])
                        enemy_units.append(eu)
                
                if not enemy_units:
                    enemy_units = [
                        {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                        {"name": "mage_acolyte", "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4, "class": "mage"},
                    ]

                # Синергии и пассивки бота — симметрично игроку. Раньше
                # бонусы получали только player_units: бот строил синергию,
                # но воевал на сырых статах (доска есть, эффекта нет).
                enemy_units = apply_synergy_bonuses(
                    enemy_units, calculate_synergy_bonuses(enemy_units, data["synergies"]))
                if self.all_units:
                    passive = calculate_passive_bonuses(enemy_units, self.all_units)
                    enemy_units = apply_passive_bonuses(enemy_units, passive)
            
            # Бонусы синергий/пассивок — иначе в шапке написано "warrior: 2",
            # а бой идёт на сырых статах из JSON
            player_units = apply_synergy_bonuses(
                player_units, calculate_synergy_bonuses(player_units, data["synergies"]))
            if self.all_units:
                passive = calculate_passive_bonuses(player_units, self.all_units)
                player_units = apply_passive_bonuses(player_units, passive)

            # Run battle simulation
            sim = BattleSimulator(seed=seed + round_num, race_data=data["races"], race_synergy_data=data["race_synergies"])
            sim.add_team("player", player_units)
            sim.add_team("enemy", enemy_units)
            battle_result = sim.run()
            total_ticks = sim.get_total_ticks()
            
            # Economy + HP: проигранный PvP бьёт тем сильнее,
            # чем больше врагов уцелело
            pvp_win = not is_creep and battle_result["winner"] == "player"
            creep_win = is_creep and battle_result["winner"] == "player"
            surviving_enemies = sum(
                1 for u in sim.teams.get("enemy", []) if u.alive)
            # Килл-бонус: +1 золота за каждого убитого врага
            # (kill-события с killer_team=player; ability_kill не существует,
            # в движке смерть от способности тоже пишется как "kill")
            kills = sum(1 for e in sim.log
                        if e.get("type") == "kill"
                        and e.get("killer_team") == "player")
            kill_gold = KILL_GOLD_PER_UNIT * kills
            econ = round_economy(
                gold=gold, pvp_win=pvp_win, creep_win=creep_win,
                hp=hp, is_creep=is_creep,
                surviving_enemy_units=surviving_enemies)
            gold = econ["gold_after"] + kill_gold
            hp = econ["hp_after"]
            eliminated = econ["is_eliminated"]

            # ── Детальная статистика боя ───────────────────────────────────
            # Урон, киллы и топ юнитов из sim.log
            dmg_by_team = {}
            kills_by_team = {}
            dmg_by_unit = {}   # attacker_id -> damage
            kills_by_unit = {} # attacker_id -> kills
            unit_names = {}    # unit_id -> (name, team, star)
            for team_name, units in sim.teams.items():
                dmg_by_team[team_name] = 0
                kills_by_team[team_name] = 0
                for u in units:
                    unit_names[u.unit_id] = (u.name, team_name, getattr(u, "star", 1))

            for e in sim.log:
                etype = e.get("type")
                if etype in ("hit", "ability_hit"):
                    dmg = e.get("damage", 0)
                    attacker_id = e.get("attacker_id")
                    if attacker_id in unit_names:
                        _, team, _ = unit_names[attacker_id]
                        dmg_by_team[team] = dmg_by_team.get(team, 0) + dmg
                        dmg_by_unit[attacker_id] = dmg_by_unit.get(attacker_id, 0) + dmg
                elif etype == "kill":
                    attacker_id = e.get("attacker_id")
                    killer_team = e.get("killer_team")
                    if killer_team in kills_by_team:
                        kills_by_team[killer_team] += 1
                    if attacker_id in unit_names:
                        kills_by_unit[attacker_id] = kills_by_unit.get(attacker_id, 0) + 1

            # Топ по урону и киллам
            top_damage = sorted(
                ((unit_names[uid][0], dmg, unit_names[uid][1], unit_names[uid][2])
                 for uid, dmg in dmg_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_kills = sorted(
                ((unit_names[uid][0], k, unit_names[uid][1], unit_names[uid][2])
                 for uid, k in kills_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]

            state = {
                "round_number": round_num,
                "is_creep": is_creep,
                "gold_earned": econ["income"],
                "interest_earned": econ["interest"],
                "kill_gold": kill_gold,
                "total_gold_after": gold,
                "hp": hp,
                "hp_lost": econ["hp_lost"],
                "eliminated": eliminated,
                "battle_result": battle_result,
                "total_ticks": total_ticks,
                # Детальная статистика
                "dmg_by_team": dmg_by_team,
                "kills_by_team": kills_by_team,
                "top_damage": top_damage,
                "top_kills": top_kills,
            }
            history.append(state)
            all_sims[round_num] = sim
            
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
                    if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                        break  # клик или клавиша пропускают паузу
                else:
                    self.clock.tick(30)
                    # Рисуем статистику боя поверх анимации
                    self.screen.fill(BG_COLOR)
                    self.draw_battle_stats(state)
                    pygame.display.flip()
                    continue
                break

            # Здоровье кончилось — матч проигран
            if eliminated:
                break

        # ── Final result ────────────────────────────────────────────────
        self.screen.fill(BG_COLOR)

        player_wins = sum(1 for s in history if s["battle_result"]["winner"] == "player")
        if eliminated:
            winner = "enemy"
            verdict = "ВЫЛЕТЕЛИ"
        else:
            winner = "player" if player_wins > len(history) - player_wins else "enemy"
            verdict = "ПОБЕДА" if winner == "player" else "ПОРАЖЕНИЕ"

        self.draw_result(verdict, "?")
        self.play_sound("win" if winner == "player" else "lose")
        if eliminated:
            self.add_shake(10.0)      # вылет бьёт по нервам

        summary_surf = self.font_small.render(
            f"Раундов выиграно: {player_wins}/{len(history)}   |   HP: {hp}",
            True, (200, 200, 200))
        r = summary_surf.get_rect(center=(self.width // 2, self.height // 2 + 50))
        self.screen.blit(summary_surf, r)

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
            f"Всего урона: {total_dmg}   |   Всего киллов: {total_kills}",
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

        gold1 = 10
        gold2 = 10
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
                    except Exception:
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
                    except Exception:
                        pass
            gold2 = player2.gold

            # ── Формируем боевые составы ──────────────────────────────────
            def make_battle_units(purchased, all_units):
                units = []
                for pu in purchased[:6]:
                    name = pu.split("★")[0]
                    if name in all_units:
                        ud = all_units[name]
                        star = 1
                        if "★" in pu:
                            star = int(pu.split("★")[1][1:])
                        hp_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                        dmg_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
                        eu = {
                            "name": name,
                            "hp": int(ud["hp"] * hp_mult),
                            "damage": int(ud["damage"] * dmg_mult),
                            "attack_speed": ud["attack_speed"],
                            "range_": ud["range"],
                            "class": ud["class"],
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
            unit_names = {}
            for team_name, units in sim.teams.items():
                dmg_by_team[team_name] = 0
                kills_by_team[team_name] = 0
                for u in units:
                    unit_names[u.unit_id] = (u.name, team_name, getattr(u, "star", 1))

            for e in sim.log:
                etype = e.get("type")
                if etype in ("hit", "ability_hit"):
                    dmg = e.get("damage", 0)
                    attacker_id = e.get("attacker_id")
                    if attacker_id in unit_names:
                        _, team, _ = unit_names[attacker_id]
                        dmg_by_team[team] = dmg_by_team.get(team, 0) + dmg
                        dmg_by_unit[attacker_id] = dmg_by_unit.get(attacker_id, 0) + dmg
                elif etype == "kill":
                    attacker_id = e.get("attacker_id")
                    killer_team = e.get("killer_team")
                    if killer_team in kills_by_team:
                        kills_by_team[killer_team] += 1
                    if attacker_id in unit_names:
                        kills_by_unit[attacker_id] = kills_by_unit.get(attacker_id, 0) + 1

            top_damage = sorted(
                ((unit_names[uid][0], dmg, unit_names[uid][1], unit_names[uid][2])
                 for uid, dmg in dmg_by_unit.items()),
                key=lambda x: x[1], reverse=True)[:3]
            top_kills = sorted(
                ((unit_names[uid][0], k, unit_names[uid][1], unit_names[uid][2])
                 for uid, k in kills_by_unit.items()),
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

            # Если нет фокуса — активируем окно
            if not pygame.display.get_active():
                try:
                    pygame.display.set_mode((self.width, self.height), pygame.SRCALPHA)
                except Exception:
                    pass
            
            for event in events:
                if event.type == pygame.QUIT:
                    return False
                elif event.type == pygame.KEYDOWN:
                    key = event.key
                    if key == pygame.K_ESCAPE:
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

            # Draw battle scene
            self._draw_battle_scene(sim, effects, tick_count)
            
            # Header
            is_creep = state["is_creep"]
            self.draw_header(state["round_number"], state["total_gold_after"],
                         is_creep, hp=state.get("hp"))
            
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
