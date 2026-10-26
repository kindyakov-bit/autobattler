"""Тесты матча: драфт с первого раунда и система HP.

До этих правок 3 раунда из 8 шли как кат-сцена (состав игрока был захардкожен),
а проиграть матч было невозможно — не было здоровья.
"""

import json
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from game.core.economy import (
    START_HP, round_economy, round_hp_damage, calculate_interest,
)


# ─────────────────────────────────────────────────────────────────────────
# HP матча
# ─────────────────────────────────────────────────────────────────────────

class TestMatchHP:
    def test_creep_rounds_never_damage_hp(self):
        assert round_hp_damage(is_creep=True, player_won=False,
                               surviving_enemy_units=6) == 0

    def test_winning_pvp_costs_no_hp(self):
        assert round_hp_damage(is_creep=False, player_won=True,
                               surviving_enemy_units=6) == 0

    def test_loss_damage_scales_with_survivors(self):
        one = round_hp_damage(False, False, 1)
        many = round_hp_damage(False, False, 5)
        assert many > one, "урон должен расти с числом выживших врагов"

    def test_loss_damage_is_positive(self):
        for survivors in range(0, 7):
            dmg = round_hp_damage(False, False, survivors)
            assert dmg > 0, f"при {survivors} выживших урон должен быть > 0"

    def test_elimination_at_zero_hp(self):
        econ = round_economy(gold=10, pvp_win=False, hp=8, is_creep=False,
                             surviving_enemy_units=6)
        assert econ["hp_after"] == 0
        assert econ["is_eliminated"] is True

    def test_not_eliminated_with_hp_left(self):
        econ = round_economy(gold=10, pvp_win=False, hp=50, is_creep=False,
                             surviving_enemy_units=1)
        assert econ["hp_after"] > 0
        assert econ["is_eliminated"] is False

    def test_hp_cannot_go_negative(self):
        econ = round_economy(gold=10, pvp_win=False, hp=3, is_creep=False,
                             surviving_enemy_units=6)
        assert econ["hp_after"] == 0

    def test_full_loss_sequence_eliminates(self):
        """Последовательные поражения должны довести до вылета."""
        hp = START_HP
        rounds = 0
        while hp > 0 and rounds < 50:
            econ = round_economy(gold=10, pvp_win=False, hp=hp, is_creep=False,
                                 surviving_enemy_units=3)
            hp = econ["hp_after"]
            rounds += 1
        assert hp == 0, f"не вылетели за {rounds} раундов"
        assert rounds < 20, f"вылет слишком долгий: {rounds} раундов"

    def test_gold_still_awarded_when_hp_tracked(self):
        """Включение HP не должно ломать экономику золота."""
        with_hp = round_economy(gold=20, pvp_win=True, hp=100, is_creep=False,
                                surviving_enemy_units=0)
        without_hp = round_economy(gold=20, pvp_win=True)
        assert with_hp["gold_after"] == without_hp["gold_after"]

    def test_backwards_compatible_call(self):
        """Старые вызовы без hp/is_creep продолжают работать."""
        econ = round_economy(gold=10, pvp_win=True)
        assert "hp_after" not in econ
        assert econ["gold_after"] > 10


# ─────────────────────────────────────────────────────────────────────────
# Драфт с первого раунда
# ─────────────────────────────────────────────────────────────────────────

class TestDraftFromRoundOne:
    def _loop_source(self):
        source = (_project_root / "ui" / "game_ui.py").read_text(encoding="utf-8")
        return source.split("def run_interactive_match")[1].split(
            "def _animate_battle")[0]

    def test_draft_runs_for_all_rounds(self):
        """Драфт вызывается ДО развилки крипы/PvP — значит и там, и там."""
        loop = self._loop_source()
        draft_pos = loop.find("_run_interactive_draft(")
        branch_pos = loop.find("if is_creep:")
        assert draft_pos != -1, "драфт не вызывается вовсе"
        assert branch_pos != -1
        assert draft_pos < branch_pos, (
            "драфт внутри ветки — значит какие-то раунды идут без решений")

    def test_draft_not_duplicated(self):
        """Один вызов на цикл, а не копия в каждой ветке."""
        loop = self._loop_source()
        assert loop.count("_run_interactive_draft(") == 1, (
            "драфт продублирован по веткам — правки будут рассинхронизироваться")

    def test_creep_rounds_have_no_hardcoded_player_units(self):
        """Ветке крипов не нужно назначать состав игрока вручную."""
        loop = self._loop_source()
        creep_branch = loop.split("if is_creep:")[1].split("else:")[0]
        assert "player_units = [" not in creep_branch, (
            "состав игрока на крип-раунде захардкожен")

    def test_match_tracks_hp(self):
        loop = self._loop_source()
        assert "hp = START_HP" in loop, "матч не начинает со здоровьем"
        assert "eliminated" in loop, "нет проверки условия вылета"

    def test_header_can_show_hp(self):
        """draw_header умеет показывать здоровье и сигналить об опасности."""
        source = (_project_root / "ui" / "game_ui.py").read_text(encoding="utf-8")
        header = source.split("def draw_header")[1].split("def ")[0]
        assert "hp" in header and "HP" in header


