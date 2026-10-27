"""Боевой движок: тактическое поле 5×5 с каждой стороны, детерминированный тик.

Поле: 5 строк × 10 колонок. Первая команда (игрок) Controls колонки 0-4
(левая половина), вторая команда (враг) — колонки 5-9 (правая половина).

Юниты имеют координаты (row, col) на поле.

Логика движения и атаки:
- Мили (range_ == 1) идут вплотную к ближайшему живому врагу (дистанция 1)
  и бьют его, когда становятся соседними клетками.
- Дальнобойные (range_ >= 2, например маг 2, лучник 3) держат дистанцию
  range_: если враг слишком близко — отходят на одну клетку, если далеко —
  приближаются на одну клетку, если в радиусе range_ — стоят на месте и бьют.
- Каждый тик юнит либо делает шаг (движение), либо атакует (по таймеру),
  либо и то и другое (сначала шаг, потом攻击, если Timer сработал).
"""

import math
import random

# ── Все типы активок, которые умеет движок ────────────────────────────────
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
KIND_DAMAGE_BONUS = "damage_bonus"
KIND_SPEED_PCT = "speed_pct"
KIND_DAMAGE_REDUCTION = "damage_reduction"
KIND_SLOW_PCT = "slow_pct"
KIND_NEXT_ATTACK = "next_attack_bonus"

# Лимиты радиуса урона по области
MAX_AOE_TARGETS = {1: 1, 2: 3}
MAX_AOE_TARGETS_DEFAULT = 5

# Потолок суммарного снижения урона
MAX_DAMAGE_REDUCTION_PCT = 90

# Совместимость со старой логикой движения (теперь не используется напрямую)
MOVE_TICKS_PER_COLUMN = 30

# Лимит тиков одного боя
MAX_BATTLE_TICKS = 900

# ── Размеры тактического поля ──────────────────────────────────────────────
BATTLE_ROWS = 5
BATTLE_COLS_PER_TEAM = 5
TOTAL_COLS = BATTLE_COLS_PER_TEAM * 2  # 10


class Unit:
    """Юнит на тактическом поле боя."""

    def __init__(self, name: str, hp: int, damage: float, attack_speed: float,
                 range_: int, team: str, unit_id: int,
                 unit_class: str = "", crit_chance: float = 0.0,
                 crit_multiplier: float = 1.75, row: int | None = None,
                 col: int | None = None):
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

        # Позиция на тактическом поле (row, col) своей половины.
        # None = авторазмещение при добавлении команды.
        self.row = row
        self.col = col
        self.start_row = row
        self.start_col = col

        # Сближение (legacy-счётчик, используется distance_to для совместимости
        # со старыми тестами; в новой логике движение происходит каждый тик
        # через _move_towards / _move_away)
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
        self.row = self.start_row
        self.col = self.start_col
        self.closing = 0
        self.attack_timer = self._ticks_per_attack()
        self.ability_cooldown = (self.active_ability or {}).get("cooldown", 0)
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
        """Обработать один тик юнитом (атака). Возвращает события атак.

        Движение теперь обрабатывается в BattleSimulator.run(), здесь только
        проверка таймера атаки и генерация события атаки.
        """
        events = []
        if not self.alive:
            return events

        if self.attack_timer <= 0:
            bonus, radius = self.consume_next_attack()
            damage = self.damage + bonus
            crit = False
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
            "row": self.row,
            "col": self.col,
            "closing": 0,
        }


