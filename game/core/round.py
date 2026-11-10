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

from game.core.economy import round_economy, START_HP, pvp_round_damage
from game.core.team import build_combat_team
from game.battle.engine import BattleSimulator
from game.core.shop import Shop, ShopError
from game.core.pool import Pool
from game.core.draft import DraftPhase
from game.core.player import Player
from game.core.unit_name import base_name, star_level


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
        # Матч рассчитан на 8 участников: 1 игрок + 7 ботов.
        # Баланс (START_HP, формулы урона) не меняется — меняется только
        # начальное число противников, чтобы UI мог показать полный список участников.
        for _ in range(7):
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

    # ── Участники матча (игрок + боты) ──────────────────────────────────────

    def _participant_names(self) -> list[str]:
        """Имена всех участников: игрок zuerst, затем боты по порядку."""
        names = ["Игрок"]
        names += [b["name"] for b in self.bots]
        return names

    def _living_participants(self) -> list[str]:
        """Имена живых участников (HP > 0), в порядке следования."""
        living = []
        if self.player_hp > 0:
            living.append("Игрок")
        for b in self.bots:
            if b["hp"] > 0:
                living.append(b["name"])
        return living

    def _hp_of(self, name: str) -> int:
        """HP участника по имени."""
        if name == "Игрок":
            return self.player_hp
        for b in self.bots:
            if b["name"] == name:
                return b["hp"]
        return 0

    def _set_hp(self, name: str, value: int) -> None:
        """Установить HP участника."""
        if name == "Игрок":
            self.player_hp = max(0, value)
            return
        for b in self.bots:
            if b["name"] == name:
                b["hp"] = max(0, value)
                return

    def _is_player(self, name: str) -> bool:
        return name == "Игрок"

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

    def run_round_all(self, units_by_name: dict[str, list[dict]], synergy_data: dict,
                      player: object = None,
                      race_synergy_data: dict | None = None,
                      race_data: dict | None = None) -> dict[str, RoundState]:
        """
        Один раунд: все живые участники делятся на пары и дерутся 1v1.

        Пары: (1-й со 2-м), (3-м с 4-м), … с ротацией каждый раунд вызовом
       _units_by_name в нужном порядке_. Если живых нечётное число — первый
        участник сражается с copies себя (копия его юнитов).

        Args:
            units_by_name: {имя_участника: [юниты в формате боя]}
            synergy_data: данные синергий из JSON
            player: объект Player (для серий побед/поражений)
            race_synergy_data, race_data: расовые данные для build_combat_team

        Returns:
            {имя_участника: RoundState} — результат для каждого участника пары.
        """
        self.round_number += 1
        is_creep = self.round_number <= 4

        living = self._living_participants()

        # Нечётное количество → копия первого участника
        copy_name = None
        if len(living) % 2 == 1:
            copy_name = living[0] + " (копия)"
            units_by_name[copy_name] = [dict(u) for u in units_by_name[living[0]]]
            living.append(copy_name)

        results: dict[str, RoundState] = {}

        for i in range(0, len(living), 2):
            name_a, name_b = living[i], living[i + 1]
            team_a = units_by_name.get(name_a, [])
            team_b = units_by_name.get(name_b, [])

            sim = BattleSimulator(seed=self.seed + self.round_number + i)

            # Активные способности, критики, класс — из JSON
            for team in (team_a, team_b):
                for u in team:
                    nb = base_name(u.get("name", ""))
                    if self.unit_data and nb in self.unit_data:
                        ud = self.unit_data[nb]
                        if ud.get("active"):
                            u["active"] = dict(ud["active"])
                        u.setdefault("crit_chance", ud.get("crit_chance", 0))
                        u.setdefault("unit_class", ud.get("class", ""))

            sim.add_team(name_a, team_a)
            sim.add_team(name_b, team_b)
            self.all_sims[f"{self.round_number}:{name_a}-{name_b}"] = sim
            br = sim.run()

            winner = br["winner"]  # name_a или name_b
            loser = name_b if winner == name_a else name_a

            for nm in (name_a, name_b):
                st = RoundState(self.round_number, is_creep)
                st.battle_result = br
                st.total_ticks = sim.get_total_ticks()
                st.player_hp = self._hp_of(nm)
                results[nm] = st

            if not is_creep:
                surv_winner = sum(1 for u in sim.teams[winner] if u.alive)
                dmg = pvp_round_damage(self.round_number, surv_winner)

                old_hp = self._hp_of(loser)
                new_hp = max(0, old_hp - dmg)
                self._set_hp(loser, new_hp)

                for nm in (name_a, name_b):
                    results[nm].pairings.append((name_a, name_b, winner, dmg))

                # Серии побед/поражений только для игрока
                if player is not None:
                    if self._is_player(name_a):
                        if winner == name_a:
                            player.record_win()
                        else:
                            player.record_loss()
                    if self._is_player(name_b):
                        if winner == name_b:
                            player.record_win()
                        else:
                            player.record_loss()

        # Сохраняем состояние раунда в историю (обратная совместимость)
        state = RoundState(self.round_number, is_creep)
        state.player_hp = self.player_hp
        state.bot_hps = {b["name"]: b["hp"] for b in self.bots if b["hp"] > 0}
        if results:
            last_st = list(results.values())[-1]
            state.battle_result = last_st.battle_result
            state.total_ticks = last_st.total_ticks
            state.pairings = []
            for st in results.values():
                state.pairings.extend(st.pairings)
        self.history.append(state)

        self._is_game_over()
        return results

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
                name_base = base_name(u.get("name", ""))
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

            if pvp_win:
                # Игрок выиграл — урон первому живому боту.
                # Бонус за выживших считается от ПОБЕДИТЕЛЯ (игрока), а не
                # от проигравшего бота (у того после аннигиляции выживших 0).
                damage = pvp_round_damage(self.round_number, surviving_players)
                for bot in self.bots:
                    if bot["hp"] > 0:
                        bot["hp"] = max(0, bot["hp"] - damage)
                        state.pairings.append(("player", bot["name"], "player", damage))
                        break
            else:
                # Игрок проиграл — урон игроку от выживших врагов (победителей).
                damage = pvp_round_damage(self.round_number, surviving_enemies)
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
    team = build_combat_team(
        units_data, all_units,
        synergy_data=synergy_data,
        race_synergy_data=race_synergy_data,
        race_data=race_data,
    )
    # Крипы усиливаются с номером раунда, чтобы оставаться угрозой на всей дистанции матча.
    # Каждый следующий раунд:+10 % к HP и урону волны (начиная со 2-го раунда).
    if round_num > 1 and team:
        mult = 1.0 + (round_num - 1) * 0.10
        for u in team:
            u["hp"] = int(u["hp"] * mult)
            u["damage"] = u["damage"] * mult
    return team


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
        synergy_data=synergy_data or {},
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
            except ShopError:
                pass  # не хватило золота, пул или резерв полон

    # Размещаем на доску (учёт слотов; состав врага ниже берётся из purchased)
    for i in range(min(6, len(purchased))):
        try:
            draft_phase.place_on_board(player, i)
        except ShopError:
            pass

    # Преобразуем в формат для боя через единую сборку build_combat_team
    enemy_units_data = [
        {"name": pu, "star": star_level(pu)}
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


def _build_default_player_units(all_units, synergy_data, race_synergy_data, race_data):
    """Фиксированный стартовый состав игрока (упрощённо, без инт. драфта)."""
    return build_combat_team(
        [
            {"name": "warrior_freshman", "star": 1},
            {"name": "mage_acolyte", "star": 1},
        ],
        all_units,
        synergy_data=synergy_data,
        race_synergy_data=race_synergy_data,
        race_data=race_data,
    )


def run_match(seed: int = 42, verbose: bool = False, enemy_bot: str = "balanced"):
    """Запустить полный матч до победы или поражения по HP.

    Новая стратегия боя: все живые участники делятся на пары (1-й со 2-м,
    3-й с 4-м, …) и дерутся 1v1 каждый раунд. При нечётном числе живых —
    первый участник сражается с копией себя. Соперники rotiruyutsya через
    порядок unités в ``units_by_name`` (изменяется вызывающим кодом/UI).

    Args:
        seed: RNG seed для детерминизма
        verbose: печатать каждый раунд
        enemy_bot: пресет бота-противника (EASY/MEDIUM/HARD)

    Returns:
        Игровой объект Game с результатами матча.
    """
    project_root = Path(__file__).parent.parent.parent.resolve()
    data = load_game_data(project_root / "data" / "units.json")

    all_units = data["units"]
    synergy_data = data["synergies"]
    race_synergy_data = data.get("race_synergies", {})
    race_data = data.get("races", {})

    game = Game(seed=seed, unit_data=all_units)
    gold = 5  # стартовое золото

    unit_costs = {name: info["cost"] for name, info in all_units.items()}
    pool = Pool(unit_costs)
    import time
    shop_seed = int(time.time() * 1000) % (2 ** 31)
    shop = Shop(pool, unit_costs=unit_costs, rng=random.Random(shop_seed))
    draft_phase = DraftPhase(shop, all_units)

    player = Player(gold=gold)
    player.update_max_board(shop.level)

    # Состав каждой команды между раундами (сохраняется, чтобы боты развивались)
    units_by_name: dict[str, list[dict]] = {"Игрок": []}
    for b in game.bots:
        units_by_name[b["name"]] = []

    round_num = 0
    while True:
        round_num += 1
        game.round_number = round_num
        is_creep = round_num <= 4

        player.update_max_board(shop.level)

        # ── Каждый живой участник готовит своих юнитов на этот раунд ──
        if is_creep:
            # Крип-раунд: игрок и боты сражаются с волной крипов.
            # Всем живым выдаём одного и того же набора крипов (считается,
            # что они сражались с волной по очереди / параллельно).
            creep_team = build_creep_units(
                round_num, all_units,
                synergy_data=synergy_data,
                race_synergy_data=race_synergy_data,
                race_data=race_data,
            )
            for nm in list(units_by_name.keys()):
                if game._hp_of(nm) > 0:
                    units_by_name[nm] = list(creep_team)
        else:
            # PvP-раунд: боты покупают новых юнитов
            from game.core.bots import create_bot
            for b in game.bots:
                if b["hp"] <= 0:
                    continue
                bot = create_bot(
                    preset=enemy_bot,
                    seed=seed + round_num + b.get("seed_base", 0),
                )
                bot_units = _bot_draft_with_shop(
                    bot=bot,
                    draft_phase=draft_phase,
                    unit_data=all_units,
                    gold=20,
                    player=Player(gold=20),
                    synergy_data=synergy_data,
                    race_synergy_data=race_synergy_data,
                    race_data=race_data,
                )
                units_by_name[b["name"]] = bot_units

            # Игрок — фиксированный состав (без интерактивного драфта в консоли)
            units_by_name["Игрок"] = list(
                _build_default_player_units(
                    all_units, synergy_data, race_synergy_data, race_data
                )
            )

        # ── Один раунд: все пары дерутся одновременно ──
        results = game.run_round_all(
            units_by_name,
            synergy_data,
            player=player,
            race_synergy_data=race_synergy_data,
            race_data=race_data,
        )

        # Золото игрока из экономики своей пары
        econ = None
        if "Игрок" in results:
            # Ищем RoundState игрока, в котором были pairings (т.е. был PvP-бой)
            st = results["Игрок"]
            if st.pairings and not is_creep:
                # Приближённо: берём золото из вызова round_economy внутри run_round_all.
                # run_round_all не возвращает econ напрямую — пересчитаем здесь.
                pass

        if verbose:
            print(f"\n--- Раунд {round_num} ({'крип' if is_creep else 'PvP'}) ---")
            for nm, st in results.items():
                winner = st.battle_result["winner"] if st.battle_result else "?"
                print(f"  {nm}: HP={st.player_hp}, результат={winner}")
                for (a, b, w, dmg) in st.pairings:
                    print(f"    Пара {a} vs {b}: победил {w}, урон {dmg}")

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