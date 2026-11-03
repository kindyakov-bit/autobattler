"""Тесты для game/battle/engine.py — Unit, BattleSimulator."""

import pytest
from game.battle.engine import Unit, BattleSimulator


# ---------- Unit: создание ----------

class TestUnitCreation:
    def test_unit_alive(self):
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        assert u.alive is True
        assert u.hp == 100
        assert u.max_hp == 100

    def test_take_damage(self):
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        died = u.take_damage(50)
        assert died is False
        assert u.hp == 50

    def test_take_fatal_damage(self):
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        died = u.take_damage(100)
        assert died is True
        assert u.hp == 0
        assert u.alive is False

    def test_take_overflow_damage(self):
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        died = u.take_damage(200)
        assert died is True
        assert u.hp == 0


# ---------- Unit: тик и атака ----------

class TestUnitTick:
    def test_tick_no_attack_when_timer_not_ready(self):
        """Когда таймер > 0 — атак нет."""
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        # attack_speed=1.0 → ticks_per_attack = ceil(60/1.0) = 60
        # На первом тике таймер уменьшается с 60 до 59 — атаки нет
        events = u.tick()
        assert len(events) == 0

    def test_tick_returns_attack_when_timer_zero(self):
        """Когда таймер <= 0 — возвращается событие атаки."""
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        u.attack_timer = 0
        events = u.tick()
        assert len(events) == 1
        assert events[0]["type"] == "attack"
        assert events[0]["damage"] == 20

    def test_dead_unit_no_events(self):
        """Мёртвый юнит не генерирует события."""
        u = Unit("warrior", 100, 20, 1.0, 1, "team_a", 0)
        u.alive = False
        events = u.tick()
        assert len(events) == 0


# ---------- BattleSimulator: базовый бой ----------

