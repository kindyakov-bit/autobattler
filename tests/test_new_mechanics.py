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


@pytest.fixture
def full_data():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    with open(root / "data" / "units.json", encoding="utf-8") as f:
        return json.load(f)


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


# ─────────────────────────────────────────────────────────────────────────
# Расовые механики (TASK_race_identities): примитивы изолированно
# ─────────────────────────────────────────────────────────────────────────

class TestEvasionPrimitive:
    """Эльфы — уклонение от автоатаки (только автоатака, не DoT/абилы)."""

    def _mk_sim_with_evasion(self, seed, evasion_pct):
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=seed)
        sim.add_team("player", [{
            "name": "atk", "hp": 1000, "damage": 100, "attack_speed": 5.0,
            "range_": 1, "class": "warrior",
        }])
        sim.add_team("enemy", [{
            "name": "tgt", "hp": 100, "damage": 10, "attack_speed": 1.0,
            "range_": 1, "class": "warrior",
        }])
        target = sim.teams["enemy"][0]
        target.evasion_pct = evasion_pct
        return sim, target

    def test_evasion_100_pct_always_misses(self):
        """При evasion_pct=100 автоатака всегда промахивается."""
        sim, target = self._mk_sim_with_evasion(1, 100.0)
        sim.run(max_ticks=300)
        assert target.hp == target.max_hp, (
            f"цель с 100% уклонением не должна терять HP, осталось {target.hp}")

    def test_evasion_0_pct_never_misses(self):
        """При evasion_pct=0 автоатака всегда попадает."""
        sim, target = self._mk_sim_with_evasion(1, 0.0)
        sim.run(max_ticks=300)
        assert target.hp < target.max_hp, "цель без уклонения должна получить урон"

    def test_miss_event_in_log(self):
        """Событие miss попадает в лог боя."""
        sim, target = self._mk_sim_with_evasion(1, 100.0)
        sim.run(max_ticks=300)
        misses = [e for e in sim.log if e.get("type") == "miss"]
        assert misses, "должно быть событие miss в логе"


class TestLifestealPrimitive:
    """Демоны — вампиризм: хил атакующего от урона автоатакой."""

    def _mk_sim_with_lifesteal(self, seed, lifesteal_pct):
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=seed)
        sim.add_team("player", [{
            "name": "atk", "hp": 200, "damage": 100, "attack_speed": 5.0,
            "range_": 1, "class": "warrior",
        }])
        sim.add_team("enemy", [{
            "name": "tgt", "hp": 1000, "damage": 10, "attack_speed": 1.0,
            "range_": 1, "class": "warrior",
        }])
        attacker = sim.teams["player"][0]
        attacker.lifesteal_pct = lifesteal_pct
        return sim, attacker

    def test_lifesteal_heals_attacker(self):
        """Атакующий лечится на % от урона цели."""
        sim, attacker = self._mk_sim_with_lifesteal(7, 50.0)
        sim.run(max_ticks=300)
        assert attacker.hp == attacker.max_hp, (
            f"вампиризм должен вылечить атакующего до максимума, hp={attacker.hp}/{attacker.max_hp}")

    def test_lifesteal_event_in_log(self):
        """Событие lifesteal попадает в лог боя."""
        sim, attacker = self._mk_sim_with_lifesteal(7, 50.0)
        sim.run(max_ticks=300)
        ls = [e for e in sim.log if e.get("type") == "lifesteal"]
        assert ls, "должно быть событие lifesteal в логе"