class TestEconomyUnchanged:
    def test_interest_still_works(self):
        assert calculate_interest(0) == 0
        assert calculate_interest(10) == 1
        assert calculate_interest(50) == 5
        assert calculate_interest(999) == 5


# ─────────────────────────────────────────────────────────────────────────
# Бот должен быть настоящим противником
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def game_env():
    import random
    from game.core.shop import Shop
    from game.core.pool import Pool
    from game.core.draft import DraftPhase
    from game.core.player import Player
    unit_data = json.loads(
        (_project_root / "data" / "units.json").read_text(encoding="utf-8"))["units"]
    unit_costs = {n: i["cost"] for n, i in unit_data.items()}
    shop = Shop(Pool(unit_costs), unit_costs=unit_costs,
                rng=random.Random(1))
    return shop, DraftPhase(shop, unit_data), Player(gold=20), unit_data


class TestBotIsARealOpponent:
    """Бот возвращал отображаемые имена вместо ключей JSON, поэтому Shop.buy
    всегда падал с «копий в пуле не осталось» — доска бота была пустой,
    и враг состоял из 2 захардкоженных юнитов. Игрок выигрывал все раунды."""

    @pytest.mark.parametrize("preset", ["casual", "balanced", "aggressive"])
    def test_bot_actually_buys_units(self, game_env, preset):
        shop, dp, bot_player, unit_data = game_env
        from game.core.bots import create_bot
        bot = create_bot(preset=preset, seed=42)
        decision = bot.decide_draft(unit_data, gold=20,
                                    current_team=[], synergy_data={})
        bought = []
        for info in decision:
            if bot_player.gold >= info.get("cost", 1):
                try:
                    bought.append(dp.buy_unit(bot_player, info["name"]))
                except Exception as e:
                    pytest.fail(f"бот не смог купить {info['name']}: {e}")
        assert len(bought) >= 3, (
            f"бот {preset} купил только {len(bought)} юнитов — доска пустая")

    def test_bot_returns_json_keys_not_display_names(self, game_env):
        """name в решении бота должен быть ключом JSON, а не 'Новобранец'."""
        shop, dp, bot_player, unit_data = game_env
        from game.core.bots import create_bot
        bot = create_bot(preset="balanced", seed=1)
        for info in bot.decide_draft(unit_data, gold=20, current_team=[],
                                     synergy_data={}):
            assert info["name"] in unit_data, (
                f"'{info['name']}' — не ключ JSON; Shop так не умеет")

    def test_bot_fills_board_against_gold(self, game_env):
        """С 20 золота бот должен занять почти все 6 слотов."""
        shop, dp, bot_player, unit_data = game_env
        from game.core.bots import create_bot
        bot = create_bot(preset="balanced", seed=7)
        decision = bot.decide_draft(unit_data, gold=20, current_team=[],
                                    synergy_data={})
        assert len(decision) == 6, f"бот выбрал только {len(decision)} юнитов"

    def test_bot_needs_synergy_data(self, game_env):
        """MEDIUM-бот получает synergy_data и старается добирать порог."""
        shop, dp, bot_player, unit_data = game_env
        from game.core.bots import create_bot
        synergy = {"warrior": {"thresholds": [2], "bonuses": {}}}
        bot = create_bot(preset="balanced", seed=3)
        with_warrior = bot.decide_draft(
            unit_data, gold=20, current_team=[{"class": "warrior"}],
            synergy_data=synergy)
        # Ищем, что среди покупок есть воин (добор до порога 2)
        classes = [i.get("class") for i in with_warrior]
        assert "warrior" in classes, (
            "MEDIUM-бот не пытается добирать синергию warrior")
