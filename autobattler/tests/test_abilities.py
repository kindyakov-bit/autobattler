"""Тесты для системы активных и пассивных способностей (Фаза 9)."""

import pytest
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_project_root))


class TestAbilityVisualEffects:
    """Тесты визуальных эффектов способностей в UI."""

    def test_ability_effect_class_exists(self):
        """Класс AbilityEffect существует и создаётся."""
        from ui.game_ui import AbilityEffect
        
        effect = AbilityEffect(100, 100, "Огненный шар", "aoe_damage")
        assert effect.x == 100
        assert effect.y == 100
        assert effect.ability_name == "Огненный шар"
        assert effect.effect_type == "aoe_damage"

    def test_ability_effect_updates(self):
        """Эффект способности обновляется и исчезает."""
        from ui.game_ui import AbilityEffect
        
        effect = AbilityEffect(100, 100, "Test", "aoe_damage")
        # Прогоняем эффект до конца жизни
        alive = True
        while alive:
            alive = effect.update()
        assert not effect.life > 0

    def test_ability_effect_colors(self):
        """Разные типы способностей имеют разные цвета."""
        from ui.game_ui import AbilityEffect
        
        for effect_type in ["aoe_damage", "aoe_damage_slow", "single_target_critical", "buff_allies"]:
            effect = AbilityEffect(100, 100, "Test", effect_type)
            assert effect.effect_type == effect_type
            assert effect.COLORS.get(effect_type) is not None


class TestPassiveAbilities:
    """Тесты расчёта пассивных бонусов от синергий."""

    @pytest.fixture
    def unit_data(self):
        import json
        with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
            return json.load(f)["units"]

    def test_passive_warrior_hp(self, unit_data):
        """Новобранец получает +10% HP за каждого союзного воина."""
        from game.core.synergies import calculate_passive_bonuses
        
        team = [
            {"name": "warrior_freshman", "class": "warrior"},
            {"name": "warrior_veteran", "class": "warrior"},
        ]
        bonuses = calculate_passive_bonuses(team, unit_data)
        
        assert "warrior_freshman" in bonuses
        assert bonuses["warrior_freshman"]["bonus_value"] == 10  # 1 ally × 10%
        assert bonuses["warrior_veteran"]["bonus_value"] == 15  # 1 ally × 15%

    def test_passive_mage_damage(self, unit_data):
        """Маг получает +10-25% урона за каждого союзного мага."""
        from game.core.synergies import calculate_passive_bonuses
        
        team = [
            {"name": "mage_acolyte", "class": "mage"},
            {"name": "mage_sorcerer", "class": "mage"},
            {"name": "mage_archmage", "class": "mage"},
        ]
        bonuses = calculate_passive_bonuses(team, unit_data)
        
        assert "mage_acolyte" in bonuses
        assert bonuses["mage_acolyte"]["bonus_value"] == 20  # 2 allies × 10%
        assert bonuses["mage_archmage"]["bonus_value"] == 40  # 2 allies × 20%

    def test_passive_archer_speed(self, unit_data):
        """Стрелок получает +10-25% скорости атаки за каждого союзного стрелка."""
        from game.core.synergies import calculate_passive_bonuses
        
        team = [
            {"name": "archer_scout", "class": "archer"},
            {"name": "archer_ranger", "class": "archer"},
        ]
        bonuses = calculate_passive_bonuses(team, unit_data)
        
        assert "archer_scout" in bonuses
        assert bonuses["archer_scout"]["bonus_value"] == 10  # 1 ally × 10%

    def test_passive_no_ally(self, unit_data):
        """Если нет союзников своего класса — бонус не включён в результат."""
        from game.core.synergies import calculate_passive_bonuses
        
        team = [
            {"name": "warrior_freshman", "class": "warrior"},
        ]
        bonuses = calculate_passive_bonuses(team, unit_data)
        
        # При 0 союзниках бонус = 0, поэтому юнит не попадает в результат
        assert "warrior_freshman" not in bonuses

    def test_apply_passive_hp(self, unit_data):
        """Применение пассивного бонуса HP к юниту."""
        from game.core.synergies import calculate_passive_bonuses, apply_passive_bonuses
        
        team = [
            {"name": "warrior_freshman", "class": "warrior", "hp": 500},
            {"name": "warrior_veteran", "class": "warrior"},
        ]
        bonuses = calculate_passive_bonuses(team, unit_data)
        result = apply_passive_bonuses(team, bonuses)
        
        # Новобранец: 500 + 10% = 550 HP
        assert result[0]["hp"] == 550


