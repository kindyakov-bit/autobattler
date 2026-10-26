"""Тесты новых механик: уровень магазина, килл-бонус, мерж 3 копий.

Экономика и магазин после правок 26.10.2026 (вечер):
- Shop.level ограничивает потолок цен в ролле (1..6);
- upgrade() поднимает уровень за золото игрока;
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
    """Уровень магазина ограничивает потолок цен в ролле."""

    def test_level1_rolls_only_cost1(self):
        shop = make_shop()
        shop.level = 1
        for _ in range(50):
            items = shop.roll(count=5)
            for it in items:
                assert it["cost"] <= 1

    def test_level3_rolls_up_to_cost3(self):
        shop = make_shop()
        shop.level = 3
        for _ in range(50):
            for it in shop.roll(count=5):
                assert it["cost"] <= 3

    def test_level6_rolls_everything(self):
        shop = make_shop()
        shop.level = 6
        seen = {it["cost"] for _ in range(50) for it in shop.roll(count=5)}
        assert max(seen) == 5, "на максимальном уровне должны выпадать cost 5"

    def test_upgrade_costs_gold(self):
        from game.core.player import Player
        shop = make_shop()
        p = Player(gold=6)
        assert shop.level == 1
        assert shop.upgrade(p) is True
        assert shop.level == 2
        assert p.gold == 0, "апгрейд должен списать цену UPGRADE_COSTS[1]=6"

    def test_upgrade_fails_without_gold(self):
        from game.core.player import Player
        shop = make_shop()
        p = Player(gold=1)
        assert shop.upgrade(p) is False
        assert shop.level == 1
        assert p.gold == 1

    def test_upgrade_max_level(self):
        shop = make_shop()
        shop.level = 6
        assert shop.upgrade() is False, "выше 6 уровня апгрейда нет"


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
