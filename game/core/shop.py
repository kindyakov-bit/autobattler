"""Магазин: покупка юнитов/предметов, слияние ★1→★2→★3, продажа."""

import random

from game.core.unit_name import base_name, star_level

# Сколько копий пула реально потребляет юнит каждой звезды (с учётом refund при слиянии).
# ★1 = 1 копия; ★2 = 3 покупки − 2 refund = 1; ★3 = 3×★2 = 3 копии.
POOL_COST_BY_STAR = {1: 1, 2: 1, 3: 3}


def accumulate_item_bonuses(unit: dict, stats: dict) -> None:
    """Накопить бонусы предмета в unit['item_bonuses'].

    Единая точка для Shop.apply_item_to_unit и восстановления юнитов в UI.
    speed_bonus_pct тоже хранится здесь — иначе предмет на скорость
    не применялся бы в build_combat_team.
    """
    bonuses = unit.setdefault("item_bonuses", {})
    for stat_name, stat_value in stats.items():
        bonuses[stat_name] = bonuses.get(stat_name, 0) + stat_value


#: Стоимость переброски витрины магазина (реролл).
ROLL_COST = 2


class ShopError(Exception):
    """Ошибка магазина."""


class Shop:
    """Управление магазином и слиянием юнитов + предметов.

    Уровень магазина (1..6): растёт автоматически каждый раунд и может
    быть докуплен за золото (upgrade_cost). Чем выше уровень, тем дороже
    юниты в ролле — «сначала в магазине только низкоуровневые».
    """

    #: Максимальная стоимость юнита, который может выпасть на уровне N.
    MAX_COST_BY_LEVEL = {1: 1, 2: 2, 3: 3, 4: 3, 5: 3, 6: 4, 7: 4, 8: 5, 9: 5, 10: 5}

    #: Цена апгрейда магазина до следующего уровня (за золото).
    #: Отключено — уровень магазина привязан к уровню игрока.
    UPGRADE_COSTS = {}

    #: Количество слотов в витрине магазина — всегда 5 на любом уровне.
    SHOP_SLOTS = {1: 5, 2: 5, 3: 5, 4: 5, 5: 5, 6: 5, 7: 5, 8: 5, 9: 5, 10: 5}

    #: Шансы выпадения юнита стоимости N (в %) для каждого уровня игрока/магазина.
    #: Ключ — уровень, значение — dict {стоимость: шанс}. Сумма = 100.
    TIER_ODDS = {
        1: {1: 80, 2: 20, 3: 0,   4: 0,   5: 0},
        2: {1: 70, 2: 30, 3: 0,   4: 0,   5: 0},
        3: {1: 55, 2: 35, 3: 10,  4: 0,   5: 0},
        4: {1: 45, 2: 40, 3: 15,  4: 0,   5: 0},
        5: {1: 35, 2: 40, 3: 25,  4: 0,   5: 0},
        6: {1: 25, 2: 35, 3: 35,  4: 5,   5: 0},
        7: {1: 20, 2: 30, 3: 40,  4: 10,  5: 0},
        8: {1: 18, 2: 24, 3: 35,  4: 20,  5: 3},
        9: {1: 15, 2: 21, 3: 30,  4: 28,  5: 6},
        10: {1: 12, 2: 18, 3: 28,  4: 32,  5: 10},
    }

    def __init__(self, pool, unit_costs: dict = None, item_data: dict = None, rng: random.Random = None):
        self.pool = pool
        self.unit_costs = unit_costs or {}  # name -> cost
        self.item_data = item_data or {}  # item_name -> item_info
        self.rng = rng or random.Random()
        self._level = 1
        self.shop_slots = self.SHOP_SLOTS[1]

    @property
    def level(self) -> int:
        return self._level

    @level.setter
    def level(self, value: int) -> None:
        self._level = max(1, min(value, 10))
        self.shop_slots = self.SHOP_SLOTS.get(self._level, 5)

    @property
    def upgrade_cost(self):
        """Цена следующего апгрейда. None — апгрейд отключен, уровень привязан к игроку."""
        return None

    def upgrade(self, player=None) -> bool:
        """Поднять уровень магазина за золото игрока.

        Отключено — уровень магазина теперь привязан к уровню игрока.
        Всегда возвращает False.
        """
        return False

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
        base = base_name(name)
        if len(player.reserve) >= player.max_bench:
            # Резерв полон — покупка разрешена только если покупаемая копия
            # завершает тройку той же звезды: 2 точные копии (резерв+доска)
            # + 1 покупаемая = 3 -> слияние освободит место.
            if self._count_copies(player, name) < 2:
                raise ShopError(f"резерв полон ({player.max_bench}), разместите или продайте юнита")
        player.gold -= cost
        self.pool.take(name)
        player.reserve.append(name)
        return self._maybe_merge(player, name)

    def sell(self, player, idx: int, from_board: bool = False) -> str:
        """Продать одного юнита. Возвращает базовое имя.

        from_board=False — продажа из резерва (скамейки).
        from_board=True  — продажа юнита с доски: его предметы возвращаются
                           в инвентарь игрока, чтобы не пропадали после продажи.
        """
        if from_board:
            if idx < 0 or idx >= len(player.board):
                raise ShopError(f"Индекс {idx} вне диапазона (board={len(player.board)})")
            unit = player.board.pop(idx)
            base = base_name(unit["name"])
            # Возвращаем предметы с проданного юнита в инвентарь игрока
            for item in unit.get("items", []):
                player.items.append(dict(item))
            star = unit.get("star", star_level(unit["name"]))
            self.pool.refund(base, copies=POOL_COST_BY_STAR.get(star, 1))
            return base
        if idx < 0 or idx >= len(player.reserve):
            raise ShopError(f"Индекс {idx} вне диапазона (reserve={len(player.reserve)})")
        name = player.reserve.pop(idx)
        base = base_name(name)
        self.pool.refund(base, copies=POOL_COST_BY_STAR.get(star_level(name), 1))
        return base

    def place(self, player, idx: int) -> dict:
        """Положить юнита из резерва на доску по индексу."""
        if idx < 0 or idx >= len(player.reserve):
            raise ShopError(f"Индекс {idx} вне диапазона (reserve={len(player.reserve)})")
        if len(player.board) >= player.max_board:
            raise ShopError(f"Доска полна ({len(player.board)}/{player.max_board})")
        name = player.reserve.pop(idx)
        unit = {"name": name, "star": star_level(name)}
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
        if len(player.reserve) >= player.max_bench:
            raise ShopError(f"резерв полон ({player.max_bench})")
        unit = player.board.pop(idx)
        # Возвращаем предметы с юнита в инвентарь игрока
        for item in unit.get("items", []):
            player.items.append(dict(item))
        player.reserve.append(unit["name"])
        return unit["name"]

    def _count_copies(self, player, target_name: str) -> int:
        """Считает копии target_name в резерве и на доске вместе."""
        count = sum(1 for r in player.reserve if r == target_name)
        count += sum(1 for u in player.board if u["name"] == target_name)
        return count

    def _has_star3(self, player: object, unit_key: str) -> bool:
        """Проверяет, есть ли у игрока уже ★3 этого юнита (макс. звёзды).

        Если игрок уже собрал ★3, дополнительные копии не нужны.
        """
        if player is None:
            return False
        star3_name = f"{unit_key}★3"
        if star3_name in player.reserve:
            return True
        return any(u["name"] == star3_name for u in player.board)

    def _remove_copies(self, player, target_name: str, count: int) -> tuple[int, dict | None]:
        """Удаляет count копий target_name из резерва и доски.

        Приоритет: сначала резерв (скамейка), потом доска. Освобождает
        слоты на доске. Возвращает (removed, board_slot) где board_slot —
        {"row": ..., "col": ...} первой снятой с доски копии или None.
        """
        removed = 0
        board_slot = None
        # Сначала из резерва
        for r in list(player.reserve):
            if r == target_name and removed < count:
                player.reserve.remove(r)
                removed += 1
        # Потом с доски (освобождаем слоты)
        if removed < count:
            for u in list(player.board):
                if u["name"] == target_name and removed < count:
                    # Возвращаем предметы с юнита в инвентарь перед удалением,
                    # иначе вещи исчезнут при слиянии
                    for item in u.get("items", []):
                        player.items.append(dict(item))
                    if board_slot is None:
                        board_slot = {"row": u.get("row"), "col": u.get("col")}
                    player.board.remove(u)
                    removed += 1
        return removed, board_slot

    def _maybe_merge(self, player, name: str) -> str:
        """Автоматически сливать 3 одинаковых в ★2, затем 3★2 в ★3.

        Считает копии по ВСЕМ places: резерву (скамейке) и доске.
        Если юниты на доске — они убираются с доски (освобождая слоты),
        а результат кладётся в резерв.

        Returns merged name (after all merges). Only returns a merged name
        if this specific call triggered a merge.
        """
        base_name = name.split("★")[0]
        returned_name = name  # default: nothing was merged

        # 3 × ★1 → ★2
        while self._count_copies(player, base_name) >= 3:
            removed, board_slot = self._remove_copies(player, base_name, 3)
            merged = base_name + "★2"
            if len(player.reserve) < player.max_bench:
                player.reserve.append(merged)
            else:
                unit = {"name": merged, "star": 2}
                if board_slot:
                    unit.update(board_slot)
                player.board.append(unit)
            self.pool.refund(base_name, copies=2)
            returned_name = merged  # this call created a ★2

        # 3 × ★2 → ★3 (только этот путь; альтернативный 2★2→★3 удалён)
        while self._count_copies(player, base_name + "★2") >= 3:
            removed, board_slot = self._remove_copies(player, base_name + "★2", 3)
            merged = base_name + "★3"
            if len(player.reserve) < player.max_bench:
                player.reserve.append(merged)
            else:
                unit = {"name": merged, "star": 3}
                if board_slot:
                    unit.update(board_slot)
                player.board.append(unit)
            # Пул НЕ возвращаем: каждый ★2 уже вернул 2 копии при своём создании,
            # поэтому ★3 netto стоит 3 базовых копий. Раньше сюда возвращались
            # "base★2" копии — несуществующий ключ, засорявший пул и магазин.
            returned_name = merged  # this call created a ★3

        return returned_name

    def roll(self, count: int = None, player: object = None) -> list[dict]:
        """Ролл магазина: случайные юниты из пула с учётом шансов tier.

        Количество карточек определяется shop_slots (зависит от уровня),
        если count не указан явно.

        Если передан player, юниты с ★3 (макс. звёзды) исключаются из
        розыгрыша, так как дополнительные копии не нужны.
        """
        if count is None:
            count = self.shop_slots
        odds = self.TIER_ODDS.get(self.level, self.TIER_ODDS[1])
        total_chance = sum(odds.values())

        shop_items = []
        for _ in range(count):
            # 1. Определяем стоимость карточки по шансам для текущего уровня
            roll_val = self.rng.randint(1, total_chance)
            current = 0
            target_cost = 1
            for cost, chance in sorted(odds.items()):
                current += chance
                if roll_val <= current:
                    target_cost = cost
                    break

            # 2. Выбираем случайного юнита этой стоимости из пула
            candidates = [
                u for u, c in self.unit_costs.items()
                if c == target_cost and self.pool.available(u) > 0
                and not self._has_star3(player, u)
            ]
            # Если нет юнитов этой стоимости, берём любой доступный юнит из пула
            # (только реальные ключи unit_costs, без фантомных записей).
            if not candidates:
                candidates = [
                    u for u in self.unit_costs
                    if self.pool.available(u) > 0 and not self._has_star3(player, u)
                ]
            if not candidates:
                break  # пул пуст

            unit_name = self.rng.choice(candidates)
            # Цена карточки — реальная цена юнита, а не выпавший target_cost.
            shop_items.append({"name": unit_name, "cost": self.unit_costs.get(unit_name, target_cost)})
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
        
        # Применяем бонусы предмета к юниту (все статы, включая speed_bonus_pct,
        # копятся в item_bonuses — их применит build_combat_team при сборке боя).
        if "stats" in item:
            accumulate_item_bonuses(unit, item["stats"])
            unit.setdefault("items", [])
            # Сохраняем копию предмета в юните, чтобы можно было вернуть при продаже
            unit["items"].append(dict(item))

        # Удаляем предмет из инвентаря (он теперь на юните)
        player.items.pop(item_idx)

        return unit

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
