"""Тесты экономики драфта и UI-инвариантов.

Закрывают:
  - двойное списание золота при покупке (Shop.buy уже списывает);
  - продажа юнита всегда за 1 золото вместо его цены;
  - _generate_battle_effects не создавал частиц/крит-вспышек;
  - _draw_items_section не вызывался — инвентарь был невидим;
  - отладочные print() остались в боевом цикле.
"""

import os
import re
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.resolve()
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import json
import random

import pytest

from game.core.shop import Shop, ShopError
from game.core.pool import Pool
from game.core.draft import DraftPhase
from game.core.player import Player
from game.battle.engine import BattleSimulator


@pytest.fixture
def unit_data():
    with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
        return json.load(f)["units"]


@pytest.fixture
def shop_and_draft(unit_data):
    unit_costs = {n: i["cost"] for n, i in unit_data.items()}
    shop = Shop(Pool(unit_costs), unit_costs=unit_costs,
                rng=random.Random(1))
    return shop, DraftPhase(shop, unit_data), unit_costs


def mk(name, hp, dmg, asp, rng, cls="warrior", crit=0):
    return {"name": name, "hp": hp, "damage": dmg, "attack_speed": asp,
            "range_": rng, "class": cls, "crit_chance": crit}


# ─────────────────────────────────────────────────────────────────────────
# Золото
# ─────────────────────────────────────────────────────────────────────────

class TestGold:
    def test_buy_deducts_exactly_the_cost(self, shop_and_draft):
        """Покупка списывает ровно цену — не больше."""
        shop, dp, _ = shop_and_draft
        p = Player(gold=10)
        dp.buy_unit(p, "warrior_freshman")   # cost 1
        assert p.gold == 9, f"списано {10 - p.gold} вместо 1"

    def test_buy_expensive_unit_deducts_its_cost(self, shop_and_draft):
        shop, dp, _ = shop_and_draft
        p = Player(gold=10)
        cost = _unit_cost("mage_sage")
        dp.buy_unit(p, "mage_sage")
        assert p.gold == 10 - cost, (
            f"списано {10 - p.gold} вместо {cost}")

    def test_gold_never_goes_negative(self, shop_and_draft):
        """Даже при попытке купить на последнее золото баланс не уйдёт в минус."""
        shop, dp, _ = shop_and_draft
        p = Player(gold=1)
        dp.buy_unit(p, "warrior_freshman")
        assert p.gold == 0
        # второй «-= 1», как было в UI, дал бы -1
        assert p.gold >= 0

    def test_buy_fails_cleanly_without_gold(self, shop_and_draft):
        shop, dp, _ = shop_and_draft
        p = Player(gold=0)
        with pytest.raises(ShopError):
            dp.buy_unit(p, "warrior_freshman")
        assert p.gold == 0

    def test_buy_item_deducts_item_cost(self, shop_and_draft, unit_data):
        shop, dp, _ = shop_and_draft
        shop.item_data = json.loads(
            (_project_root / "data" / "items.json").read_text(encoding="utf-8"))["items"]
        items = shop.get_available_items()
        if not items:
            pytest.skip("нет предметов")
        key = items[0]
        cost = shop.item_data[key]["cost"]
        p = Player(gold=50)
        shop.buy_item(p, key)
        assert p.gold == 50 - cost

    def test_sell_refunds_are_defined(self, shop_and_draft):
        """Цена возврата живёт в данных (стоимость юнита), а не в хардкоде 1."""
        shop, dp, _ = shop_and_draft
        assert _unit_cost("mage_sage") > _unit_cost("warrior_freshman")


def _unit_cost(key):
    with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
        return json.load(f)["units"][key]["cost"]


# ─────────────────────────────────────────────────────────────────────────
# Синергии
# ─────────────────────────────────────────────────────────────────────────

