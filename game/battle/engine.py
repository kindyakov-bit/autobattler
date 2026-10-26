"""Боевой движок: детерминированный тик + seeded RNG.

Масштаб времени
---------------
1 тик = 1 кадр симуляции. Атака происходит раз в
``ceil(60 / attack_speed)`` тиков, поэтому бой на 600 тиков ≈ 10 секунд.
Кулдауны способностей и длительности эффектов указаны в ТЕХ ЖЕ тиках.

Целевание
---------
Юниты выстроены в колонку: юнит с индексом i стоит в i-й колонке своей команды.
Дистанция между юнитом i и врагом j = ``1 + (i + j + 1) // 2`` колонок: оба
отступают от переднего края своей команды, поэтому задние юниты и досягаемость
хуже. Юнит бьёт только если ``range_ >= дистанция``.

Шкала подобрана так, чтобы range=6 (легендарный маг) доставал до любого врага,
а ближние юниты (range_ <= 1) сближались на одну колонку каждые
``MOVE_TICKS_PER_COLUMN`` тиков — задним линиям нужно время, чтобы вступить в бой.

Способности
-----------
Поддержанные типы активок (данные — в data/units.json):
    - aoe_damage            — урон по области
    - single_target_critical — гарантированный крит по самому слабому врагу
    - aoe_damage_slow       — урон по области + замедление врагов
    - aoe_damage_buff       — урон по области + бафф своей скорости атаки
    - buff_allies           — снижение входящего урона союзникам
    - buff_next_attack      — следующая атака бьёт по области с бонусом урона
    - aura                  - бафф собственного урона за союзников своего класса

Все эффекты «на N тиков» живут в Unit.statuses и корректно истекают.

Использование:
    sim = BattleSimulator(seed=42)
    sim.add_team("player", team_data)
    sim.add_team("enemy", enemy_data)
    result = sim.run()  # dict с итогами боя
"""

import math
import random

# Все типы активок, которые умеет движок. Всё, чего нет в этом кортеже,
# считается ошибкой данных (а не молча неработающей способностью).
SUPPORTED_ABILITY_TYPES = (
    "aoe_damage",
    "single_target_critical",
    "aoe_damage_slow",
    "aoe_damage_buff",
    "buff_allies",
    "buff_next_attack",
    "aura",
)

# Виды временных эффектов на юните
KIND_DAMAGE_BONUS = "damage_bonus"        # +плоский урон себе
KIND_SPEED_PCT = "speed_pct"              # +% к своей скорости атаки
KIND_DAMAGE_REDUCTION = "damage_reduction"  # -% ко входящему урону
KIND_SLOW_PCT = "slow_pct"                # -% к скорости атаки (накладывается на врага)
KIND_NEXT_ATTACK = "next_attack_bonus"    # бонус следующей атаки + свой радиус

# Лимиты радиуса урона по области
MAX_AOE_TARGETS = {1: 1, 2: 3}
MAX_AOE_TARGETS_DEFAULT = 5

# Сколько тиков занимает сближение на одну колонку (для ближнего боя).
# Значение подобрано так, чтобы сдвигать момент первого удара: атака
# происходит раз в ceil(60 / attack_speed) тиков, поэтому сближение на
# 30 тиков за колонку реально задерживает выход задних линий в бой.
MOVE_TICKS_PER_COLUMN = 30

# Максимум тиков сближения. Должен перекрывать самую длинную дистанцию
# (1 + 5 + 5 = 11 колонок), иначе задний юнит не дойдёт никогда.
MAX_CLOSING_TICKS = 1000

# Потолок суммарного снижения урона. Несколько «Щитовых стен» не должны
# складываться в 100%+ и потом лечить юнита отрицательным уроном.
MAX_DAMAGE_REDUCTION_PCT = 90