class BattleSimulator:
    """Симулятор боя на тактическом поле 5×5 с каждой стороны."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
        self._next_id = 0
        self.teams: dict[str, list[Unit]] = {}
        self._team_index: dict[int, int] = {}   # unit_id -> индекс внутри команды
        self._team_side: dict[str, str] = {}    # team_name -> "left" / "right"
        self._team_side_order = 0               # 0 = left, 1 = right
        self.log: list[dict] = []
        self.tick_count = 0
        self._tick_history: list[dict] = []
        self._attack_events: list[dict] = []
        self._ability_events: list[dict] = []

    # ── Формирование команд ────────────────────────────────────────────────

    def _assign_side(self, team_name: str) -> str:
        """Назначить стороне поля: первая команда — левая, вторая — правая."""
        if team_name in self._team_side:
            return self._team_side[team_name]
        side = "left" if self._team_side_order == 0 else "right"
        self._team_side[team_name] = side
        self._team_side_order += 1
        return side

    def _team_col_range(self, team_name: str) -> tuple[int, int]:
        """Диапазон колонок для команды на поле."""
        side = self._team_side.get(team_name, "left")
        if side == "left":
            return 0, BATTLE_COLS_PER_TEAM - 1
        return BATTLE_COLS_PER_TEAM, TOTAL_COLS - 1

    def add_team(self, name: str, units_data: list[dict]) -> None:
        """Добавить юнитов к команде (повторный вызов дополняет, а не заменяет).

        Поддерживаемые поля units_data:
            - item_bonuses: {"hp_bonus": 200, "damage_bonus": 25, ...}
            - active:       dict активной способности из units.json
            - row / col:    стартовая позиция на тактическом поле (опционально)
            - unit_class:   класс юнита (warrior/mage/archer) — для aura
            - crit_chance / crit_multiplier: настройка критов
        """
        self._assign_side(name)
        team_units = self.teams.setdefault(name, [])

        for ud in units_data:
            bonuses = ud.get("item_bonuses", {})
            hp = int(ud["hp"]) + bonuses.get("hp_bonus", 0)
            damage = float(ud["damage"]) + bonuses.get("damage_bonus", 0)
            attack_speed = float(ud["attack_speed"])

            speed_pct = bonuses.get("speed_bonus_pct", 0)
            if speed_pct:
                attack_speed *= (1 + speed_pct / 100)

            row = ud.get("row")
            col = ud.get("col")

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
                row=row,
                col=col,
            )

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

        # Авторасстановка по сетке 5×5 своей половины для юнитов без row/col
        self._auto_place_team(name)

        # Пересчитываем индексы внутри команды
        for team_name, units in self.teams.items():
            for idx, u in enumerate(units):
                self._team_index[u.unit_id] = idx

    def _auto_place_team(self, team_name: str) -> None:
        """Расставить юнитов команды по сетке 5×5 своей половины, начиная от
        границы с врагом (передние юниты у краёв: левый в кол 4, правый — в кол 5).

        Свободные клетки генерируются в порядке: от границы к центру,
        сверху вниз.
        """
        c0, c1 = self._team_col_range(team_name)
        units = self.teams[team_name]
        side = self._team_side.get(team_name, "left")

        # Порядок колонок: от границы к центру команды
        if side == "left":
            col_order = list(range(c1, c0 - 1, -1))   # 4, 3, 2, 1, 0
        else:
            col_order = list(range(c0, c1 + 1))       # 5, 6, 7, 8, 9

        free = [(r, c) for r in range(BATTLE_ROWS) for c in col_order]
        idx = 0
        for u in units:
            if u.row is None or u.col is None:
                if idx < len(free):
                    u.row, u.col = free[idx]
                    u.start_row, u.start_col = u.row, u.col
                    idx += 1
            else:
                u.row = max(0, min(BATTLE_ROWS - 1, u.row))
                u.col = max(c0, min(c1, u.col))
                u.start_row, u.start_col = u.row, u.col
                idx += 1

    # ── Дистанции и цели ───────────────────────────────────────────────────

    def _find_unit(self, unit_id: int) -> Unit | None:
        for team in self.teams.values():
            for u in team:
                if u.unit_id == unit_id:
                    return u
        return None

    def distance(self, a: Unit, b: Unit) -> int:
        """Манхэттенская дистанция между двумя юнитами на поле (минимум 1)."""
        return max(1, abs(a.row - b.row) + abs(a.col - b.col))

    def distance_to(self, attacker: Unit, target: Unit) -> int:
        """Манхэттенская дистанция между двумя юнитами (минимум 1),
        с учётом сближения (closing) для обратной совместимости."""
        base_row = attacker.row if attacker.row is not None else 0
        base_col = attacker.col if attacker.col is not None else 0
        target_row = target.row if target.row is not None else 0
        target_col = target.col if target.col is not None else 0
        base = max(1, abs(base_row - target_row) + abs(base_col - target_col))
        if attacker.closing:
            base = max(1, base - attacker.closing // MOVE_TICKS_PER_COLUMN)
        return base

    def _cell_occupied_by_ally(self, unit: Unit, row: int, col: int) -> bool:
        """Проверка, занята ли клетка живым союзником."""
        if not (0 <= row < BATTLE_ROWS and 0 <= col < TOTAL_COLS):
            return True  # вне поля — считаем занятым
        for u in self.teams.get(unit.team, []):
            if u is not unit and u.alive and u.row == row and u.col == col:
                return True
        return False

    def _move_towards(self, unit: Unit, target_row: int, target_col: int) -> None:
        """Сдвинуть юнита на одну клетку ближе к целевой позиции."""
        # Сначала по колонке (к врагу), потом по строке
        dc = 0
        if target_col < unit.col:
            dc = -1
        elif target_col > unit.col:
            dc = 1

        dr = 0
        if target_row < unit.row:
            dr = -1
        elif target_row > unit.row:
            dr = 1

        candidates = []
        if dc != 0:
            candidates.append((unit.row, unit.col + dc))
        if dr != 0:
            candidates.append((unit.row + dr, unit.col))
        if dc != 0 and dr != 0:
            candidates.append((unit.row + dr, unit.col + dc))

        for nr, nc in candidates:
            nr = max(0, min(BATTLE_ROWS - 1, nr))
            nc = max(0, min(TOTAL_COLS - 1, nc))
            if (nr, nc) == (unit.row, unit.col):
                continue
            if not self._cell_occupied_by_ally(unit, nr, nc):
                unit.row, unit.col = nr, nc
                return

    def _move_away(self, unit: Unit, target: Unit) -> None:
        """Сдвинуть юнита на одну клетку дальше от цели (удержание дистанции)."""
        # Направление от цели
        dr = 0
        if target.row < unit.row:
            dr = 1    # цель выше — уходим вниз
        elif target.row > unit.row:
            dr = -1   # цель ниже — уходим вверх

        dc = 0
        if target.col > unit.col:
            dc = -1   # цель справа — уходим влево
        elif target.col < unit.col:
            dc = 1    # цель слева — уходим вправо

        candidates = []
        if dc != 0:
            candidates.append((unit.row, unit.col + dc))
        if dr != 0:
            candidates.append((unit.row + dr, unit.col))
        if dc != 0 and dr != 0:
            candidates.append((unit.row + dr, unit.col + dc))

        for nr, nc in candidates:
            nr = max(0, min(BATTLE_ROWS - 1, nr))
            nc = max(0, min(TOTAL_COLS - 1, nc))
            if (nr, nc) == (unit.row, unit.col):
                continue
            if not self._cell_occupied_by_ally(unit, nr, nc):
                unit.row, unit.col = nr, nc
                return

    def _has_target_in_range(self, unit: Unit) -> bool:
        """Есть ли живой враг, до которого юнит сейчас достаёт (дистанция <= range_)."""
        enemies = self._alive_enemies(unit)
        if not enemies:
            return False
        nearest = min(enemies, key=lambda e: self.distance(unit, e))
        return unit.range_ >= self.distance(unit, nearest)

    def _alive_enemies(self, unit: Unit) -> list[Unit]:
        return [u for t, lst in self.teams.items()
                if t != unit.team for u in lst if u.alive]

    def _enemies_in_radius(self, unit: Unit, radius: int) -> list[Unit]:
        """Цели урона по области: враги в радиусе `radius` от кастера.

        Достаём только если до ближайшего врага есть дистанция (range_).
        Возвращаем до `cap` ближайших.
        """
        enemies = sorted(self._alive_enemies(unit),
                         key=lambda e: self.distance(unit, e))
        if not enemies:
            return []
        if unit.range_ < self.distance(unit, enemies[0]):
            return []
        cap = MAX_AOE_TARGETS.get(radius, MAX_AOE_TARGETS_DEFAULT)
        return [e for e in enemies if self.distance(unit, e) <= radius][:cap]

    def _find_targets(self, event: dict) -> list[Unit]:
        """Найти цели для атаки: ближайший живой враг в радиусе range_."""
        attacker = self._find_unit(event["attacker_id"])
        if not attacker or not attacker.alive:
            return []

        enemies = self._alive_enemies(attacker)
        if not enemies:
            return []

        radius = event.get("aoe_radius", 0)
        if radius and radius > 0:
            return self._enemies_in_radius(attacker, radius)

        nearest = min(enemies, key=lambda e: self.distance(attacker, e))
        if attacker.range_ < self.distance(attacker, nearest):
            return []          # не достаёт — цель не выбрана
        return [nearest]

    # ── Урон от атак ───────────────────────────────────────────────────────

    def _apply_attack(self, event: dict) -> list[dict]:
        """Применить событие атаки: найти цели и нанести урон."""
        damage_events = []
        targets = self._find_targets(event)

        if not targets:
            return damage_events

        self._attack_events.append({
            "tick": self.tick_count,
            "attacker_id": event["attacker_id"],
            "attacker_team": event["attacker_team"],
            "damage": event["damage"],
            "targets": [t.unit_id for t in targets],
            "is_critical": event.get("is_critical", False),
        })

        for target in targets:
            variance = 0.9 + self.rng.random() * 0.2          # [0.9, 1.1]
            rolled = event["damage"] * variance
            died = target.take_damage(rolled)

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
                for target in self._enemies_in_radius(unit, radius):
                    target.add_status(
                        KIND_SLOW_PCT,
                        eff.get("slow_duration", 10),
                        pct=eff.get("slow_pct", 30),
                    )

            elif atype == "aoe_damage_buff":
                unit.add_status(
                    KIND_SPEED_PCT,
                    eff.get("speed_bonus_duration", 20),
                    pct=eff.get("speed_bonus_pct", 20),
                )

        elif atype == "single_target_critical":
            events += self._apply_single_target_critical(
                unit, eff.get("damage", 0))

        elif atype == "buff_allies":
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
            unit.add_status(
                KIND_NEXT_ATTACK,
                eff.get("duration", 60),
                amount=eff.get("bonus_damage", 0),
                radius=eff.get("radius", 1),
            )
            events.append(self._record_ability(unit, [unit.unit_id]))

        elif atype == "aura":
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
        alive = {}
        for name, units in self.teams.items():
            alive[name] = [u for u in units if u.alive]

        dead_teams = [n for n, u in alive.items() if len(u) == 0]
        live_teams = [n for n, u in alive.items() if len(u) > 0]

        if len(dead_teams) == 1 and len(live_teams) == 1:
            return self._result(live_teams[0], "annihilation")

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

    def run(self, max_ticks: int = MAX_BATTLE_TICKS) -> dict:
        """Запустить бой. max_ticks — лимит (по умолчанию MAX_BATTLE_TICKS)."""
        self.log = []
        self.tick_count = 0
        self._tick_history = []
        self._attack_events = []
        self._ability_events = []
        self.rng = random.Random(self.seed)

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

                # 3. Движение к цели / удержание дистанции
                enemies = self._alive_enemies(unit)
                if enemies:
                    nearest = min(enemies, key=lambda e: self.distance(unit, e))
                    dist = self.distance(unit, nearest)
                    if unit.range_ <= 1:
                        # Мили:approaches up to distance 1
                        if dist > 1:
                            self._move_towards(unit, nearest.row, nearest.col)
                    else:
                        # Дальние: держать дистанцию range_
                        if dist < unit.range_:
                            self._move_away(unit, nearest)
                        elif dist > unit.range_:
                            self._move_towards(unit, nearest.row, nearest.col)

                # 4. Атака (по таймеру)
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
        return {name: [u.snapshot() for u in units]
                for name, units in self.teams.items()}

    def get_unit_positions(self, player_units, enemy_units):
        """Позиции на тактическом поле 5×5: игрок слева (колонки 0-4),
        враг справа (колонки 5-9)."""
        cell_w = 100
        cell_h = 70
        offset_x = 60
        offset_y = 100
        enemy_offset_x = 600  # сдвиг правой половины

        positions = {}

        for u in player_units:
            x = offset_x + u.col * cell_w
            y = offset_y + u.row * cell_h
            positions[u] = (x + cell_w // 2, y + cell_h // 2)

        for u in enemy_units:
            x = offset_x + enemy_offset_x + u.col * cell_w
            y = offset_y + u.row * cell_h
            positions[u] = (x + cell_w // 2, y + cell_h // 2)

        return positions

    def restore_from_snapshot(self, snapshot: dict) -> None:
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
                u.row = data.get("row", u.row)
                u.col = data.get("col", u.col)
                u.closing = data.get("closing", 0)
                u._refresh_stats()

    def get_total_ticks(self) -> int:
        return len(self._tick_history)

    def get_attack_events(self, up_to_tick: int = None) -> list[dict]:
        if up_to_tick is not None:
            return [e for e in self._attack_events if e["tick"] <= up_to_tick]
        return list(self._attack_events)

    def get_ability_events(self, up_to_tick: int = None) -> list[dict]:
        if up_to_tick is not None:
            return [e for e in self._ability_events if e["tick"] <= up_to_tick]
        return list(self._ability_events)

    def print_state(self) -> str:
        lines = [f"=== Тик {self.tick_count} ==="]
        for name, units in self.teams.items():
            alive_units = [u for u in units if u.alive]
            dead_units = [u for u in units if not u.alive]
            hp_str = ", ".join(
                f"{u.name}({u.row},{u.col}): {u.hp:.0f}/{u.max_hp}"
                for u in alive_units)
            if dead_units:
                dead_str = ", ".join(f"☠{u.name}" for u in dead_units)
                lines.append(f"[{name}] {hp_str} | {dead_str}")
            else:
                lines.append(f"[{name}] {hp_str}")
        return "\n".join(lines)
