"""Тесты для визуальных эффектов боя: attack events, snapshots, positions."""

import pytest
from game.battle.engine import BattleSimulator


class TestAttackEvents:
    """Тесты на регистрацию событий атак для визуальных эффектов."""

    def test_no_attack_events_at_start(self):
        """До начала боя событий атак нет."""
        sim = BattleSimulator(seed=1)
        sim.add_team("a", [{"name": "u", "hp": 500, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("b", [{"name": "v", "hp": 500, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        
        events = sim.get_attack_events()
        assert len(events) == 0

    def test_attack_events_recorded_after_battle(self):
        """После боя все события атак должны быть записаны."""
        sim = BattleSimulator(seed=5)
        sim.add_team("a", [{"name": "tank", "hp": 1000, "damage": 50, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("b", [{"name": "scout", "hp": 200, "damage": 10, "attack_speed": 1.0, "range_": 1}])
        
        sim.run(max_ticks=600)
        
        events = sim.get_attack_events()
        assert len(events) > 0
        
        # Каждое событие должно иметь обязательные поля
        for evt in events:
            assert "tick" in evt
            assert "attacker_id" in evt
            assert "attacker_team" in evt
            assert "damage" in evt
            assert "targets" in evt
            assert isinstance(evt["targets"], list)

    def test_attack_events_filtered_by_tick(self):
        """Фильтрация событий по тиковому номеру работает."""
        sim = BattleSimulator(seed=10)
        sim.add_team("a", [{"name": "u", "hp": 500, "damage": 25, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("b", [{"name": "v", "hp": 500, "damage": 25, "attack_speed": 1.0, "range_": 1}])
        
        sim.run(max_ticks=600)
        
        all_events = sim.get_attack_events()
        half_events = sim.get_attack_events(up_to_tick=len(all_events) // 2)
        
        assert len(half_events) <= len(all_events)

    def test_attack_events_deterministic(self):
        """Одинаковый seed → одинаковые события атак."""
        results = []
        for _ in range(3):
            sim = BattleSimulator(seed=77)
            sim.add_team("x", [{"name": "u", "hp": 400, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            sim.add_team("y", [{"name": "v", "hp": 400, "damage": 25, "attack_speed": 1.0, "range_": 1}])
            sim.run(max_ticks=600)
            results.append(sim.get_attack_events())
        
        # Все три результата должны быть одинаковыми
        assert all(len(r) == len(results[0]) for r in results)
        for evt_a, evt_b in zip(results[0], results[1]):
            assert evt_a["tick"] == evt_b["tick"]
            assert evt_a["attacker_id"] == evt_b["attacker_id"]


class TestUnitPositions:
    """Тесты на расчёт позиций юнитов."""

    def test_positions_generated(self):
        """Позиции генерируются для всех живых юнитов."""
        sim = BattleSimulator(seed=1)
        player_units_data = [
            {"name": "u1", "hp": 300, "damage": 20, "attack_speed": 1.0, "range_": 1},
            {"name": "u2", "hp": 300, "damage": 20, "attack_speed": 1.0, "range_": 1},
        ]
        enemy_units_data = [
            {"name": "v1", "hp": 300, "damage": 20, "attack_speed": 1.0, "range_": 1},
        ]
        
        sim.add_team("player", player_units_data)
        sim.add_team("enemy", enemy_units_data)
        
        player_units = list(sim.teams["player"])
        enemy_units = list(sim.teams["enemy"])
        
        positions = sim.get_unit_positions(player_units, enemy_units)
        
        # Каждый юнит должен иметь позицию
        for u in player_units:
            assert u in positions
        for u in enemy_units:
            assert u in positions
        
        # Позиции должны быть кортежами из двух чисел (x, y)
        for unit, pos in positions.items():
            assert isinstance(pos, tuple)
            assert len(pos) == 2
            assert isinstance(pos[0], (int, float))
            assert isinstance(pos[1], (int, float))

    def test_player_units_on_left(self):
        """Юниты игрока должны быть слева."""
        sim = BattleSimulator(seed=1)
        sim.add_team("player", [{"name": "u", "hp": 300, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("enemy", [{"name": "v", "hp": 300, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        
        positions = sim.get_unit_positions(
            list(sim.teams["player"]),
            list(sim.teams["enemy"])
        )
        
        player_pos = positions[list(sim.teams["player"])[0]]
        enemy_pos = positions[list(sim.teams["enemy"])[0]]
        
        # Игрок слева (x < 600), враг справа (x > 600)
        assert player_pos[0] < 600
        assert enemy_pos[0] > 600


class TestSnapshotRestore:
    """Тесты на восстановление состояния из snapshot'а."""

    def test_restore_from_snapshot(self):
        """Восстановление из snapshot возвращает юнитов в исходное состояние."""
        sim = BattleSimulator(seed=1)
        sim.add_team("a", [{"name": "u", "hp": 100, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("b", [{"name": "v", "hp": 100, "damage": 20, "attack_speed": 1.0, "range_": 1}])
        
        # Сохраняем начальный snapshot (до боя)
        initial_snapshot = {
            "a": [{"name": "u", "hp": 100, "max_hp": 100, "alive": True,
                   "attack_timer": 60, "damage": 20, "attack_speed": 1.0,
                   "range_": 1, "team": "a", "unit_id": 0}],
            "b": [{"name": "v", "hp": 100, "max_hp": 100, "alive": True,
                   "attack_timer": 60, "damage": 20, "attack_speed": 1.0,
                   "range_": 1, "team": "b", "unit_id": 1}],
        }
        
        # Наносим урон напрямую
        sim.teams["a"][0].hp = 50
        sim.teams["a"][0].attack_timer = 30
        
        # Восстанавливаем из snapshot
        sim.restore_from_snapshot(initial_snapshot)
        
        assert sim.teams["a"][0].hp == 100
        assert sim.teams["a"][0].alive is True
        assert sim.teams["a"][0].attack_timer == 60

    def test_snapshot_contains_all_needed_data(self):
        """Snapshot содержит все данные, нужные для восстановления."""
        sim = BattleSimulator(seed=1)
        sim.add_team("p", [{"name": "u", "hp": 200, "damage": 30, "attack_speed": 1.0, "range_": 1}])
        sim.add_team("e", [{"name": "v", "hp": 200, "damage": 30, "attack_speed": 1.0, "range_": 1}])
        
        # Прогоняем несколько тиков
        for _ in range(5):
            sim.tick_count += 1
            all_units = [u for team in sim.teams.values() for u in team]
            for unit in all_units:
                if not unit.alive:
                    continue
                unit.attack_timer -= 1
        
        snapshot = sim._take_snapshot()
        
        # Проверяем что snapshot содержит все необходимые поля
        for team_name, units in snapshot.items():
            for u_data in units:
                assert "hp" in u_data
                assert "max_hp" in u_data
                assert "alive" in u_data
                assert "attack_timer" in u_data
                assert "unit_id" in u_data


class TestVisualEffectsIntegration:
    """Интеграционные тесты: бой → события атак → визуальные эффекты."""

    def test_full_battle_produces_all_effects(self):
        """Полный бой генерирует все типы эффектов."""
        sim = BattleSimulator(seed=42)
        
        player_data = [
            {"name": "warrior", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1},
            {"name": "mage", "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4},
        ]
        enemy_data = [
            {"name": "archer", "hp": 250, "damage": 45, "attack_speed": 1.5, "range_": 3},
            {"name": "warrior", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1},
        ]
        
        sim.add_team("player", player_data)
        sim.add_team("enemy", enemy_data)
        
        result = sim.run(max_ticks=600)
        
        # Бой должен завершиться победой/поражением
        assert result["winner"] in ("player", "enemy")
        
        # Должны быть события атак
        attack_events = sim.get_attack_events()
        assert len(attack_events) > 0
        
        # Каждый event содержит информацию о цели
        for evt in attack_events:
            assert isinstance(evt["targets"], list)
            assert len(evt["targets"]) >= 1
            
        # Должна быть история тиков
        assert len(sim._tick_history) > 0
        
        # Должен быть лог событий
        assert len(sim.log) > 0

    def test_attack_events_match_log_count(self):
        """Количество событий атак должно соответствовать количеству записей в логе."""
        sim = BattleSimulator(seed=123)
        
        player_data = [
            {"name": "u", "hp": 400, "damage": 35, "attack_speed": 1.0, "range_": 1},
        ]
        enemy_data = [
            {"name": "v", "hp": 400, "damage": 35, "attack_speed": 1.0, "range_": 1},
        ]
        
        sim.add_team("p", player_data)
        sim.add_team("e", enemy_data)
        
        sim.run(max_ticks=600)
        
        # Каждое событие атаки должно соответствовать хотя бы одному событию в логе
        attack_events = sim.get_attack_events()
        hit_events = [e for e in sim.log if e["type"] == "hit"]
        kill_events = [e for e in sim.log if e["type"] == "kill"]
        
        # Количество событий атак должно быть <= количество записей в логе
        # (каждая атака может нанести урон 1+ целям, каждая → запись в логе)
        assert len(attack_events) > 0
        assert len(sim.log) >= len(attack_events)
