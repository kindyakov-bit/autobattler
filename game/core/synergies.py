"""Расчёт бонусов синергий и пассивных способностей от состава команды.

Синергия активируется когда в команде >= N юнитов данного класса.
Каждый порог (threshold) даёт свой бонус.

Расовые бонусы работают аналогично синергиям классов, но активируются по
расе юнита. Каждая раса даёт базовые бонусы всем своим юнитам, плюс
рассовые синергии при порогах 2/4 юнитов одной расы.

Пассивные способности работают поверх синергий:
  - synergy_buff: бонус за каждого союзного юнита своего класса

Активные способности (aura, buff_allies, buff_next_attack, ...) живут в
game/battle/engine.py — здесь только пассивки.

Пример: Воин 2/4
  - 2+ воина: +15% HP ко всем воинам
  - 4+ воинов: +30% HP ко всем воинам (перекрывает предыдущий)

Бонусы синергий и пассивок применяются через apply_synergy_bonuses() /
apply_passive_bonuses() и всегда считаются от ``_base_*`` значений, поэтому
их можно вызывать в любом порядке без повторного компаундирования.
"""


from game.core.unit_name import star_multiplier


def calculate_synergy_bonuses(team_units: list[dict], synergy_data: dict) -> dict:
    """Рассчитать все активные бонусы синергий для команды.

    Args:
        team_units: список юнитов в команде (каждый с полем 'class')
        synergy_data: структура синергий из data/units.json ['synergies']

    Returns:
        Словарь {synergy_name: {bonus_key: bonus_value, ...}} для всех активных синергий.
    """
    # Подсчёт юнитов по классам
    class_counts = {}
    for unit in team_units:
        cls = unit.get("class")
        if cls:
            class_counts[cls] = class_counts.get(cls, 0) + 1

    result = {}
    for syn_name, syn_info in synergy_data.items():
        count = class_counts.get(syn_name, 0)
        thresholds = syn_info.get("thresholds", [])
        bonuses = syn_info.get("bonuses", {})

        # Находим максимальный активированный порог
        active_bonus = None
        for threshold in sorted(thresholds):
            if count >= threshold:
                bonus_key = str(threshold)
                if bonus_key in bonuses:
                    active_bonus = bonuses[bonus_key]

        if active_bonus is not None:
            result[syn_name] = active_bonus

    return result


def calculate_race_bonuses(team_units: list[dict], race_synergy_data: dict) -> dict:
    """Рассчитать все активные бонусы расовых синергий для команды.

    Аналогично calculate_synergy_bonuses(), но подсчёт ведётся по полю 'race'.

    Args:
        team_units: список юнитов в команде (каждый с полем 'race')
        race_synergy_data: структура расовых синергий из data/units.json ['race_synergies']

    Returns:
        Словарь {race_name: {bonus_key: bonus_value, ...}} для всех активных расовых синергий.
    """
    # Подсчёт юнитов по расам
    race_counts = {}
    for unit in team_units:
        race = unit.get("race")
        if race:
            race_counts[race] = race_counts.get(race, 0) + 1

    result = {}
    for race_name, race_info in race_synergy_data.items():
        count = race_counts.get(race_name, 0)
        thresholds = race_info.get("thresholds", [])
        bonuses = race_info.get("bonuses", {})

        active_bonus = None
        for threshold in sorted(thresholds):
            if count >= threshold:
                bonus_key = str(threshold)
                if bonus_key in bonuses:
                    active_bonus = bonuses[bonus_key]

        if active_bonus is not None:
            result[race_name] = active_bonus

    return result


