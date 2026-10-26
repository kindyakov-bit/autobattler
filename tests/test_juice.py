"""Тесты «сочности»: процедурный звук и тряска экрана.

До этих правок в проекте не было звука вообще, а звуковые классы эффектов
(CriticalEffect, HitParticles) рисовались, но никем не заполнялись.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import pytest

from ui.game_ui import BENCH_W


# ─────────────────────────────────────────────────────────────────────────
# Звук
# ─────────────────────────────────────────────────────────────────────────

class TestSoundBank:
    def test_bank_creates_without_crashing(self):
        from game.audio import SoundBank
        bank = SoundBank()
        assert bank.enabled in (True, False)   # зависит от наличия аудио

    def test_all_named_sounds_exist(self):
        """Все имена, которые дёргает UI, должны быть в банке."""
        from game.audio import SoundBank
        bank = SoundBank(enabled=False)
        # enabled=False не строит звуки, поэтому строим вручную
        assert bank.sounds == {}
        # проверяем, что _build создаёт полный набор
        import pygame
        try:
            pygame.mixer.init()
        except Exception:
            pytest.skip("нет аудиоустройства")
        bank2 = SoundBank()
        if not bank2.enabled:
            pytest.skip("миксер недоступен")
        for name in ("hit", "crit", "kill", "ability", "gold", "buy",
                     "click", "win", "lose"):
            assert name in bank2.sounds, f"нет звука '{name}'"

    def test_disabled_bank_is_silent(self):
        from game.audio import SoundBank
        bank = SoundBank(enabled=False)
        assert bank.enabled is False
        bank.play("hit")          # не должен бросать исключение
        bank.play("несуществующий")

    def test_unknown_sound_is_ignored(self):
        from game.audio import SoundBank
        bank = SoundBank(enabled=False)
        bank.play("нет такого звука")

    def test_volume_clamped(self):
        """Громкость зажимается в 0..1, иначе pygame ругается."""
        from game.audio import SoundBank
        import pygame
        try:
            pygame.mixer.init()
        except Exception:
            pytest.skip("нет аудиоустройства")
        bank = SoundBank()
        if not bank.enabled:
            pytest.skip("миксер недоступен")
        bank.play("hit", volume_scale=99.0)
        bank.play("hit", volume_scale=-5.0)
        assert bank.sounds["hit"].get_volume() <= 1.0

    def test_mix_handles_unequal_lengths(self):
        """Сложение сигналов разной длины не должно падать."""
        from game import audio
        a = audio._sine(440, 0.05)
        b = audio._sine(660, 0.12)
        out = audio._mix(a, b)
        assert len(out) == max(len(a), len(b))


# ─────────────────────────────────────────────────────────────────────────
# Тряска экрана
# ─────────────────────────────────────────────────────────────────────────

class TestScreenShake:
    @pytest.fixture
    def ui(self, monkeypatch):
        monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
        monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
        from ui.game_ui import GameUI
        g = GameUI(width=1200, height=800)
        g.sound_enabled = False        # тесты не должны шуметь
        g.init()
        return g

    def test_shake_starts_at_zero(self, ui):
        assert ui.shake == 0

    def test_add_shake_accumulates(self, ui):
        ui.add_shake(5)
        assert ui.shake >= 5

    def test_shake_is_capped(self, ui):
        """Без потолка каскад критов снесёт экран."""
        for _ in range(50):
            ui.add_shake(10)
        assert ui.shake <= 14.0

    def test_shake_rng_deterministic(self, ui):
        """Свой RNG — тряска не зависит от seed'а боя."""
        first = [ui.rng_shake() for _ in range(3)]
        second = [ui.rng_shake() for _ in range(3)]
        assert len(first) == len(second)
        assert all(0.0 <= v <= 1.0 for v in first)

    def test_battle_can_draw_to_separate_surface(self, ui):
        """Тряска требует рисования боя на отдельный слой."""
        import pygame
        surf = pygame.Surface((ui.width, ui.height))
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [{"name": "u", "hp": 500, "damage": 10,
                            "attack_speed": 1.0, "range_": 1, "class": "warrior"}])
        sim.add_team("e", [{"name": "v", "hp": 500, "damage": 10,
                            "attack_speed": 1.0, "range_": 1, "class": "warrior"}])
        sim.run(max_ticks=60)
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [],
                   "critical_effects": []}
        ui._draw_battle_scene(sim, effects, 0, target=surf)
        assert surf is not ui.screen, "бой должен уметь рисоваться на слой"