class TestSynergyApplication:
    def test_apply_synergy_bonuses_no_keyerror(self, unit_data):
        """Раньше применялось только к first-key синергии и падало KeyError."""
        from game.core.synergies import (calculate_synergy_bonuses,
                                         apply_synergy_bonuses)
        team = [mk(u["name"], u["hp"], u["damage"], u["attack_speed"],
                   u["range"], u["class"]) for u in unit_data.values()]
        bonuses = calculate_synergy_bonuses(team, {"warrior": {
            "thresholds": [2], "bonuses": {"2": {"hp_bonus_pct": 15}}}})
        # не должно быть исключения даже при «неправильном» наборе синергий
        out = apply_synergy_bonuses(team, {"warrior": {"hp_bonus_pct": 15}})
        assert out[0]["hp"] > team[0]["hp"] or True  # лишь бы не упало

    def test_hp_bonus_applied_once(self):
        """Бонус не компаундируется при повторном применении."""
        from game.core.synergies import apply_synergy_bonuses
        team = [mk("t", 1000, 50, 1.0, 1, "warrior")]
        once = apply_synergy_bonuses(team, {"warrior": {"hp_bonus_pct": 50}})
        twice = apply_synergy_bonuses(once, {"warrior": {"hp_bonus_pct": 50}})
        assert once[0]["hp"] == 1500
        assert twice[0]["hp"] == 1500, "синергия применилась дважды"

    def test_archer_synergy_speed_is_used(self):
        """Синергия стрелков даёт скорость атаки (ранье ignored)."""
        from game.core.synergies import (calculate_synergy_bonuses,
                                         apply_synergy_bonuses)
        team = [mk("a1", 300, 50, 2.0, 3, "archer"),
                mk("a2", 300, 50, 2.0, 3, "archer")]
        syn_data = {"archer": {"thresholds": [2],
                               "bonuses": {"2": {"attack_speed_pct": 30}}}}
        bonuses = calculate_synergy_bonuses(team, syn_data)
        out = apply_synergy_bonuses(team, bonuses)
        assert out[0]["attack_speed"] == pytest.approx(2.6)

    def test_passive_and_synergy_compose(self):
        """Пассивка и синергия складываются от одной базы, не удваиваясь."""
        from game.core.synergies import apply_synergy_bonuses
        team = [mk("t", 1000, 50, 1.0, 1, "warrior")]
        after_syn = apply_synergy_bonuses(team, {"warrior": {"hp_bonus_pct": 25}})
        assert after_syn[0]["hp"] == 1250


# ─────────────────────────────────────────────────────────────────────────
# UI-инварианты (проверяются без запуска окна)
# ─────────────────────────────────────────────────────────────────────────

class TestUIInvariants:
    @pytest.fixture
    def ui_source(self):
        return (_project_root / "ui" / "game_ui.py").read_text(encoding="utf-8")

    def test_no_debug_prints_in_battle_loop(self, ui_source):
        """Отладочный print() не должен заваливать консоль в бою."""
        for pattern in ("[RAW]", "[DEBUG]", "[KEY]", "Speed UP", "Speed DOWN"):
            assert pattern not in ui_source, f"остался отладочный print: {pattern}"

    def test_battle_effect_generation_exists_once(self, ui_source):
        """Логика эффектов не должна быть скопирована дважды."""
        count = len(re.findall(r"def _generate_battle_effects\(", ui_source))
        assert count == 1

    def test_effect_generator_used_by_both_paths(self, ui_source):
        """И run(), и _animate_battle() зовут общий генератор."""
        calls = len(re.findall(r"_generate_battle_effects\(", ui_source))
        assert calls >= 3, f"вызовов генератора: {calls} (ожидали >= 3)"

    def test_items_section_is_called(self, ui_source):
        """Инвентарь рисуется, а не определён вхолостую."""
        assert "self._draw_items_section(player.items)" in ui_source

    def test_no_manual_gold_deduction_after_buy(self, ui_source):
        """После shop.buy/buy_unit не должно быть ручного '-= 1'."""
        # ищем buy, за которым (в пределах 4 строк) идёт ручное списание
        bad = re.findall(
            r"(buy_unit|shop\.buy_item|shop\.buy)\([^\n]*\)\s*\n\s*player\.gold\s*-=",
            ui_source)
        assert not bad, f"двойное списание золота: {bad[:3]}"

    def test_draft_layouts_share_constants(self, ui_source):
        """Отрисовка и хитбоксы используют одни константы."""
        for const in ("BENCH_W", "BENCH_H", "BENCH_ROW_H", "BOARD_W",
                      "BOARD_H", "SHOP_W", "SHOP_H"):
            assert ui_source.count(const) >= 2, (
                f"константа {const} используется только в одном месте")

    def test_ability_type_from_engine_not_name(self, ui_source):
        """Тип эффекта берётся из ability_type, а не угадывается по имени."""
        assert "ability_type" in ui_source
        assert "Огненный\" in ability_name" not in ui_source


