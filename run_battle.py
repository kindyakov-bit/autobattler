"""Консольный раннер: загрузка данных из JSON и запуск симуляции боя.

Использование:
    python run_battle.py                          # бой по умолчанию
    python run_battle.py --seed 123               # свой seed
    python run_battle.py --verbose                # подробный лог каждого тика
"""

import json
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.battle.engine import BattleSimulator


def load_units(json_path: str) -> dict:
    """Загрузить данные юнитов из JSON."""
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_team(data: dict, team_name: str, unit_keys: list[str]) -> list[dict]:
    """Собрать список юнитов для команды из JSON данных."""
    units = []
    for key in unit_keys:
        if key not in data["units"]:
            raise ValueError(f"Юнит '{key}' не найден в data/units.json")
        ud = dict(data["units"][key])
        ud["team"] = team_name
        units.append(ud)
    return units


def run_battle(seed: int, verbose: bool = False):
    """Запустить симуляцию боя."""
    json_path = PROJECT_ROOT / "data" / "units.json"
    data = load_units(str(json_path))

    # Формируем составы команд (MVP: по 3 юнита на каждую сторону)
    # Игрок: 1x новичок, 2x ветеран, 1x послушник
    player_units = [
        "warrior_freshman",
        "warrior_veteran",
        "mage_acolyte",
    ]

    # Враг (бот): 1x скаут, 2x маг-чародей
    enemy_units = [
        "archer_scout",
        "mage_sorcerer",
        "mage_sorcerer",
    ]

    sim = BattleSimulator(seed=seed)
    sim.add_team("player", build_team(data, "player", player_units))
    sim.add_team("enemy", build_team(data, "enemy", enemy_units))

    if verbose:
        print(f"=== БОЙ (seed={seed}) ===")
        print()

    result = sim.run()

    # Вывод результатов
    print(f"\n{'='*50}")
    print(f"ПОБЕДИТЕЛЬ: {result['winner'].upper()}")
    print(f"Причина: {result['reason']}")
    print(f"Тиков прошло: {result['ticks']}")
    print()

    for name, hp in result.get("team_hp", {}).items():
        status = "ЖИВ" if hp > 0 else "УНИЧТОЖЕН"
        print(f"  [{name}] HP: {hp} ({status})")

    # Показываем последние события (последние 10 тиков)
    if verbose and sim.log:
        print("\n--- Последние события ---")
        for event in sim.log[-20:]:
            if event["type"] == "hit":
                print(f"  [{event['tick']}] удар: {event['damage']} урона, "
                      f"жертва HP={event['target_hp']}")
            elif event["type"] == "kill":
                print(f"  [{event['tick']}] КИЛЛ! жертва HP={event['target_hp']}")

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Автобатлер — консольный симулятор боя")
    parser.add_argument("--seed", type=int, default=42, help="Seed для RNG (по умолчанию 42)")
    parser.add_argument("--verbose", action="store_true", help="Подробный лог каждого тика")
    args = parser.parse_args()

    run_battle(seed=args.seed, verbose=args.verbose)


if __name__ == "__main__":
    main()
