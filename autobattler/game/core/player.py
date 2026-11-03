"""Состояние игрока: золото, bench, board, управление юнитами, уровень и опыт."""


class Player:
    """Игрок: золото, резерв (bench), доска (board), инвентарь предметов, уровень и опыт."""

    # Сколько опыта нужно для перехода с уровня N на N+1.
    # Ключ — текущий уровень, значение — XP до следующего.
    XP_TABLE = {
        1: 2,   # 1 -> 2
        2: 6,   # 2 -> 3
        3: 10,  # 3 -> 4
        4: 20,  # 4 -> 5
        5: 36,  # 5 -> 6
        6: 60,  # 6 -> 7
        7: 90,  # 7 -> 8
        8: 130, # 8 -> 9
    }

    MAX_LEVEL = 9

    # Стоимость покупки 4 опыта за золото
    XP_COST_GOLD = 4
    XP_PER_PURCHASE = 4

    # Бесплатный опыт за раунд
    XP_PER_ROUND = 2

    def __init__(self, gold: int = 0):
        self.gold = gold
        self.reserve: list[str] = []       # bench — купленные юниты
        self.board: list[dict] = []         # на доске — {'name': str, 'star': int, ...}
        self.items: list[dict] = []         # инвентарь предметов
        self.max_bench = 20                 # макс. размер банка (соответствует BENCH_MAX в ui/game_ui.py)
        self.level = 1                      # уровень игрока (1..9)
        self.xp = 0                         # текущий опыт
        self.xp_to_next_level = self.XP_TABLE[1]  # опыта нужно до следующего уровня
        self.max_board = self.level + 1     # макс. юнитов на доске = level + 1

    def add_xp(self, amount: int) -> bool:
        """Добавить опыт. Возвращает True, если уровень повысился."""
        if self.level >= self.MAX_LEVEL:
            return False
        self.xp += amount
        leveled_up = False
        while self.xp >= self.xp_to_next_level and self.level < self.MAX_LEVEL:
            self.xp -= self.xp_to_next_level
            self.level += 1
            self.xp_to_next_level = self.XP_TABLE.get(self.level, 999999)
            self.max_board = self.level + 1
            leveled_up = True
        return leveled_up

    def buy_xp(self, cost: int = None, xp_amount: int = None) -> bool:
        """Купить опыт за золото. По умолчанию 4 золота за 4 XP.

        Возвращает True, если покупка успешна.
        """
        cost = cost if cost is not None else self.XP_COST_GOLD
        xp_amount = xp_amount if xp_amount is not None else self.XP_PER_PURCHASE
        if self.gold < cost:
            return False
        if self.level >= self.MAX_LEVEL:
            return False
        self.gold -= cost
        self.add_xp(xp_amount)
        return True

    def add_round_xp(self) -> bool:
        """Дать бесплатный опыт за начало раунда. Возвращает True, если уровень повысился."""
        return self.add_xp(self.XP_PER_ROUND)

    def update_max_board(self, shop_level: int) -> None:
        """Обновить максимальный размер доски.

        Уровень игрока определяет лимит: level + 1 слота.
        shop_level оставлен для обратной совместимости, но не влияет на max_board.
        """
        self._board_level = shop_level
        self.max_board = self.level + 1

    def buy(self, name: str) -> None:
        """Положить юнит в резерв (без списания золота — делает Shop)."""
        if len(self.reserve) >= self.max_bench:
            raise ValueError(f"bench full ({self.max_bench})")
        self.reserve.append(name)

    def sell(self, name: str, price: int = 0) -> list[str]:
        """Продать одну копию из резерва. Возвращает проданное имя."""
        if name in self.reserve:
            self.reserve.remove(name)
            return [name]
        raise ValueError(f"Unit {name} not in reserve")

    def place(self, name: str) -> dict:
        """Положить юнита из резерва на доску."""
        if name not in self.reserve:
            raise ValueError(f"{name} not in reserve")
        self.reserve.remove(name)
        if len(self.board) >= self.max_board:
            raise ValueError(f"board full ({self.max_board})")
        unit = {"name": name, "star": 1 if "★" not in name else int(name.split("★")[1][1:]), "_base_hp": 0}
        self.board.append(unit)
        return unit

    def remove_from_board(self, idx: int) -> dict:
        """Убрать юнита с доски обратно в резерв."""
        if idx < 0 or idx >= len(self.board):
            raise ValueError(f"Invalid board index {idx}")
        unit = self.board.pop(idx)
        self.reserve.append(unit["name"])
        return unit

    def get_synergy_count(self, class_name: str, all_units: dict | None = None) -> int:
        """Сколько юнитов класса class_name на доске.

        Если передан ``all_units`` (data/units.json['units']), класс берется
        из определения юнита (поле ``class``). Иначе — старый фолбэк по
        префиксу имени (работает только для warrior_/mage_/archer_).
        """
        base = class_name.lower()
        count = 0
        for u in self.board:
            name_base = u["name"].split("★")[0]
            cls = None
            if all_units is not None and name_base in all_units:
                cls = all_units[name_base].get("class", "")
            if cls:
                if cls == class_name:
                    count += 1
            else:
                # Фолбэк: имя начинается с имени класса
                if name_base.lower().startswith(base):
                    count += 1
        return count

    def get_race_count(self, race_name: str, all_units: dict | None = None) -> int:
        """Сколько юнитов расы ``race_name`` на доске.

        Если передан ``all_units``, раса берётся из определения юнита
        (поле ``race``). Иначе возвращает 0.
        """
        base = race_name.lower()
        count = 0
        for u in self.board:
            name_base = u["name"].split("★")[0]
            race = None
            if all_units is not None and name_base in all_units:
                race = all_units[name_base].get("race", "")
            if race and race.lower() == base:
                count += 1
        return count

    def get_team_stats(self, all_units: dict | None = None) -> list[dict]:
        """Получить список юнитов на доске для боя (dict-формат).

        Класс берётся из ``all_units`` (поле ``class``), а не из префикса
        имени, чтобы не ошибаться на юнитах вроде ``demon_succubus``
        (класс mage) или ``priest`` (класс healer).
        """
        units = []
        for u in self.board:
            unit_dict = dict(u)
            name_base = u["name"].split("★")[0]
            cls = ""
            if all_units is not None and name_base in all_units:
                cls = all_units[name_base].get("class", "")
            if not cls:
                # Фолбэк: префикс имени
                cls = name_base.split("_")[0]
            unit_dict["class"] = cls
            units.append(unit_dict)
        return units
