"""Экономика игрока: золото, доход, проценты, здоровье матча."""

MAX_INTEREST = 3        # максимальный бонус от процентов (золота)
INTEREST_THRESHOLD = 10 # каждый порог × 10 золота = +1 к проценту

BASE_INCOME = 5         # базовый доход за любой раунд
WIN_BONUS = 1           # дополнительный бонус за победу над игроком
CREEP_WIN_GOLD = 2      # за победу над крипами (в дополнение к базовому)

# Бонусы за серию побед: ключ — длина серии, значение — бонус золота
WIN_STREAK_BONUS = {
    3: 1,   # 3 победы подряд
    4: 1,   # 4 победы подряд
    5: 2,   # 5 побед подряд
    6: 2,   # 6 побед подряд
    7: 3,   # 7 побед подряд
    8: 4,   # 8 побед подряд (макс.)
}

# Бонусы за серию поражений: ключ — длина серии, значение — бонус золота
LOSS_STREAK_BONUS = {
    3: 1,   # 3 поражения подряд
    4: 1,   # 4 поражения подряд
    5: 2,   # 5 поражений подряд
    6: 2,   # 6 поражений подряд
    7: 2,   # 7 поражений подряд
    8: 2,   # 8+ поражений подряд (макс.)
}

MAX_GOLD = 100          # максимум золота игрока

# ── Здоровье матча (как в Underlords/TFT) ─────────────────────────────────
START_HP = 75           # стартовое здоровье игрока
PVP_LOSS_BASE_DAMAGE = 7   # базовый урон за проигранный PvP-раунд
PVP_LOSS_DAMAGE_PER_UNIT = 2   # + за каждого выжившего врага


def calculate_interest(gold: int) -> int:
    """Рассчитать проценты от текущего золота.

    +1 золото за каждые 10 золота, максимум MAX_INTEREST.
    """
    return min(MAX_INTEREST, gold // INTEREST_THRESHOLD)


def base_income(pvp_win: bool = False, creep_win: bool = False) -> int:
    """Базовый доход раунда (без interest и стриков).

    Всегда BASE_INCOME (5), плюс WIN_BONUS (1) за победу над игроком,
    плюс CREEP_WIN_GOLD (2) за победу над крипами.
    """
    income = BASE_INCOME
    if creep_win:
        income += CREEP_WIN_GOLD
    elif pvp_win:
        income += WIN_BONUS
    return income


def win_streak_bonus(streak: int) -> int:
    """Бонус золота за серию побед.

    1-2 победы: 0, 3-4: 1, 5-6: 2, 7: 3, 8+: 4.
    Серия обнуляется на 8.
    """
    if streak < 3:
        return 0
    return WIN_STREAK_BONUS.get(min(streak, 8), 0)


def loss_streak_bonus(streak: int) -> int:
    """Бонус золота за серию поражений.

    1-2 поражения: 0, 3-4: 1, 5+: 2.
    """
    if streak < 3:
        return 0
    return min(2, LOSS_STREAK_BONUS.get(min(streak, 8), 2))


def round_hp_damage(is_creep: bool, player_won: bool,
                    surviving_enemy_units: int) -> int:
    """Сколько HP теряет игрок по итогам раунда.

    Крип-раунды здоровья не отнимают — это разминка.
    Проигранный PvP бьёт тем сильнее, чем больше врагов уцелело.
    """
    if is_creep or player_won:
        return 0
    return (PVP_LOSS_BASE_DAMAGE
            + PVP_LOSS_DAMAGE_PER_UNIT * max(0, surviving_enemy_units))


def pvp_base_damage(round_num: int) -> int:
    """Базовый урон за проигранный PvP-раунд, растёт с номером раунда.

    Единая формула для ядра (round.py) и UI. Значения соответствуют
    живому балансу UI (5/10/15/20); раньше round.py использовал 6/12/18/24.
    """
    if round_num <= 10:
        return 5
    if round_num <= 20:
        return 10
    if round_num <= 30:
        return 15
    return 20


def pvp_round_damage(round_num: int, winner_survivors: int) -> int:
    """Урон проигравшему в PvP: база + за каждого выжившего у ПОБЕДИТЕЛЯ.

    winner_survivors — сколько юнитов выжило у выигравшей стороны.
    Раньше в round.py/UI бралась выжившая сторона ПРОИГРАВШЕГО (всегда 0
    при аннигиляции), поэтому бонус за выживших не работал.
    """
    return pvp_base_damage(round_num) + PVP_LOSS_DAMAGE_PER_UNIT * max(0, winner_survivors)


def round_economy(gold: int, pvp_win: bool = False, creep_win: bool = False,
                  hp: int = None, is_creep: bool = False,
                  surviving_enemy_units: int = 0,
                  win_streak: int = 0, loss_streak: int = 0) -> dict:
    """Рассчитать экономику раунда.

    Args:
        gold: текущее золото игрока ДО раунда
        pvp_win: победа в PvP (против другого игрока/бота)
        creep_win: победа над крипами (нейтральный раунд)
        hp: текущее здоровье (если None — HP не считается, совместимость)
        is_creep: крип-раунд (не отнимает здоровье)
        surviving_enemy_units: сколько врагов выжило после боя
        win_streak: текущая серия побед (0 если нет)
        loss_streak: текущая серия поражений (0 если нет)

    Returns:
        {'gold_after', 'income', 'interest', 'total_earned',
         'hp_after', 'hp_lost', 'is_eliminated',
         'win_streak_bonus', 'loss_streak_bonus'}
    """
    income = base_income(pvp_win=pvp_win, creep_win=creep_win)
    interest = calculate_interest(gold)

    # Бонус за серию побед или поражений (не складываются)
    streak_bonus = 0
    streak_bonus_type = None
    if win_streak >= 3:
        streak_bonus = win_streak_bonus(win_streak)
        streak_bonus_type = "win"
    elif loss_streak >= 3:
        streak_bonus = loss_streak_bonus(loss_streak)
        streak_bonus_type = "loss"

    total_earned = income + interest + streak_bonus

    # Применяем максимум золота
    new_gold = min(gold + total_earned, MAX_GOLD)

    result = {
        "gold_after": new_gold,
        "income": income,
        "interest": interest,
        "total_earned": total_earned,
        "win_streak_bonus": streak_bonus if streak_bonus_type == "win" else 0,
        "loss_streak_bonus": streak_bonus if streak_bonus_type == "loss" else 0,
    }

    if hp is None:
        # старый интерфейс: вызывающий код про HP не знает
        return result

    hp_lost = round_hp_damage(is_creep, pvp_win, surviving_enemy_units)
    hp_after = max(0, hp - hp_lost)
    result.update({
        "hp_after": hp_after,
        "hp_lost": hp_lost,
        "is_eliminated": hp_after <= 0,
    })
    return result
