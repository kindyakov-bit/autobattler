"""Фазa драфта: покупка, продажа, размещение юнитов между раундами."""

import random


class DraftPhase:
    """Управление фазой драфта между раундами."""

    def __init__(self, shop, unit_data: dict):
        self.shop = shop
        self.unit_data = unit_data  # {name: {...}} из JSON
        self.rng = random.Random()

    def get_shop_items(self, count: int = 10) -> list[dict]:
        """Получить список юнитов в магазине (ролл)."""
        return self.shop.roll(count=count)

    def buy_unit(self, player, name: str) -> str:
        """Купить юнита из магазина. Возвращает имя после merge."""
        cost = self.unit_data.get(name, {}).get("cost", 1)
        return self.shop.buy(player, name, cost=cost)

    def sell_unit(self, player, idx: int) -> str:
        """Продать юнита из резерва. Возвращает базовое имя."""
        return self.shop.sell(player, idx)

    def place_on_board(self, player, idx: int) -> dict:
        """Разместить юнита на доске."""
        return self.shop.place(player, idx)

    def remove_from_board(self, player, idx: int) -> str:
        """Убрать юнита с доски."""
        return self.shop.remove_from_board(player, idx)

    def get_board_units(self, player) -> list[dict]:
        """Получить список юнитов на доске для боя."""
        return player.get_team_stats()

    def get_bench_info(self, player) -> list[str]:
        """Информация о резерве."""
        return list(player.reserve)

    def get_synergy_counts(self, player) -> dict:
        """Сколько юнитов каждого класса на доске."""
        counts = {}
        for u in player.board:
            base = u["name"].split("★")[0]
            cls = base.split("_")[0]  # warrior, mage, archer
            counts[cls] = counts.get(cls, 0) + 1
        return counts