def calculate_unity_bonuses(team_units: list[dict], race_synergy_data: dict) -> dict:
    """Рассчитать бонус «Единство» для людей: за каждый уникальный класс в команде.

    Аналогично calculate_race_bonuses(), но бонус масштабируется числом уникальных
    классов в команде (не только числом людей). Возвращает бонус только для расы
    «human», если у людей активирован хотя бы один порог синергии.

    Args:
        team_units: список юнитов в команде (каждый с полями 'race', 'class')
        race_synergy_data: структура расовых синергий из data/units.json ['race_synergies']

    Returns:
        Словарь {"human": {"unity_damage_pct": N, "unity_hp_pct": N}} или {}.
    """
    human_info = race_synergy_data.get("human")
    if not human_info:
        return {}

    # Подсчёт людей и уникальных классов во всей команде
    human_count = 0
    unique_classes = set()
    for unit in team_units:
        if unit.get("race") == "human":
            human_count += 1
        cls = unit.get("class")
        if cls:
            unique_classes.add(cls)

    if human_count == 0:
        return {}

    thresholds = human_info.get("thresholds", [])
    bonuses = human_info.get("bonuses", {})

    # Находим最大 активный порог для людей
    active_bonus = None
    for threshold in sorted(thresholds):
        if human_count >= threshold:
            bonus_key = str(threshold)
            if bonus_key in bonuses:
                active_bonus = bonuses[bonus_key]

    if active_bonus is None:
        return {}

    class_count = len(unique_classes)
    if class_count == 0:
        return {}

    base_damage = active_bonus.get("unity_damage_pct", 0)
    base_hp = active_bonus.get("unity_hp_pct", 0)

    if base_damage == 0 and base_hp == 0:
        return {}

    result = {
        "human": {
            "unity_damage_pct": base_damage * class_count,
            "unity_hp_pct": base_hp * class_count,
        }
    }
    udmg = result["human"]["unity_damage_pct"]
    uhp = result["human"]["unity_hp_pct"]
    return result


def calculate_passive_bonuses(team_units: list[dict], unit_data: dict) -> dict:
    """Рассчитать пассивные бонусы от способностей юнитов.

    Поддерживает типы пассивных способностей:
      - synergy_buff: бонус за каждого союзного юнита своего класса
      - aura: пассивная аура (возвращает данные для применения)

    Args:
        team_units: список юнитов в команде (каждый с полем 'class')
        unit_data: словарь определений юнитов из data/units.json ['units']

    Returns:
        Словарь {unit_name: {passive_type: bonus_value}} для юнитов с активными пассивками.
    """
    result = {}

    for unit in team_units:
        name_base = unit.get("name", "").split("★")[0]
        cls = unit.get("class")

        if not cls or name_base not in unit_data:
            continue

        unit_def = unit_data[name_base]
        passive = unit_def.get("passive")

        if not passive or passive.get("type") != "synergy_buff":
            continue

        # synergy_buff: бонус за каждого союзного юнита своего класса или расы
        count_by = passive.get("count_by", "class")
        ally_count = 0
        for other in team_units:
            if other is unit:
                continue
            if count_by == "race":
                if other.get("race") == unit.get("race"):
                    ally_count += 1
            else:
                if other.get("class") == cls:
                    ally_count += 1

        effect_type = passive["effect"]
        bonus_key = None
        bonus_value = 0

        if "hp_bonus_pct_per_ally" in effect_type:
            bonus_key = "hp_bonus_pct"
            bonus_value = effect_type["hp_bonus_pct_per_ally"] * ally_count
        elif "damage_bonus_pct_per_ally" in effect_type:
            bonus_key = "damage_bonus_pct"
            bonus_value = effect_type["damage_bonus_pct_per_ally"] * ally_count
        elif "speed_bonus_pct_per_ally" in effect_type:
            bonus_key = "speed_bonus_pct"
            bonus_value = effect_type["speed_bonus_pct_per_ally"] * ally_count
        elif "damage_reduction_pct_per_ally" in effect_type:
            bonus_key = "damage_reduction_pct"
            bonus_value = effect_type["damage_reduction_pct_per_ally"] * ally_count

        if bonus_value:
            # Пассивка скейлится от звёзды юнита (★1 = ×1.0, ★2 = ×1.5, ★3 = ×2.0).
            bonus_value = round(bonus_value * star_multiplier(unit.get("star", 1)))

        if bonus_value > 0 and bonus_key:
            result[name_base] = {
                "passive_name": passive["name"],
                "bonus_key": bonus_key,
                "bonus_value": bonus_value,
                "ally_count": ally_count,
            }

    return result


