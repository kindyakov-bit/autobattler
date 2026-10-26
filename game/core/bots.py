"""Bots AI: simple strategies for PvP rounds.

Difficulty levels:
  - EASY: buys cheapest units, random placement
  - MEDIUM: builds synergies (2+ of one class), balanced composition
  - HARD: optimizes composition by power-to-cost ratio
"""

import random


class BotConfig:
    """Bot configuration."""

    def __init__(self, name: str, difficulty: str = "MEDIUM"):
        self.name = name
        self.difficulty = difficulty  # EASY / MEDIUM / HARD
        self.rng = random.Random()


class SimpleBot:
    """Simple bot for the autobattler."""

    def __init__(self, name: str, difficulty: str = "MEDIUM", seed: int = None):
        self.name = name
        self.difficulty = difficulty
        self.rng = random.Random(seed)
        self.gold = 0
        self.units_on_board: list[dict] = []

    def decide_draft(self, available_units: dict, gold: int,
                     current_team: list[dict], synergy_data: dict) -> list[dict]:
        """Make draft decisions."""
        if self.difficulty == "EASY":
            return self._easy_draft(available_units, gold)
        elif self.difficulty == "MEDIUM":
            return self._medium_draft(available_units, gold, current_team, synergy_data)
        else:  # HARD
            return self._hard_draft(available_units, gold, current_team, synergy_data)

    def _easy_draft(self, available_units: dict, gold: int) -> list[dict]:
        """EASY: buys cheapest units within budget."""
        purchases = []
        remaining_gold = gold
        sorted_units = sorted(available_units.values(), key=lambda u: u.get("cost", 1))
        for unit in sorted_units:
            cost = unit.get("cost", 1)
            if remaining_gold >= cost and len(purchases) < 6:
                purchases.append(dict(unit))
                remaining_gold -= cost
        return purchases

    def _medium_draft(self, available_units: dict, gold: int,
                      current_team: list[dict], synergy_data: dict) -> list[dict]:
        """MEDIUM: tries to build a 2+ class synergy."""
        purchases = []
        remaining_gold = gold
        class_counts = {}
        for u in current_team:
            cls = u.get("class")
            if cls:
                class_counts[cls] = class_counts.get(cls, 0) + 1
        target_class = None
        for syn_name in synergy_data:
            count = class_counts.get(syn_name, 0)
            thresholds = synergy_data[syn_name].get("thresholds", [])
            if count >= 1 and len(thresholds) > 0 and count < thresholds[0]:
                target_class = syn_name
                break
        same_class_units = [u for u in available_units.values()
                           if u.get("class") == target_class]
        other_units = [u for u in available_units.values()
                       if u.get("class") != target_class]
        all_sorted = same_class_units + other_units
        all_sorted.sort(key=lambda u: u.get("cost", 1))
        for unit in all_sorted:
            cost = unit.get("cost", 1)
            if remaining_gold >= cost and len(purchases) < 6:
                purchases.append(dict(unit))
                remaining_gold -= cost
        return purchases

    def _hard_draft(self, available_units: dict, gold: int,
                    current_team: list[dict], synergy_data: dict) -> list[dict]:
        """HARD: optimizes composition by power-to-cost ratio."""
        purchases = []
        remaining_gold = gold

        def unit_power(u):
            hp = u.get("hp", 100)
            dmg = u.get("damage", 10)
            cost = max(1, u.get("cost", 1))
            return (dmg * 2 + hp / 10) / cost

        sorted_units = sorted(available_units.values(),
                              key=unit_power, reverse=True)
        for unit in sorted_units:
            cost = unit.get("cost", 1)
            if remaining_gold >= cost and len(purchases) < 6:
                purchases.append(dict(unit))
                remaining_gold -= cost
        return purchases

    def get_team(self) -> list[dict]:
        """Get current team composition."""
        return list(self.units_on_board)


BOT_PRESETS = {
    "aggressive": {"name": "Aggressive", "difficulty": "HARD"},
    "balanced":   {"name": "Balanced",   "difficulty": "MEDIUM"},
    "casual":     {"name": "Casual",     "difficulty": "EASY"},
}


def create_bot(preset: str = "balanced", seed: int = None) -> SimpleBot:
    """Create a bot from preset."""
    config = BOT_PRESETS.get(preset, BOT_PRESETS["balanced"])
    return SimpleBot(
        name=config["name"],
        difficulty=config["difficulty"],
        seed=seed,
    )