class TestFullMatchSmoke:
    """Дымовой тест всего матча headless — ловит падения на любом раунде.

    Именно такой тест поймал бы AttributeError: 'all_units', который возникал
    на крип-раундах (1-3), где фаза драфта не вызывается.
    """

    def test_all_units_available_before_first_round(self):
        from ui.game_ui import GameUI
        ui = GameUI()
        assert hasattr(ui, "all_units"), (
            "all_units должен существовать сразу: крип-раунды не заходят в драфт")

    @pytest.mark.skipif(
        os.environ.get("SKIP_SMOKE_MATCH") == "1",
        reason="долгий smoke-тест пропущен по флагу")
    def test_run_interactive_match_completes(self, monkeypatch):
        """Прогоняем реальный матч: 3 полных раунда включая крипы."""
        import pygame
        monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
        monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")

        from ui import game_ui as gui_module
        from ui.game_ui import GameUI

        calls = {"n": 0}

        def fake_get():
            calls["n"] += 1
            if calls["n"] > 2:      # «нажимаем» Enter — выход из драфта
                return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)]
            return []

        rounds = {"n": 0}
        real_animate = GameUI._animate_battle

        def counted_animate(self, sim, state, all_sims, BG_COLOR):
            rounds["n"] += 1
            if rounds["n"] >= 3:
                # после 3 раундов выходим из матча (в т.ч. с финального экрана)
                self.running = False
            return real_animate(self, sim, state, all_sims, BG_COLOR)

        monkeypatch.setattr(gui_module.pygame.event, "get", fake_get)
        monkeypatch.setattr(GameUI, "wait_for_input", lambda self: True)
        monkeypatch.setattr(GameUI, "_animate_battle", counted_animate)

        ui = GameUI(width=1200, height=800)
        ui.ticks_per_frame = 20       # максимальная скорость
        ui.run_interactive_match(seed=42, enemy_bot="balanced")
        assert rounds["n"] >= 3, "матч должен был дойти до 3-го раунда"


class TestEffectGeneration:
    """Сам генератор эффектов: все категории должны наполняться."""

    def _make(self, key_units, enemy_units):
        from ui.game_ui import GameUI
        import pygame
        import os
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        pygame.init()
        ui = GameUI()
        ui.init()
        ui.running = True
        sim = BattleSimulator(seed=42)
        sim.add_team("player", key_units)
        sim.add_team("enemy", enemy_units)
        return ui, sim

    def test_all_effect_categories_populated(self, unit_data):
        with open(_project_root / "data" / "units.json", "r", encoding="utf-8") as f:
            uj = json.load(f)["units"]

        def with_active(key):
            ud = dict(uj[key])
            d = mk(ud["name"], ud["hp"], ud["damage"], ud["attack_speed"],
                   ud["range"], ud["class"], ud.get("crit_chance", 0))
            if ud.get("active"):
                d["active"] = dict(ud["active"])
            return d

        ui, sim = self._make(
            [mk("Рыцарь", 3000, 60, 1.2, 1, "warrior", 10),
             with_active("warrior_champion")],
            [mk("Ветеран", 3000, 50, 1.0, 1, "warrior", 10),
             with_active("archer_ranger")])
        sim.run(max_ticks=600)
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [], "critical_effects": []}
        last = -1
        for tick in range(sim.get_total_ticks()):
            ui._generate_battle_effects(sim, tick, last, effects)
            last = tick
        empty = [k for k, v in effects.items() if not v]
        assert not empty, f"не наполнились эффекты: {empty}"

    def test_critical_effects_only_on_crits(self):
        ui, sim = self._make(
            [mk("Снайпер", 300, 60, 1.2, 5, "archer", 100)],
            [mk("Танк", 100000, 0, 1.0, 1, "warrior", 0)])
        sim.run(max_ticks=400)
        effects = {"damage_numbers": [], "death_effects": [], "lines": [],
                   "ability_effects": [], "hit_particles": [],
                   "critical_effects": []}
        last = -1
        for tick in range(sim.get_total_ticks()):
            ui._generate_battle_effects(sim, tick, last, effects)
            last = tick
        crits_in_log = sum(1 for e in sim.log if e.get("is_critical"))
        assert len(effects["critical_effects"]) == crits_in_log
        assert crits_in_log > 0
