"""Единая сборка боевой команды: статы + звёзды + предметы + расовые бонусы + синергии + пассивки.

Все места, которые формируют список юнитов для BattleSimulator (игрок, боты, крипы),
должны использовать эту функцию, чтобы статы считались одинаково.
"""

from game.core.synergies import (
    calculate_synergy_bonuses, apply_synergy_bonuses,
    calculate_race_bonuses, apply_race_bonuses,
    calculate_passive_bonuses, apply_passive_bonuses,
)


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
        name_base = name.split("★")[0]
        if name_base not in all_units:
            continue
        ud = all_units[name_base]

        star = u.get("star", 1)
        hp_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0
        dmg_mult = 1.5 if star == 2 else 2.0 if star == 3 else 1.0

        hp = int(ud["hp"] * hp_mult)
        damage = float(ud["damage"]) * dmg_mult
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
            "mana_per_kill": mana_per_kill,
            "row": u.get("row"),
            "col": u.get("col"),
        }

        if ud.get("active"):
            unit_data["active"] = dict(ud["active"])
        if "item_bonuses" in u:
            unit_data["item_bonuses"] = u["item_bonuses"]

        team.append(unit_data)

    # Классовые синергии (warrior/mage/archer 2/4)
    if synergy_data:
        syn_bonuses = calculate_synergy_bonuses(team, synergy_data)
        team = apply_synergy_bonuses(team, syn_bonuses)

    # Расовые синергии (human/orc/demon/elf/undead 2/4)
    if race_synergy_data:
        race_bonuses_map = calculate_race_bonuses(team, race_synergy_data)
        team = apply_race_bonuses(team, race_bonuses_map)

    # Пассивные способности (synergy_buff по классу или расе)
    if all_units:
        passive = calculate_passive_bonuses(team, all_units)
        team = apply_passive_bonuses(team, passive)

    return team
