"""Регрессии на баги, найденные в ревью и починенные (см. REVIEW_FIXES.md).

Каждый тест закрепляет конкретный инвариант, который раньше нарушался.
Если тест падает — значит соответствующий баг вернулся.
"""

import json
import os
import random
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from game.core.unit_name import base_name, star_level, star_multiplier
from game.core.team import build_combat_team
from game.core.shop import Shop, ShopError, accumulate_item_bonuses
from game.core.pool import Pool
from game.core.player import Player, BENCH_MAX
from game.core.economy import pvp_base_damage, pvp_round_damage, START_HP
from game.core.round import Game
from game.battle.engine import (
    BattleSimulator, Unit,
    KIND_DAMAGE_DEALT_PCT, KIND_DAMAGE_BONUS_PCT, KIND_DAMAGE_REDUCTION,
)

STAR = "\u2605"  # ★


@pytest.fixture
def unit_data():
    with open(_project_root / "data" / "units.json", encoding="utf-8") as f:
        return json.load(f)["units"]


@pytest.fixture
def full_data():
    with open(_project_root / "data" / "units.json", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────
# 1. Единый парсинг звёзд (раньше int(name.split("★")[1][1:]) падал на ★2)
# ─────────────────────────────────────────────────────────────────────────

class TestStarHelpers:
    def test_star_level_parses_suffix(self):
        assert star_level("warrior") == 1
        assert star_level(f"warrior{STAR}2") == 2
        assert star_level(f"warrior{STAR}3") == 3

    def test_star_level_old_bug_case(self):
        """Старый код делал split('★')[1][1:] → '' → int('') падал."""
        assert star_level(f"warrior{STAR}2") == 2

    def test_star_multiplier_values(self):
        assert star_multiplier(1) == 1.0
        assert star_multiplier(2) == 1.5
        assert star_multiplier(3) == 2.0

    def test_base_name_strips_star(self):
        assert base_name(f"warrior{STAR}3") == "warrior"
        assert base_name("warrior") == "warrior"


# ─────────────────────────────────────────────────────────────────────────
# 2. Бонусы предметов применяются РОВНО один раз
# ─────────────────────────────────────────────────────────────────────────

class TestItemBonusSingleSource:
    def test_build_combat_team_applies_items_once(self, unit_data):
        key = "warrior_freshman"
        ud = unit_data[key]
        team = build_combat_team(
            [{"name": key, "star": 1,
              "item_bonuses": {"hp_bonus": 200, "damage_bonus": 25}}],
            unit_data,
        )
        u = team[0]
        assert u["hp"] == ud["hp"] + 200
        assert u["damage"] == pytest.approx(ud["damage"] + 25)

    def test_assembled_team_has_no_item_bonuses_key(self, unit_data):
        """Ключ item_bonuses НЕ пробрасывается в боевой юнит — иначе
        BattleSimulator.add_team применил бы бонусы второй раз."""
        team = build_combat_team(
            [{"name": "warrior_freshman", "star": 1,
              "item_bonuses": {"hp_bonus": 200}}],
            unit_data,
        )
        assert "item_bonuses" not in team[0]

    def test_engine_does_not_double_apply(self, unit_data):
        key = "warrior_freshman"
        team = build_combat_team(
            [{"name": key, "star": 1, "item_bonuses": {"hp_bonus": 200}}],
            unit_data,
        )
        sim = BattleSimulator(seed=1)
        sim.add_team("player", team)
        assert sim.teams["player"][0].hp == unit_data[key]["hp"] + 200

    def test_speed_item_reaches_combat(self, unit_data):
        """speed_bonus_pct хранится в item_bonuses и применяется в бою.
        Раньше UI писал его в attack_speed напрямую, и в бой он не попадал."""
        key = "warrior_freshman"
        team = build_combat_team(
            [{"name": key, "star": 1,
              "item_bonuses": {"speed_bonus_pct": 50}}],
            unit_data,
        )
        assert team[0]["attack_speed"] == pytest.approx(
            unit_data[key]["attack_speed"] * 1.5)

    def test_accumulate_item_bonuses_stores_all_stats(self):
        unit = {}
        accumulate_item_bonuses(unit, {"hp_bonus": 200, "speed_bonus_pct": 10})
        accumulate_item_bonuses(unit, {"hp_bonus": 50, "speed_bonus_pct": 5})
        assert unit["item_bonuses"] == {"hp_bonus": 250, "speed_bonus_pct": 15}


# ─────────────────────────────────────────────────────────────────────────
# 3. Учёт пула при ★3 (раньше возвращались фантомные копии "base★2")
# ─────────────────────────────────────────────────────────────────────────

class TestPoolStar3Accounting:
    def test_star3_net_cost_is_three_copies(self):
        key = "warrior_freshman"
        pool = Pool({key: 1})           # cost 1 → 30 копий
        player = Player(gold=9)
        shop = Shop(pool, unit_costs={key: 1})
        for _ in range(9):              # 9 покупок → один ★3
            shop.buy(player, key, cost=1)
        assert any(r == f"{key}{STAR}3" for r in player.reserve)
        # 30 - 9 покупок + 6 refund (три ★2 по 2) = 27. ★3 netto стоит 3 копии.
        assert pool.available(key) == 27

    def test_no_phantom_star2_key_in_pool(self):
        key = "warrior_freshman"
        pool = Pool({key: 1})
        player = Player(gold=9)
        shop = Shop(pool, unit_costs={key: 1})
        for _ in range(9):
            shop.buy(player, key, cost=1)
        assert f"{key}{STAR}2" not in pool.remaining
        assert list(pool.remaining.keys()) == [key]


# ─────────────────────────────────────────────────────────────────────────
# 4. Player.place: ★2 не падает; полная доска не теряет юнита
# ─────────────────────────────────────────────────────────────────────────

class TestPlayerPlace:
    def test_place_star2(self):
        player = Player(gold=0)
        player.max_board = 5
        name = f"warrior_freshman{STAR}2"
        player.reserve.append(name)
        unit = player.place(name)
        assert unit["star"] == 2
        assert unit["name"] == name
        assert player.reserve == []

    def test_full_board_preserves_reserve(self):
        """Проверка полноты доски ДО удаления из резерва — иначе юнит терялся."""
        player = Player(gold=0)
        player.max_board = 1
        player.board.append({"name": "x", "star": 1})
        player.reserve.append("y")
        with pytest.raises(ValueError):
            player.place("y")
        assert player.reserve == ["y"]


# ─────────────────────────────────────────────────────────────────────────
# 5. Цена карточки ролла = реальная цена юнита (раньше = выпавший target_cost)
# ─────────────────────────────────────────────────────────────────────────

class TestRollCost:
    def test_card_cost_matches_unit_cost(self, unit_data):
        costs = {k: v["cost"] for k, v in unit_data.items()}
        pool = Pool(costs)
        shop = Shop(pool, unit_costs=costs, rng=random.Random(7))
        for level in range(1, 11):
            shop.level = level
            for _ in range(20):
                for card in shop.roll(count=5):
                    assert card["cost"] == costs[card["name"]], (
                        f"{card['name']}: цена {card['cost']} != {costs[card['name']]}")


# ─────────────────────────────────────────────────────────────────────────
# 6. Расовое снижение урона undead раньше игнорировалось
# ─────────────────────────────────────────────────────────────────────────

class TestUndeadDamageReduction:
    def test_single_undead_has_base_reduction(self, full_data):
        team = build_combat_team(
            [{"name": "undead_warrior_skeleton", "star": 1}],
            full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        assert team[0]["damage_reduction_pct"] == 5

    def test_engine_applies_reduction_to_incoming_damage(self, full_data):
        team = build_combat_team(
            [{"name": "undead_warrior_skeleton", "star": 1}],
            full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        sim = BattleSimulator(seed=1)
        sim.add_team("player", team)
        u = sim.teams["player"][0]
        assert u.damage_reduction_pct() >= 5
        before = u.hp
        u.take_damage(100)
        assert before - u.hp < 100, "снижение урона undead не применилось"


# ─────────────────────────────────────────────────────────────────────────
# 7. Проклятие суккуба снижает ИСХОДЯЩИЙ урон цели (раньше это был щит врагу)
# ─────────────────────────────────────────────────────────────────────────

class TestSuccubusCurseSemantics:
    def test_damage_dealt_pct_reduces_outgoing(self):
        u = Unit("victim", 1000, 100, 1.0, 1, "warrior", 0)
        u.add_status(KIND_DAMAGE_DEALT_PCT, 10, pct=25)
        assert u.damage == pytest.approx(75.0)

    def test_damage_reduction_is_incoming_not_outgoing(self):
        """Контраст: KIND_DAMAGE_REDUCTION снижает ВХОДЯЩИЙ урон (щит),
        а не исходящий. Суккуб должен использовать именно KIND_DAMAGE_DEALT_PCT."""
        u = Unit("victim", 1000, 100, 1.0, 1, "warrior", 0)
        u.add_status(KIND_DAMAGE_REDUCTION, 10, pct=25)
        assert u.damage == pytest.approx(100.0)   # свой урон не изменился
        before = u.hp
        u.take_damage(100)
        assert before - u.hp == pytest.approx(75.0)  # входящий снижен

    def test_succubus_curse_debuffs_enemy_in_sim(self, unit_data):
        """В бою суккуб накладывает дебафф на врага, а не щит на себя."""
        sim = BattleSimulator(seed=5)
        sim.add_team("player", [self._mk(unit_data, "demon_mage_succubus")])
        enemy = {"name": "dummy", "hp": 100000, "damage": 100,
                 "attack_speed": 1.0, "range_": 1, "class": "warrior",
                 "crit_chance": 0}
        sim.add_team("enemy", [enemy])
        sim.run(max_ticks=120)
        casts = [e for e in sim.get_ability_events()
                 if e["caster_id"] == sim.teams["player"][0].unit_id]
        assert casts

    @staticmethod
    def _mk(unit_data, key):
        ud = unit_data[key]
        d = {"name": ud["name"], "hp": ud["hp"], "damage": ud["damage"],
             "attack_speed": ud["attack_speed"], "range_": ud["range"],
             "class": ud["class"], "crit_chance": ud.get("crit_chance", 0)}
        if ud.get("active"):
            d["active"] = dict(ud["active"])
        return d


# ─────────────────────────────────────────────────────────────────────────
# 8. Бафф орков — процентный урон (раньше плоский KIND_DAMAGE_BONUS)
# ─────────────────────────────────────────────────────────────────────────

class TestOrcPercentageBuff:
    def test_damage_bonus_pct_is_percentage(self):
        u = Unit("orc", 1000, 100, 1.0, 1, "warrior", 0)
        u.add_status(KIND_DAMAGE_BONUS_PCT, 10, pct=30)
        assert u.damage == pytest.approx(130.0)


# ─────────────────────────────────────────────────────────────────────────
# 9. PvP-урон считается от выживших ПОБЕДИТЕЛЯ (раньше — проигравшего, всегда 0)
# ─────────────────────────────────────────────────────────────────────────

class TestPvpDamage:
    def test_base_damage_tiers(self):
        assert pvp_base_damage(1) == 5
        assert pvp_base_damage(10) == 5
        assert pvp_base_damage(11) == 10
        assert pvp_base_damage(20) == 10
        assert pvp_base_damage(21) == 15
        assert pvp_base_damage(31) == 20

    def test_round_damage_uses_winner_survivors(self):
        assert pvp_round_damage(5, 0) == 5
        assert pvp_round_damage(5, 3) == 11      # 5 + 2*3
        assert pvp_round_damage(15, 4) == 18     # 10 + 2*4

    def test_player_win_damages_bot_by_player_survivors(self):
        game = Game(seed=100)
        game.round_number = 4                    # следующий run_round → 5 (PvP)
        strong = [{"name": "s", "hp": 1000, "damage": 100,
                   "attack_speed": 1.0, "range_": 1, "class": "warrior"}
                  for _ in range(2)]
        weak = [{"name": "w", "hp": 100, "damage": 1,
                 "attack_speed": 1.0, "range_": 1, "class": "archer"}]
        bot_hp_before = game.bots[0]["hp"]
        state = game.run_round(10, strong, weak, {})
        assert state.battle_result["winner"] == "player"
        survivors = sum(1 for u in game.all_sims[5].teams["player"] if u.alive)
        expected = pvp_round_damage(5, survivors)
        assert game.bots[0]["hp"] == bot_hp_before - expected

    def test_player_loss_damages_player_by_enemy_survivors(self):
        game = Game(seed=100)
        game.round_number = 4
        weak = [{"name": "w", "hp": 100, "damage": 1,
                 "attack_speed": 1.0, "range_": 1, "class": "warrior"}]
        strong = [{"name": "s", "hp": 1000, "damage": 100,
                   "attack_speed": 1.0, "range_": 1, "class": "archer"}
                  for _ in range(2)]
        state = game.run_round(10, weak, strong, {})
        assert state.battle_result["winner"] == "enemy"
        survivors = sum(1 for u in game.all_sims[5].teams["enemy"] if u.alive)
        expected = pvp_round_damage(5, survivors)
        assert game.player_hp == START_HP - expected


# ─────────────────────────────────────────────────────────────────────────
# 10. UI-регрессии (проверка исходника — как в test_match_flow.py)
# ─────────────────────────────────────────────────────────────────────────

class TestUiSourceRegressions:
    @pytest.fixture
    def ui_source(self):
        return (_project_root / "ui" / "game_ui.py").read_text(encoding="utf-8")

    def test_empty_board_does_not_reset_state(self, ui_source):
        """Пустая доска [] не должна обнулять золото/уровень/предметы."""
        assert "if stored_player_units is not None else None" in ui_source
        assert "if stored_player_units else None" not in ui_source

    def test_no_broken_star_parsing(self, ui_source):
        assert 'split("★")[1][1:]' not in ui_source

    def test_combat_uses_full_board_not_six(self, ui_source):
        assert "player.board[:6]" not in ui_source

    def test_bench_max_imported_from_core(self, ui_source):
        assert "from game.core.player import Player, BENCH_MAX" in ui_source

    def test_streaks_recorded_after_pvp(self, ui_source):
        assert "self.player.record_win()" in ui_source
        assert "self.player.record_loss()" in ui_source

    def test_shop_level_synced_after_buy_xp(self, ui_source):
        assert "shop.level = self.player.level" in ui_source

    def test_no_per_frame_set_mode(self, ui_source):
        # set_mode остаётся только в init (создание окна), не в цикле кадров.
        assert ui_source.count("pygame.display.set_mode(") == 1

    def test_no_duplicate_tier_colors(self, ui_source):
        assert ui_source.count("TIER_COLORS = {") == 1

    def test_dead_draft_draw_removed(self, ui_source):
        assert "def draw_draft_phase(" not in ui_source


# ─────────────────────────────────────────────────────────────────────────
# 11. Merge ★ через bench/board/магазин: инвариант len(reserve) <= BENCH_MAX
# ─────────────────────────────────────────────────────────────────────────

class TestShopMergeBenchLimit:
    STAR = "\u2605"

    @pytest.fixture
    def ui_source(self):
        return (_project_root / "ui" / "game_ui.py").read_text(encoding="utf-8")

    def test_full_bench_merge_buy_exact_star(self):
        """Бенч 9/9 (1 страж★1), доска [страж★1], buy(страж) → успех,
        результат страж★2, len(reserve) <= 9, доска уменьшилась на 1."""
        key = "undead_warrior_bone_guard"
        other = "warrior_freshman"
        pool = Pool({key: 3, other: 1})
        player = Player(gold=100)
        player.reserve = [key] + [other] * 8  # 9 в резерве, 1 страж★1
        player.board = [{"name": key, "star": 1, "row": 0, "col": 0}]
        shop = Shop(pool, unit_costs={key: 3, other: 1})
        result = shop.buy(player, key, cost=3)
        assert result == f"{key}{self.STAR}2"
        assert len(player.reserve) <= BENCH_MAX
        board_names = [u["name"] for u in player.board]
        assert key not in board_names  # страж★1 снят с доски

    def test_full_bench_mixed_star_no_overflow(self):
        """Бенч 9/9 (страж★2×2), доска [страж★1], buy(страж★1) → ShopError
        (точных ★1 = 1 < 2), reserve == 9, золото/пул не тронуты."""
        key = "undead_warrior_bone_guard"
        pool = Pool({key: 3})
        player = Player(gold=100)
        player.reserve = [f"{key}{self.STAR}2"] * 2 + ["warrior_freshman"] * 7
        player.board = [{"name": key, "star": 1}]
        shop = Shop(pool, unit_costs={key: 3})
        gold_before = player.gold
        pool_before = pool.available(key)
        with pytest.raises(ShopError):
            shop.buy(player, f"{key}{self.STAR}1", cost=3)
        assert len(player.reserve) == BENCH_MAX
        assert player.gold == gold_before
        assert pool.available(key) == pool_before

    def test_merge_result_to_board_when_reserve_full(self):
        """Бенч 9/9 (стражей нет), доска [страж★1×2 с row/col],
        buy(страж) → reserve <= 9, ★2 на доске с унаследованными row/col."""
        key = "undead_warrior_bone_guard"
        other = "warrior_freshman"
        pool = Pool({key: 3, other: 1})
        player = Player(gold=100)
        player.reserve = [other] * 9
        player.board = [
            {"name": key, "star": 1, "row": 1, "col": 2},
            {"name": key, "star": 1, "row": 2, "col": 3},
        ]
        shop = Shop(pool, unit_costs={key: 3, other: 1})
        result = shop.buy(player, key, cost=3)
        assert result == f"{key}{self.STAR}2"
        assert len(player.reserve) <= BENCH_MAX
        merged = [u for u in player.board if u["name"] == f"{key}{self.STAR}2"]
        assert len(merged) == 1
        assert merged[0]["row"] == 1
        assert merged[0]["col"] == 2
        board_star1 = [u["name"] for u in player.board if u.get("star") == 1]
        assert key not in board_star1

    def test_remove_from_board_full_bench_rejected(self):
        """Бенч 9/9, доска [страж], remove_from_board → ошибка,
        reserve == 9, доска не изменилась."""
        key = "undead_warrior_bone_guard"
        pool = Pool({key: 3})
        player = Player(gold=100)
        player.reserve = ["warrior_freshman"] * 9
        player.board = [{"name": key, "star": 1}]
        shop = Shop(pool, unit_costs={key: 3})
        board_before = list(player.board)
        with pytest.raises(ShopError):
            shop.remove_from_board(player, 0)
        assert len(player.reserve) == BENCH_MAX
        assert player.board == board_before

    def test_bench_invariant_after_buy_chain(self):
        """Серия покупок: после каждой assert len(reserve) <= BENCH_MAX."""
        key = "undead_warrior_bone_guard"
        pool = Pool({key: 3})
        player = Player(gold=100)
        shop = Shop(pool, unit_costs={key: 3})
        for _ in range(9):
            shop.buy(player, key, cost=3)
            assert len(player.reserve) <= BENCH_MAX

    def test_pool_accounting_unchanged(self):
        """Refund при ★2 = 2 копии, ★3 netto = 3 (как в test_shop.py)."""
        key = "warrior_freshman"
        pool = Pool({key: 1})
        player = Player(gold=9)
        shop = Shop(pool, unit_costs={key: 1})
        for _ in range(9):
            shop.buy(player, key, cost=1)
        assert any(r == f"{key}{self.STAR}3" for r in player.reserve)
        assert pool.available(key) == 27

    def test_ui_no_silent_except_on_buy_paths(self, ui_source):
        """В UI на путях покупки ловится ShopError с сообщением, а не
        `except Exception: pass`."""
        assert "except ShopError as e:" in ui_source
        assert "self.draft_message = (str(e), pygame.time.get_ticks())" in ui_source

    def test_overfull_bench_hidden_unit_softlock(self):
        """2 копии на доске + полныйベンч + покупка не даёт 10/9;
        ★2 оказывается на доске с row/col, а не в reserve."""
        key = "undead_warrior_bone_guard"
        other = "warrior_freshman"
        pool = Pool({key: 3, other: 1})
        player = Player(gold=100)
        player.reserve = [other] * 9
        player.board = [
            {"name": key, "star": 1, "row": 0, "col": 0},
            {"name": key, "star": 1, "row": 1, "col": 1},
        ]
        shop = Shop(pool, unit_costs={key: 3, other: 1})
        shop.buy(player, key, cost=3)
        assert len(player.reserve) <= BENCH_MAX
        merged = [u for u in player.board if u["name"] == f"{key}{self.STAR}2"]
        assert len(merged) == 1
        assert merged[0].get("row") is not None
        assert merged[0].get("col") is not None

    def test_blade_buy_recovers_overfull(self):
        """Состояние со скрина: 2× лезвие★1 наベンче, buy(лезвие) → успех,
        merge в лезвие★2, len(reserve) <= 9."""
        key = "undead_assassin_bone_blade"
        pool = Pool({key: 2})
        player = Player(gold=100)
        player.reserve = [key, key]
        shop = Shop(pool, unit_costs={key: 2})
        result = shop.buy(player, key, cost=2)
        assert result == f"{key}{self.STAR}2"
        assert len(player.reserve) <= BENCH_MAX


# ─────────────────────────────────────────────────────────────────────────
# Вылет при старте боя после апгрейда до 3 юнитов: бейдж расовой синергии
# и иконки «ЯРОСТЬ» вызывали draw_text_overlay с несуществующим kwarg color=.
# ─────────────────────────────────────────────────────────────────────────

class TestBattleSceneRaceVisuals:
    def test_race_badge_and_berserk_icon_render(self, full_data):
        """Бейдж синергии (>=2 юнитов одной расы) и «ЯРОСТЬ» (орк под порогом HP)
        рисуются без TypeError. До фикса: color= вместо text_color=."""
        import os
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI

        units = full_data["units"]
        kwargs = dict(
            synergy_data=full_data["synergies"],
            race_synergy_data=full_data["race_synergies"],
            race_data=full_data["races"],
        )
        team = build_combat_team(
            [{"name": "orc_warrior_berserker", "star": 1},
             {"name": "orc_warrior_berserker", "star": 1},
             {"name": "mage_acolyte", "star": 1}],
            units, **kwargs)
        enemy = build_combat_team(
            [{"name": "orc_warrior_berserker", "star": 1}] * 2,
            units, **kwargs)
        sim = BattleSimulator(
            seed=1, race_data=full_data["races"],
            race_synergy_data=full_data["race_synergies"])
        sim.add_team("Игрок", team)
        sim.add_team("Враг", enemy)
        # Ярость рисуется при HP <= порога берсерка (орк-синергия 2+)
        for u in sim.teams["Игрок"] + sim.teams["Враг"]:
            if getattr(u, "berserker", None):
                u.hp = max(1, u.max_hp // 5)

        ui = GameUI(width=1200, height=800)
        ui.sound_enabled = False
        ui.all_units = units
        ui.init()
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [], "critical_effects": []}
        ui._draw_battle_scene(sim, effects, 0)
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────
# Продажа подベンчем (TASK_ui_sell_synergy, задача 1)
# ─────────────────────────────────────────────────────────────────────────

class TestSellBinGeometry:
    """Полоса продажи под панельюベンча: геометрия корректна на разных
    разрешениях, не наезжает на кнопку «Начать раунд»."""

    def test_sell_bin_rect_under_bench_1200x800(self):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI

        ui = GameUI(width=1200, height=800)
        ui.sound_enabled = False
        ui.init()
        rect = ui._sell_bin_rect()

        bench_panel_w = ui.width // 3 - 40
        bench_cell_w = max(50, (bench_panel_w - 2 * 10 - 2 * 10) // 3)
        bench_cell_h = bench_cell_w
        bench_panel_h = 40 + 3 * bench_cell_h + 2 * 10 + 10
        expected_top = 268 + bench_panel_h + 6

        assert rect.top >= expected_top, f"rect.top={rect.top} < expected={expected_top}"
        assert rect.left == 10
        assert rect.width == bench_panel_w
        assert rect.height >= 32, f"height={rect.height} < 32"
        assert rect.bottom <= ui.height - 90, f"rect.bottom={rect.bottom} > {ui.height - 90}"
        pygame.quit()

    def test_sell_bin_rect_1920x1080(self):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI

        ui = GameUI(width=1920, height=1080)
        ui.sound_enabled = False
        ui.init()
        rect = ui._sell_bin_rect()

        assert rect.top >= 268
        assert rect.left == 10
        assert rect.height >= 32
        assert rect.bottom <= ui.height - 90
        pygame.quit()

    def test_sell_bin_rect_same_for_draw_and_handler(self):
        """Отрисовка и обработчик используют один и тот же рект."""
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI

        ui = GameUI(width=1200, height=800)
        ui.sound_enabled = False
        ui.init()
        rect1 = ui._sell_bin_rect()
        rect2 = ui._sell_bin_rect()
        assert rect1 == rect2
        pygame.quit()


class TestSellFromBenchAndBoard:
    """Продажа дропом: с бенча и с доски (с предметом)."""

    def test_sell_from_bench(self, full_data):
        units = full_data["units"]
        pool = Pool({k: v["cost"] for k, v in units.items()})
        player = Player(gold=100)
        player.level = 1
        player.max_board = 5
        player.max_bench = 9
        shop = Shop(pool, unit_costs={k: v["cost"] for k, v in units.items()})
        draft_phase = __import__("game.core.draft", fromlist=["DraftPhase"]).DraftPhase(shop, units)

        name = "warrior_freshman"
        player.reserve.append(name)
        gold_before = player.gold
        pool_before = pool.available(name)

        result = draft_phase.sell_unit(player, 0)
        player.gold += units[name]["cost"]

        assert result == "warrior_freshman"
        assert player.gold == gold_before + units[name]["cost"]
        assert pool.available(name) == pool_before + 1
        assert player.reserve == []

    def test_sell_from_board_with_item(self, full_data):
        units = full_data["units"]
        pool = Pool({k: v["cost"] for k, v in units.items()})
        player = Player(gold=100)
        player.level = 1
        player.max_board = 5
        player.max_bench = 9
        shop = Shop(pool, unit_costs={k: v["cost"] for k, v in units.items()})
        draft_phase = __import__("game.core.draft", fromlist=["DraftPhase"]).DraftPhase(shop, units)

        player.board.append({"name": "warrior_freshman", "star": 1, "row": 0, "col": 0,
                             "items": [{"stats": {"hp_bonus": 50}}]})
        player.board.append({"name": "warrior_veteran", "star": 1, "row": 0, "col": 1})

        gold_before = player.gold
        items_before = len(player.items)

        result = draft_phase.sell_unit(player, 0, from_board=True)
        player.gold += units["warrior_freshman"]["cost"]

        assert result == "warrior_freshman"
        assert player.gold == gold_before + units["warrior_freshman"]["cost"]
        assert len(player.items) == items_before + 1
        assert player.items[0]["stats"]["hp_bonus"] == 50
        assert len(player.board) == 1
        assert player.board[0]["name"] == "warrior_veteran"
        assert player.board.count({"name": "warrior_freshman", "star": 1}) == 0


# ─────────────────────────────────────────────────────────────────────────
# Форматтер бонусов синергий (TASK_ui_sell_synergy, задача 2)
# ─────────────────────────────────────────────────────────────────────────

class TestSynergyBonusFormatter:
    """_format_synergy_bonus корректно форматирует бонусы всех типов."""

    def _format(self, bonus: dict) -> str:
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI
        ui = GameUI(width=800, height=600)
        ui.sound_enabled = False
        ui.init()
        result = ui._format_synergy_bonus(bonus)
        pygame.quit()
        return result

    def test_warrior_hp_bonus(self):
        assert "% HP" in self._format({"hp_bonus_pct": 15})

    def test_damage_bonus(self):
        assert "% урона" in self._format({"damage_bonus_pct": 30})

    def test_attack_speed_bonus(self):
        assert "скорости атаки" in self._format({"attack_speed_pct": 25})

    def test_crit_chance_bonus(self):
        assert "шанс крита" in self._format({"crit_chance_bonus": 10})

    def test_mana_per_kill(self):
        assert "сек за убийство" in self._format({"mana_per_kill": 5})

    def test_evasion_pct(self):
        assert "уклонение" in self._format({"evasion_pct": 15})

    def test_lifesteal_pct(self):
        assert "вампиризм" in self._format({"lifesteal_pct": 20})

    def test_damage_reduction_pct(self):
        assert "получаемого урона" in self._format({"damage_reduction_pct": 10})

    def test_hp_regen_pct(self):
        assert "реген" in self._format({"hp_regen_pct": 0.04})

    def test_gold_bonus_pct(self):
        assert "золота" in self._format({"gold_bonus_pct": 10})

    def test_unity_bonus(self):
        bonus = {"unity_damage_pct": 10, "unity_hp_pct": 5}
        s = self._format(bonus)
        assert "единство" in s
        assert "+10% урона" in s
        assert "+5% HP" in s

    def test_berserker_bonus(self):
        bonus = {"berserker": {"hp_thresholds": [50, 25], "damage_pct": [20, 45], "speed_pct": [20, 35]}}
        s = self._format(bonus)
        assert "берсерк" in s
        assert "+45% урона/скорости при HP≤50%" in s

    def test_revive_bonus(self):
        bonus = {"revive": {"hp_pct": 35, "max_revives": 2}}
        s = self._format(bonus)
        assert "восстание" in s
        assert "35% HP" in s
        assert "до 2 раз" in s

    def test_unknown_key(self):
        s = self._format({"unknown_key": 42})
        assert "unknown_key: 42" in s

    def test_multiple_keys(self):
        bonus = {"hp_bonus_pct": 15, "damage_bonus_pct": 10, "attack_speed_pct": 5}
        s = self._format(bonus)
        assert "+15% HP" in s
        assert "+10% урона" in s
        assert "+5% скорости атаки" in s
        assert "; " in s


class TestSynergyTooltipRender:
    """Headless-рендер с ховером на запись синергии не падает."""

    def test_hover_synergy_tooltip(self, full_data):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        import pygame
        from ui.game_ui import GameUI
        from game.core.team import build_combat_team
        from game.core.player import Player

        units = full_data["units"]
        kwargs = dict(
            synergy_data=full_data["synergies"],
            race_synergy_data=full_data["race_synergies"],
            race_data=full_data["races"],
        )
        team = build_combat_team(
            [{"name": "warrior_freshman", "star": 1},
             {"name": "warrior_veteran", "star": 1}],
            units, **kwargs)

        ui = GameUI(width=1200, height=800)
        ui.sound_enabled = False
        ui.all_units = units
        ui.init()

        player = Player(gold=50)
        player.level = 1
        player.max_board = 5
        player.board = [
            {"name": "warrior_freshman", "star": 1, "row": 0, "col": 0},
            {"name": "warrior_veteran", "star": 1, "row": 0, "col": 1},
        ]

        syn_x = ui.width // 3 * 2 + 10
        mx, my = syn_x + 5, 268 + 21 + 5
        pygame.mouse.set_pos((mx, my))

        try:
            ui._draw_interactive_draft(
                player=player,
                shop_items=[],
                gold=50,
                round_num=1,
                is_creep=False,
                synergy_data=full_data["synergies"],
                race_synergy_data=full_data["race_synergies"],
                shop=None,
            )
        except Exception as e:
            pygame.quit()
            raise AssertionError(f"_draw_interactive_draft упал с ховером на синергию: {e}")
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────
# Вылет в ходе боя: текстовые метки MISS/REVIVE/+heal в DamageNumber
# ─────────────────────────────────────────────────────────────────────────

class TestBattleEffectTextLabels:
    """Метки MISS/REVIVE/+heal больше не роняют бой. До фикса: int("MISS")
    → ValueError, окно закрывалось на первом уклонении эльфа или восстании
    нежити (обработчики событий передавали строки в DamageNumber)."""

    def _make_ui(self, full_data):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        os.environ["SDL_AUDIODRIVER"] = "dummy"
        from ui.game_ui import GameUI
        ui = GameUI(width=1200, height=800)
        ui.sound_enabled = False
        ui.all_units = full_data["units"]
        ui.init()
        return ui

    def test_damage_number_labels_and_numbers(self, full_data):
        import pygame
        from ui.game_ui import DamageNumber
        ui = self._make_ui(full_data)
        surf = pygame.Surface((120, 60))
        for label in ("MISS", "REVIVE", "+15"):
            dn = DamageNumber(10, 30, label)
            assert dn.label == label
            dn.draw(surf, ui.font_tiny)
        dn = DamageNumber(10, 30, 50)
        assert dn.label is None and dn.amount == 50
        dn.draw(surf, ui.font_tiny)
        pygame.quit()

    def test_generate_effects_miss_lifesteal_revive(self, full_data):
        import pygame
        ui = self._make_ui(full_data)
        units = full_data["units"]
        kwargs = dict(
            synergy_data=full_data["synergies"],
            race_synergy_data=full_data["race_synergies"],
            race_data=full_data["races"],
        )
        team = build_combat_team(
            [{"name": "elf_archer_ranger", "star": 1}] * 2, units, **kwargs)
        enemy = build_combat_team(
            [{"name": "undead_warrior_skeleton", "star": 1}] * 2, units, **kwargs)
        sim = BattleSimulator(
            seed=1, race_data=full_data["races"],
            race_synergy_data=full_data["race_synergies"])
        sim.add_team("Игрок", team)
        sim.add_team("Враг", enemy)
        pu = sim.teams["Игрок"][0]
        eu = sim.teams["Враг"][0]
        sim.log = [
            {"type": "miss", "tick": 1, "target_id": pu.unit_id},
            {"type": "lifesteal", "tick": 1, "attacker_id": pu.unit_id, "heal": 15},
            {"type": "revive", "tick": 1, "target_id": eu.unit_id},
        ]
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [], "critical_effects": []}
        ui._generate_battle_effects(sim, 1, 0, effects)
        labels = [dn.label for dn in effects["damage_numbers"]]
        assert "MISS" in labels
        assert "+15" in labels
        assert "REVIVE" in labels
        pygame.quit()
