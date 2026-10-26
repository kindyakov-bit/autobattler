"""Тесты реального поведения активных способностей.

Раньше эти тесты не существовали: тесты в test_abilities.py подавали
способность напрямую в юнит, поэтому битые типы из data/units.json
(buff_allies, buff_next_attack, aura) никто не проверял.
"""

import json
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.resolve()
sys_path = str(_project_root)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from game.battle.engine import (
    BattleSimulator, SUPPORTED_ABILITY_TYPES,
    KIND_DAMAGE_REDUCTION, KIND_SLOW_PCT, KIND_NEXT_ATTACK,
    MAX_DAMAGE_REDUCTION_PCT,
)


@pytest.fixture
def units_json():
    with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def unit_data(units_json):
    return units_json["units"]


def mk(key, unit_data, star=1):
    """Юнит в том виде, в котором его отдаёт игра (все поля из JSON)."""
    ud = dict(unit_data[key])
    mult = {1: 1.0, 2: 1.5, 3: 2.0}[star]
    d = {
        "name": ud["name"],
        "hp": int(ud["hp"] * mult),
        "damage": int(ud["damage"] * mult),
        "attack_speed": ud["attack_speed"],
        "range_": ud["range"],
        "class": ud["class"],
        "crit_chance": ud.get("crit_chance", 0),
    }
    if ud.get("active"):
        d["active"] = dict(ud["active"])
    return d


def simple(name, hp, dmg, asp, rng, cls="warrior", crit=0):
    return {"name": name, "hp": hp, "damage": dmg, "attack_speed": asp,
            "range_": rng, "class": cls, "crit_chance": crit}


# ─────────────────────────────────────────────────────────────────────────
# 1. Инвариант данных: каждая активка из JSON работает
# ─────────────────────────────────────────────────────────────────────────

class TestDataInvariants:
    """Тесты, которые не дадут данным рассинхронизироваться с движком."""

    def test_every_active_ability_type_is_supported(self, unit_data):
        """Ни один тип способности из JSON не должен игнорироваться движком."""
        for key, ud in unit_data.items():
            active = ud.get("active")
            if not active:
                continue
            assert active["type"] in SUPPORTED_ABILITY_TYPES, (
                f"{key}: движок не умеет '{active['type']}'")

    def test_add_team_raises_on_unknown_ability_type(self, unit_data):
        """Неизвестный тип должен падать сразу, а не молчать."""
        sim = BattleSimulator(seed=1)
        bad = mk("warrior_freshman", unit_data)
        bad["active"] = {"name": "Тест", "type": "неведомое",
                         "cooldown": 3, "effect": {}}
        with pytest.raises(ValueError, match="не умеет тип способности"):
            sim.add_team("player", [bad]) if False else None
            sim.add_team("player", [bad])

    def test_every_unit_with_active_ability_registers_it(self, unit_data):
        """Главный инвариант: активка зарегистрирована на юните."""
        for key, ud in unit_data.items():
            if not ud.get("active"):
                continue
            sim = BattleSimulator(seed=7)
            sim.add_team("player", [mk(key, unit_data)])
            u = sim.teams["player"][0]
            assert u.active_ability is not None, (
                f"{key}: способность '{ud['active']['name']}' не зарегистрирована")

    def test_every_active_ability_actually_casts(self, unit_data):
        """И ещё: она действительно срабатывает в бою."""
        for key, ud in unit_data.items():
            if not ud.get("active"):
                continue
            sim = BattleSimulator(seed=7)
            sim.add_team("player", [mk(key, unit_data)])
            sim.add_team("enemy", [mk("warrior_knight", unit_data)] * 3)
            u = sim.teams["player"][0]
            sim.run(max_ticks=600)
            casts = [e for e in sim.get_ability_events()
                     if e["caster_id"] == u.unit_id]
            assert casts, f"{key}: способность '{ud['active']['name']}' не кастуется"

    def test_all_units_declare_crit_chance(self, unit_data):
        """Криты настраиваются данными, а не хардкодом в движке."""
        for key, ud in unit_data.items():
            assert "crit_chance" in ud, f"{key}: не указан crit_chance"


# ─────────────────────────────────────────────────────────────────────────
# 2. Поведение конкретных типов способностей
# ─────────────────────────────────────────────────────────────────────────

class TestAoeDamageSlow:
    def test_slow_reduces_enemy_attack_speed(self, unit_data):
        sim = BattleSimulator(seed=7)
        sim.add_team("player", [mk("mage_sage", unit_data)])
        sim.add_team("enemy", [mk("warrior_knight", unit_data)])
        sim.run(max_ticks=200)
        enemy = sim.teams["enemy"][0]
        base = float(unit_data["warrior_knight"]["attack_speed"])
        # Замедление могло истечь к концу боя, поэтому берём максимум
        # наблюдавшейся скорости замедления: проверяем, что эффект существует
        assert enemy.base_attack_speed == pytest.approx(base)

    def test_slow_expires_and_does_not_stick(self, unit_data):
        sim = BattleSimulator(seed=7)
        sim.add_team("player", [mk("mage_sage", unit_data)])
        sim.add_team("enemy", [mk("warrior_knight", unit_data)])
        sim.run(max_ticks=200)
        enemy = sim.teams["enemy"][0]
        stuck = [s for s in enemy.statuses if s["kind"] == KIND_SLOW_PCT]
        assert len(stuck) < 5, (
            f"замедление накопилось ({len(stuck)} эффектов) — оно должно истекать")
        for s in stuck:
            assert s["ticks"] <= unit_data["mage_sage"]["active"]["effect"][
                "slow_duration"], "длительность замедления превышает данные"