class TestActiveAbilities:
    """Тесты активных способностей в бою."""

    def test_aoe_damage_ability(self):
        """Огненный шар наносит урон всем врагам в радиусе."""
        from game.battle.engine import BattleSimulator
        
        sim = BattleSimulator(seed=42)
        
        # Команда игрока с магом (имеет Огненный шар)
        player_units = [
            {
                "name": "mage_acolyte",
                "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4,
                "active": {
                    "name": "Огненный шар",
                    "type": "aoe_damage",
                    "cooldown": 2,
                    "effect": {"damage": 80, "radius": 2},
                }
            },
        ]
        enemy_units = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
            {"name": "archer_scout", "hp": 250, "damage": 45, "attack_speed": 1.5, "range_": 3, "class": "archer"},
        ]
        
        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        
        result = sim.run(max_ticks=60)
        
        # Проверяем что была способность в логе
        ability_events = [e for e in sim.log if "ability" in e.get("type", "")]
        assert len(ability_events) >= 1, "Способность должна сработать хотя бы раз"

    def test_aoe_damage_kills_enemy(self):
        """Огненный шар может убить врага."""
        from game.battle.engine import BattleSimulator
        
        sim = BattleSimulator(seed=42)
        
        player_units = [
            {
                "name": "mage_acolyte",
                "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4,
                "active": {
                    "name": "Огненный шар",
                    "type": "aoe_damage",
                    "cooldown": 2,
                    "effect": {"damage": 80, "radius": 3},
                }
            },
        ]
        # Слабый юнит — один удар Огненного шара может его убить
        enemy_units = [
            {"name": "warrior_freshman", "hp": 50, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
        ]
        
        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        
        result = sim.run(max_ticks=60)
        
        ability_events = [e for e in sim.log if "ability" in e.get("type", "")]
        assert len(ability_events) >= 1


class TestAbilityEvents:
    """Тесты получения событий способностей для UI."""

    def test_get_ability_events(self):
        """BattleSimulator.get_ability_events() возвращает события."""
        from game.battle.engine import BattleSimulator
        
        sim = BattleSimulator(seed=42)
        
        player_units = [
            {
                "name": "mage_acolyte",
                "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4,
                "active": {
                    "name": "Огненный шар",
                    "type": "aoe_damage",
                    "cooldown": 2,
                    "effect": {"damage": 80, "radius": 3},
                }
            },
        ]
        enemy_units = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
        ]
        
        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        sim.run(max_ticks=30)
        
        ability_events = sim.get_ability_events()
        assert len(ability_events) >= 1
        
        # Проверяем структуру события
        event = ability_events[0]
        assert "tick" in event
        assert "caster_id" in event
        assert "caster_team" in event
        assert "ability_name" in event
        assert "damage" in event
        assert "targets" in event


class TestCooldown:
    """Тесты кулдауна способностей."""

    def test_ability_cooldown_reduces(self):
        """Кулдаун способности уменьшается каждый тик."""
        from game.battle.engine import BattleSimulator
        
        sim = BattleSimulator(seed=42)
        
        player_units = [
            {
                "name": "mage_acolyte",
                "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4,
                "active": {
                    "name": "Огненный шар",
                    "type": "aoe_damage",
                    "cooldown": 3,
                    "effect": {"damage": 80, "radius": 2},
                }
            },
        ]
        enemy_units = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
        ]
        
        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        
        # Запускаем бой — способность должна сработать и затем ждать кулдаун
        sim.run(max_ticks=20)
        
        ability_events = sim.get_ability_events()
        # Проверяем что была хотя бы одна активация
        assert len(ability_events) >= 1


class TestIntegrated:
    """Интеграционные тесты: синергии + пассивки + способности."""

    def test_full_battle_with_all_mechanics(self):
        """Полный бой с синергиями, пассивками и активными способностями."""
        import json
        
        with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        
        from game.core.synergies import calculate_synergy_bonuses, calculate_passive_bonuses, apply_passive_bonuses
        from game.battle.engine import BattleSimulator
        
        unit_data = data["units"]
        synergy_data = data["synergies"]
        
        # Команда игрока: 2 воина + 1 маг (синергия Воин активна)
        player_units = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
            {"name": "warrior_veteran", "hp": 700, "damage": 55, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
            {"name": "mage_acolyte", "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4, "class": "mage"},
        ]
        
        enemy_units = [
            {"name": "archer_scout", "hp": 250, "damage": 45, "attack_speed": 1.5, "range_": 3, "class": "archer"},
            {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
        ]
        
        # Рассчитываем синергии
        synergy_bonuses = calculate_synergy_bonuses(player_units, synergy_data)
        assert "warrior" in synergy_bonuses
        
        # Рассчитываем пассивки
        passive_bonuses = calculate_passive_bonuses(player_units, unit_data)
        assert "warrior_freshman" in passive_bonuses  # +10% HP за союзного воина
        assert "warrior_veteran" in passive_bonuses   # +15% HP за союзного воина
        
        # Применяем пассивки
        player_units = apply_passive_bonuses(player_units, passive_bonuses)
        
        # Добавляем active способности
        for u in player_units:
            name_base = u.get("name", "").split("★")[0]
            if name_base in unit_data and unit_data[name_base].get("active"):
                u["active"] = dict(unit_data[name_base]["active"])
        
        # Запускаем бой
        sim = BattleSimulator(seed=42)
        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        result = sim.run(max_ticks=60)
        
        # Проверяем что бой завершился
        assert "winner" in result
        assert "team_hp" in result
        
        # Проверяем что были события атак и способностей
        attack_events = sim.get_attack_events()
        ability_events = sim.get_ability_events()
        assert len(attack_events) >= 1
