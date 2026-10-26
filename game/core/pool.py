"""Пул копий юнитов: сколько свободных копий каждой единицы осталось в игре."""

COPIES_BY_COST = {1: 29, 2: 22, 3: 18, 4: 12, 5: 10}


class Pool:
    """Трекает свободные копии юнитов. unit_costs: имя -> стоимость (1..5)."""

    def __init__(self, unit_costs: dict):
        self.remaining = {u: COPIES_BY_COST[c] for u, c in unit_costs.items()}

    def take(self, unit: str) -> None:
        """Взять копию на доску. Когда копии кончились — юнит исчерпан."""
        self.remaining[unit] -= 1
        if self.remaining[unit] == 0:
            del self.remaining[unit]

    def refund(self, unit: str, copies: int = 1) -> None:
        """Вернуть copies копий в пул (слияние ★2 возвращает 2)."""
        self.remaining[unit] = self.remaining.get(unit, 0) + copies

    def available(self, unit: str) -> int:
        """Свободные копии (0, если юнит исчерпан)."""
        return self.remaining.get(unit, 0)
