"""Магазин: покупка юнитов/предметов, слияние ★1→★2→★3, продажа."""

import random


class ShopError(Exception):
    """Ошибка магазина."""


class Shop:
    """Управление магазином и слиянием юнитов + предметов.

    Уровень магазина (1..6): растёт автоматически каждый раунд и может
    быть докуплен за золото (upgrade_cost). Чем выше уровень, тем дороже
    юниты в ролле — «сначала в магазине только низкоуровневые».
    """

    #: Максимальная стоимость юнита, который может выпасть на уровне N.
    MAX_COST_BY_LEVEL = {1: 1, 2: 2, 3: 3, 4: 3, 5: 4, 6: 5}

    #: Цена апгрейда магазина до следующего уровня (за золото).
    UPGRADE_COSTS = {1: 6, 2: 8, 3: 10, 4: 12, 5: 14}

    def __init__(self, pool, unit_costs: dict = None, item_data: dict = None, rng: random.Random = None):
        self.pool = pool
        self.unit_costs = unit_costs or {}  # name -> cost
        self.item_data = item_data or {}  # item_name -> item_info
        self.rng = rng or random.Random()
        self.level = 1

    @property
    def upgrade_cost(self):
        """Цена следующего апгрейда (None = максимальный уровень)."""
        return self.UPGRADE_COSTS.get(self.level)

    def upgrade(self, player=None) -> bool:
        """Поднять уровень магазина за золото игрока.

        Возвращает True, если уровень вырос. Без player — бесплатное
        повышение (используется автоматическим ростом по раундам).
        """
        if self.level >= max(self.MAX_COST_BY_LEVEL):
            return False
        if player is not None:
            cost = self.UPGRADE_COSTS.get(self.level)
            if cost is None or player.gold < cost:
                return False
            player.gold -= cost
        self.level += 1
        return True

    def _roll_candidates(self) -> list[str]:
        """Кандидаты ролла: юниты в пуле, чья цена <= потолка уровня."""
        max_cost = self.MAX_COST_BY_LEVEL.get(self.level, 1)
        return [u for u, c in self.unit_costs.items()
                if c <= max_cost and self.pool.available(u) > 0]

    def buy(self, player, name: str, cost: int = 1) -> str:
        """Покупка одной копии: списывает gold, берёт копию из пула,
        кладёт в резерв и сразу пытается слить 3 одинаковых.
        Возвращает имя, оказавшееся в резерве (после merge)."""
        if player.gold < cost:
            raise ShopError(f"нужно {cost} золота, есть {player.gold}")
        if self.pool.available(name) == 0:
            raise ShopError(f"{name}: копий в пуле не осталось")
        player.gold -= cost
        self.pool.take(name)
        player.buy(name)
        return self._maybe_merge(player, name)

    def sell(self, player, idx: int) -> str:
        """Продать юнита из резерва по индексу. Возвращает базовое имя."""
        if idx < 0 or idx >= len(player.reserve):
            raise ShopError(f"Индекс {idx} вне диапазона (reserve={len(player.reserve)})")
        name = player.reserve.pop(idx)
        base_name = name.split("★")[0]
        self.pool.refund(base_name, copies=1)
        return base_name

    def place(self, player, idx: int) -> dict:
        """Положить юнита из резерва на доску по индексу."""
        if idx < 0 or idx >= len(player.reserve):
            raise ShopError(f"Индекс {idx} вне диапазона (reserve={len(player.reserve)})")
        name = player.reserve.pop(idx)
        star = 1
        if "★" in name:
            star_str = name.split("★")[1]
            star = int(star_str) if star_str.isdigit() else 1
        unit = {"name": name, "star": star}
        player.board.append(unit)
        return unit

    def set_base_stats(self, player, idx: int, hp: int, damage: float, attack_speed: float):
        """Установить базовые статы юнита на доске (для применения процентных бонусов)."""
        if idx < 0 or idx >= len(player.board):
            raise ShopError(f"Индекс {idx} вне диапазона (board={len(player.board)})")
        unit = player.board[idx]
        unit["_base_hp"] = hp
        unit["_base_damage"] = damage
        unit["_base_attack_speed"] = attack_speed

    def remove_from_board(self, player, idx: int) -> str:
        """Убрать юнита с доски обратно в резерв. Возвращает имя."""
        if idx < 0 or idx >= len(player.board):
            raise ShopError(f"Индекс {idx} вне диапазона (board={len(player.board)})")
        unit = player.board.pop(idx)
        player.reserve.append(unit["name"])
        return unit["name"]

    def _maybe_merge(self, player, name: str) -> str:
        """Автоматически сливать 3 одинаковых в ★2, затем ★2+★2 в ★3, затем 3★2→★3.
        
        Returns merged name (after all merges). Only returns a merged name
        if this specific call triggered a merge.
        """
        base_name = name.split("★")[0]
        returned_name = name  # default: nothing was merged

        # Try to merge three base copies into ★2
        while sum(1 for r in player.reserve if r == base_name) >= 3:
            removed = []
            for r in list(player.reserve):
                if r == base_name:
                    player.reserve.remove(r)
                    removed.append(r)
                    if len(removed) == 3:
                        break
            merged = base_name + "★2"
            player.reserve.append(merged)
            self.pool.refund(base_name, copies=2)
            returned_name = merged  # this call created a ★2

        # Try to merge two ★2 copies into ★3
        while sum(1 for r in player.reserve if r == base_name + "★2") >= 2:
            removed = []
            for r in list(player.reserve):
                if r == base_name + "★2":
                    player.reserve.remove(r)
                    removed.append(r)
                    if len(removed) == 2:
                        break
            merged = base_name + "★3"
            player.reserve.append(merged)
            returned_name = merged  # this call created a ★3

        # Try to merge three ★2 copies into ★3 (альтернативный путь)
        while sum(1 for r in player.reserve if r == base_name + "★2") >= 3:
            removed = []
            for r in list(player.reserve):
                if r == base_name + "★2":
                    player.reserve.remove(r)
                    removed.append(r)
                    if len(removed) == 3:
                        break
            merged = base_name + "★3"
            player.reserve.append(merged)
            returned_name = merged  # this call created a ★3

        return returned_name

    def roll(self, count: int = 5) -> list[dict]:
        """Ролл магазина: случайные юниты из пула.

        Уровень магазина ограничивает потолок цены: на 1-м уровне
        выпадают только cost 1, на 2-м — cost 1-2, и так далее. Пока в
        пуле нет подходящих (дорогие раскуплены), роллим из всех доступных.
        """
        candidates = self._roll_candidates()
        if not candidates:
            candidates = [u for u in self.pool.remaining if self.pool.available(u) > 0]
        if not candidates:
            raise ShopError("пул пуст")

        shop_items = []
        for _ in range(count):
            unit_name = self.rng.choice(candidates)
            cost = self.unit_costs.get(unit_name, 1)
            shop_items.append({"name": unit_name, "cost": cost})
        return shop_items

    def get_available_units(self) -> list[str]:
        """Список всех юнитов, доступных в пуле."""
        return list(self.pool.remaining.keys())

    def buy_item(self, player, item_name: str) -> dict:
        """Купить предмет из магазина.
        
        Returns:
            dict с информацией о предмете.
        """
        if item_name not in self.item_data:
            raise ShopError(f"Предмет {item_name} не найден")
        
        item_info = self.item_data[item_name]
        cost = item_info["cost"]
        
        if player.gold < cost:
            raise ShopError(f"нужно {cost} золота, есть {player.gold}")
        
        player.gold -= cost
        
        # Предмет кладётся в инвентарь игрока (не в reserve)
        item_copy = dict(item_info)
        item_copy["id"] = f"{item_name}_{len(player.items)}"
        player.items.append(item_copy)
        
        return item_copy

    def apply_item_to_unit(self, player, item_idx: int, unit_idx: int) -> dict:
        """Применить предмет из инвентаря к юниту на доске.
        
        Returns:
            Обновлённый юнит с применённым бонусом.
        """
        if item_idx < 0 or item_idx >= len(player.items):
            raise ShopError(f"Индекс предмета {item_idx} вне диапазона")
        if unit_idx < 0 or unit_idx >= len(player.board):
            raise ShopError(f"Индекс юнита {unit_idx} вне диапазона")
        
        item = player.items[item_idx]
        unit = player.board[unit_idx]
        
        # Применяем бонусы предмета к юниту
        if "stats" in item:
            if "item_bonuses" not in unit:
                unit["item_bonuses"] = {}
            
            for stat_name, stat_value in item["stats"].items():
                if stat_name == "speed_bonus_pct":
                    # Процентная прибавка — применяется к базовой скорости
                    base_speed = unit.get("_base_attack_speed", 1.0)
                    unit["attack_speed"] = base_speed * (1 + stat_value / 100)
                else:
                    # Фиксированная прибавка
                    current_val = unit.get("item_bonuses", {}).get(stat_name, 0)
                    unit["item_bonuses"][stat_name] = current_val + stat_value
        
        # Удаляем предмет из инвентаря (одноразовый)
        player.items.pop(item_idx)
        
        return unit

    def remove_item_from_unit(self, player, unit_idx: int) -> dict:
        """Снять предмет с юнита и вернуть в инвентарь.
        
        Returns:
            Снятый предмет.
        """
        if unit_idx < 0 or unit_idx >= len(player.board):
            raise ShopError(f"Индекс юнита {unit_idx} вне диапазона")

        # Предметы хранятся в стат_словах юнита, а не как отдельный объект
        # Для простоты: снимаем все бонусы (восстанавливаем базовые)
        # В полной версии здесь было бы хранение original_stats
        return None

    def roll_items(self, count: int = 3) -> list[dict]:
        """Ролл предметов в магазине."""
        available_items = list(self.item_data.keys())
        if not available_items:
            raise ShopError("нет доступных предметов")
        
        shop_items = []
        for _ in range(count):
            item_name = self.rng.choice(available_items)
            item_info = self.item_data[item_name]
            shop_items.append({
                "name": item_info["name"],
                "item_key": item_name,
                "cost": item_info["cost"],
                "stats": item_info.get("stats", {}),
                "description": item_info.get("description", ""),
            })
        return shop_items

    def get_available_items(self) -> list[str]:
        """Список всех предметов, доступных в магазине."""
        return list(self.item_data.keys())
