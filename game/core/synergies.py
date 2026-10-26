"""Расчёт бонусов синергий и пассивных способностей от состава команды.

Синергия активируется когда в команде >= N юнитов данного класса.
Каждый порог (threshold) даёт свой бонус.

Пассивные способности работают поверх синергий:
  - synergy_buff: бонус за каждого союзного юнита своего класса
  - aura: пассивная аура урона/защиты
  - buff_allies: бафф союзников

Пример: Воин 2/4
  - 2+ воина: +15% HP ко всем воинам
  - 4+ воинов: +30% HP ко всем воинам (перекрывает предыдущий)
"""


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
        
        # synergy_buff: бонус за каждого союзного юнита своего класса
        ally_count = 0
        for other in team_units:
            if other is unit:
                continue
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
        
        if bonus_value > 0 and bonus_key:
            result[name_base] = {
                "passive_name": passive["name"],
                "bonus_key": bonus_key,
                "bonus_value": bonus_value,
                "ally_count": ally_count,
            }
    
    return result


def apply_synergy_hp_bonuses(team_units: list[dict], synergy_bonuses: dict) -> list[dict]:
    """Применить HP-бонусы синергий к юнитам команды.

    Возвращает список словарей с изменённым max_hp (оригинал не меняется).

    Args:
        team_units: исходные данные юнитов
        synergy_bonuses: результат calculate_synergy_bonuses()

    Returns:
        Список юнитов с применёнными бонусами HP.
    """
    # Собираем все HP-бонусы для каждого класса
    hp_bonus_pct = 0
    for syn_name, bonuses in synergy_bonuses.items():
        if "hp_bonus_pct" in bonuses:
            # Находим класс синергии (по имени)
            for unit in team_units:
                if unit.get("class") == syn_name:
                    hp_bonus_pct += bonuses["hp_bonus_pct"]
                    break

    modified = []
    for unit in team_units:
        u = dict(unit)  # копия
        if "hp_bonus_pct" in synergy_bonuses and u.get("class") == list(synergy_bonuses.keys())[0]:
            bonus = synergy_bonuses["hp_bonus_pct"]
            original_hp = unit.get("_base_hp", unit.get("hp", 100))
            u["hp"] = int(original_hp * (1 + bonus / 100))
        modified.append(u)

    return modified


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
        
        if name_base in passive_bonuses:
            bonus_info = passive_bonuses[name_base]
            # Добавляем пассивный бонус к соответствующему полю
            if "hp_bonus_pct" in bonus_info["bonus_key"]:
                u["hp"] = int(u.get("hp", 100) * (1 + bonus_info["bonus_value"] / 100))
            elif "damage_bonus_pct" in bonus_info["bonus_key"]:
                u["damage"] = u.get("damage", 50) * (1 + bonus_info["bonus_value"] / 100)
            elif "speed_bonus_pct" in bonus_info["bonus_key"]:
                u["attack_speed"] = u.get("attack_speed", 1.0) * (1 + bonus_info["bonus_value"] / 100)
        
        # Сохраняем информацию о пассивке для UI
        if name_base in passive_bonuses:
            u["_passive_bonus"] = passive_bonuses[name_base]
        
        modified.append(u)

    return modified


def get_active_synergies(team_units: list[dict], synergy_data: dict) -> list[str]:
    """Получить список активных названий синергий для команды."""
    bonuses = calculate_synergy_bonuses(team_units, synergy_data)
    return list(bonuses.keys())


def get_active_passives(team_units: list[dict], unit_data: dict) -> list[str]:
    """Получить список активных пассивных способностей для команды."""
    bonuses = calculate_passive_bonuses(team_units, unit_data)
    return [b["passive_name"] for b in bonuses.values() if b["bonus_value"] > 0]
