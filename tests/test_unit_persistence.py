"""Тесты переноса состава между раундами.

Два бага, которые видны только в игре:
  1. восстановленный юнит клался И на бенч, И на доску — 3 юнита выглядели
     как 6 карточек («клоны из ниоткуда»);
  2. звёздность терялась: имя собиралось как 'name★★' вместо 'name★2',
     а Shop.place парсит только цифру после '★'.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest


@pytest.fixture
def draft_env(monkeypatch):
    """GameUI + окружение _run_interactive_draft без окна."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    from ui.game_ui import GameUI
    g = GameUI(width=1200, height=800)
    g.sound_enabled = False
    g.init()
    return g


def run_draft(ui, units, gold=10, round_num=2):
    """Вызывает _run_interactive_draft и сразу выходит по Enter."""
    import pygame
    import pygame.event

    calls = {"n": 0}

    def fake_get():
        calls["n"] += 1
        if calls["n"] > 1:
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)]
        return []

    real = pygame.event.get
    pygame.event.get = fake_get
    try:
        return ui._run_interactive_draft(
            round_num=round_num, is_creep=False, synergy_data={},
            seed=42, existing_units={"units": units, "gold": gold})
    finally:
        pygame.event.get = real


class TestNoDuplicateUnits:
    def test_restored_unit_not_duplicated(self, draft_env):
        """Юнит не должен оказаться одновременно на бенче и на доске."""
        units = [{"name": "warrior_freshman", "star": 1}]
        result = run_draft(draft_env, units)
        assert result is not None
        player_units, _ = result
        # бой строится с доски — там должен быть ровно 1 юнит
        assert len(player_units) == 1, (
            f"восстановлен {len(player_units)} юнитов из 1 — дубликат")

    def test_restored_units_keep_count(self, draft_env):
        units = [
            {"name": "warrior_freshman", "star": 1},
            {"name": "mage_acolyte", "star": 1},
            {"name": "archer_scout", "star": 1},
        ]
        _, _ = run_draft(draft_env, units)
        player_units = run_draft(draft_env, units)[0]
        assert len(player_units) == 3, (
            f"ожидали 3 юнита, получили {len(player_units)}")

    def test_overflow_goes_to_bench(self, draft_env):
        """Если доска полна, перелив уходит на бенч — не теряется."""
        # настоящие ключи из units.json, иначе финальная сборка их отбросит
        units = [
            {"name": "warrior_freshman", "star": 1},
            {"name": "warrior_veteran", "star": 1},
            {"name": "warrior_champion", "star": 1},
            {"name": "mage_acolyte", "star": 1},
            {"name": "mage_sorcerer", "star": 1},
            {"name": "mage_archmage", "star": 1},
        ]
        player_units, _ = run_draft(draft_env, units)
        assert len(player_units) == 6, (
            f"восстановили {len(player_units)} из 6 — часть состава потерялась")


class TestStarPersistence:
    def test_star_level_survives_restore(self, draft_env):
        """★2 не должен превращаться в ★1 при переносе между раундами."""
        units = [{"name": "warrior_freshman", "star": 2}]
        player_units, _ = run_draft(draft_env, units)
        assert player_units, "состав потерялся"
        # HP ★2 = 500*1.5 = 750; если звёздность потеряна, будет 500
        hp = player_units[0]["hp"]
        assert hp > 700, f"HP {hp} — звёздность ★2 потерялась (ожидали 750)"

    def test_star3_survives_restore(self, draft_env):
        units = [{"name": "warrior_freshman", "star": 3}]
        player_units, _ = run_draft(draft_env, units)
        hp = player_units[0]["hp"]
        assert hp > 950, f"HP {hp} — звёздность ★3 потерялась (ожидали 1000)"

    def test_star_name_format_is_parsable_by_shop(self, draft_env):
        """Имя 'name★2' должно парситься Shop.place обратно в star=2."""
        from game.core.shop import Shop
        from game.core.player import Player
        import random
        p = Player(gold=10)
        p.reserve.append("warrior_freshman★2")
        shop = Shop(pool=None, unit_costs={}, rng=random.Random(1))
        unit = shop.place(p, 0)
        assert unit["star"] == 2, (
            f"Shop.place прочитал star={unit['star']} из "
            f"'{p.reserve[0] if p.reserve else 'warrior_freshman★2'}'")


class TestFullMatchPersistence:
    def test_units_do_not_accumulate_over_rounds(self, monkeypatch):
        """Сквозной прогон: состав не должен расти с каждым раундом."""
        monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
        monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
        import pygame
        import pygame.event
        from ui.game_ui import GameUI

        calls = {"n": 0}

        def fake_get():
            calls["n"] += 1
            if calls["n"] > 2:
                return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)]
            return []

        seen = []
        real_draft = GameUI._run_interactive_draft

        def counted(self, round_num, is_creep, synergy_data, seed,
                    existing_units=None):
            res = real_draft(self, round_num, is_creep, synergy_data, seed,
                             existing_units)
            if res:
                seen.append(len(res[0]))
            return res

        real_animate = GameUI._animate_battle

        def animate(self, sim, state, all_sims, BG):
            if len(seen) >= 4:
                self.running = False
            return real_animate(self, sim, state, all_sims, BG)

        monkeypatch.setattr(pygame.event, "get", fake_get)
        monkeypatch.setattr(GameUI, "wait_for_input", lambda self: True)
        monkeypatch.setattr(GameUI, "_run_interactive_draft", counted)
        monkeypatch.setattr(GameUI, "_animate_battle", animate)

        ui = GameUI(width=1200, height=800)
        ui.ticks_per_frame = 20
        ui.run_interactive_match(seed=42, enemy_bot="balanced")
        assert len(seen) >= 3, "матч не дошёл до 3 раундов"
        # После первого раунда состав не должен таинственно расти:
        # 3 юнита в раунде 2 не превращаются в 6 к раунду 4.
        assert seen[1] == seen[2], (
            f"состав рос между раундами: {seen}")
