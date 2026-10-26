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

# ── Раскладка фазы драфта (одна True на отрисовку и на клики мышью) ──────────
# Хитбоксы и рисование обязаны использовать одни и те же числа, иначе
# «невидимые» слоты остаются кликабельными, а видимые — нет.
SHOP_X0, SHOP_Y0, SHOP_W, SHOP_H, SHOP_STEP = 20, 85, 100, 95, 110

BENCH_X0, BENCH_Y0, BENCH_W, BENCH_H = 20, 235, 85, 26
BENCH_COLS, BENCH_ROW_H, BENCH_MAX = 5, 32, 10

BOARD_X0, BOARD_Y0, BOARD_W, BOARD_H = 20, 240, 85, 30   # BOARD_X0 += width // 3
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

    def rng_shake(self) -> float:
        """Случайное число 0..1 для тряски."""
        return self.shake_rng.random()

    def tier_color(self, display_name: str):
        """Цвет рамки по цене юнита. display_name — русское имя из JSON."""
        cost = self._cost_by_display_name.get(display_name)
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
                  tier_color=None):
        """Draw a unit with HP bar and ability cooldown indicator.

        target=None рисует на главный экран (драфт, результаты);
        при тряске бой рисуется на отдельный слой.
        tier_color — цвет рамки по цене юнита (см. TIER_COLORS).
        """
        surf = target if target is not None else self.screen
        name = unit_dict.get("name", "?")
        hp = unit_dict.get("hp", 0)
        max_hp = unit_dict.get("_base_hp", unit_dict.get("hp", 100))

        rect_w, rect_h = 140, 50
        pygame.draw.rect(surf, team_color, (x, y, rect_w, rect_h), border_radius=6)
        pygame.draw.rect(surf, tier_color or (255, 255, 255),
                         (x, y, rect_w, rect_h), width=1, border_radius=6)

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
                                 round_num: int, is_creep: bool, synergy_data: dict):
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

        # ── SHOP section ────────────────────────────────────────────────
        pygame.draw.rect(self.screen, (40, 60, 80), (10, 55, self.width - 20, 130), border_radius=8)
        shop_title = self.font_small.render("SHOP — R=roll N=next", True, (200, 200, 200))
        self.screen.blit(shop_title, (20, 65))

        item_x = SHOP_X0
        slot_color = (60, 80, 100)
        for i, item in enumerate(shop_items[:10]):
            x = item_x + i * SHOP_STEP
            if x > self.width - 120:
                break
            color = slot_color
            name_key = item.get("name", "?")
            # Показываем русское имя из units.json вместо английского ключа
            if not name_key.startswith("ITEM:"):
                name = self.all_units.get(name_key, {}).get("name", name_key)
            else:
                name = name_key
            cost = item.get("cost", 1)

            # Подсветка выбранного shop item
            border_color = (255, 255, 100) if i == self.selected_shop_idx else (100, 150, 200)
            border_width = 3 if i == self.selected_shop_idx else 1
            pygame.draw.rect(self.screen, color, (x, 85, 100, 95), border_radius=6)
            pygame.draw.rect(self.screen, border_color, (x, 85, 100, 95), width=border_width, border_radius=6)

            name_surf = self.font_tiny.render(
                self.fit_text(name, SHOP_W - 10), True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 5, 90))

            cost_surf = self.font_tiny.render(f"${cost}", True, (255, 215, 0))
            self.screen.blit(cost_surf, (x + 5, 110))

            # Рамка тира — сразу видно, что за юнит в слоте
            if border_color != (255, 255, 100):
                border_color = self.tier_color(name)

        # ── BENCH section ───────────────────────────────────────────────
        pygame.draw.rect(self.screen, (30, 50, 70), (10, 195, self.width // 3 - 20, 180), border_radius=8)
        bench_title = self.font_small.render(f"BENCH ({len(player.reserve)}) — D=place", True, (200, 200, 200))
        self.screen.blit(bench_title, (20, 205))

        for i, unit_name in enumerate(player.reserve[:BENCH_MAX]):
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
            name_surf = self.font_micro.render(
                self.fit_text(display_name, BENCH_W - 8, self.font_micro),
                True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 3, y + 4))

        # ── BOARD section ───────────────────────────────────────────────
        pygame.draw.rect(self.screen, (40, 70, 40), (self.width // 3 + 10, 195, self.width // 3 - 20, 180), border_radius=8)
        board_title = self.font_small.render(f"BOARD ({len(player.board)}/6) — F=remove", True, (200, 200, 200))
        self.screen.blit(board_title, (self.width // 3 + 20, 205))

        for i, unit in enumerate(player.board[:6]):
            x = BOARD_X0 + self.width // 3 + (i % BOARD_COLS) * (
                (self.width // 3 - 40) // BOARD_COLS)
            y = BOARD_Y0 + (i // BOARD_COLS) * BOARD_ROW_H

            # Переводим английский ключ на русское имя (до использования!)
            unit_name = unit.get("name", "?")
            base = unit_name.split("★")[0]
            ru_name = self.all_units.get(base, {}).get("name", base)
            display_name = ru_name + self.star_suffix(unit_name)

            # Подсветка board slot (при наведении)
            if self.selected_bench_idx is None and self.selected_shop_idx is None:
                border_color = (255, 255, 100)
            else:
                border_color = self.tier_color(display_name)
            border_width = 2
            pygame.draw.rect(self.screen, slot_color, (x, y, BOARD_W, BOARD_H), border_radius=4)
            pygame.draw.rect(self.screen, border_color, (x, y, BOARD_W, BOARD_H), width=border_width, border_radius=4)
            name_surf = self.font_micro.render(
                self.fit_text(display_name, BOARD_W - 8, self.font_micro),
                True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 3, y + 4))

        # ── Synergy info ────────────────────────────────────────────────
        syn_x = self.width // 3 * 2 + 10
        syn_title = self.font_small.render("SYNERGIES", True, (200, 200, 200))
        self.screen.blit(syn_title, (syn_x, 205))
        for idx, cls_name in enumerate(["warrior", "mage", "archer"]):
            count = player.get_synergy_count(cls_name)
            if count > 0:
                syn_color = (100, 255, 100) if count >= 2 else (200, 200, 100)
                syn_text = self.font_tiny.render(f"{cls_name}: {count}", True, syn_color)
                self.screen.blit(syn_text, (syn_x, 225 + idx * 20))

        # ── Inventory ───────────────────────────────────────────────────
        # Раньше метод _draw_items_section() не вызывался нигде, поэтому
        # купленные предметы было не видно.
        self._draw_items_section(player.items)

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
        pygame.draw.rect(self.screen, (50, 40, 70), (inv_x - 10, inv_y - 5, self.width // 3 - 30, len(items) * 35 + 20), border_radius=8)
        
        inv_title = self.font_small.render("INVENTORY", True, (200, 150, 200))
        self.screen.blit(inv_title, (inv_x, inv_y))
        inv_y += 25
        
        for i, item in enumerate(items[:4]):
            x = inv_x
            y = inv_y + i * 35
            color = (80, 60, 100)
            pygame.draw.rect(self.screen, color, (x, y, 100, 28), border_radius=4)
            
            # Item icon (colored square based on type)
            item_type = item.get("type", "accessory")
            if item_type == "armor":
                icon_color = (150, 150, 150)
            elif item_type == "weapon":
                icon_color = (200, 50, 50)
            elif item_type == "legendary":
                icon_color = (255, 215, 0)
            else:
                icon_color = (100, 150, 255)
            
            pygame.draw.rect(self.screen, icon_color, (x + 3, y + 3, 8, 22), border_radius=2)
            
            name_surf = self.font_tiny.render(item.get("name", "?"), True, (255, 255, 255))
            self.screen.blit(name_surf, (x + 14, y + 4))

    def _mixed_roll(self, shop, count=7, item_count=3):
        """Смешанный ролл: юниты + предметы."""
        unit_items = shop.roll(count=count)
        try:
            item_items = shop.roll_items(count=item_count)
            # Добавляем префикс 'ITEM:' для предметов чтобы различать
        except Exception:
            item_items = []
        
        all_items = list(unit_items) + [{"name": f"ITEM:{i['name']}", "cost": i["cost"], "item_key": i.get("item_key", "")} for i in item_items]
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

        rng = random.Random(seed + round_num * 100)
        pool = Pool(unit_costs)
        shop = Shop(pool, unit_costs=unit_costs, item_data=items_data.get("items", {}), rng=rng)
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
                if len(player.board) < 6:
                    player.board.append(
                        {"name": name, "star": star, **u.get("stats", {})})
                else:
                    player.reserve.append(name)

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

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = event.pos
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
                        # ── BENCH ── (те же координаты, что и при отрисовке)
                        cell_w = (self.width // 3 - 40) // BENCH_COLS
                        for i in range(min(len(player.reserve), BENCH_MAX)):
                            bx = BENCH_X0 + (i % BENCH_COLS) * cell_w
                            by = BENCH_Y0 + (i // BENCH_COLS) * BENCH_ROW_H
                            rect = pygame.Rect(bx, by, BENCH_W, BENCH_H)
                            if rect.collidepoint(mx, my):
                                if len(player.board) < 6:
                                    try:
                                        draft_phase.place_on_board(player, i)
                                        name_base = player.board[-1]["name"].split("★")[0]
                                        if name_base in all_units:
                                            ud = all_units[name_base]
                                            unit = player.board[-1]
                                            shop.set_base_stats(player, len(player.board) - 1,
                                                                int(ud["hp"] * (1.5 if unit.get("star", 1) == 2 else 2.0 if unit.get("star", 1) == 3 else 1)),
                                                                int(ud["damage"] * (1.5 if unit.get("star", 1) == 2 else 2.0 if unit.get("star", 1) == 3 else 1)),
                                                                ud["attack_speed"])
                                    except Exception:
                                        pass
                                self.selected_bench_idx = i
                                self.selected_shop_idx = None
                                break
                        else:
                            # ── BOARD ──
                            cell_w2 = (self.width // 3 - 40) // BOARD_COLS
                            for i in range(len(player.board)):
                                cx = BOARD_X0 + self.width // 3 + (i % BOARD_COLS) * cell_w2
                                cy = BOARD_Y0 + (i // BOARD_COLS) * BOARD_ROW_H
                                rect = pygame.Rect(cx, cy, BOARD_W, BOARD_H)
                                if rect.collidepoint(mx, my):
                                    try:
                                        draft_phase.remove_from_board(player, i)
                                    except Exception:
                                        pass
                                    self.selected_bench_idx = None
                                    self.selected_shop_idx = None
                                    break

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
                    "name": name_base,
                    "hp": int(ud["hp"] * hp_mult),
                    "damage": int(ud["damage"] * dmg_mult),
                    "attack_speed": ud["attack_speed"],
                    "range_": ud["range"],
                    "class": ud["class"],
                    "crit_chance": ud.get("crit_chance", 0),
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

        return player_units, player.gold

    def _get_unit_positions(self, player_units, enemy_units):
        """Get (x,y) positions for each unit on screen."""
        cx = self.width // 2
        cy = 100
        unit_w = 150
        positions = {}

        for i in range(len(player_units)):
            x = 30 + i * (unit_w + 10)
            y = cy + i * 70
            cx_pos = x + 70  # center of unit rect
            cy_pos = y + 25
            positions[player_units[i]] = (cx_pos, cy_pos)

        for i in range(len(enemy_units)):
            x = cx + 50 + i * (unit_w + 10)
            y = cy + i * 70
            cx_pos = x + 70
            cy_pos = y + 25
            positions[enemy_units[i]] = (cx_pos, cy_pos)

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
                {"name": unit.name, "hp": unit.hp, "_base_hp": unit.max_hp},
                rect_x, rect_y, PLAYER_COLOR, target=surf,
                ability_name=ability_name,
                ability_cooldown=ability_cooldown,
                ability_cooldown_max=ability_cooldown_max,
                tier_color=self.tier_color(unit.name),
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
                {"name": unit.name, "hp": unit.hp, "_base_hp": unit.max_hp},
                rect_x, rect_y, ENEMY_COLOR, target=surf,
                ability_name=ability_name,
                ability_cooldown=ability_cooldown,
                ability_cooldown_max=ability_cooldown_max,
                tier_color=self.tier_color(unit.name),
            )

        # Draw dead units (faded)
        # set_alpha на главной поверхности pygame не работает — прозрачность
        # делаем затемнённым цветом карточки.
        for unit in player_units:
            if not unit.alive:
                x, y = positions[unit]
                self.draw_unit(
                    {"name": unit.name, "hp": 0, "_base_hp": unit.max_hp},
                    x - 70, y - 25, (45, 45, 55), target=surf
                )

        for unit in enemy_units:
            if not unit.alive:
                x, y = positions[unit]
                self.draw_unit(
                    {"name": unit.name, "hp": 0, "_base_hp": unit.max_hp},
                    x - 70, y - 25, (45, 45, 55), target=surf
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
        # Купленные юниты между раундами. Крип-раунды их не сбрасывают.
        stored_player_units = None

        for round_num in range(1, 9):
            # Раунды 1-3 — крипы, потом каждый третий (6, 9, ...) — крип, остальные — PvP
            is_creep = round_num <= 3 or round_num % 3 == 0

            # ── Драфт игрока. С ПЕРВОГО раунда. ────────────────────────────
            # Раньше крип-раунды шли с захардкоженным составом, то есть три
            # раунда из восьми были кат-сценой без единого решения игрока.
            existing = {"units": stored_player_units, "gold": gold} \
                if stored_player_units else None
            result = self._run_interactive_draft(
                round_num=round_num,
                is_creep=is_creep,
                synergy_data=data["synergies"],
                seed=seed,
                existing_units=existing,
            )
            if result is None:
                return  # user quit
            player_units, gold = result
            stored_player_units = player_units

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
            sim = BattleSimulator(seed=seed + round_num)
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
            econ = round_economy(
                gold=gold, pvp_win=pvp_win, creep_win=creep_win,
                hp=hp, is_creep=is_creep,
                surviving_enemy_units=surviving_enemies)
            gold = econ["gold_after"]
            hp = econ["hp_after"]
            eliminated = econ["is_eliminated"]

            state = {
                "round_number": round_num,
                "is_creep": is_creep,
                "gold_earned": econ["income"],
                "interest_earned": econ["interest"],
                "total_gold_after": gold,
                "hp": hp,
                "hp_lost": econ["hp_lost"],
                "eliminated": eliminated,
                "battle_result": battle_result,
                "total_ticks": total_ticks,
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
                self.clock.tick(30)

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
                    self.clock.tick(30)
                
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
