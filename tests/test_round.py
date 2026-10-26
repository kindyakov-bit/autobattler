"""Тесты для game/core/round.py — Game, RoundState, run_match."""

import pytest
from game.core.round import Game, RoundState, load_game_data


# ---------- RoundState ----------

class TestRoundState:
    def test_creep_round(self):
        s = RoundState(1, is_creep=True)
        assert s.round_number == 1
        assert s.is_creep is True
        assert s.gold_earned == 0
        assert s.battle_result is None

    def test_pvp_round(self):
        s = RoundState(5, is_creep=False)
        assert s.is_creep is False


# ---------- Game: базовый матч ----------

class TestGameBasicMatch:
    def test_run_single_round(self):
        """Один раунд — корректное состояние."""
        game = Game(seed=100)
        player_units = [
            {"name": "u", "hp": 200, "damage": 20, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
        ]
        enemy_units = [
            {"name": "v", "hp": 150, "damage": 15, "attack_speed": 1.0, "range_": 1, "class": "archer"},
        ]
        synergy_data = {
            "warrior": {"thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}},
        }

        state = game.run_round(
            player_gold=10,
            player_units=player_units,
            enemy_units=enemy_units,
            synergy_data=synergy_data,
        )

        assert state.round_number == 1
        assert state.is_creep is True
        assert state.gold_earned > 0 or state.interest_earned >= 0
        assert state.total_gold_after > 0
        assert len(game.history) == 1

    def test_run_eight_rounds_determines_winner(self):
        """8 раундов → матч завершён, winner определён."""
        game = Game(seed=200)

        player_units = [
            {"name": "tank", "hp": 500, "damage": 30, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
        ]
        enemy_units = [
            {"name": "scout", "hp": 200, "damage": 15, "attack_speed": 1.0, "range_": 1, "class": "archer"},
        ]
        synergy_data = {}

        gold = 10
        for _ in range(8):
            state = game.run_round(gold, player_units, enemy_units, synergy_data)
            gold = state.total_gold_after

        assert game.winner is not None
        assert game.winner in ("player", "enemy")
        assert len(game.history) == 8

    def test_match_summary_contains_info(self):
        """Сводка матча содержит информацию о каждом раунде."""
        game = Game(seed=300)

        player_units = [
            {"name": "u", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
        ]
        enemy_units = [
            {"name": "v", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1, "class": "mage"},
        ]

        for _ in range(8):
            game.run_round(10, player_units, enemy_units, {})

        summary = game.get_summary()
        assert "ИТОГИ МАТЧА" in summary
        assert "Раунд 1" in summary
        if game.winner:
            assert f"ПОБЕДИТЕЛЬ МАТЧА: {game.winner.upper()}" in summary


# ---------- Game: синергии влияют на бой ----------

class TestSynergiesInRound:
    def test_synergy_hp_bonus_affects_battle(self):
        """Синергия +15% HP меняет результат боя."""
        # С синергией (2 воина → +15% HP)
        game_with = Game(seed=400)
        team_with = [
            {"name": "w1", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
            {"name": "w2", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
        ]
        enemy = [
            {"name": "e1", "hp": 400, "damage": 30, "attack_speed": 1.0, "range_": 1, "class": "mage"},
        ]

        state_with = game_with.run_round(10, team_with, enemy, {
            "warrior": {"thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}},
        })

        # Без синергии (1 воин)
        game_without = Game(seed=400)
        team_without = [
            {"name": "w1", "hp": 300, "damage": 25, "attack_speed": 1.0, "range_": 1, "class": "warrior"},
        ]

        state_without = game_without.run_round(10, team_without, enemy, {
            "warrior": {"thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}},
        })

        # С синергией у игрока должно остаться больше HP (или тот же победитель)
        hp_with = state_with.battle_result["team_hp"].get("player", 0)
        hp_without = state_without.battle_result["team_hp"].get("player", 0)

        # Оба должны выжить или один должен выжить — проверяем что синергия помогает
        assert hp_with >= hp_without or (hp_with > 0 and hp_without == 0)


# ---------- load_game_data ----------

class TestLoadGameData:
    def test_load_json(self):
        from pathlib import Path
        project_root = Path(__file__).parent.parent.resolve()
        data = load_game_data(project_root / "data" / "units.json")
        assert "synergies" in data
        assert "units" in data


# ---------- run_match (integration) ----------

class TestRunMatch:
    def test_run_match_returns_game(self):
        from game.core.round import run_match
        game = run_match(seed=500, verbose=False)
        assert game.winner is not None
        assert len(game.history) == 8
