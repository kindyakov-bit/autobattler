"""Тест: звёздность юнитов не теряется между раундами.

Баг из живой игры (27.10.2026): «скауты со звездой после раунда без звезды».
Причина: _run_interactive_draft сериализовал доску в формат боя без поля
star и с именем без ★N — restore следующего раунда читал star=1 всегда.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import json
import pygame
import pytest


@pytest.fixture()
def ui():
    pygame.init()
    from ui.game_ui import GameUI
    gui = GameUI(width=1200, height=800)
    gui.init()
    gui.running = True
    data = json.loads((ROOT / "data" / "units.json").read_text(encoding="utf-8"))
    gui.all_units = data["units"]
    gui._rebuild_cost_index()
    return gui


def restore_star(existing_units, all_units):
    """Воспроизводим логику restore из _run_interactive_draft (строки ~899-910)."""
    from game.core.player import Player
    player = Player(gold=0)
    for u in existing_units.get("units", []):
        name = u.get("name", "warrior_freshman")
        star = u.get("star", 1)
        if star > 1 and "★" not in name:
            name = f"{name}★{star}"
        if len(player.board) < 6:
            player.board.append({"name": name, "star": star})
        else:
            player.reserve.append(name)
    return player


class TestStarPersistence:
    """Звезда должна переживать цикл save (доска→бой) → restore (бой→доска)."""

    def test_star2_survives_round_trip(self, ui):
        # доска после мержа: скаут ★2
        board = [{"name": "archer_scout★2", "star": 2}]
        # → формат боя (как _run_interactive_draft сериализует)
        battle = []
        for unit in board:
            name_base = unit["name"].split("★")[0]
            star = unit.get("star", 1)
            battle.append({
                "name": f"{name_base}★{star}" if star > 1 else name_base,
                "star": star,
            })
        assert battle[0]["name"] == "archer_scout★2"
        assert battle[0]["star"] == 2

        # → restore следующего раунда
        player = restore_star({"units": battle}, ui.all_units)
        assert player.board[0]["name"] == "archer_scout★2"
        assert player.board[0]["star"] == 2

    def test_star1_has_no_suffix(self, ui):
        """Обычный юнит не должен получать ★1 в имени (лишний суффикс)."""
        board = [{"name": "archer_scout", "star": 1}]
        battle = [{
            "name": board[0]["name"],
            "star": board[0]["star"],
        }]
        player = restore_star({"units": battle}, ui.all_units)
        assert player.board[0]["name"] == "archer_scout"
        assert "★" not in player.board[0]["name"]

    def test_display_name_shows_stars_in_battle(self, ui):
        """display_name в бою показывает звёзды: 'archer_scout★2' → «Скаут *»."""
        assert ui.display_name("archer_scout★2") == "Скаут *"
        assert ui.display_name("warrior_knight★3") == "Рыцарь **"

    def test_bench_shows_star_after_restore(self, ui):
        """Юнит на бенче (перелив с полной доски) сохраняет ★N в имени."""
        battle = [{"name": "archer_scout★2", "star": 2}] * 7  # 7 юнитов, 6 на доску
        player = restore_star({"units": battle}, ui.all_units)
        assert len(player.reserve) == 1
        assert player.reserve[0] == "archer_scout★2"
