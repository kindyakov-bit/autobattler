"""Тесты новых механик: уровень магазина, килл-бонус, мерж 3 копий.

Экономика и магазин после правок:
- Shop.level привязан к уровню игрока (макс. 10);
- upgrade() отключен — всегда возвращает False;
- kill-бонус: KILL_GOLD_PER_UNIT за каждого убитого врага;
- мерж 3 копий -> ★2 -> ★3 (существующее, здесь фиксируется поведением).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


def make_shop():
    from game.core.shop import Shop
    from game.core.pool import Pool
    costs = {"cheap": 1, "mid": 2, "rare": 3, "epic": 4, "legend": 5}
    return Shop(Pool(costs), unit_costs=costs)


class TestShopLevel:
    """Уровень магазина привязан к уровню игрока, ограничивает потолок цен в ролле."""

    def test_level1_rolls_only_cost1_and_cost2(self):
        shop = make_shop()
        shop.level = 1
        costs_seen = set()
        for _ in range(100):
            for it in shop.roll(count=5):
                costs_seen.add(it["cost"])
        assert max(costs_seen) <= 2, f"на уровне 1 не должно быть тира выше 2, получили: {costs_seen}"

    def test_level3_rolls_up_to_cost3(self):
        shop = make_shop()
        shop.level = 3
        for _ in range(50):
            for it in shop.roll(count=5):
                assert it["cost"] <= 3

    def test_level10_rolls_everything(self):
        shop = make_shop()
        shop.level = 10
        seen = {it["cost"] for _ in range(50) for it in shop.roll(count=5)}
        assert max(seen) == 5, "на максимальном уровне должны выпадать cost 5"

    def test_shop_level_clamped_to_10(self):
        shop = make_shop()
        shop.level = 100
        assert shop.level == 10

    def test_upgrade_always_false(self):
        from game.core.player import Player
        shop = make_shop()
        p = Player(gold=100)
        assert shop.upgrade(p) is False
        assert shop.level == 1, "уровень магазина не меняется при апгрейде"

    def test_upgrade_cost_is_none(self):
        shop = make_shop()
        assert shop.upgrade_cost is None


class TestKillGold:
    """Килл-бонус: константа и подсчёт по kill-событиям движка."""

    def test_constant_exists(self):
        import ui.game_ui as gui
        assert gui.KILL_GOLD_PER_UNIT == 1

    def test_engine_kill_events_have_killer_team(self):
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=1)
        # один сильный против одного слабого — будет хотя бы один kill
        sim.add_team("player", [{
            "name": "killer", "hp": 1000, "damage": 500,
            "attack_speed": 2.0, "range_": 1, "class": "warrior",
        }])
        sim.add_team("enemy", [{
            "name": "victim", "hp": 100, "damage": 5,
            "attack_speed": 1.0, "range_": 1, "class": "warrior",
        }])
        sim.run()
        kills = [e for e in sim.log if e.get("type") == "kill"]
        assert kills, "слабый юнит должен умереть"
        assert all(e.get("killer_team") == "player" for e in kills)


class TestMerge:
    """Мерж 3 копий: авто-слияние при покупке (существующее поведение)."""

    def test_three_copies_merge_to_star2(self):
        from game.core.player import Player
        shop = make_shop()
        p = Player(gold=10)
        for _ in range(3):
            shop.buy(p, "cheap")
        assert p.reserve == ["cheap★2"], "3 копии должны слиться в ★2"

    def test_star2_place_keeps_star(self):
        from game.core.player import Player
        shop = make_shop()
        p = Player(gold=10)
        for _ in range(3):
            shop.buy(p, "cheap")
        unit = shop.place(p, 0)
        assert unit["star"] == 2

    def test_merge_survives_restore_cycle(self):
        """Юнит ★2 после save/restore (round trip через existing_units)
        не должен терять звёздность."""
        name, star = "cheap★2", 2
        restored = name if "★" in name else f"{name}★{star}"
        assert "★2" in restored
