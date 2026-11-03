"""Игровой цикл: раунды, фазы, управление состоянием игры.

Структура матча:
  - Раунды 1-4: крип-раунды (игрок vs нейтральные юниты)
  - Раунды 5+: PvP (игрок vs боты)

Каждый раунд проходит фазы:
  1. DRAFT — покупка юнитов из магазина
  2. BATTLE — бой между командами
  3. REWARD — начисление золота за результат

Игра продолжается до поражения HP игрока или всех ботов.
"""

import json
import random
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path при прямом запуске
_SCRIPT_DIR = Path(__file__).parent.parent.parent.resolve()
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from game.core.economy import round_economy, START_HP
from game.core.team import build_combat_team
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
        self.player_hp = 0
        self.bot_hps = {}  # bot_name -> hp
        self.pairings = []  # list of (name1, name2, winner_name, damage_to_loser)


class Game:
    """Основной игровой цикл: раунды, экономика, бой."""

    def __init__(self, seed: int = 42, unit_data: dict = None):
        self.seed = seed
        self.unit_data = unit_data  # data/units.json['units'] для пассивных способностей
        self.round_number = 0
        self.winner = None
        self.history: list[RoundState] = []
        self.all_sims: dict[int, object] = {}  # round_num -> BattleSimulator (all rounds)
        self.player_hp = START_HP
        self.bots: list[dict] = []  # persistent bots with hp, level, preset
        # Добавляем первого бота
        self._add_bot(seed)

    def _add_bot(self, seed_base: int = 0) -> None:
        """Добавить нового бота в игру."""
        bot_level = self._bot_level_for_round(self.round_number + 1)
        self.bots.append({
            "hp": START_HP,
            "level": bot_level,
            "preset": "balanced",
            "seed_base": seed_base + len(self.bots) * 1000,
            "name": f"Бот {len(self.bots) + 1}",
        })

    @staticmethod
    def _bot_level_for_round(round_num: int) -> int:
        """Уровень бота по номеру раунда (для PvP, раунды 5+)."""
        if round_num <= 6:
            return 3
        if round_num <= 8:
            return 4
        if round_num <= 11:
            return 5
        if round_num <= 14:
            return 6
        if round_num <= 18:
            return 7
        if round_num <= 22:
            return 8
        if round_num <= 27:
            return 9
        return 10

    @staticmethod
    def _base_damage_for_round(round_num: int) -> int:
        """Базовый урон за проигрыш в PvP-раунде, растёт с номером раунда."""
        if round_num <= 10:
            return 6
        if round_num <= 20:
            return 12
        if round_num <= 30:
            return 18
        return 24

    def _is_game_over(self) -> bool:
        """Проверить, завершена ли игра по HP."""
        if self.player_hp <= 0:
            self.winner = "enemy"
            return True
        living_bots = [b for b in self.bots if b["hp"] > 0]
        if not living_bots:
            self.winner = "player"
            return True
        return False

    def _get_match_result(self) -> dict:
        """Вернуть результат матча по HP."""
        if self.player_hp <= 0:
            living_bots = sum(1 for b in self.bots if b["hp"] > 0)
            return {"winner": "enemy", "place": living_bots + 1, "reason": "player_hp_zero"}
        if all(b["hp"] <= 0 for b in self.bots):
            return {"winner": "player", "place": 1, "reason": "all_bots_dead"}
        return {"winner": None, "place": None, "reason": "ongoing"}

    def run_round(self, player_gold: int, player_units: list[dict],
                  enemy_units: list[dict], synergy_data: dict,
                  shop: object = None, player: object = None) -> RoundState:
        """Запустить один раунд.

        Args:
            player_gold: золото игрока ДО раунда
            player_units: юниты игрока (с полями hp, damage, attack_speed, range_, class)
            enemy_units: юниты противника
            synergy_data: данные синергий из JSON
            shop: объект Shop для покупки юнитов в фазе драфта
            player: объект Player (для начисления опыта за раунд)

        Returns:
            RoundState с результатами раунда.
        """
        self.round_number += 1
        is_creep = self.round_number <= 4

        state = RoundState(self.round_number, is_creep)
        state.player_hp = self.player_hp
        state.bot_hps = {b["name"]: b["hp"] for b in self.bots if b["hp"] > 0}

        # Начисляем бесплатный опыт за раунд (+1 XP)
        if player is not None:
            player.add_round_xp()

        # Фаза 1: синергии и пассивки уже применены в build_combat_team() перед
        # вызовом run_round — здесь не применяем повторно, иначе будет дубль.
        state.synergy_bonuses = {}

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
        state.battle_result = sim.run()
        state.total_ticks = sim.get_total_ticks()

        pvp_win = not is_creep and state.battle_result["winner"] == "player"
        creep_win = is_creep and state.battle_result["winner"] == "player"

        # Обновляем серии побед/поражений (только для PvP-раундов)
        if player is not None and not is_creep:
            if pvp_win:
                player.record_win()
            else:
                player.record_loss()

        # Для PvP-раундов: применяем урон по HP участникам
        if not is_creep:
            surviving_enemies = sum(
                1 for u in sim.teams.get("enemy", []) if u.alive)
            surviving_players = sum(
                1 for u in sim.teams.get("player", []) if u.alive)
            base_dmg = self._base_damage_for_round(self.round_number)

            if pvp_win:
                # Игрок выиграл — урон первому живому боту
                for bot in self.bots:
                    if bot["hp"] > 0:
                        damage = base_dmg + 2 * surviving_enemies
                        bot["hp"] = max(0, bot["hp"] - damage)
                        state.pairings.append(("player", bot["name"], "player", damage))
                        break
            else:
                # Игрок проиграл — урон игроку
                damage = base_dmg + 2 * surviving_players
                self.player_hp = max(0, self.player_hp - damage)
                state.pairings.append(("player", "bot", "bot", damage))

        # Фаза 3: экономика
        econ = round_economy(
            gold=player_gold,
            pvp_win=pvp_win,
            creep_win=creep_win,
            is_creep=is_creep,
            win_streak=player.win_streak if player is not None else 0,
            loss_streak=player.loss_streak if player is not None else 0,
        )
        state.gold_earned = econ["income"]
        state.interest_earned = econ["interest"]
        state.total_gold_after = econ["gold_after"]

        self.history.append(state)

        # Проверяем конец матча по HP
        self._is_game_over()

        return state

    def _determine_match_winner(self) -> dict:
        """Определить результат матча по HP."""
        return self._get_match_result()

    def _get_match_result(self) -> dict:
        """Вернуть результат матча по HP."""
        if self.player_hp <= 0:
            living_bots = sum(1 for b in self.bots if b["hp"] > 0)
            return {"winner": "enemy", "place": living_bots + 1, "reason": "player_hp_zero"}
        if all(b["hp"] <= 0 for b in self.bots):
            return {"winner": "player", "place": 1, "reason": "all_bots_dead"}
        return {"winner": None, "place": None, "reason": "ongoing"}

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


