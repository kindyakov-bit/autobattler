"""Экономика игрока: золото, базовый доход, перерасход, проценты (interest)."""

MAX_INTEREST = 5        # максимальный бонус от процентов
INTEREST_THRESHOLD = 10 # каждый порог × 10 золота = +1 к проценту


WIN_GOLD = 1            # утешительное золото за поражение в PvP
CREEP_WIN_GOLD = 2      # за победу над крипами


def calculate_interest(gold: int) -> int:
    """Рассчитать проценты от текущего золота.

    +1 процент за каждые 10 золота, максимум MAX_INTEREST.
    """
    return min(MAX_INTEREST, gold // INTEREST_THRESHOLD)


def base_income(pvp_win: bool = False, creep_win: bool = False) -> int:
    """Базовый доход раунда (без interest)."""
    if creep_win:
        return CREEP_WIN_GOLD
    return WIN_GOLD if pvp_win else WIN_GOLD


def round_economy(gold: int, pvp_win: bool = False, creep_win: bool = False) -> dict:
    """Рассчитать экономику раунда.

    Args:
        gold: текущее золото игрока ДО раунда
        pvp_win: победа в PvP (против другого игрока/бота)
        creep_win: победа над крипами (нейтральный раунд)

    Returns:
        {'gold_after': int, 'income': int, 'interest': int, 'total_earned': int}
    """
    income = base_income(pvp_win=pvp_win, creep_win=creep_win)
    interest = calculate_interest(gold)
    total_earned = income + interest

    return {
        "gold_after": gold + total_earned,
        "income": income,
        "interest": interest,
        "total_earned": total_earned,
    }