def apply_synergy_bonuses(team_units: list[dict], synergy_bonuses: dict) -> list[dict]:
    """Применить бонусы синергий к юнитам команды (оригинал не меняется).

    Поддерживает все бонусы, которые описал calculate_synergy_bonuses():
    hp_bonus_pct, damage_bonus_pct, attack_speed_pct. Бонус всегда считается
    от ``_base_*`` (исходного значения), поэтому синергии и пассивки можно
    применять в любом порядке — они не будут складываться повторно.

    Args:
        team_units: исходные данные юнитов (у каждого есть 'class')
        synergy_bonuses: результат calculate_synergy_bonuses()

    Returns:
        Список юнитов с применёнными бонусами.
    """
    modified = []
    for unit in team_units:
        u = dict(unit)
        bonuses = synergy_bonuses.get(u.get("class"), {})

        # Запоминаем базу, чтобы повторное применение не компаундировалось
        u.setdefault("_base_hp", u.get("hp", 100))
        u.setdefault("_base_damage", u.get("damage", 50))
        u.setdefault("_base_attack_speed", u.get("attack_speed", 1.0))
        u.setdefault("_base_crit_chance", u.get("crit_chance", 0))

        if "hp_bonus_pct" in bonuses:
            u["hp"] = int(u["_base_hp"] * (1 + bonuses["hp_bonus_pct"] / 100))
        if "damage_bonus_pct" in bonuses:
            u["damage"] = u["_base_damage"] * (1 + bonuses["damage_bonus_pct"] / 100)
        if "attack_speed_pct" in bonuses:
            u["attack_speed"] = u["_base_attack_speed"] * (
                1 + bonuses["attack_speed_pct"] / 100)
        if "crit_chance_bonus" in bonuses:
            u["crit_chance"] = u["_base_crit_chance"] + bonuses["crit_chance_bonus"]

        modified.append(u)

    return modified


def apply_race_bonuses(team_units: list[dict], race_bonuses: dict) -> list[dict]:
    """Применить расовые бонусы к юнитам команды (оригинал не меняется).

    Поддерживает бонусы из calculate_race_bonuses():
    hp_bonus_pct, damage_bonus_pct, attack_speed_pct, crit_chance_bonus,
    crit_damage_bonus_pct, damage_reduction_pct, evasion_pct, lifesteal_pct,
    berserker, revive. Бонус всегда считается от ``_base_*`` значений.

    Args:
        team_units: исходные данные юнитов (у каждого есть 'race')
        race_bonuses: результат calculate_race_bonuses()

    Returns:
        Список юнитов с применёнными расовыми бонусами.
    """
    modified = []
    for unit in team_units:
        u = dict(unit)
        bonuses = race_bonuses.get(u.get("race"), {})

        # Запоминаем базу, чтобы повторное применение не компаундировалось
        u.setdefault("_base_hp", u.get("hp", 100))
        u.setdefault("_base_damage", u.get("damage", 50))
        u.setdefault("_base_attack_speed", u.get("attack_speed", 1.0))
        u.setdefault("_base_crit_chance", u.get("crit_chance", 0))
        u.setdefault("_base_damage_reduction_pct", u.get("damage_reduction_pct", 0))
        u.setdefault("_base_crit_multiplier", u.get("crit_multiplier", 1.75))

        # Процентные бонусы HP и урона складываются от базы (не компаундируются):
        # базовый расовый бонус + unity (Единство людей за уникальные классы).
        hp_pct_total = 0
        if "hp_bonus_pct" in bonuses:
            hp_pct_total += bonuses["hp_bonus_pct"]
        if "unity_hp_pct" in bonuses:
            hp_pct_total += bonuses["unity_hp_pct"]
        if hp_pct_total:
            u["hp"] = int(u["_base_hp"] * (1 + hp_pct_total / 100))

        damage_pct_total = 0
        if "damage_bonus_pct" in bonuses:
            damage_pct_total += bonuses["damage_bonus_pct"]
        if "unity_damage_pct" in bonuses:
            damage_pct_total += bonuses["unity_damage_pct"]
        if damage_pct_total:
            u["damage"] = u["_base_damage"] * (1 + damage_pct_total / 100)
        if "attack_speed_pct" in bonuses:
            u["attack_speed"] = u["_base_attack_speed"] * (
                1 + bonuses["attack_speed_pct"] / 100)
        if "crit_chance_bonus" in bonuses:
            u["crit_chance"] = u["_base_crit_chance"] + bonuses["crit_chance_bonus"]
        if "damage_reduction_pct" in bonuses:
            u["damage_reduction_pct"] = (
                u["_base_damage_reduction_pct"] + bonuses["damage_reduction_pct"])
        if "hp_regen_pct" in bonuses:
            # Пороговый реген нежити накапливается на базовом поле из team.py,
            # иначе бонус за 2/4 Units не доедет до движка.
            u["hp_regen_pct"] = u.get("hp_regen_pct", 0) + bonuses["hp_regen_pct"]
        if "crit_damage_bonus_pct" in bonuses:
            u["crit_multiplier"] = (
                u["_base_crit_multiplier"] + bonuses["crit_damage_bonus_pct"] / 100.0)
        if "evasion_pct" in bonuses:
            u["evasion_pct"] = bonuses["evasion_pct"]
        if "lifesteal_pct" in bonuses:
            u["lifesteal_pct"] = bonuses["lifesteal_pct"]
        if "berserker" in bonuses:
            u["berserker"] = bonuses["berserker"]
        if "revive" in bonuses:
            u["revive"] = bonuses["revive"]

        modified.append(u)

    return modified