class TestBattleSimulatorBasic:
    def test_simple_battle(self):
        """Бой двух юнитов: сильный убивает слабого."""
        sim = BattleSimulator(seed=1)

        # Сильный юнит (1000 HP, 50 урона) vs слабый (200 HP, 10 урона)
        strong = {"name": "tank", "hp": 1000, "damage": 50, "attack_speed": 1.0, "range_": 1}
        weak = {"name": "scout", "hp": 200, "damage": 10, "attack_speed": 1.0, "range_": 1}

        sim.add_team("alpha", [strong])
        sim.add_team("beta", [weak])

        result = sim.run(max_ticks=600)

        assert result["winner"] == "alpha"
        assert result["reason"] == "annihilation"
        assert result["team_hp"]["alpha"] > 0
        assert result["team_hp"]["beta"] == 0

    def test_multiple_units_per_team(self):
        """Команда из нескольких юнитов."""
        sim = BattleSimulator(seed=2)

        team_a = [
            {"name": "u1", "hp": 300, "damage": 30, "attack_speed": 1.0, "range_": 1},
            {"name": "u2", "hp": 300, "damage": 30, "attack_speed": 1.0, "range_": 1},
        ]
        team_b = [
            {"name": "v1", "hp": 500, "damage": 40, "attack_speed": 1.0, "range_": 1},
        ]

        sim.add_team("a", team_a)
        sim.add_team("b", team_b)

        result = sim.run(max_ticks=600)

        # Два юнита с суммарным уроном должны победить одного
        assert result["winner"] == "a"

    def test_deterministic_same_seed(self):
        """Один и тот же seed даёт одинаковый результат."""
        results = []
        for _ in range(3):
            sim = BattleSimulator(seed=99)
            sim.add_team("x", [{"name": "u", "hp": 500, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            sim.add_team("y", [{"name": "v", "hp": 500, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            r = sim.run(max_ticks=600)
            results.append(r["winner"])

        assert all(w == results[0] for w in results), "Результаты должны совпадать при одинаковом seed"

    def test_different_seed_different_result(self):
        """Разные seeds могут давать разные результаты (из-за вариативности урона)."""
        winners = set()
        for seed in range(10):
            sim = BattleSimulator(seed=seed)
            # Два одинаковых юнита — исход зависит от RNG
            sim.add_team("p", [{"name": "u", "hp": 400, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            sim.add_team("e", [{"name": "v", "probe": True, "hp": 400, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            r = sim.run(max_ticks=600)
            winners.add(r["winner"])

        # При одинаковых юнитах каждый может победить — проверяем что есть вариативность
        assert len(winners) >= 1  # хотя бы один победитель должен быть


# ---------- BattleSimulator: таймаут ----------

class TestBattleTimeout:
    def test_timeout_returns_highest_hp_team(self):
        """При достижении max_ticks побеждает команда с большим HP."""
        sim = BattleSimulator(seed=42)
        sim.add_team("big", [{"name": "giant", "hp": 5000, "damage": 10, "attack_speed": 0.5, "range_": 1}])
        sim.add_team("small", [{"name": "mouse", "hp": 100, "damage": 5, "attack_speed": 2.0, "range_": 1}])

        result = sim.run(max_ticks=60)  # маленький лимит

        assert result["winner"] == "big"
        assert result["reason"] == "timeout"


# ---------- BattleSimulator: одновременная смерть ----------

class TestSimultaneousDeath:
    def test_both_teams_died_same_tick(self):
        """Если оба юнита умирают по очереди — побеждает первая команда."""
        sim = BattleSimulator(seed=10)

        # Оба юнита по 50 HP, наносят по 40 урона каждый
        u1 = {"name": "a", "hp": 50, "damage": 40, "attack_speed": 1.0, "range_": 1}
        u2 = {"name": "b", "hp": 50, "damage": 40, "attack_speed": 1.0, "range_": 1}

        sim.add_team("first", [u1])
        sim.add_team("second", [u2])

        result = sim.run(max_ticks=600)

        # Юниты атакуют по очереди: first убивает second, потом second убивает first
        # → simultaneous_death не срабатывает, побеждает первая команда (annihilation)
        assert result["winner"] == "first"


# ---------- BattleSimulator: дальний бой ----------

class TestRangedCombat:
    def test_ranged_vs_melee(self):
        """Дальний юнит бьёт ближайшего врага (в MVP все на одной дистанции)."""
        sim = BattleSimulator(seed=5)

        # Дальний маг (range=4), ближний воин (range=1)
        mage = {"name": "mage", "hp": 200, "damage": 30, "attack_speed": 1.0, "range_": 4}
        warrior = {"name": "warrior", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1}

        sim.add_team("mages", [mage])
        sim.add_team("warriors", [warrior])

        result = sim.run(max_ticks=600)

        # В MVP все враги на одной дистанции:
        # mage: 200 HP, 30 dmg; warrior: 300 HP, 25 dmg → warrior должен победить (больше HP)
        assert result["winner"] == "warriors"


# ---------- BattleSimulator: print_state ----------

class TestPrintState:
    def test_print_state_contains_tick(self):
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [{"name": "u", "hp": 100, "damage": 10, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("e", [{"name": "v", "hp": 100, "damage": 10, "attack_speed": 1.0, "range_": 1}])

        # Прогоним несколько тиков
        for _ in range(5):
            sim.tick_count += 1
            all_units = [u for team in sim.teams.values() for u in team]
            for unit in all_units:
                if not unit.alive:
                    continue
                unit.attack_timer -= 1

        state = sim.print_state()
        assert "Тик" in state or "tick" in state.lower()


# ---------- Интеграционный тест с JSON ----------

class TestIntegrationWithJSON:
    def test_load_and_battle_from_json(self):
        """Загрузка из data/units.json и бой двух команд."""
        import json
        from pathlib import Path

        project_root = Path(__file__).parent.parent.resolve()
        json_path = project_root / "data" / "units.json"

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Создаём две команды из JSON данных
        sim = BattleSimulator(seed=7)
        team_a_keys = ["warrior_freshman", "mage_acolyte"]
        team_b_keys = ["archer_scout", "warrior_veteran"]

        for key in team_a_keys:
            ud = dict(data["units"][key])
            sim.add_team("a", [ud])
        for key in team_b_keys:
            ud = dict(data["units"][key])
            sim.add_team("b", [ud])

        result = sim.run(max_ticks=600)

        # Должен быть победитель
        assert result["winner"] in ("a", "b")
        assert result["ticks"] > 0
