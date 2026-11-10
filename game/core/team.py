"""Единая сборка боевой команды: статы + звёзды + предметы + расовые бонусы + синергии + пассивки.

Все места, которые формируют список юнитов для BattleSimulator (игрок, боты, крипы),
должны использовать эту функцию, чтобы статы считались одинаково.
"""

from game.core.synergies import (
    calculate_synergy_bonuses, apply_synergy_bonuses,
    calculate_race_bonuses, apply_race_bonuses,
    calculate_passive_bonuses, apply_passive_bonuses,
    calculate_unity_bonuses,
)
from game.core.unit_name import base_name, star_multiplier

# Множитель силовых полей способности по тиру юнита (cost).
TIER_ABILITY_MULT = {1: 1.0, 2: 1.25, 3: 1.5, 4: 1.8, 5: 2.2}
# Поля effect, которые масштабируются звёздами и тиром.
# Длительность, радиус, проценты и тактовые задержки НЕ масштабируются.
ABILITY_SCALABLE_KEYS = {
    "damage", "heal", "shield", "bonus_damage",
    "damage_per_tick", "heal_per_tick", "absorb", "arrival_damage",
}


def _scale_ability_effect(effect: dict | None, factor: float) -> dict:
    """Вернуть копию effect с силовыми полями, масштабированными на factor."""
    if not effect:
        return {}
    scaled = dict(effect)
    for key in ABILITY_SCALABLE_KEYS:
        if key in scaled:
            scaled[key] = round(scaled[key] * factor)
    return scaled


def build_combat_team(
    units_data: list[dict],
    all_units: dict,
    synergy_data: dict | None = None,
    race_synergy_data: dict | None = None,
    race_data: dict | None = None,
) -> list[dict]:
    """Собрать боевую команду из покупаемых юнитов в формат BattleSimulator.

    Применяет (в порядке):
      1. Базовые статы из units.json + мультипликатор звёзд (★2 = ×1.5, ★3 = ×2.0)
      2. Бонусы предметов (item_bonuses)
      3. Базовые расовые бонусы (races[race]['bonuses'])
      4. Классовые синергии (warrior/mage/archer 2/4)
      5. Расовые синергии (human/orc/demon/elf/undead 2/4)
      6. Пассивные способности (synergy_buff по классу или расе)

    Args:
        units_data: список юнитов с полями name (с ★N), star, row, col, item_bonuses
        all_units: data/units.json['units'] — полные определения юнитов
        synergy_data: синергии классов (warrior/mage/archer)
        race_synergy_data: расовые синергии (2/4 юнита одной расы)
        race_data: базовые определения рас (races[race]['bonuses'])

    Returns:
        Список юнитов в формате для BattleSimulator.add_team.
    """
    team = []
    for u in units_data:
        name = u.get("name", "")
        name_base = base_name(name)
        if name_base not in all_units:
            continue
        ud = all_units[name_base]

        star = u.get("star", 1)
        mult = star_multiplier(star)

        hp = int(ud["hp"] * mult)
        damage = float(ud["damage"]) * mult
        attack_speed = float(ud["attack_speed"])

        # Предметы
        bonuses = u.get("item_bonuses", {})
        hp = int(hp + bonuses.get("hp_bonus", 0))
        damage = damage + bonuses.get("damage_bonus", 0)
        speed_pct = bonuses.get("speed_bonus_pct", 0)
        if speed_pct:
            attack_speed = attack_speed * (1 + speed_pct / 100)

        # Базовые расовые бонусы (races[race]['bonuses'])
        race = ud.get("race", "human")
        race_def = (race_data or {}).get(race, {})
        race_bonuses = race_def.get("bonuses", {})
        hp = int(hp * (1 + race_bonuses.get("hp_bonus_pct", 0) / 100))
        damage = damage * (1 + race_bonuses.get("damage_bonus_pct", 0) / 100)
        attack_speed = attack_speed * (1 + race_bonuses.get("attack_speed_pct", 0) / 100)
        crit_chance = ud.get("crit_chance", 0) + race_bonuses.get("crit_chance_bonus", 0)
        crit_multiplier = ud.get("crit_multiplier", 1.75) + race_bonuses.get(
            "crit_damage_bonus_pct", 0
        ) / 100.0
        hp_regen_pct = race_bonuses.get("hp_regen_pct", 0)
        damage_reduction_pct = race_bonuses.get("damage_reduction_pct", 0)
        mana_per_kill = ud.get("mana_per_kill", 0)  # ускорение к/д за килл (магия)

        unit_data = {
            "name": name,
            "star": star,
            "hp": hp,
            "damage": damage,
            "attack_speed": attack_speed,
            "range_": int(ud.get("range", ud.get("range_", 1))),
            "class": ud.get("class", ""),
            "race": race,
            "crit_chance": crit_chance,
            "crit_multiplier": crit_multiplier,
            "hp_regen_pct": hp_regen_pct,
            "damage_reduction_pct": damage_reduction_pct,
            "mana_per_kill": mana_per_kill,
            "row": u.get("row"),
            "col": u.get("col"),
        }

        if ud.get("active"):
            cost = ud.get("cost", 1)
            factor = star_multiplier(star) * TIER_ABILITY_MULT.get(cost, 1.0)
            unit_data["active"] = dict(ud["active"])
            unit_data["active"]["effect"] = _scale_ability_effect(
                unit_data["active"].get("effect", {}), factor)
        # item_bonuses сюда НЕ пробрасываем: они уже применены к hp/damage/speed
        # выше. Иначе BattleSimulator.add_team применил бы их второй раз.

        team.append(unit_data)

    # Классовые синергии (warrior/mage/archer 2/4)
    if synergy_data:
        syn_bonuses = calculate_synergy_bonuses(team, synergy_data)
        team = apply_synergy_bonuses(team, syn_bonuses)

    # Расовые синергии (human/orc/demon/elf/undead 2/4)
    if race_synergy_data:
        race_bonuses_map = calculate_race_bonuses(team, race_synergy_data)
        # Единство людей: бонус за уникальные классы масштабирует расовый бонус
        unity = calculate_unity_bonuses(team, race_synergy_data)
        if unity:
            for race_name, ub in unity.items():
                if race_name in race_bonuses_map:
                    # Копия, чтобы не мутировать исходные данные JSON
                    race_bonuses_map[race_name] = dict(race_bonuses_map[race_name])
                    race_bonuses_map[race_name].update(ub)
                else:
                    race_bonuses_map[race_name] = ub
        team = apply_race_bonuses(team, race_bonuses_map)

    # Пассивные способности (synergy_buff по классу или расе)
    if all_units:
        passive = calculate_passive_bonuses(team, all_units)
        team = apply_passive_bonuses(team, passive)

    return team