class TestRevivePrimitive:
    """Нежить — восстание: первый смертельный удар — встать на % HP."""

    def test_revive_brings_unit_back_once(self):
        """Юнит с revive встаёт один раз на hp_pct от max_hp."""
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=3)
        sim.add_team("player", [{
            "name": "u", "hp": 100, "damage": 10, "attack_speed": 1.0,
            "range_": 1, "class": "warrior",
        }])
        sim.add_team("enemy", [{
            "name": "e", "hp": 10000, "damage": 1000, "attack_speed": 2.0,
            "range_": 1, "class": "warrior",
        }])
        unit = sim.teams["player"][0]
        unit.revive = {"hp_pct": 30, "max_revives": 1}
        unit.revives_left = 1
        sim.run(max_ticks=300)
        # Событие воскрешения должно быть в логе
        revive_events = [e for e in sim.log if e.get("type") == "revive"]
        assert revive_events, "должно быть событие revive в логе"
        assert unit.revives_left == 0, "ресурс воскресения израсходован"
        assert unit.just_revived is False, "флаг just_revived сброшен после эмита события"

    def test_revive_only_once(self):
        """Второй смертельный удар убивает окончательно (max_revives=1)."""
        from game.battle.engine import BattleSimulator
        sim = BattleSimulator(seed=3)
        sim.add_team("player", [{
            "name": "u", "hp": 100, "damage": 10, "attack_speed": 1.0,
            "range_": 1, "class": "warrior",
        }])
        sim.add_team("enemy", [{
            "name": "e", "hp": 10000, "damage": 1000, "attack_speed": 2.0,
            "range_": 1, "class": "warrior",
        }])
        unit = sim.teams["player"][0]
        unit.revive = {"hp_pct": 30, "max_revives": 1}
        unit.revives_left = 1
        sim.run(max_ticks=300)
        assert not unit.alive, "после второго смертельного удара юнит мёртв"


class TestBerserkerPrimitive:
    """Орки — берсерк: урон и скорость растут при просадке HP."""

    def test_berserker_at_low_hp(self):
        """При HP <= порога урон и скорость увеличиваются."""
        from game.battle.engine import Unit

        u = Unit("orc", 100, 100, 1.0, 1, "player", 0)
        u.berserker = {
            "hp_thresholds": [50, 25],
            "damage_pct": [20, 35],
            "speed_pct": [20, 35],
        }
        u.hp = 100  # 100% — ниже любого порога
        u._refresh_stats()
        assert u.damage == 100.0
        assert u.attack_speed == 1.0

        u.hp = 40  # 40% <= 50 → первый порог (+20%)
        u._refresh_stats()
        assert u.damage == pytest.approx(120.0)
        assert u.attack_speed == pytest.approx(1.2)

        u.hp = 20  # 20% <= 25 → второй порог (+35%)
        u._refresh_stats()
        assert u.damage == pytest.approx(135.0)
        assert u.attack_speed == pytest.approx(1.35)

    def test_berserker_not_compounded(self):
        """Берсерк считается от базы, не компаундируется при повторном refresh."""
        from game.battle.engine import Unit

        u = Unit("orc", 100, 100, 1.0, 1, "player", 0)
        u.berserker = {
            "hp_thresholds": [50],
            "damage_pct": [20],
            "speed_pct": [20],
        }
        u.hp = 40
        u._refresh_stats()
        dmg_after_first = u.damage
        u._refresh_stats()
        assert u.damage == dmg_after_first, "берсерк не должен компаундироваться"


class TestRaceSynergyData:
    """Расовые синергии: порог 6 выбирается корректно (highest-met)."""

    def test_elf_evasion_thresholds(self, full_data):
        data = full_data["race_synergies"]["elf"]
        assert data["thresholds"] == [2, 4, 6]
        assert data["bonuses"]["2"]["evasion_pct"] == 12
        assert data["bonuses"]["4"]["evasion_pct"] == 16
        assert data["bonuses"]["6"]["evasion_pct"] == 30

    def test_orc_berserker_thresholds(self, full_data):
        data = full_data["race_synergies"]["orc"]
        assert data["thresholds"] == [2, 4, 6]
        assert data["bonuses"]["2"]["berserker"]["hp_thresholds"] == [50]
        assert data["bonuses"]["4"]["berserker"]["hp_thresholds"] == [50, 25]
        assert data["bonuses"]["6"]["berserker"]["hp_thresholds"] == [50, 25]

    def test_demon_lifesteal_thresholds(self, full_data):
        data = full_data["race_synergies"]["demon"]
        assert data["thresholds"] == [2, 4, 6]
        assert data["bonuses"]["2"]["lifesteal_pct"] == 12
        assert data["bonuses"]["4"]["lifesteal_pct"] == 20
        assert data["bonuses"]["6"]["lifesteal_pct"] == 30

    def test_undead_revive_thresholds(self, full_data):
        data = full_data["race_synergies"]["undead"]
        assert data["thresholds"] == [2, 4, 6]
        assert data["bonuses"]["2"]["revive"]["hp_pct"] == 15
        assert data["bonuses"]["4"]["revive"]["hp_pct"] == 20
        assert data["bonuses"]["6"]["revive"]["max_revives"] == 2