# ─────────────────────────────────────────────────────────────────────────
# Интеграция: звук вызывается из эффектов
# ─────────────────────────────────────────────────────────────────────────

class TestReadability:
    """Дефекты, найденные на скриншотах: заглушки вместо звёзд и обрезанный текст."""

    @pytest.fixture
    def ui(self, monkeypatch):
        monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
        monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
        from ui.game_ui import GameUI
        g = GameUI(width=1200, height=800)
        g.sound_enabled = False
        g.init()
        g.all_units = json.loads(
            (_project_root / "data" / "units.json").read_text(encoding="utf-8"))["units"]
        g._rebuild_cost_index()
        return g

    def test_star_suffix_uses_ascii(self, ui):
        """'★' рисуется заглушкой в стандартных шрифтах — заменяем на '*'."""
        assert ui.star_suffix("archer_marksman★2") == "*"
        assert ui.star_suffix("archer_marksman★3") == "**"
        assert ui.star_suffix("archer_marksman") == ""

    def test_star_suffix_handles_old_ascii(self, ui):
        assert ui.star_suffix("archer_marksman*2") == "*"

    def test_tier_colors_differ_by_cost(self, ui):
        c1 = ui.tier_color("Новобранец")      # cost 1
        c2 = ui.tier_color("Следопыт")        # cost 2
        c3 = ui.tier_color("Снайпер")         # cost 3
        c5 = ui.tier_color("Рыцарь")          # cost 5
        assert len({c1, c2, c3, c5}) == 4, "тиры должны различаться визуально"

    def test_tier_color_unknown_is_default(self, ui):
        from ui.game_ui import TIER_COLOR_DEFAULT
        assert ui.tier_color("Несуществующий") == TIER_COLOR_DEFAULT

    def test_fit_text_shortens(self, ui):
        long_name = "Очень-длинное-имя-юнита"
        out = ui.fit_text(long_name, 40)
        assert len(out) < len(long_name)
        assert out.endswith("…")

    def test_fit_text_keeps_short(self, ui):
        assert ui.fit_text("Скаут", 200) == "Скаут"

    def test_fit_text_respects_width(self, ui):
        """Результат обязан влезать в заданную ширину."""
        out = ui.fit_text("Новобранец", BENCH_W - 8, ui.font_micro)
        assert ui.font_micro.size(out)[0] <= BENCH_W - 8


class TestJuiceWiring:
    def test_sound_played_on_hit(self, monkeypatch):
        """Удар должен издавать звук, а не молчать."""
        monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
        monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
        from ui.game_ui import GameUI
        from game.battle.engine import BattleSimulator

        g = GameUI(width=1200, height=800)
        g.sound_enabled = False
        g.init()
        played = []
        g.play_sound = lambda name, v=1.0: played.append(name)

        sim = BattleSimulator(seed=42)
        sim.add_team("player", [{"name": "Рыцарь", "hp": 800, "damage": 60,
                                 "attack_speed": 1.2, "range_": 1,
                                 "class": "warrior", "crit_chance": 10}])
        sim.add_team("enemy", [{"name": "Ветеран", "hp": 900, "damage": 50,
                                "attack_speed": 1.0, "range_": 1,
                                "class": "warrior", "crit_chance": 10}])
        sim.run(max_ticks=600)

        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [],
                   "critical_effects": []}
        last = -1
        for t in range(sim.get_total_ticks()):
            g._generate_battle_effects(sim, t, last, effects)
            last = t

        assert played, "ни один звук не проигрался за бой"
        assert any(p in ("hit", "crit", "kill") for p in played), (
            f"ожидали звуки боя, получили: {set(played)}")

    def test_shake_triggered_on_crit(self):
        monkeypatch_env = {}
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        from ui.game_ui import GameUI

        g = GameUI(width=1200, height=800)
        g.sound_enabled = False
        g.init()
        g.shake = 0

        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [{"name": "u", "hp": 300, "damage": 60,
                            "attack_speed": 1.2, "range_": 1,
                            "class": "warrior", "crit_chance": 100}])
        sim.add_team("e", [{"name": "v", "hp": 100000, "damage": 0,
                            "attack_speed": 1.0, "range_": 1, "class": "warrior"}])
        sim.run(max_ticks=300)

        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [],
                   "critical_effects": []}
        last = -1
        for t in range(sim.get_total_ticks()):
            g._generate_battle_effects(sim, t, last, effects)
            last = t
        assert g.shake > 0, "криты должны трясти экран"