# Волны крипов по номеру раунда. Раньше крипы были одинаковы во всех
# крип-раундах — три раунда подряд one and the same бой.
# Сложность растёт и числом, и качеством юнитов.
CREEP_WAVES: dict[int, list[str]] = {
    1: ["warrior_freshman", "archer_scout"],
    2: ["warrior_freshman", "warrior_freshman", "archer_scout"],
    3: ["warrior_veteran", "warrior_freshman", "archer_scout", "archer_scout"],
    6: ["warrior_veteran", "warrior_freshman", "archer_scout",
        "archer_scout", "mage_acolyte"],
}
# Для раундов вне таблицы (9, 12, ...) — последняя волна + ещё юнит
CREEP_FALLBACK_GROWTH = 1


def creep_wave_for(round_num: int) -> list[str]:
    """Состав волны крипов для раунда round_num."""
    if round_num in CREEP_WAVES:
        return list(CREEP_WAVES[round_num])
    last_round = max(CREEP_WAVES)
    wave = list(CREEP_WAVES[last_round])
    extra = round_num // 3 - last_round // 3
    for _ in range(max(0, extra) * CREEP_FALLBACK_GROWTH):
        wave.append("warrior_veteran")
    return wave


def build_creep_units(round_num: int, all_units: dict,
                      player_units: list[dict] | None = None,
                      synergy_data: dict | None = None,
                      race_synergy_data: dict | None = None,
                      race_data: dict | None = None) -> list[dict]:
    """Собрать врагов крип-раунда в формате для боя.

    Качество волны растёт с номером раунда (CREEP_WAVES), а КОЛИЧЕСТВО
    подстраивается под размер доски игрока: крипы — разминка, а не стена.
    player_units=None → прежнее поведение.

    Использует единую сборку build_combat_team для статов, расовых бонусов,
    синергий и пассивок — как у игрока и ботов.
    """
    wave = creep_wave_for(round_num)
    if player_units is not None:
        target = max(1, min(len(player_units), 6))
        if len(wave) > target:
            wave = wave[:target]
        elif len(wave) < target:
            # добираем циклично юнитами той же волны — качество
            # остаётся уровнем раунда, растёт только количество
            base = list(wave)
            i = 0
            while len(wave) < target:
                wave.append(base[i % len(base)])
                i += 1
    units_data = []
    for key in wave:
        ud = all_units.get(key)
        if not ud:
            continue
        units_data.append({"name": key, "star": 1})
    return build_combat_team(
        units_data, all_units,
        synergy_data=synergy_data,
        race_synergy_data=race_synergy_data,
        race_data=race_data,
    )


