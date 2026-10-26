"""Состояние игрока: золото, bench, board, управление юнитами."""


class Player:
    """Игрок: золото, резерв (bench), доска (board), инвентарь предметов."""

    def __init__(self, gold: int = 0):
        self.gold = gold
        self.reserve: list[str] = []       # bench — купленные юниты
        self.board: list[dict] = []         # на доске — {'name': str, 'star': int, ...}
        self.items: list[dict] = []         # инвентарь предметов
        self.max_bench = 30                 # макс. размер банка
        self.max_board = 6                  # макс. юнитов на доске

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

    def get_synergy_count(self, class_name: str) -> int:
        """Сколько юнитов класса class_name на доске."""
        # name format: "class_something" или "class_something★2"
        base = class_name.lower()
        count = 0
        for u in self.board:
            if u["name"].lower().startswith(base):
                count += 1
        return count

    def get_team_stats(self) -> list[dict]:
        """Получить список юнитов на доске для боя (dict-формат)."""
        units = []
        for u in self.board:
            unit_dict = dict(u)
            # Extract class from name
            name_base = u["name"].split("★")[0]
            unit_dict["class"] = name_base.split("_")[0]  # warrior, mage, archer
            units.append(unit_dict)
        return units
