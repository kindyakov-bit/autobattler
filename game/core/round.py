"""Игровой цикл: раунды, фазы, управление состоянием игры.

Структура матча:
  - Раунды 1-4: крип-раунды (игрок vs нейтральные юниты)
  - Раунды 5+: PvP (игрок vs бот/другой игрок)

Каждый раунд проходит фазы:
  1. DRAFT — покупка юнитов из магазина
  2. BATTLE — бой между командами
  3. REWARD — начисление золота за результат
"""

import json
import random
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path при прямом запуске
_SCRIPT_DIR = Path(__file__).parent.parent.parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from game.core.economy import round_economy
from game.core.synergies import calculate_synergy_bonuses, apply_synergy_bonuses
from game.battle.engine import BattleSimulator
from game.core.shop import Shop
from game.core.pool import Pool
from game.core.draft import DraftPhase
from game.core.player import Player


class RoundState:
    """Состояние одного раунда."""

    def __init__(self, round_number: int, is_creep: bool):
        self.round_number = round_number
        self.is_creep = is_creep
        self.gold_earned = 0
        self.interest_earned = 0
        self.total_gold_after = 0
        self.battle_result = None
        self.synergy_bonuses = {}


class Game:
    """Основной игровой цикл: раунды, экономика, бой."""

    def __init__(self, seed: int = 42, unit_data: dict = None):
        self.seed = seed
        self.unit_data = unit_data  # data/units.json['units'] для пассивных способностей
        self.round_number = 0
        self.winner = None
        self.history: list[RoundState] = []
        self.all_sims: dict[int, object] = {}  # round_num -> BattleSimulator (all rounds)

    def run_round(self, player_gold: int, player_units: list[dict],
                  enemy_units: list[dict], synergy_data: dict,
                  shop: object = None) -> RoundState:
        """Запустить один раунд.

        Args:
            player_gold: золото игрока ДО раунда
            player_units: юниты игрока (с полями hp, damage, attack_speed, range_, class)
            enemy_units: юниты противника
            synergy_data: данные синергий из JSON
            shop: объект Shop для покупки юнитов в фазе драфта

        Returns:
            RoundState с результатами раунда.
        """
        self.round_number += 1
        is_creep = self.round_number <= 4

        state = RoundState(self.round_number, is_creep)

        # Фаза 1: расчёт синергий игрока (бонусы применяются к статам юнитов)
        state.synergy_bonuses = calculate_synergy_bonuses(player_units, synergy_data)
        player_units = apply_synergy_bonuses(player_units, state.synergy_bonuses)

        # Фаза 1.5: применяем пассивные способности (если есть unit_data)
        if self.unit_data:
            from game.core.synergies import calculate_passive_bonuses, apply_passive_bonuses
            passive_bonuses = calculate_passive_bonuses(player_units, self.unit_data)
            player_units = apply_passive_bonuses(player_units, passive_bonuses)

        # Фаза 2: бой
        sim = BattleSimulator(seed=self.seed + self.round_number)

        # Передаём активные способности и криты из JSON в юниты для симулятора
        if self.unit_data:
            for u in player_units:
                name_base = u.get("name", "").split("★")[0]
                if name_base in self.unit_data:
                    ud = self.unit_data[name_base]
                    if ud.get("active"):
                        u["active"] = dict(ud["active"])
                    u.setdefault("crit_chance", ud.get("crit_chance", 0))
                    u.setdefault("unit_class", ud.get("class", ""))

        sim.add_team("player", player_units)
        sim.add_team("enemy", enemy_units)
        self.all_sims[self.round_number] = sim
        state.battle_result = sim.run(max_ticks=600)
        # Сохраняем количество тиков для UI
        state.total_ticks = sim.get_total_ticks()

        pvp_win = not is_creep and state.battle_result["winner"] == "player"
        creep_win = is_creep and state.battle_result["winner"] == "player"

        # Фаза 3: экономика
        econ = round_economy(gold=player_gold, pvp_win=pvp_win, creep_win=creep_win)
        state.gold_earned = econ["income"]
        state.interest_earned = econ["interest"]
        state.total_gold_after = econ["gold_after"]

        self.history.append(state)

        # Проверяем конец матча (после 8 раундов — победитель по очкам)
        if self.round_number >= 8:
            self.winner = self._determine_match_winner()

        return state

    def _determine_match_winner(self) -> str:
        """Определить победителя матча по результатам всех раундов."""
        player_wins = sum(1 for s in self.history if s.battle_result["winner"] == "player")
        enemy_wins = sum(1 for s in self.history if s.battle_result["winner"] != "player")

        return "player" if player_wins > enemy_wins else "enemy"

    def get_summary(self) -> str:
        """Получить текстовую сводку матча."""
        lines = ["=" * 50, "ИТОГИ МАТЧА", "=" * 50]

        for state in self.history:
            winner = state.battle_result["winner"] if state.battle_result else "?"
            reason = state.battle_result.get("reason", "") if state.battle_result else ""

            lines.append(
                f"\nРаунд {state.round_number} "
                f"({'крип' if state.is_creep else 'PvP'}): "
                f"{winner} ({reason})"
            )
            lines.append(f"  Золото: +{state.gold_earned} (база) +{state.interest_earned}% (проценты)")

        lines.append("\n" + "=" * 50)
        if self.winner:
            lines.append(f"ПОБЕДИТЕЛЬ МАТЧА: {self.winner.upper()}")
        else:
            lines.append("МАТЧ НЕ ЗАВЕРШЁН")

        return "\n".join(lines)