def _bot_draft_with_shop(bot, draft_phase: DraftPhase, unit_data: dict, gold: int, player: Player,
                         synergy_data: dict | None = None,
                         race_synergy_data: dict | None = None,
                         race_data: dict | None = None) -> list[dict]:
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

    # Преобразуем в формат для боя через единую сборку build_combat_team
    enemy_units_data = [
        {"name": pu, "star": 1 if "★" not in pu else int(pu.split("★")[1][1:])}
        for pu in purchased[:6]
    ]
    enemy_unit_list = build_combat_team(
        enemy_units_data, unit_data,
        synergy_data=synergy_data,
        race_synergy_data=race_synergy_data,
        race_data=race_data,
    )

    if not enemy_unit_list:
        enemy_unit_list = [
            {"name": "warrior_freshman", "hp": 500, "damage": 40,
             "attack_speed": 1.2, "range_": 1, "class": "warrior",
             "crit_chance": 10},
        ]

    return enemy_unit_list


def run_match(seed: int = 42, verbose: bool = False, enemy_bot: str = "balanced"):
    """Запустить полный матч до победы или поражения по HP.

    Args:
        seed: RNG seed для детерминизма
        verbose: печатать каждый раунд
        enemy_bot: пресет бота-противника (EASY/MEDIUM/HARD)

    Returns:
        Игровой объект Game с результатами матча.
    """
    project_root = Path(__file__).parent.parent.parent.resolve()
    data = load_game_data(project_root / "data" / "units.json")

    # Загружаем все юниты из JSON для выбора ботом
    all_units = data["units"]

    game = Game(seed=seed, unit_data=all_units)
    gold = 5  # стартовое золото (как в Dota Underlords / TFT)

    # Создаём пул и магазин на весь матч
    unit_costs = {name: info["cost"] for name, info in all_units.items()}
    pool = Pool(unit_costs)
    # Магазин получает свой независимый случайный rng, не связанный с battle seed,
    # иначе при одном и том же seed магазин будет продавать одни и те же юниты.
    import time
    shop_seed = int(time.time() * 1000) % (2 ** 31)
    shop = Shop(pool, unit_costs=unit_costs, rng=random.Random(shop_seed))
    draft_phase = DraftPhase(shop, all_units)

    # Игрок для отслеживания доски и уровня магазина
    player = Player(gold=gold)
    player.update_max_board(shop.level)

    round_num = 0
    while True:
        round_num += 1
        game.round_number = round_num
        is_creep = round_num <= 4

        # Уровень магазина привязан к уровню игрока — отдельного авто-рoste нет.
        player.update_max_board(shop.level)

        if is_creep:
            # Крип-раунд: волна через build_combat_team (статы, расы, синергии)
            enemy_units = build_creep_units(
                round_num, all_units, synergy_data=data["synergies"],
                race_synergy_data=data["race_synergies"], race_data=data["races"],
            )
            player_units = build_combat_team(
                [
                    {"name": "warrior_freshman", "star": 1},
                    {"name": "mage_acolyte", "star": 1},
                ],
                all_units,
                synergy_data=data["synergies"],
                race_synergy_data=data["race_synergies"],
                race_data=data["races"],
            )
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
                synergy_data=data["synergies"],
                race_synergy_data=data["race_synergies"],
                race_data=data["races"],
            )

            # Игрок тоже может выбрать состав (упрощённо — фиксированный)
            player_units = build_combat_team(
                [
                    {"name": "warrior_freshman", "star": 1},
                    {"name": "mage_acolyte", "star": 1},
                ],
                all_units,
                synergy_data=data["synergies"],
                race_synergy_data=data["race_synergies"],
                race_data=data["races"],
            )

        state = game.run_round(
            player_gold=gold,
            player_units=list(player_units),
            enemy_units=list(enemy_units),
            synergy_data=data["synergies"],
            shop=shop,
            player=player,
        )
        gold = state.total_gold_after

        if verbose:
            print(f"\n--- Раунд {state.round_number} ({'крип' if state.is_creep else 'PvP'}) ---")
            print(f"  Победитель: {state.battle_result['winner']}")
            print(f"  Золото: +{state.gold_earned} (база) +{state.interest_earned}%")
            print(f"  HP игрока: {state.player_hp}")
            for bot_name, bot_hp in state.bot_hps.items():
                print(f"  HP {bot_name}: {bot_hp}")

        if game.winner is not None:
            break

    return game


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Автобатлер — полный матч")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    game = run_match(seed=args.seed, verbose=args.verbose)
    print(game.get_summary())