def apply_synergy_hp_bonuses(team_units: list[dict], synergy_bonuses: dict) -> list[dict]:
    """Обратная совместимость: только HP-бонусы. См. apply_synergy_bonuses()."""
    return apply_synergy_bonuses(team_units, synergy_bonuses)


def apply_passive_bonuses(team_units: list[dict], passive_bonuses: dict) -> list[dict]:
    """Применить пассивные бонусы к юнитам команды.

    Args:
        team_units: исходные данные юнитов
        passive_bonuses: результат calculate_passive_bonuses()

    Returns:
        Список юнитов с применёнными пассивными бонусами (добавляет поля).
    """
    modified = []
    for unit in team_units:
        u = dict(unit)
        name_base = u.get("name", "").split("★")[0]

        # Запоминаем базу, чтобы бонус не компаундировался при повторном
        # применении (и чтобы синергии + пассивки складывались предсказуемо)
        u.setdefault("_base_hp", u.get("hp", 100))
        u.setdefault("_base_damage", u.get("damage", 50))
        u.setdefault("_base_attack_speed", u.get("attack_speed", 1.0))

        if name_base in passive_bonuses:
            bonus_info = passive_bonuses[name_base]
            # Добавляем пассивный бонус к соответствующему полю
            if "hp_bonus_pct" in bonus_info["bonus_key"]:
                u["hp"] = int(u["_base_hp"] * (1 + bonus_info["bonus_value"] / 100))
            elif "damage_bonus_pct" in bonus_info["bonus_key"]:
                u["damage"] = u["_base_damage"] * (1 + bonus_info["bonus_value"] / 100)
            elif "speed_bonus_pct" in bonus_info["bonus_key"]:
                u["attack_speed"] = u["_base_attack_speed"] * (
                    1 + bonus_info["bonus_value"] / 100)
            elif "damage_reduction_pct" in bonus_info["bonus_key"]:
                u["damage_reduction_pct"] = u.get("damage_reduction_pct", 0) + bonus_info["bonus_value"]

        # Сохраняем информацию о пассивке для UI
        if name_base in passive_bonuses:
            u["_passive_bonus"] = passive_bonuses[name_base]

        modified.append(u)

    return modified


def get_active_synergies(team_units: list[dict], synergy_data: dict) -> list[str]:
    """Получить список активных названий синергий для команды."""
    bonuses = calculate_synergy_bonuses(team_units, synergy_data)
    return list(bonuses.keys())


def get_active_race_synergies(team_units: list[dict], race_synergy_data: dict) -> list[str]:
    """Получить список активных названий расовых синергий для команды."""
    bonuses = calculate_race_bonuses(team_units, race_synergy_data)
    return list(bonuses.keys())


def get_active_passives(team_units: list[dict], unit_data: dict) -> list[str]:
    """Получить список активных пассивных способностей для команды."""
    bonuses = calculate_passive_bonuses(team_units, unit_data)
    return [b["passive_name"] for b in bonuses.values() if b["bonus_value"] > 0]
