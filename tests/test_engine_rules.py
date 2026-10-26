"""Тесты правил боя: дистанции/range, криты, идемпотентность, честный урон.

Эти тесты закрывают дефекты, которые жили в проекте месяцами:
  - range_ полностью игнорировался при выборе цели;
  - способности выдавали «вечный» бафф и нерабочее замедление;
  - повторный run() не сбрасывал юнитов;
  - в лог писался урон ДО применения щитов.
"""

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from game.battle.engine import (
    BattleSimulator, Unit, MOVE_TICKS_PER_COLUMN,
)


def simple(name, hp, dmg, asp, rng, cls="warrior", crit=0):
    return {"name": name, "hp": hp, "damage": dmg, "attack_speed": asp,
            "range_": rng, "class": cls, "crit_chance": crit}


# ─────────────────────────────────────────────────────────────────────────
# Дубли методов — симптом «правки дописыванием в конец файла»
# ─────────────────────────────────────────────────────────────────────────

class TestNoDuplicateCode:
    def test_no_duplicated_method_definitions(self):
        """Ни один метод движка не должен быть определён дважды."""
        import inspect
        from game.battle import engine
        text = inspect.getsource(engine)
        for method in ("_check_result", "run", "_apply_attack", "_take_snapshot",
                       "_enemies_in_radius", "_cast_ability", "distance_to"):
            count = text.count(f"def {method}(")
            assert count == 1, f"метод {method}() определён {count} раз(а)"


# ─────────────────────────────────────────────────────────────────────────
# range и дистанция
# ─────────────────────────────────────────────────────────────────────────

class TestRangeTargeting:
    def test_distance_grows_with_position(self):
        """Юнит в тылу дальше до врагов, чем передовой."""
        sim = BattleSimulator(seed=1)
        sim.add_team("player", [simple(f"p{i}", 100, 10, 1.0, 1) for i in range(6)])
        sim.add_team("enemy", [simple(f"e{j}", 100, 10, 1.0, 1) for j in range(6)])
        front, back = sim.teams["player"][0], sim.teams["player"][5]
        enemy_front = sim.teams["enemy"][0]
        assert sim.distance_to(front, enemy_front) == 1
        assert sim.distance_to(back, enemy_front) > sim.distance_to(
            front, enemy_front)

    def test_melee_unit_cannot_hit_distant_target(self):
        """Ближний юнит не бьёт врага, до которого не достаёт."""
        sim = BattleSimulator(seed=1)
        # Дальний боец в тылу player (индекс 5) vs один враг впереди enemy
        sim.add_team("player", [simple(f"p{i}", 100, 10, 1.0, 1) for i in range(6)])
        sim.add_team("enemy", [simple("e0", 100000, 0, 1.0, 5, "archer")])
        melee_back = sim.teams["player"][5]
        enemy = sim.teams["enemy"][0]
        d = sim.distance_to(melee_back, enemy)
        assert d > melee_back.range_, "юнит в тылу должен быть вне дистанции"

    def test_ranged_unit_hits_from_back_line(self):
        """Дальний юнит достаёт до врага, который вне дистанции ближнего боя."""
        sim = BattleSimulator(seed=1)
        sim.add_team("player", [simple(f"p{i}", 100, 10, 1.0, 1) for i in range(6)])
        sim.add_team("enemy", [simple("e0", 100000, 0, 1.0, 5, "archer")])
        ranged = Unit("r", 100, 10, 1.0, 6, "player", 99)
        sim._team_index[99] = 5
        enemy = sim.teams["enemy"][0]
        assert sim.distance_to(ranged, enemy) <= ranged.range_

    def test_backline_melee_needs_time_to_engage(self):
        """Удар заднего ближнего юнита задерживается сближением."""
        sim = BattleSimulator(seed=11)
        sim.add_team("player", [simple(f"p{i}", 5000, 40, 1.0, 1) for i in range(6)])
        sim.add_team("enemy", [simple(f"e{j}", 5000, 40, 1.0, 1) for j in range(6)])
        sim.run(max_ticks=600)
        first_hit = {}
        for ev in sim.log:
            if ev["type"] in ("hit", "kill"):
                first_hit.setdefault(ev["attacker_id"], ev["tick"])
        assert first_hit.get(5, 0) > first_hit.get(0, 0), (
            "юнит в 6-й колонке должен вступать в бой позже передового")

    def test_single_units_always_adjacent(self):
        """1v1: оба на дистанции 1 — ломать старые тесты нельзя."""
        sim = BattleSimulator(seed=1)
        sim.add_team("a", [simple("u", 100, 10, 1.0, 1)])
        sim.add_team("b", [simple("v", 100, 10, 1.0, 1)])
        a, b = sim.teams["a"][0], sim.teams["b"][0]
        assert sim.distance_to(a, b) == 1
        assert sim._find_targets({"attacker_id": a.unit_id}) == [b]

    def test_closes_distance_over_time(self):
        """Сближение уменьшает дистанцию ровно на 1 колонку за N тиков."""
        sim = BattleSimulator(seed=1)
        sim.add_team("player", [simple(f"p{i}", 100, 10, 1.0, 1) for i in range(6)])
        sim.add_team("enemy", [simple("e0", 100, 10, 1.0, 5, "archer")])
        melee = sim.teams["player"][5]
        enemy = sim.teams["enemy"][0]
        before = sim.distance_to(melee, enemy)
        melee.closing = MOVE_TICKS_PER_COLUMN
        after = sim.distance_to(melee, enemy)
        assert after == before - 1


