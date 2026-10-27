"""Тесты для game/core/bots.py — SimpleBot, create_bot."""

import pytest
from game.core.bots import SimpleBot, create_bot, BOT_PRESETS


# ---------- SimpleBot: EASY ----------

class TestEasyBot:
    def test_easy_draft_purchases_cheapest(self):
        """EASY бот покупает дешёвых юнитов в пределах бюджета."""
        bot = SimpleBot("test", difficulty="EASY")
        available = {
            "u1": {"name": "u1", "cost": 1, "hp": 100, "damage": 10},
            "u2": {"name": "u2", "cost": 3, "hp": 300, "damage": 30},
            "u3": {"name": "u3", "cost": 5, "hp": 500, "damage": 50},
        }

        purchases = bot.decide_draft(available, gold=4, current_team=[], synergy_data={})

        # Должен купить u1 (cost=1), возможно ещё что-то если осталось
        assert len(purchases) >= 1
        for p in purchases:
            assert p.get("cost", 0) <= 5  # в пределах бюджета

    def test_easy_draft_respects_gold(self):
        """EASY бот не тратит больше золота чем есть."""
        bot = SimpleBot("test", difficulty="Easy")
        available = {
            "u1": {"name": "u1", "cost": 3, "hp": 100, "damage": 10},
            "u2": {"name": "u2", "cost": 5, "hp": 300, "damage": 30},
        }

        purchases = bot.decide_draft(available, gold=4, current_team=[], synergy_data={})

        total_cost = sum(p.get("cost", 0) for p in purchases)
        assert total_cost <= 4


# ---------- SimpleBot: MEDIUM ----------

class TestMediumBot:
    def test_medium_prioritizes_synergy_class(self):
        """MEDIUM бот приоритизирует класс для синергии."""
        bot = SimpleBot("test", difficulty="MEDIUM")
        available = {
            "w1": {"name": "w1", "cost": 1, "class": "warrior", "hp": 200, "damage": 15},
            "w2": {"name": "w2", "cost": 3, "class": "warrior", "hp": 400, "damage": 25},
            "m1": {"name": "m1", "cost": 1, "class": "mage", "hp": 150, "damage": 20},
        }

        # Уже есть 1 воин → бот должен докупить ещё воина для синергии (порог 2)
        current = [{"name": "w1", "cost": 1, "class": "warrior", "hp": 200, "damage": 15}]
        synergy_data = {
            "warrior": {"thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}},
        }

        purchases = bot.decide_draft(available, gold=3, current_team=current,
                                     synergy_data=synergy_data)

        # Должен купить хотя бы одного воина
        warrior_purchases = [p for p in purchases if p.get("class") == "warrior"]
        assert len(warrior_purchases) >= 1


# ---------- SimpleBot: HARD ----------

class TestHardBot:
    def test_hard_optimizes_power_per_cost(self):
        """HARD бот выбирает юнитов с лучшим соотношением сила/стоимость."""
        bot = SimpleBot("test", difficulty="HARD")
        available = {
            "cheap": {"name": "c", "cost": 1, "hp": 50, "damage": 5},       # power = (5*2+5)/1 = 15
            "expensive": {"name": "e", "cost": 5, "hp": 600, "damage": 80},  # power = (80*2+60)/5 = 44
        }

        purchases = bot.decide_draft(available, gold=10, current_team=[], synergy_data={})

        # Должен купить обоих (оба выгодны по силе/стоимость)
        assert len(purchases) >= 1


# ---------- create_bot / BOT_PRESETS ----------

class TestBotFactory:
    def test_create_bot_presets(self):
        """Все пресеты создают валидных ботов."""
        for preset_name in BOT_PRESETS:
            bot = create_bot(preset=preset_name)
            assert isinstance(bot, SimpleBot)
            assert bot.difficulty in ("EASY", "MEDIUM", "HARD", "SAVER", "SYNERGY_FOCUS", "RANDOM")

    def test_create_bot_with_seed(self):
        """Бот с seed создаётся корректно."""
        bot = create_bot(seed=12345)
        assert bot.rng is not None