def load_game_data(json_path: str | Path) -> dict:
    """Загрузить данные из JSON."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _bot_draft_with_shop(bot, draft_phase: DraftPhase, unit_data: dict, gold: int, player: Player) -> list[dict]:
    """Бот покупает юнитов из магазина и размещает на доску.
    
    Returns:
        Список юнитов в формате для боя (с star-уровнем).
    """
    
    # Бот решает, что купить
    draft_decision = bot.decide_draft(
        available_units=unit_data,
        gold=gold,
        current_team=[],
        synergy_data={},
    )
    
    # Покупаем через Shop (с авто-мержем)
    purchased = []
    for unit_info in draft_decision:
        name = unit_info["name"]
        cost = unit_info.get("cost", 1)
        if gold >= cost:
            try:
                merged_name = draft_phase.buy_unit(player, name)
                purchased.append(merged_name)
                gold -= cost
            except Exception:
                pass  # не хватило золота или пула
    
    # Размещаем на доску
    board_units = []
    for i, unit_name in enumerate(purchased[:6]):
        try:
            draft_phase.place_on_board(player, i)
            board_units.append({"name": unit_name, "star": 1 if "★" not in unit_name else int(unit_name.split("★")[1][1:])})
        except Exception:
            pass
    
    # Преобразуем в формат для боя (с учётом star-уровня)
    enemy_unit_list = []
    for unit_info in draft_decision[:6]:
        name = unit_info["name"]
        if name in unit_data:
            ud = dict(unit_data[name])
            # Star-бонусы: ★2 = +50% HP/dmg, ★3 = +100% HP/dmg
            star = 1
            for pu in purchased:
                if pu.startswith(name) and "★" in pu:
                    star = int(pu.split("★")[1][1:])
            hp_mult = 1.5 if star == 2 else 2.0
            dmg_mult = 1.5 if star == 2 else 2.0
            enemy_unit_list.append({
                "name": name,
                "hp": int(ud["hp"] * hp_mult),
                "damage": int(ud["damage"] * dmg_mult),
                "attack_speed": ud["attack_speed"],
                "range_": ud["range"],
                "class": ud["class"],
                "crit_chance": ud.get("crit_chance", 0),
                "active": dict(ud["active"]) if ud.get("active") else None,
            })

    if not enemy_unit_list:
        enemy_unit_list = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40,
             "attack_speed": 1.2, "range_": 1, "class": "warrior",
             "crit_chance": 10},
        ]
    
    return enemy_unit_list


def run_match(seed: int = 42, verbose: bool = False, enemy_bot: str = "balanced"):
    """Запустить полный матч (8 раундов).

    Args:
        seed: RNG seed для детерминизма
        verbose: печатать каждый раунд
        enemy_bot: пресет бота-противника (EASY/MEDIUM/HARD)
    """
    project_root = Path(__file__).parent.parent.parent.resolve()
    data = load_game_data(project_root / "data" / "units.json")

    # Загружаем все юниты из JSON для выбора ботом
    all_units = data["units"]

    game = Game(seed=seed, unit_data=all_units)
    gold = 10  # стартовое золото (как в Dota Underlords / TFT)
    
    # Создаём пул и магазин на весь матч
    unit_costs = {name: info["cost"] for name, info in all_units.items()}
    pool = Pool(unit_costs)
    shop = Shop(pool, unit_costs=unit_costs, rng=random.Random(seed))
    draft_phase = DraftPhase(shop, all_units)

    for round_num in range(1, 9):
        is_creep = round_num <= 4

        if is_creep:
            # Крип-раунд: фиксированный состав крипов
            enemy_units = [
                {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                {"name": "archer_scout", "hp": 250, "damage": 45, "attack_speed": 1.5, "range_": 3, "class": "archer"},
            ]
            player_units = [
                {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                {"name": "mage_acolyte", "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4, "class": "mage"},
            ]
        else:
            # PvP-раунд: бот покупает юнитов из магазина через DraftPhase
            from game.core.bots import create_bot
            bot = create_bot(preset=enemy_bot, seed=seed + round_num)
            
            # Бот покупает и размещает юнитов
            enemy_units = _bot_draft_with_shop(
                bot=bot,
                draft_phase=draft_phase,
                unit_data=all_units,
                gold=gold,
                player=Player(gold=gold),
            )

            # Игрок тоже может выбрать состав (упрощённо — фиксированный)
            player_units = [
                {"name": "warrior_freshman", "hp": 500, "damage": 40, "attack_speed": 1.2, "range_": 1, "class": "warrior"},
                {"name": "mage_acolyte", "hp": 300, "damage": 65, "attack_speed": 1.0, "range_": 4, "class": "mage"},
            ]

        state = game.run_round(
            player_gold=gold,
            player_units=list(player_units),
            enemy_units=list(enemy_units),
            synergy_data=data["synergies"],
        )
        gold = state.total_gold_after

        if verbose:
            print(f"\n--- Раунд {state.round_number} ({'крип' if state.is_creep else 'PvP'}) ---")
            print(f"  Победитель: {state.battle_result['winner']}")
            print(f"  Золото: +{state.gold_earned} (база) +{state.interest_earned}%")

    return game


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Автобатлер — полный матч")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    game = run_match(seed=args.seed, verbose=args.verbose)
    print(game.get_summary())