# ─────────────────────────────────────────────────────────────────────────
# Криты
# ─────────────────────────────────────────────────────────────────────────

class TestCrits:
    def _run(self, key_units, enemy, seeds=range(25)):
        crits = total = 0
        for seed in seeds:
            sim = BattleSimulator(seed=seed)
            sim.add_team("p", key_units)
            sim.add_team("e", enemy)
            sim.run(max_ticks=600)
            for e in sim.log:
                if e["type"] in ("hit", "kill"):
                    total += 1
                    crits += 1 if e.get("is_critical") else 0
        return crits, total

    def test_crit_chance_is_percent_not_fraction(self):
        """Шанс 20% не должен означать «всегда крит»."""
        crits, total = self._run(
            [simple("sniper", 300, 40, 1.2, 5, "archer", crit=20)],
            [simple("tank", 5000, 0, 1.0, 1)])
        assert total > 0
        assert 0 < crits < total, f"критов {crits} из {total} — шанс сломан"

    def test_no_crits_when_chance_zero(self):
        """Без crit_chance критов нет вовсе."""
        crits, total = self._run(
            [simple("plain", 300, 40, 1.2, 1, "warrior", crit=0)],
            [simple("tank", 5000, 0, 1.0, 1)])
        assert crits == 0

    def test_crit_deals_more_damage(self):
        """Критовое попадание сильнее обычного."""
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [simple("u", 100, 100, 1.0, 1, "warrior", crit=100)])
        sim.add_team("e", [simple("v", 100000, 0, 1.0, 4, "archer")])
        sim.run(max_ticks=200)
        attacker_id = sim.teams["p"][0].unit_id
        damages = [e["damage"] for e in sim.log
                   if e["type"] == "hit" and e.get("attacker_id") == attacker_id]
        assert damages and all(d > 100 for d in damages), (
            f"крит должен увеличивать урон, получено {damages}")


# ─────────────────────────────────────────────────────────────────────────
# Идемпотентность и корректность состояния
# ─────────────────────────────────────────────────────────────────────────