class Unit:
    """Юнит на поле боя."""

    def __init__(self, name: str, hp: int, damage: float, attack_speed: float,
                 range_: int, team: str, unit_id: int,
                 unit_class: str = "", crit_chance: float = 0.0,
                 crit_multiplier: float = 1.75):
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.base_damage = float(damage)
        self.damage = float(damage)
        self.base_attack_speed = float(attack_speed)
        self.attack_speed = float(attack_speed)
        self.range_ = int(range_)
        self.team = team
        self.unit_id = unit_id
        self.unit_class = unit_class
        self.alive = True

        # Криты (данные из JSON, по умолчанию выключены)
        self.crit_chance = float(crit_chance)
        self.crit_multiplier = float(crit_multiplier)

        # Временные эффекты: [{"kind": ..., "ticks": N, ...}]
        self.statuses: list[dict] = []
        # Сколько тиков юнит сближался с врагом (только для ближнего боя)
        self.closing = 0
        # Реально применённый урон (после снижения) — для честных цифр в UI
        self.last_damage = 0.0

        # Таймер до следующей атаки (в тиках)
        self.attack_timer = self._ticks_per_attack()

        # Активная способность
        self.active_ability: dict | None = None
        self.ability_cooldown = 0

    # ── Базовые расчёты ────────────────────────────────────────────────────

    def _ticks_per_attack(self) -> int:
        """Тиков между атаками при текущей скорости атаки."""
        return max(1, math.ceil(60 / max(0.05, self.attack_speed)))

    def _refresh_stats(self) -> None:
        """Пересчитать damage/attack_speed из базы + активных эффектов."""
        damage = self.base_damage
        speed = self.base_attack_speed
        for st in self.statuses:
            kind = st["kind"]
            if kind == KIND_DAMAGE_BONUS:
                damage += st.get("amount", 0)
            elif kind == KIND_SPEED_PCT:
                speed *= (1 + st.get("pct", 0) / 100)
            elif kind == KIND_SLOW_PCT:
                speed *= (1 - st.get("pct", 0) / 100)
        self.damage = damage
        self.attack_speed = max(0.05, speed)

    # ── Временные эффекты ──────────────────────────────────────────────────

    def add_status(self, kind: str, ticks: int, **params) -> None:
        """Наложить эффект на `ticks` тиков."""
        self.statuses.append({"kind": kind, "ticks": ticks, **params})
        self._refresh_stats()

    def tick_statuses(self) -> None:
        """Уменьшить длительность эффектов, снять истёкшие, пересчитать статы."""
        if self.statuses:
            self.statuses = [s for s in self.statuses if s["ticks"] > 1]
            for s in self.statuses:
                s["ticks"] -= 1
            self._refresh_stats()

    def damage_reduction_pct(self) -> float:
        """Суммарное снижение входящего урона в процентах (с потолком)."""
        total = sum(s.get("pct", 0) for s in self.statuses
                    if s["kind"] == KIND_DAMAGE_REDUCTION)
        return min(MAX_DAMAGE_REDUCTION_PCT, total)

    def next_attack_bonus(self) -> tuple[float, int]:
        """(бонус урона, радиус) следующей атаки, если он есть."""
        bonus = 0.0
        radius = 0
        for s in self.statuses:
            if s["kind"] == KIND_NEXT_ATTACK:
                bonus += s.get("amount", 0)
                radius = max(radius, s.get("radius", 1))
        return bonus, radius

    def consume_next_attack(self) -> tuple[float, int]:
        """Забрать бонус следующей атаки (снимая эффект)."""
        bonus, radius = self.next_attack_bonus()
        if bonus:
            self.statuses = [s for s in self.statuses
                             if s["kind"] != KIND_NEXT_ATTACK]
            self._refresh_stats()
        return bonus, radius

    def reset(self) -> None:
        """Вернуть юнита в исходное состояние (для повторного run())."""
        self.hp = self.max_hp
        self.alive = True
        self.statuses = []
        self.closing = 0
        self.attack_timer = self._ticks_per_attack()
        self.ability_cooldown = (self.active_ability or {}).get("cooldown", 0) \
            if self.active_ability else 0
        self._refresh_stats()

    # ── Урон ───────────────────────────────────────────────────────────────

    def take_damage(self, amount: float) -> bool:
        """Нанести урон (с учётом снижения урона). True если юнит умер."""
        effective = max(0.0, amount * (1 - self.damage_reduction_pct() / 100))
        self.hp -= effective
        self.last_damage = effective
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            return True
        return False

    def tick(self, rng: random.Random | None = None) -> list[dict]:
        """Обработать один тик юнитом. Возвращает список событий атак."""
        events = []
        if not self.alive:
            return events

        # Таймер уже уменьшен в BattleSimulator.run() — проверяем только условие
        if self.attack_timer <= 0:
            bonus, radius = self.consume_next_attack()
            damage = self.damage + bonus
            crit = False
            # crit_chance в данных указан в процентах (0..100)
            if rng is not None and self.crit_chance > 0:
                if rng.random() < self.crit_chance / 100.0:
                    crit = True
                    damage *= self.crit_multiplier

            events.append({
                "type": "attack",
                "attacker_id": self.unit_id,
                "attacker_team": self.team,
                "damage": damage,
                "range_": self.range_,
                "aoe_radius": radius,
                "is_critical": crit,
            })

        return events

    def snapshot(self) -> dict:
        """Сериализуемое состояние юнита для анимации."""
        return {
            "name": self.name,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "alive": self.alive,
            "attack_timer": self.attack_timer,
            "damage": self.damage,
            "attack_speed": self.attack_speed,
            "range_": self.range_,
            "team": self.team,
            "unit_id": self.unit_id,
            "active_ability": self.active_ability,
            "ability_cooldown": self.ability_cooldown,
            "base_damage": self.base_damage,
            "base_attack_speed": self.base_attack_speed,
            "unit_class": self.unit_class,
            "statuses": [dict(s) for s in self.statuses],
            "closing": self.closing,
        }