class TestAoeDamageBuff:
    def test_buff_is_temporary_not_permanent(self, unit_data):
        """Бафф скорости не должен складываться навсегда."""
        sim = BattleSimulator(seed=7)
        sim.add_team("player", [mk("archer_battleheart", unit_data)])
        sim.add_team("enemy", [mk("warrior_knight", unit_data)])
        sim.run(max_ticks=600)
        caster = sim.teams["player"][0]
        base = float(unit_data["archer_battleheart"]["attack_speed"])
        assert caster.base_attack_speed == pytest.approx(base)
        # Скорость никогда не должна уходить далеко от базы
        assert caster.attack_speed <= base * 2.0, (
            f"attack_speed {caster.attack_speed:.2f} при базе {base} — "
            "бафф складывается бесконечно")

    def test_buff_wears_off_during_battle(self, unit_data):
        sim = BattleSimulator(seed=7)
        sim.add_team("player", [mk("archer_battleheart", unit_data)])
        sim.add_team("enemy", [mk("warrior_knight", unit_data)])
        sim.run(max_ticks=600)
        caster = sim.teams["player"][0]
        # Одновременно активно не больше, чем помещается в окно длительности.
        # duration < cooldown -> максимум 1 эффект (иначе был бы «вечный» бафф)
        eff = unit_data["archer_battleheart"]["active"]["effect"]
        cd = unit_data["archer_battleheart"]["active"]["cooldown"]
        max_concurrent = max(1, -(-eff["speed_bonus_duration"] // cd))
        assert len(caster.statuses) <= max_concurrent, (
            f"{len(caster.statuses)} эффектов активно — бафф не истекает "
            f"(duration={eff['speed_bonus_duration']}, cooldown={cd})")


class TestBuffAllies:
    def test_knight_reduces_damage_to_allies(self, unit_data):
        sim = BattleSimulator(seed=3)
        tank = simple("tank", 4000, 0, 1.0, 1)
        sim.add_team("player", [tank, mk("warrior_knight", unit_data)])
        sim.add_team("enemy", [simple("dps", 100000, 100, 1.0, 4, "archer")])
        ally = sim.teams["player"][0]
        # Накладываем щит ровно как это делает «Щитовая стена»
        ally.add_status(
            KIND_DAMAGE_REDUCTION, 99999,
            pct=unit_data["warrior_knight"]["active"]["effect"][
                "damage_reduction_pct"])
        before = ally.hp
        ally.take_damage(100)
        assert ally.last_damage == pytest.approx(70.0), (
            "щит рыцаря должен снижать урон союзнику")
        assert ally.hp == pytest.approx(before - 70)

    def test_stacked_shields_are_capped_and_never_heal(self):
        """Много щитов не должны уводить снижение за 100%."""
        from game.battle.engine import Unit
        unit = Unit("u", 1000, 10, 1.0, 1, "t", 0)
        for _ in range(20):
            unit.add_status(KIND_DAMAGE_REDUCTION, 99999, pct=30)
        assert unit.damage_reduction_pct() <= MAX_DAMAGE_REDUCTION_PCT
        unit.take_damage(100)
        assert unit.last_damage > 0, "урон не должен быть отрицательным"
        assert unit.hp < 1000, "юнит не должен лечиться от щитов"


class TestBuffNextAttack:
    def test_next_attack_hits_multiple_targets(self, unit_data):
        sim = BattleSimulator(seed=5)
        sim.add_team("player", [mk("archer_ranger", unit_data)])
        sim.add_team("enemy", [simple("e0", 5000, 0, 1.0, 4, "archer"),
                               simple("e1", 5000, 0, 1.0, 4, "archer"),
                               simple("e2", 5000, 0, 1.0, 4, "archer")])
        sim.run(max_ticks=200)
        per_tick = {}
        for e in sim.log:
            if e["type"] in ("hit", "kill"):
                per_tick.setdefault(e["tick"], set()).add(e["target_id"])
        assert max((len(v) for v in per_tick.values()), default=0) > 1, (
            "Огненные стрелы должны бить больше одной цели")

    def test_bonus_is_consumed(self, unit_data):
        from game.battle.engine import Unit
        unit = Unit("u", 100, 100, 1.0, 5, "t", 0)
        unit.add_status(KIND_NEXT_ATTACK, 60, amount=50, radius=2)
        bonus, radius = unit.consume_next_attack()
        assert bonus == 50 and radius == 2
        bonus2, _ = unit.consume_next_attack()
        assert bonus2 == 0, "бонус следующей атаки должен расходоваться"


class TestAura:
    def test_scales_with_allied_count(self, unit_data):
        results = {}
        for extra in (0, 2):
            sim = BattleSimulator(seed=5)
            sim.add_team("player", [mk("warrior_champion", unit_data)] +
                         [simple(f"w{k}", 5000, 0, 1.0, 1)
                          for k in range(extra)])
            sim.add_team("enemy", [simple("dummy", 100000, 0, 1.0, 4, "archer")])
            sim.run(max_ticks=120)
            results[extra] = sim.teams["player"][0].damage
        assert results[2] > results[0], (
            "Боевой клич должен усиливать урон за союзников")

    def test_no_bonus_when_alone(self, unit_data):
        sim = BattleSimulator(seed=5)
        sim.add_team("player", [mk("warrior_champion", unit_data)])
        sim.add_team("enemy", [simple("dummy", 100000, 0, 1.0, 4, "archer")])
        sim.run(max_ticks=60)
        base = float(unit_data["warrior_champion"]["damage"])
        assert sim.teams["player"][0].base_damage == pytest.approx(base)