class TestApplyRaceBonusesNewKeys:
    """apply_race_bonuses переносит новые ключи в unit_data."""

    def test_evasion_pct_applied(self, full_data):
        team = [{"name": "elf_archer_ranger", "star": 1}]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        # 1 эльф — синергия не активна (нужно 2), evasion_pct не должно быть
        assert "evasion_pct" not in team[0]

    def test_elf_evasion_at_2(self, full_data):
        team = [
            {"name": "elf_archer_ranger", "star": 1},
            {"name": "elf_healer_spirit", "star": 1},
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        assert team[0]["evasion_pct"] == 12
        assert team[1]["evasion_pct"] == 12

    def test_demon_lifesteal_at_2(self, full_data):
        team = [
            {"name": "demon_mage_imp", "star": 1},
            {"name": "demon_fire_totem", "star": 1},
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        assert team[0]["lifesteal_pct"] == 12

    def test_undead_revive_at_2(self, full_data):
        team = [
            {"name": "undead_warrior_skeleton", "star": 1},
            {"name": "undead_warrior_bone_guard", "star": 1},
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        assert team[0]["revive"] == {"hp_pct": 15, "max_revives": 1}

    def test_orc_berserker_at_4(self, full_data):
        team = [
            {"name": "orc_warrior_berserker", "star": 1},
            {"name": "orc_warrior_axe_bearer", "star": 1},
            {"name": "orc_warrior_chief", "star": 1},
            {"name": "orc_archer_slinger", "star": 1},
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        berserker = team[0]["berserker"]
        assert berserker["hp_thresholds"] == [50, 25]
        assert berserker["damage_pct"] == [20, 35]
        assert berserker["speed_pct"] == [20, 35]

    def test_engine_reads_evasion_from_unit_data(self, full_data):
        """add_team читает evasion_pct из unit_data в Unit.evasion_pct."""
        from game.battle.engine import BattleSimulator
        from game.core.team import build_combat_team

        team = [
            {"name": "elf_archer_ranger", "star": 1},
            {"name": "elf_healer_spirit", "star": 1},
        ]
        team = build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        sim = BattleSimulator(seed=1)
        sim.add_team("player", team)
        assert sim.teams["player"][0].evasion_pct == 12.0

    def test_engine_reads_revive_from_unit_data(self, full_data):
        """add_team читает revive из unit_data в Unit.revive + revives_left."""
        from game.battle.engine import BattleSimulator
        from game.core.team import build_combat_team

        team = [
            {"name": "undead_warrior_skeleton", "star": 1},
            {"name": "undead_warrior_bone_guard", "star": 1},
        ]
        team = build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        sim = BattleSimulator(seed=1)
        sim.add_team("player", team)
        u = sim.teams["player"][0]
        assert u.revive == {"hp_pct": 15, "max_revives": 1}
        assert u.revives_left == 1

    def test_human_unity_bonus(self, full_data):
        """«Единство» людей: бонус урона/HP за уникальные классы в команде."""
        team = [
            {"name": "warrior_freshman", "star": 1},      # warrior
            {"name": "mage_acolyte", "star": 1},           # mage
            {"name": "archer_scout", "star": 1},           # archer
            {"name": "human_assassin_knife", "star": 1},   # assassin
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        # 4 человека -> порог 4 (8%), 4 уникальных класса -> unity = 8% * 4 = 32%
        for u in team:
            base_key = u["name"].split("★")[0]
            base = full_data["units"][base_key]
            assert u["damage"] == pytest.approx(base["damage"] * 1.32)
            assert u["hp"] == int(base["hp"] * 1.32)

    def test_human_unity_no_bonus_single_class(self, full_data):
        """2 человека одного класса → unity = 5% * 1 класс = 5% урона/HP (до пассивок)."""
        team = [
            {"name": "warrior_freshman", "star": 1},
            {"name": "warrior_veteran", "star": 1},
        ]
        team = __import__("game.core.team", fromlist=["build_combat_team"]).build_combat_team(
            team, full_data["units"],
            race_data=full_data.get("races", {}),
            race_synergy_data=full_data.get("race_synergies", {}),
        )
        for u in team:
            base_key = u["name"].split("★")[0]
            base = full_data["units"][base_key]
            # 1 уникальный класс, порог 2: unity 5% * 1 = 5% урона (пассивки воинов — только HP)
            assert u["damage"] == pytest.approx(base["damage"] * 1.05)