class BattleSimulator:
    """Симулятор боя: два отряда, детерминированный тик."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self._next_id = 0
        self.teams: dict[str, list[Unit]] = {}
        self._team_index: dict[int, int] = {}   # unit_id -> индекс внутри команды
        self.log: list[dict] = []
        self.tick_count = 0
        self._tick_history: list[dict] = []
        self._attack_events: list[dict] = []
        self._ability_events: list[dict] = []

    # ── Формирование команд ────────────────────────────────────────────────

    def add_team(self, name: str, units_data: list[dict]) -> None:
        """Добавить юнитов к команде (повторный вызов дополняет, а не заменяет).

        Поддерживаемые поля units_data:
            - item_bonuses: {"hp_bonus": 200, "damage_bonus": 25, "speed_bonus_pct": 10}
            - active:       dict активной способности из units.json
            - crit_chance / crit_multiplier: настройка критов
            - unit_class:   класс юнита (warrior/mage/archer) — для aura-способностей
        """
        team_units = self.teams.setdefault(name, [])

        for ud in units_data:
            bonuses = ud.get("item_bonuses", {})
            hp = int(ud["hp"]) + bonuses.get("hp_bonus", 0)
            damage = float(ud["damage"]) + bonuses.get("damage_bonus", 0)
            attack_speed = float(ud["attack_speed"])

            # Процентный бонус к скорости атаки (от предметов)
            speed_pct = bonuses.get("speed_bonus_pct", 0)
            if speed_pct:
                attack_speed *= (1 + speed_pct / 100)

            u = Unit(
                name=ud["name"],
                hp=hp,
                damage=damage,
                attack_speed=attack_speed,
                range_=int(ud.get("range", ud.get("range_", 1))),
                team=name,
                unit_id=self._next_id,
                unit_class=ud.get("unit_class", ud.get("class", "")),
                crit_chance=float(ud.get("crit_chance", 0.0)),
                crit_multiplier=float(ud.get("crit_multiplier", 1.75)),
            )

            # Активная способность. Неизвестный тип — ошибка данных, её надо
            # слышать сразу, а не искать потом «почему способность не работает».
            ability = ud.get("active")
            if ability:
                atype = ability.get("type")
                if atype not in SUPPORTED_ABILITY_TYPES:
                    raise ValueError(
                        f"Юнит '{u.name}': движок не умеет тип способности "
                        f"'{atype}'. Поддерживаются: {', '.join(SUPPORTED_ABILITY_TYPES)}"
                    )
                u.active_ability = dict(ability)
                u.ability_cooldown = ability.get("cooldown", 3)

            self._next_id += 1
            team_units.append(u)

        # Пересчитываем индексы внутри команды (нужны для дистанции)
        for team_name, units in self.teams.items():
            for idx, u in enumerate(units):
                self._team_index[u.unit_id] = idx

    # ── Дистанции и цели ───────────────────────────────────────────────────

    def _find_unit(self, unit_id: int) -> Unit | None:
        for team in self.teams.values():
            for u in team:
                if u.unit_id == unit_id:
                    return u
        return None

    def distance_to(self, attacker: Unit, target: Unit) -> int:
        """Дистанция в колонках, с учётом сближения атакующего.

        База — ``1 + (i + j + 1) // 2``: юнит с индексом i и враг с индексом j
        оба отстоят от переднего края своей команды.
        """
        ai = self._team_index.get(attacker.unit_id, 0)
        tj = self._team_index.get(target.unit_id, 0)
        base = 1 + (ai + tj + 1) // 2
        if attacker.range_ <= 1 and attacker.closing:
            base = max(1, base - attacker.closing // MOVE_TICKS_PER_COLUMN)
        return base

    def _alive_enemies(self, unit: Unit) -> list[Unit]:
        return [u for t, lst in self.teams.items()
                if t != unit.team for u in lst if u.alive]

    def _enemies_in_radius(self, unit: Unit, radius: int) -> list[Unit]:
        """Цели урона по области.

        Радиус в данных — это «ширина захвата»: сколько врагов с переднего края
        попадает под удар (radius 1 → 1 цель, 2 → 3, 3+ → до 5).
        Досягаемость (``range_``) при этом проверяется отдельно: если кастующему
        не достать даже до ближайшего врага, способность ни по кому не бьёт.
        """
        enemies = sorted(self._alive_enemies(unit),
                         key=lambda e: self.distance_to(unit, e))
        if not enemies:
            return []
        if unit.range_ < self.distance_to(unit, enemies[0]):
            return []                      # не достаём ни до кого
        cap = MAX_AOE_TARGETS.get(radius, MAX_AOE_TARGETS_DEFAULT)
        return enemies[:cap]

    def _find_targets(self, event: dict) -> list[Unit]:
        """Найти цели для атаки: ближайший живой враг в радиусе действия."""
        attacker = self._find_unit(event["attacker_id"])
        if not attacker or not attacker.alive:
            return []

        enemies = self._alive_enemies(attacker)
        if not enemies:
            return []

        radius = event.get("aoe_radius", 0)
        if radius and radius > 0:
            return self._enemies_in_radius(attacker, radius)

        nearest = min(enemies, key=lambda e: self.distance_to(attacker, e))
        if attacker.range_ < self.distance_to(attacker, nearest):
            return []          # не достаёт — цель не выбрана
        return [nearest]

    # ── Урон от атак ───────────────────────────────────────────────────────

    def _apply_attack(self, event: dict) -> list[dict]:
        """Применить событие атаки: найти цели и нанести урон."""
        damage_events = []
        targets = self._find_targets(event)

        if not targets:
            return damage_events      # махнул в возду — визуального события нет

        # Событие атаки для визуальных эффектов (линии атак)
        self._attack_events.append({
            "tick": self.tick_count,
            "attacker_id": event["attacker_id"],
            "attacker_team": event["attacker_team"],
            "damage": event["damage"],
            "targets": [t.unit_id for t in targets],
            "is_critical": event.get("is_critical", False),
        })

        for target in targets:
            # Вариативность урона ±10%, детерминированная от seed
            variance = 0.9 + self.rng.random() * 0.2          # [0.9, 1.1]
            rolled = event["damage"] * variance
            died = target.take_damage(rolled)

            # В лог пишем РЕАЛЬНО применённый урон (после щитов/снижения),
            # чтобы цифры над юнитами совпадали с его полосой HP.
            devent = {
                "type": "hit",
                "tick": self.tick_count,
                "attacker_id": event["attacker_id"],
                "target_id": target.unit_id,
                "damage": round(target.last_damage, 1),
                "target_hp": target.hp,
                "is_critical": event.get("is_critical", False),
            }
            if died:
                devent["type"] = "kill"
                devent["killer_team"] = event["attacker_team"]

            damage_events.append(devent)

        return damage_events

    # ── Способности ────────────────────────────────────────────────────────

    def _record_ability(self, unit: Unit, targets: list[int]) -> dict:
        """Записать событие каста способности (и в лог, и для визуальных эффектов)."""
        ability = unit.active_ability or {}
        event = {
            "tick": self.tick_count,
            "caster_id": unit.unit_id,
            "caster_team": unit.team,
            "ability_name": ability.get("name", ""),
            "ability_type": ability.get("type", ""),
            "targets": list(targets),
        }
        self._ability_events.append(event)
        log_event = dict(event)
        log_event["type"] = "ability_buff"
        return log_event

    def _cast_ability(self, unit: Unit) -> list[dict]:
        """Применить активную способность юнита. Возвращает события для лога."""
        ability = unit.active_ability
        if not ability:
            return []

        atype = ability["type"]
        eff = ability.get("effect", {})
        events: list[dict] = []

        if atype in ("aoe_damage", "aoe_damage_slow", "aoe_damage_buff"):
            radius = eff.get("radius", 2)
            events += self._apply_aoe_damage(
                unit, eff.get("damage", 0), radius)

            if atype == "aoe_damage_slow":
                # Замедление всех задетых врагов
                for target in self._enemies_in_radius(unit, radius):
                    target.add_status(
                        KIND_SLOW_PCT,
                        eff.get("slow_duration", 10),
                        pct=eff.get("slow_pct", 30),
                    )

            elif atype == "aoe_damage_buff":
                # Временный бафф собственной скорости атаки
                unit.add_status(
                    KIND_SPEED_PCT,
                    eff.get("speed_bonus_duration", 20),
                    pct=eff.get("speed_bonus_pct", 20),
                )

        elif atype == "single_target_critical":
            events += self._apply_single_target_critical(
                unit, eff.get("damage", 0))

        elif atype == "buff_allies":
            # Снижение входящего урона всем союзникам
            for ally in self.teams.get(unit.team, []):
                if not ally.alive:
                    continue
                ally.add_status(
                    KIND_DAMAGE_REDUCTION,
                    eff.get("duration", 20),
                    pct=eff.get("damage_reduction_pct", 30),
                )
            targets = [a.unit_id for a in self.teams[unit.team] if a.alive]
            events.append(self._record_ability(unit, targets))

        elif atype == "buff_next_attack":
            # Следующая атака бьёт по области с бонусом урона
            unit.add_status(
                KIND_NEXT_ATTACK,
                eff.get("duration", 60),
                amount=eff.get("bonus_damage", 0),
                radius=eff.get("radius", 1),
            )
            events.append(self._record_ability(unit, [unit.unit_id]))

        elif atype == "aura":
            # Бонус к урону за каждого союзника своего класса
            allies = sum(1 for a in self.teams.get(unit.team, [])
                         if a.alive and a is not unit
                         and a.unit_class == unit.unit_class)
            amount = eff.get("bonus_damage_per_ally", 0) * allies
            if amount:
                unit.add_status(
                    KIND_DAMAGE_BONUS,
                    eff.get("duration", ability.get("cooldown", 6)),
                    amount=amount,
                )
            events.append(self._record_ability(unit, [unit.unit_id]))

        return events

    def _apply_aoe_damage(self, caster: Unit, damage, radius: int) -> list[dict]:
        """Урон по области всем врагам в радиусе."""
        events = []
        if not caster.alive:
            return events

        targets = self._enemies_in_radius(caster, radius)
        ability_name = caster.active_ability.get("name", "") if caster.active_ability else ""

        for target in targets:
            rolled = damage * (0.9 + self.rng.random() * 0.2)
            died = target.take_damage(rolled)

            event = {
                "type": "ability_hit",
                "tick": self.tick_count,
                "caster_id": caster.unit_id,
                "caster_team": caster.team,
                "target_id": target.unit_id,
                "damage": round(target.last_damage, 1),
                "target_hp": target.hp,
                "ability_name": ability_name,
                "ability_type": caster.active_ability["type"],
            }
            if died:
                event["type"] = "ability_kill"
                event["killer_team"] = caster.team

            events.append(event)

        # Событие способности для визуальных эффектов
        self._ability_events.append({
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "ability_name": ability_name,
            "ability_type": caster.active_ability["type"],
            "damage": damage,
            "targets": [t.unit_id for t in targets],
        })

        return events

    def _apply_single_target_critical(self, caster: Unit, damage) -> list[dict]:
        """Гарантированный крит по самому слабому врагу."""
        events = []
        enemies = self._alive_enemies(caster)
        if not enemies:
            return events

        target = min(enemies, key=lambda u: u.hp)
        rolled = damage * (0.9 + self.rng.random() * 0.2)
        died = target.take_damage(rolled)

        event = {
            "type": "ability_hit",
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "target_id": target.unit_id,
            "damage": round(target.last_damage, 1),
            "target_hp": target.hp,
            "ability_name": "Выстрел смерти",
            "ability_type": "single_target_critical",
            "is_critical": True,
        }
        if died:
            event["type"] = "ability_kill"
            event["killer_team"] = caster.team

        events.append(event)

        self._ability_events.append({
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "ability_name": "Выстрел смерти",
            "ability_type": "single_target_critical",
            "damage": damage,
            "targets": [target.unit_id],
        })

        return events

    # ── Результат ──────────────────────────────────────────────────────────

    def _check_result(self) -> dict | None:
        """Проверить условие конца боя. Возвращает результат или None."""
        alive = {}
        for name, units in self.teams.items():
            alive[name] = [u for u in units if u.alive]

        dead_teams = [n for n, u in alive.items() if len(u) == 0]
        live_teams = [n for n, u in alive.items() if len(u) > 0]

        # Одна команда уничтожена — победила другая
        if len(dead_teams) == 1 and len(live_teams) == 1:
            return self._result(live_teams[0], "annihilation")

        # Обе уничтожены одновременно — побеждает первая команда
        if len(dead_teams) == 2:
            return self._result(list(self.teams.keys())[0], "simultaneous_death")

        return None

    def _result(self, winner: str, reason: str) -> dict:
        return {
            "winner": winner,
            "reason": reason,
            "ticks": self.tick_count,
            "team_hp": {n: sum(u.hp for u in units)
                        for n, units in self.teams.items()},
        }

    # ── Основной цикл ──────────────────────────────────────────────────────

    def run(self, max_ticks: int = 600) -> dict:
        """Запустить бой. max_ticks — лимит (по умолчанию 10 секунд игры)."""
        self.log = []
        self.tick_count = 0
        self._tick_history = []
        self._attack_events = []
        self._ability_events = []
        # Каждый прогон начинается с одного и того же состояния RNG,
        # поэтому run() можно вызывать повторно и получать тот же бой.
        self.rng = random.Random(self.seed)

        # Юниты могли быть использованы ранее — возвращаем в исходное состояние
        for team in self.teams.values():
            for unit in team:
                unit.reset()

        while self.tick_count < max_ticks:
            all_units = [u for team in self.teams.values() for u in team]

            for unit in all_units:
                if not unit.alive:
                    continue

                # 1. Истечение временных эффектов
                unit.tick_statuses()

                # 2. Кулдаун способности
                if unit.active_ability and unit.ability_cooldown > 0:
                    unit.ability_cooldown -= 1

                # 3. Ближние юниты сближаются с врагом
                if unit.range_ <= 1 and unit.closing < MAX_CLOSING_TICKS:
                    unit.closing += 1

                # 4. Атака
                unit.attack_timer -= 1
                if unit.attack_timer <= 0:
                    for event in unit.tick(self.rng):
                        self.log.extend(self._apply_attack(event))
                    unit.attack_timer = unit._ticks_per_attack()

                # 5. Способность (когда готова)
                if unit.alive and unit.active_ability and unit.ability_cooldown == 0:
                    self.log.extend(self._cast_ability(unit))
                    unit.ability_cooldown = unit.active_ability.get("cooldown", 3)

            # Snapshot для анимации
            self._tick_history.append(self._take_snapshot())

            result = self._check_result()
            if result is not None:
                return result

            self.tick_count += 1

        # Таймаут — победа у команды с большим суммарным HP
        return self._result(
            max(self.teams, key=lambda n: sum(u.hp for u in self.teams[n])),
            "timeout",
        )

    # ── Состояние для UI ───────────────────────────────────────────────────

    def _take_snapshot(self) -> dict:
        """Сохранить состояние всех юнитов для анимации."""
        return {name: [u.snapshot() for u in units]
                for name, units in self.teams.items()}

    def get_unit_positions(self, player_units, enemy_units):
        """Позиции юнитов на экране: игрок слева, враги справа, со смещением."""
        cx = 600  # центр экрана (половина 1200)
        cy = 140
        positions = {}

        for i in range(len(player_units)):
            x = 30 + i * 160
            y = cy + i * 80
            positions[player_units[i]] = (x + 70, y + 25)

        for i in range(len(enemy_units)):
            x = cx + 50 + i * 160
            y = cy + i * 80
            positions[enemy_units[i]] = (x + 70, y + 25)

        return positions

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Восстановить состояние юнитов из snapshot'а."""
        for name, units in self.teams.items():
            if name not in snapshot:
                continue
            for i, data in enumerate(snapshot[name]):
                if i >= len(units):
                    break
                u = units[i]
                u.hp = data["hp"]
                u.max_hp = data["max_hp"]
                u.alive = data["alive"]
                u.attack_timer = data["attack_timer"]
                u.active_ability = data.get("active_ability")
                u.ability_cooldown = data.get("ability_cooldown", 0)
                u.base_damage = data.get("base_damage", u.base_damage)
                u.base_attack_speed = data.get("base_attack_speed", u.base_attack_speed)
                u.unit_class = data.get("unit_class", u.unit_class)
                u.statuses = [dict(s) for s in data.get("statuses", [])]
                u.closing = data.get("closing", 0)
                u._refresh_stats()

    def get_total_ticks(self) -> int:
        """Общее количество тиков в истории."""
        return len(self._tick_history)

    def get_attack_events(self, up_to_tick: int = None) -> list[dict]:
        """События атак для визуальных эффектов."""
        if up_to_tick is not None:
            return [e for e in self._attack_events if e["tick"] <= up_to_tick]
        return list(self._attack_events)

    def get_ability_events(self, up_to_tick: int = None) -> list[dict]:
        """События способностей для визуальных эффектов."""
        if up_to_tick is not None:
            return [e for e in self._ability_events if e["tick"] <= up_to_tick]
        return list(self._ability_events)

    def print_state(self) -> str:
        """Текущее состояние поля (для консоли)."""
        lines = [f"=== Тик {self.tick_count} ==="]
        for name, units in self.teams.items():
            alive_units = [u for u in units if u.alive]
            dead_units = [u for u in units if not u.alive]
            hp_str = ", ".join(f"{u.name}: {u.hp:.0f}/{u.max_hp}" for u in alive_units)
            if dead_units:
                dead_str = ", ".join(f"☠{u.name}" for u in dead_units)
                lines.append(f"[{name}] {hp_str} | {dead_str}")
            else:
                lines.append(f"[{name}] {hp_str}")
        return "\n".join(lines)
