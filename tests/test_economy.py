"""Тесты для game/core/synergies.py и улучшенной economy.py."""

import pytest
from game.core.synergies import (
    calculate_synergy_bonuses,
    get_active_synergies,
)
from game.core.economy import (
    calculate_interest,
    round_economy,
    base_income,
)


# ---------- calculate_synergy_bonuses ----------

class TestCalculateSynergyBonuses:
    def test_no_units_no_bonuses(self):
        """Пустая команда — никаких бонусов."""
        bonuses = calculate_synergy_bonuses([], {})
        assert bonuses == {}

    def test_single_unit_no_threshold_met(self):
        """1 юнит, порог 2 — синергия не активна."""
        team = [{"class": "warrior"}]
        syn_data = {"warrior": {"thresholds": [2, 4], "bonuses": {}}}
        bonuses = calculate_synergy_bonuses(team, syn_data)
        assert bonuses == {}

    def test_two_warriors_activates_threshold_2(self):
        """2 воина — активируется порог 2."""
        team = [{"class": "warrior"}, {"class": "warrior"}]
        syn_data = {
            "warrior": {
                "thresholds": [2, 4],
                "bonuses": {"2": {"hp_bonus_pct": 15}},
            }
        }
        bonuses = calculate_synergy_bonuses(team, syn_data)
        assert "warrior" in bonuses
        assert bonuses["warrior"]["hp_bonus_pct"] == 15

    def test_four_warriors_activates_threshold_4(self):
        """4+ воина — активируется порог 4 (перекрывает порог 2)."""
        team = [{"class": "warrior"} for _ in range(4)]
        syn_data = {
            "warrior": {
                "thresholds": [2, 4],
                "bonuses": {"2": {"hp_bonus_pct": 15}, "4": {"hp_bonus_pct": 30}},
            }
        }
        bonuses = calculate_synergy_bonuses(team, syn_data)
        assert bonuses["warrior"]["hp_bonus_pct"] == 30

    def test_multiple_synergies(self):
        """Несколько синергий считаются независимо."""
        team = [
            {"class": "warrior"}, {"class": "warrior"},
            {"class": "mage"}, {"class": "mage"},
        ]
        syn_data = {
            "warrior": {
                "thresholds": [2],
                "bonuses": {"2": {"hp_bonus_pct": 15}},
            },
            "mage": {
                "thresholds": [2],
                "bonuses": {"2": {"mana_per_kill": 5}},
            },
        }
        bonuses = calculate_synergy_bonuses(team, syn_data)
        assert "warrior" in bonuses
        assert "mage" in bonuses

    def test_mixed_classes(self):
        """Смешанный состав: только те классы что набрали порог."""
        team = [
            {"class": "warrior"}, {"class": "warrior"},  # 2 воина → синергия активна
            {"class": "mage"},                            # 1 маг → синергия неактивна
        ]
        syn_data = {
            "warrior": {
                "thresholds": [2],
                "bonuses": {"2": {"hp_bonus_pct": 15}},
            },
            "mage": {
                "thresholds": [2],
                "bonuses": {"2": {"mana_per_kill": 5}},
            },
        }
        bonuses = calculate_synergy_bonuses(team, syn_data)
        assert "warrior" in bonuses
        assert "mage" not in bonuses


# ---------- get_active_synergies ----------

class TestGetActiveSynergies:
    def test_returns_list_of_names(self):
        team = [{"class": "warrior"} for _ in range(3)]
        syn_data = {
            "warrior": {"thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}},
        }
        active = get_active_synergies(team, syn_data)
        assert active == ["warrior"]

    def test_empty_team(self):
        active = get_active_synergies([], {})
        assert active == []


# ---------- calculate_interest ----------

class TestCalculateInterest:
    def test_zero_gold_no_interest(self):
        assert calculate_interest(0) == 0

    def test_9_gold_no_interest(self):
        assert calculate_interest(9) == 0

    def test_10_gold_one_percent(self):
        assert calculate_interest(10) == 1

    def test_49_gold_three_percent_max(self):
        assert calculate_interest(49) == 3

    def test_50_gold_three_percent_max(self):
        assert calculate_interest(50) == 3

    def test_100_gold_still_three_percent_max(self):
        assert calculate_interest(100) == 3

    def test_large_gold_still_capped_at_three(self):
        assert calculate_interest(999) == 3


# ---------- round_economy ----------

class TestRoundEconomy:
    def test_creep_win_with_interest(self):
        """Победа над крипами + проценты."""
        result = round_economy(gold=40, creep_win=True)
        assert result["income"] == 7       # BASE_INCOME 5 + CREEP_WIN_GOLD 2
        assert result["interest"] == 3     # 40 // 10 = 4, capped at MAX_INTEREST=3
        assert result["total_earned"] == 10
        assert result["gold_after"] == 50

    def test_pvp_win_with_interest(self):
        """Победа в PvP."""
        result = round_economy(gold=50, pvp_win=True)
        assert result["income"] == 6       # BASE_INCOME 5 + WIN_BONUS 1
        assert result["interest"] == 3     # max 3
        assert result["total_earned"] == 9

    def test_loss_with_interest(self):
        """Поражение + проценты."""
        result = round_economy(gold=30)
        assert result["income"] == 5       # BASE_INCOME only
        assert result["interest"] == 3     # 30 // 10 = 3
        assert result["total_earned"] == 8

    def test_zero_gold_loss(self):
        """Ноль золота — только базовый доход."""
        result = round_economy(gold=0)
        assert result["income"] == 5
        assert result["interest"] == 0
        assert result["gold_after"] == 5

    def test_max_interest(self):
        """Максимальный процент при 30+ золота."""
        result = round_economy(gold=60, pvp_win=True)
        assert result["interest"] == 3
        assert result["total_earned"] == 9


# ---------- base_income ----------

class TestBaseIncome:
    def test_creep_win(self):
        assert base_income(creep_win=True) == 7

    def test_pvp_win_only(self):
        assert base_income(pvp_win=True) == 6

    def test_loss(self):
        assert base_income() == 5