class TestRunIdempotence:
    def test_repeated_run_gives_same_result(self):
        """run() можно вызвать повторно и получить тот же бой."""
        sim = BattleSimulator(seed=7)
        sim.add_team("p", [simple("u", 500, 40, 1.2, 1, "warrior", 10)])
        sim.add_team("e", [simple("v", 500, 40, 1.2, 1, "warrior", 10)])
        r1 = sim.run()
        r2 = sim.run()
        r3 = sim.run()
        assert r1 == r2 == r3, "повторный run() должен быть детерминирован"

    def test_units_reset_between_runs(self):
        """HP/статусы юнитов сбрасываются, а не продолжают копиться."""
        sim = BattleSimulator(seed=7)
        sim.add_team("p", [simple("u", 500, 40, 1.2, 1, "warrior", 10)])
        sim.add_team("e", [simple("v", 500, 40, 1.2, 1, "warrior", 10)])
        sim.run()
        for u in sim.teams["p"] + sim.teams["e"]:
            sim.run()
            break
        u = sim.teams["p"][0]
        assert u.statuses == []
        assert u.attack_timer > 0


class TestHonestDamage:
    def test_log_shows_damage_after_reduction(self):
        """Цифра в логе должна совпадать с убранным HP."""
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [simple("dps", 5000, 100, 1.0, 4, "archer")])
        sim.add_team("e", [simple("tank", 100000, 0, 1.0, 1)])
        tank = sim.teams["e"][0]
        tank.add_status("damage_reduction", 99999, pct=50)
        attacker = sim.teams["p"][0]
        events = sim._apply_attack({
            "type": "attack", "attacker_id": attacker.unit_id,
            "attacker_team": "p", "damage": 100, "range_": 4,
        })
        assert events, "должно быть попадание"
        assert events[0]["damage"] <= 55.0, (
            f"в логе урон {events[0]['damage']} без учёта щита (50%)")
        hp_drop = 100000 - tank.hp
        assert events[0]["damage"] == pytest.approx(hp_drop, abs=0.1), (
            "цифра урона должна равняться убранному HP")

    def test_speed_buff_is_bounded_by_duration(self):
        """Сколько бы раз ни кастовали бафф, скорость растёт ограниченно."""
        from game.battle.engine import Unit
        unit = Unit("u", 100, 10, 2.0, 3, "t", 0)
        # 20 кастов: каждый даёт +20% на 5 тиков
        for _ in range(20):
            unit.add_status("speed_pct", 5, pct=20)
            unit.tick_statuses()
        # Одновременно активно не больше 5 эффектов (длительность 5 тиков),
        # поэтому множитель ограничен 1.2^5, а не 1.2^20
        assert unit.attack_speed <= unit.base_attack_speed * (1.2 ** 5) + 1e-9

    def test_speed_buff_expires(self):
        """После истечения длительности скорость возвращается к базовой."""
        from game.battle.engine import Unit
        unit = Unit("u", 100, 10, 2.0, 3, "t", 0)
        unit.add_status("speed_pct", 3, pct=20)
        for _ in range(3):
            unit.tick_statuses()
        assert unit.attack_speed == pytest.approx(unit.base_attack_speed)


class TestSnapshot:
    def test_snapshot_restores_statuses(self):
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [simple("u", 100, 10, 1.0, 1, "warrior", 0)])
        sim.add_team("e", [simple("v", 100, 10, 1.0, 1, "warrior", 0)])
        u = sim.teams["p"][0]
        u.add_status("damage_reduction", 10, pct=30)
        snap = sim._take_snapshot()
        u.take_damage(10)
        u.statuses = []
        sim.restore_from_snapshot(snap)
        assert [s["kind"] for s in u.statuses] == ["damage_reduction"]
        assert u.damage_reduction_pct() == 30

    def test_snapshot_has_all_ui_fields(self):
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [simple("u", 100, 10, 1.0, 1, "warrior", 0)])
        sim.add_team("e", [simple("v", 100, 10, 1.0, 1, "warrior", 0)])
        snap = sim._take_snapshot()
        for team in snap.values():
            for ud in team:
                for field in ("hp", "max_hp", "alive", "attack_timer",
                              "unit_id", "damage", "attack_speed",
                              "statuses", "closing", "base_damage"):
                    assert field in ud, f"в snapshot нет поля {field}"
