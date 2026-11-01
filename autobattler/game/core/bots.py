"""Bots AI: simple strategies for PvP rounds.

Difficulty levels:
   - EASY: buys cheapest units, random placement
   - MEDIUM: builds synergies (2+ of one class), balanced composition
   - HARD: optimizes composition by power-to-cost ratio

ВАЖНО: decide_draft() возвращает юнитов с полем ``name`` = КЛЮЧ из
data/units.json (например "warrior_freshman"), а не отображаемое имя
("Новобранец"). Магазин и пул работают с ключами — если вернуть
отображаемое имя, Shop.buy упадёт с «копий в пуле не осталось» и бот
останется с пустой доской.
"""

import random


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
        """Make draft decisions.

        Returns:
            Список юнитов с ``name`` = ключ JSON, ``cost``, ``display_name``,
            ``class``. Вызывающий код кормит их Shop/DraftPhase.
        """
        if self.difficulty == "EASY":
            return self._easy_draft(available_units, gold)
        elif self.difficulty == "MEDIUM":
            return self._medium_draft(available_units, gold, current_team, synergy_data)
        elif self.difficulty == "HARD":
            return self._hard_draft(available_units, gold, current_team, synergy_data)
        elif self.difficulty == "SAVER":
            return self._saver_draft(available_units, gold)
        elif self.difficulty == "SYNERGY_FOCUS":
            return self._synergy_focus_draft(
                available_units, gold, current_team, synergy_data)
        elif self.difficulty == "RANDOM":
            return self._random_draft(available_units, gold)
        else:
            return self._easy_draft(available_units, gold)

    # ── общая механика покупки ─────────────────────────────────────────────

    @staticmethod
    def _as_purchasable(key: str, unit: dict) -> dict:
        """Превратить определение юнита в «покупаемый» элемент для магазина."""
        return {
            "name": key,                       # ключ JSON — им оперирует Shop
            "cost": unit.get("cost", 1),
            "display_name": unit.get("name", key),
            "class": unit.get("class", ""),
        }

    def _buy_loop(self, sorted_units, gold: int) -> list[dict]:
        """Покупаем по очереди, пока хватает золота и слотов (до 6)."""
        purchases = []
        remaining_gold = gold
        for key, unit in sorted_units:
            cost = unit.get("cost", 1)
            if remaining_gold >= cost and len(purchases) < 6:
                purchases.append(self._as_purchasable(key, unit))
                remaining_gold -= cost
        return purchases

    # ── стратегии ──────────────────────────────────────────────────────────

    def _easy_draft(self, available_units: dict, gold: int) -> list[dict]:
        """EASY: buys cheapest units within budget."""
        units = sorted(available_units.items(), key=lambda kv: kv[1].get("cost", 1))
        return self._buy_loop(units, gold)

    def _medium_draft(self, available_units: dict, gold: int,
                      current_team: list[dict], synergy_data: dict) -> list[dict]:
        """MEDIUM: строит синергию — добирает порог 2/4 одного класса.

        Раньше код искал класс, где «не хватает одного юнита до порога», но
        такое условие требовало уже имеющегося юнита этого класса. Бот всегда
        стартует с пустой доски, поэтому target_class никогда не выбирался и
        синергии не строились никогда. Теперь бот сам выбирает целевой класс.
        """
        class_counts = {}
        for u in current_team:
            cls = u.get("class")
            if cls:
                class_counts[cls] = class_counts.get(cls, 0) + 1

        # Выбираем класс, который выгоднее всего добирать: чем ниже порог и
        # чем дешевле юниты класса, тем лучше. Учитываем уже купленных.
        best_class, best_score = None, -1.0
        for syn_name, syn_info in synergy_data.items():
            thresholds = sorted(syn_info.get("thresholds", []))
            if not thresholds:
                continue
            have = class_counts.get(syn_name, 0)
            need = next((t for t in thresholds if t > have), None)
            if need is None:
                continue
            to_buy = need - have
            units_of_class = [(k, u) for k, u in available_units.items()
                              if u.get("class") == syn_name]
            if len(units_of_class) < to_buy:
                continue
            cheapest = sorted((u.get("cost", 1) for _, u in units_of_class))[:to_buy]
            price = sum(cheapest)
            if price > gold:
                continue
            # выгоднее: низкая цена за порог и низкий сам порог
            score = (len(thresholds) - thresholds.index(need)) * 10 - price
            if score > best_score:
                best_class, best_score = syn_name, score

        target_class = best_class if best_class is not None else "warrior"

        same = [(k, u) for k, u in available_units.items()
                if u.get("class") == target_class]
        other = [(k, u) for k, u in available_units.items()
                 if u.get("class") != target_class]
        # Дешёвые первыми внутри своей группы
        same.sort(key=lambda kv: kv[1].get("cost", 1))
        other.sort(key=lambda kv: kv[1].get("cost", 1))
        return self._buy_loop(same + other, gold)

    def _hard_draft(self, available_units: dict, gold: int,
                    current_team: list[dict], synergy_data: dict) -> list[dict]:
        """HARD: optimizes composition by power-to-cost ratio."""

        def unit_power(kv):
            u = kv[1]
            hp = u.get("hp", 100)
            dmg = u.get("damage", 10)
            cost = max(1, u.get("cost", 1))
            return (dmg * 2 + hp / 10) / cost

        units = sorted(available_units.items(), key=unit_power, reverse=True)
        return self._buy_loop(units, gold)

    def get_team(self) -> list[dict]:
        """Get current team composition."""
        return list(self.units_on_board)

    # ── новые стили ботов ──────────────────────────────────────────────────

    def _saver_draft(self, available_units: dict, gold: int) -> list[dict]:
        """Экономичный бот: не тратит золото рано, копит на прокадку магазина.

        Покупает только самых дешёвых юнитов (cost 1), оставляет резерв
        золота для будущих раундов. В поздней игре может позволить себе
        дорогих юнитов.
        """
        cheap = [(k, u) for k, u in available_units.items()
                 if u.get("cost", 1) <= 1]
        cheap.sort(key=lambda kv: kv[1].get("cost", 1))
        # Тратим не больше половины золота, копим остальное
        budget = gold // 2
        return self._buy_loop(cheap, budget)

    def _synergy_focus_draft(self, available_units: dict, gold: int,
                             current_team: list[dict],
                             synergy_data: dict) -> list[dict]:
        """Синергийный бот: агрессивно собирает одного класса до порога 4.

        Выбирает класс с наибольшим количеством уже имеющихся юнитов и
        докупает его же, чтобы быстро закрыть пороги синергии 2 и 4.
        """
        class_counts = {}
        for u in current_team:
            cls = u.get("class")
            if cls:
                class_counts[cls] = class_counts.get(cls, 0) + 1

        if not class_counts:
            # Первый раунд — выбираем класс с самыми дешёвыми юнитами
            best_class = None
            best_price = float('inf')
            for syn_name, syn_info in synergy_data.items():
                units_of_class = [(k, u) for k, u in available_units.items()
                                  if u.get("class") == syn_name]
                if not units_of_class:
                    continue
                price = min(u.get("cost", 1) for _, u in units_of_class)
                if price < best_price:
                    best_price = price
                    best_class = syn_name
            target_class = best_class or "warrior"
        else:
            # Добираем класс, которого уже больше всего
            target_class = max(class_counts, key=class_counts.get)

        same = [(k, u) for k, u in available_units.items()
                if u.get("class") == target_class]
        other = [(k, u) for k, u in available_units.items()
                 if u.get("class") != target_class]
        same.sort(key=lambda kv: kv[1].get("cost", 1))
        other.sort(key=lambda kv: kv[1].get("cost", 1))
        # Сначала своёicho, потом остальные на оставшиеся деньги
        return self._buy_loop(same + other, gold)

    def _random_draft(self, available_units: dict, gold: int) -> list[dict]:
        """Случайный бот: покупает случайных юнитов в рамках бюджета."""
        units = list(available_units.items())
        self.rng.shuffle(units)
        units.sort(key=lambda kv: kv[1].get("cost", 1))
        return self._buy_loop(units, gold)


BOT_PRESETS = {
    "aggressive":   {"name": "Aggressive",   "difficulty": "HARD"},
    "balanced":     {"name": "Balanced",     "difficulty": "MEDIUM"},
    "casual":       {"name": "Casual",       "difficulty": "EASY"},
    "saver":        {"name": "Saver",        "difficulty": "SAVER"},
    "synergy_focus":{"name": "Synergy Focus","difficulty": "SYNERGY_FOCUS"},
    "random":       {"name": "Random",       "difficulty": "RANDOM"},
}


def create_bot(preset: str = "balanced", seed: int = None) -> SimpleBot:
    """Create a bot from preset."""
    config = BOT_PRESETS.get(preset, BOT_PRESETS["balanced"])
    return SimpleBot(
        name=config["name"],
        difficulty=config["difficulty"],
        seed=seed,
    )


def create_bot(preset: str = "balanced", seed: int = None) -> SimpleBot:
    """Create a bot from preset."""
    config = BOT_PRESETS.get(preset, BOT_PRESETS["balanced"])
    return SimpleBot(
        name=config["name"],
        difficulty=config["difficulty"],
        seed=seed,
    )
