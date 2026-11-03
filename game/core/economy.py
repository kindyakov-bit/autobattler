"""Экономика игрока: золото, доход, проценты, здоровье матча."""

MAX_INTEREST = 5        # максимальный бонус от процентов
INTEREST_THRESHOLD = 10 # каждый порог × 10 золота = +1 к проценту

WIN_GOLD = 1            # утешительное золото за поражение в PvP
CREEP_WIN_GOLD = 2      # за победу над крипами

# ── Здоровье матча (как в Underlords/TFT) ─────────────────────────────────
START_HP = 100          # стартовое здоровье игрока
PVP_LOSS_BASE_DAMAGE = 5   # базовый урон за проигранный PvP-раунд
PVP_LOSS_DAMAGE_PER_UNIT = 2   # + за каждого выжившего врага


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


def round_economy(gold: int, pvp_win: bool = False, creep_win: bool = False,
                  hp: int = None, is_creep: bool = False,
                  surviving_enemy_units: int = 0) -> dict:
    """Рассчитать экономику раунда.

    Args:
        gold: текущее золото игрока ДО раунда
        pvp_win: победа в PvP (против другого игрока/бота)
        creep_win: победа над крипами (нейтральный раунд)
        hp: текущее здоровье (если None — HP не считается, совместимость)
        is_creep: крип-раунд (не отнимает здоровье)
        surviving_enemy_units: сколько врагов выжило после боя

    Returns:
        {'gold_after', 'income', 'interest', 'total_earned',
         'hp_after', 'hp_lost', 'is_eliminated'}
    """
    income = base_income(pvp_win=pvp_win, creep_win=creep_win)
    interest = calculate_interest(gold)
    total_earned = income + interest

    result = {
        "gold_after": gold + total_earned,
        "income": income,
        "interest": interest,
        "total_earned": total_earned,
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
