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
    "heal",
    "assassin_teleport",
    "shield",
    "dot",
    "stun",
    "taunt",
    "heal_over_time",
    "execute",
)

# Виды временных эффектов на юните
KIND_DAMAGE_BONUS = "damage_bonus"          # плоская прибавка к урону
KIND_DAMAGE_BONUS_PCT = "damage_bonus_pct"  # процентная прибавка к урону
KIND_DAMAGE_DEALT_PCT = "damage_dealt_pct"  # снижение ИСХОДЯЩЕГО урона (дебафф)
KIND_SPEED_PCT = "speed_pct"
KIND_DAMAGE_REDUCTION = "damage_reduction"  # снижение ВХОДЯЩЕГО урона (щит)
KIND_SLOW_PCT = "slow_pct"
KIND_NEXT_ATTACK = "next_attack_bonus"
KIND_CRIT_CHANCE = "crit_chance"

# Временные эффекты новых типов способностей (§2)
KIND_SHIELD = "shield"              # поглощающий щит (amount = запас поглощения)
KIND_DOT = "dot"                    # урон по времени (damage_per_tick)
KIND_STUN = "stun"                  # оглушение (пропуск хода)
KIND_TAUNT = "taunt"                # провокация (source_id = кастер)
KIND_HEAL_OVER_TIME = "heal_over_time"  # лечение со временем (heal_per_tick)

# Лимиты радиуса урона по области
MAX_AOE_TARGETS = {1: 1, 2: 3}
MAX_AOE_TARGETS_DEFAULT = 5

# Потолок суммарного снижения урона
MAX_DAMAGE_REDUCTION_PCT = 90

# Совместимость со старой логикой движения (теперь не используется напрямую)
MOVE_TICKS_PER_COLUMN = 30

# Лимит тиков одного боя
MAX_BATTLE_TICKS = 900

# Канонический таймскейл боя: 60 тиков = 1 секунда.
# Автоатака уже использует этот таймскейл (_ticks_per_attack = ceil(60/as)).
# Способности (cooldown/duration) должны жить в тех же тиках.
TICKS_PER_SECOND = 60

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
                 col: int | None = None, race: str = ""):
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
        self.race = race
        self.alive = True

        # Криты (данные из JSON, по умолчанию выключены)
        self.crit_chance = float(crit_chance)
        self.crit_multiplier = float(crit_multiplier)
        self.base_crit_chance = float(crit_chance)
        self.crit_damage_bonus_pct = 0.0  # бонус к множителю крита (расовый demon)

        # Регенерация HP в тик (расовый бонус нежити, hp_regen_pct)
        self.hp_regen_pct = 0.0

        # Базовое снижение урона (расовые синергии нежити 2/4)
        self._base_damage_reduction_pct = 0.0

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

        # Расовая идентичность: уклонение (эльфы) — шанс увернуться от автоатаки
        self.evasion_pct = 0.0
        # Расовая идентичность: вампиризм (демоны) — хил от урона автоатаки
        self.lifesteal_pct = 0.0
        # Расовая идентичность: берсерк (орки) — конфиг {hp_thresholds, damage_pct, speed_pct}
        self.berserker = None
        # Расовая идентичность: восстание (нежить) — встать один раз на % HP
        self.revive = None
        self.revives_left = 0
        self.just_revived = False

        # Ассасин: ожидание перед телепортом, флаг телепорта, цель —最弱 враг
        self.assassin_wait = 0          # тиков ожидания перед телепортом
        self.assassin_teleported = False  # уже телепортировался
        self.assassin_target_weakest = False  # бить самого слабого, а не ближнего
        self.assassin_payload = None    # payload способности (урон/стан/дот при прибытии)

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
        """Пересчитать damage/attack_speed/crit_chance из базы + активных эффектов."""
        damage = self.base_damage
        speed = self.base_attack_speed
        crit_chance = self.base_crit_chance
        for st in self.statuses:
            kind = st["kind"]
            if kind == KIND_DAMAGE_BONUS:
                damage += st.get("amount", 0)
            elif kind == KIND_DAMAGE_BONUS_PCT:
                damage *= (1 + st.get("pct", 0) / 100)
            elif kind == KIND_DAMAGE_DEALT_PCT:
                damage *= (1 - st.get("pct", 0) / 100)
            elif kind == KIND_SPEED_PCT:
                speed *= (1 + st.get("pct", 0) / 100)
            elif kind == KIND_SLOW_PCT:
                speed *= (1 - st.get("pct", 0) / 100)
            elif kind == KIND_CRIT_CHANCE:
                crit_chance += st.get("amount", 0)
        # Берсерк (орки): динамический бонус урона и скорости от текущего HP%
        # Находим наименьший порог ≥ текущий HP% (сильнейший применимый тир).
        # Пороги и бонусы выровнены по индексу: thresholds[i] → damage_pcts[i]/speed_pcts[i].
        if self.berserker:
            thresholds = self.berserker.get("hp_thresholds", [])
            damage_pcts = self.berserker.get("damage_pct", [])
            speed_pcts = self.berserker.get("speed_pct", [])
            if thresholds and damage_pcts and speed_pcts:
                hp_pct = self.hp / max(self.max_hp, 1) * 100.0
                best_idx = None
                best_th = None
                for i, th in enumerate(thresholds):
                    if hp_pct <= th and (best_th is None or th < best_th):
                        best_th = th
                        best_idx = i
                if best_idx is not None:
                    dmg_pct = damage_pcts[min(best_idx, len(damage_pcts) - 1)]
                    spd_pct = speed_pcts[min(best_idx, len(speed_pcts) - 1)]
                    damage *= (1 + dmg_pct / 100.0)
                    speed *= (1 + spd_pct / 100.0)
        self.damage = max(0.0, damage)
        self.attack_speed = max(0.05, speed)
        self.crit_chance = crit_chance

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
        total = self._base_damage_reduction_pct
        total += sum(s.get("pct", 0) for s in self.statuses
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
        # Ассасин: сбрасываем ожидание и телепорт, цель на самого слабого сохраняем
        eff = (self.active_ability or {}).get("effect", {})
        self.assassin_wait = eff.get("wait_ticks", 0)
        self.assassin_teleported = False
        self.assassin_target_weakest = eff.get("target_weakest", False)
        self.assassin_payload = dict(eff)  # payload прибытия доступен уже после сброса
        # Восстание (нежить): сбрасываем счётчик воскрешений на начало боя
        if self.revive:
            self.revives_left = self.revive.get("max_revives", 1)
        self.just_revived = False
        self._refresh_stats()

    # ── Урон ───────────────────────────────────────────────────────────────

    def take_damage(self, amount: float) -> bool:
        """Нанести урон (с учётом снижения урона и поглощения щитом).
        True если юнит умер."""
        effective = max(0.0, amount * (1 - self.damage_reduction_pct() / 100))
        remaining = self._absorb_shield(effective)
        self.hp -= remaining
        self.last_damage = remaining
        if self.hp <= 0:
            # Восстание (нежить): первый смертельный удар — встать на % HP
            if self.revive and self.revives_left > 0:
                self.hp = int(self.max_hp * self.revive["hp_pct"] / 100.0)
                self.alive = True
                self.revives_left -= 1
                self.just_revived = True
                self._refresh_stats()
                return False  # не смерть — встал снова
            self.hp = 0
            self.alive = False
            return True
        self._refresh_stats()  # берсерк реагирует на просадку HP mid-fight
        return False

    def _absorb_shield(self, amount: float) -> float:
        """Погасить урон активными щитами (KIND_SHIELD), вернуть остаток к HP."""
        remaining = amount
        for s in self.statuses:
            if s["kind"] == KIND_SHIELD:
                absorb = s.get("amount", 0)
                if absorb <= 0:
                    continue
                take = min(remaining, absorb)
                s["amount"] = absorb - take
                remaining -= take
                if remaining <= 0:
                    break
        return remaining

    def is_stunned(self) -> bool:
        """Юнит оглушён — пропускает движение, атаку и способность."""
        return any(s["kind"] == KIND_STUN for s in self.statuses)

    def taunt_source_id(self) -> int | None:
        """ID кастера, который проверовал этого юнита (KIND_TAUNT), или None."""
        for s in self.statuses:
            if s["kind"] == KIND_TAUNT:
                return s.get("source_id")
        return None

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
            "base_crit_chance": self.base_crit_chance,
            "unit_class": self.unit_class,
            "statuses": [dict(s) for s in self.statuses],
            "row": self.row,
            "col": self.col,
            "closing": 0,
            "assassin_wait": self.assassin_wait,
            "assassin_teleported": self.assassin_teleported,
            "assassin_target_weakest": self.assassin_target_weakest,
        }


class BattleSimulator:
    """Симулятор боя на тактическом поле 5×5 с каждой стороны."""

    def __init__(self, seed: int = 42, race_data: dict | None = None, race_synergy_data: dict | None = None):
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
        self.race_data = race_data or {}       # определения рас из data/units.json ['races']
        self.race_synergy_data = race_synergy_data or {}  # расовые синергии ['race_synergies']

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

        Ожидает, что базовые статы, звёзды, предметы, расовые бонусы, синергии
        и пассивки уже применены через build_combat_team(). Здесь только:
        создаём Unit, валидируем тип активной способности, расставляем по полю.

        item_bonuses применяется только для «сырых» юнитов, переданных напрямую
        (не через build_combat_team). Собранная команда item_bonuses не содержит,
        поэтому двойного учёта нет.

        Поддерживаемые поля units_data:
            - item_bonuses: {"hp_bonus": 200, "damage_bonus": 25, ...}
            - active:       dict активной способности из units.json
            - row / col:    стартовая позиция на тактическом поле (опционально)
            - unit_class:   класс юнита (warrior/mage/archer) — для aura
            - crit_chance / crit_multiplier: настройка критов
            - race / hp_regen_pct / mana_per_kill: расовые поля
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

            # Раса и расовые бонусы уже применены в build_combat_team()
            race = ud.get("race", "human")
            crit_chance = float(ud.get("crit_chance", 0.0))
            crit_multiplier = float(ud.get("crit_multiplier", 1.75))
            hp_regen_pct = ud.get("hp_regen_pct", 0)
            mana_per_kill = ud.get("mana_per_kill", 0)

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
                crit_chance=crit_chance,
                crit_multiplier=crit_multiplier,
                row=row,
                col=col,
                race=race,
            )
            u.hp_regen_pct = hp_regen_pct
            u.mana_per_kill = mana_per_kill
            u._base_damage_reduction_pct = float(ud.get("damage_reduction_pct", 0))
            # Новые расовые механики (race_synergies → apply_race_bonuses → unit_data → Unit)
            u.evasion_pct = float(ud.get("evasion_pct", 0))
            u.lifesteal_pct = float(ud.get("lifesteal_pct", 0))
            u.berserker = ud.get("berserker")
            u.revive = ud.get("revive")
            u.revives_left = u.revive.get("max_revives", 1) if u.revive else 0
            u.just_revived = False

            ability = ud.get("active")
            if ability:
                atype = ability.get("type")
                if atype not in SUPPORTED_ABILITY_TYPES:
                    raise ValueError(
                        f"Юнит '{u.name}': движок не умеет тип способности "
                        f"'{atype}'. Поддерживаются: {', '.join(SUPPORTED_ABILITY_TYPES)}"
                    )
                u.active_ability = dict(ability)
                # Нормализация времени способности: секунды (данные) -> тики (движок).
                cd_sec = ability.get("cooldown", 1.0)
                u.active_ability["cooldown"] = max(1, round(cd_sec * TICKS_PER_SECOND))
                eff = u.active_ability.get("effect")
                if eff and "duration" in eff:
                    eff = dict(eff)
                    eff["duration"] = max(1, round(eff["duration"] * TICKS_PER_SECOND))
                    u.active_ability["effect"] = eff
                # mana_per_kill: секунды/килл -> тики/килл
                u.mana_per_kill = int(ud.get("mana_per_kill", 0) * TICKS_PER_SECOND)
                u.ability_cooldown = u.active_ability["cooldown"]

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

        Ближние бойцы (range=1) ставятся на переднюю линию, дальние — сзади.
        Клетки заполняются по строкам (а не колонкой за колонкой), чтобы между
        союзниками оставались пробелы для движения — иначе задние юниты блокируют
        путь передовой, и чемпион застревает за своими же бойцами.
        """
        c0, c1 = self._team_col_range(team_name)
        units = self.teams[team_name]
        side = self._team_side.get(team_name, "left")

        # Порядок колонок: от границы к центру команды
        if side == "left":
            col_order = list(range(c1, c0 - 1, -1))   # 4, 3, 2, 1, 0
        else:
            col_order = list(range(c0, c1 + 1))       # 5, 6, 7, 8, 9

        # Сначала ближние (range=1) — на переднюю линию, потом дальние — сзади
        auto_units = [u for u in units if u.row is None or u.col is None]
        ordered = sorted(auto_units, key=lambda u: u.range_)

        # Занятые вручную клетки исключаем из свободных заранее
        free = []
        for r in range(BATTLE_ROWS):
            for c in col_order:
                free.append((r, c))
        for u in units:
            if u.row is not None and u.col is not None:
                u.row = max(0, min(BATTLE_ROWS - 1, u.row))
                u.col = max(c0, min(c1, u.col))
                u.start_row, u.start_col = u.row, u.col
                try:
                    free.remove((u.row, u.col))
                except ValueError:
                    pass

        # Расставляем по строкам: для каждой строки берём по одной клетке в колонке,
        # чтобы между союзниками оставались пробелы для движения.
        for u in ordered:
            if free:
                u.row, u.col = free.pop(0)
                u.start_row, u.start_col = u.row, u.col

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

    def _cell_occupied_by_enemy(self, unit: Unit, row: int, col: int) -> bool:
        """Проверка, занята ли клетка живым врагом."""
        if not (0 <= row < BATTLE_ROWS and 0 <= col < TOTAL_COLS):
            return False
        for team_name, team_units in self.teams.items():
            if team_name == unit.team:
                continue
            for eu in team_units:
                if eu is not unit and eu.alive and eu.row == row and eu.col == col:
                    return True
        return False

    def _cell_occupied(self, unit: Unit, row: int, col: int) -> bool:
        """Проверка, занята ли клетка любым живым юнитом (союзником или врагом)."""
        return self._cell_occupied_by_ally(unit, row, col) or self._cell_occupied_by_enemy(unit, row, col)

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

        # Если основные направления заняты союзниками — пробуем обойти:
        # сначала диагонали и боковые смещения, потом любое свободное место
        fallback = []
        if dc != 0:
            # Движемся по колонке к врагу — пробуем сдвинуться вверх/вниз на той же колонке
            fallback.append((unit.row - 1, unit.col + dc))
            fallback.append((unit.row + 1, unit.col + dc))
            # Или просто вверх/вниз по текущей колонке
            fallback.append((unit.row - 1, unit.col))
            fallback.append((unit.row + 1, unit.col))
        if dr != 0:
            # Движемся по строке к врагу — пробуем сдвинуться влево/вправо на той же строке
            fallback.append((unit.row + dr, unit.col - 1))
            fallback.append((unit.row + dr, unit.col + 1))
            # Или просто влево/вправо по текущей строке
            fallback.append((unit.row, unit.col - 1))
            fallback.append((unit.row, unit.col + 1))

        # Добавляем все fallback-варианты к основным candidatos
        candidates.extend(fallback)

        # Если всё ещё не нашли — любое свободное соседнее место
        if not any(
            not self._cell_occupied(unit, max(0, min(BATTLE_ROWS - 1, nr)), max(0, min(TOTAL_COLS - 1, nc)))
            for nr, nc in candidates
            if (nr, nc) != (unit.row, unit.col)
        ):
            for dr_fb in (-1, 0, 1):
                for dc_fb in (-1, 0, 1):
                    if dr_fb == 0 and dc_fb == 0:
                        continue
                    candidates.append((unit.row + dr_fb, unit.col + dc_fb))

        for nr, nc in candidates:
            nr = max(0, min(BATTLE_ROWS - 1, nr))
            nc = max(0, min(TOTAL_COLS - 1, nc))
            if (nr, nc) == (unit.row, unit.col):
                continue
            if not self._cell_occupied(unit, nr, nc):
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

        # Fallback: любое свободное соседнее место
        if not candidates:
            for dr_fb in (-1, 0, 1):
                for dc_fb in (-1, 0, 1):
                    if dr_fb == 0 and dc_fb == 0:
                        continue
                    candidates.append((unit.row + dr_fb, unit.col + dc_fb))

        for nr, nc in candidates:
            nr = max(0, min(BATTLE_ROWS - 1, nr))
            nc = max(0, min(TOTAL_COLS - 1, nc))
            if (nr, nc) == (unit.row, unit.col):
                continue
            if not self._cell_occupied_by_ally(unit, nr, nc):
                unit.row, unit.col = nr, nc
                return

    def _teleport_assassin(self, unit: Unit) -> None:
        """Телепортирует убийцу в задние ряды противника.

        Враг находится с противоположной стороны поля. Задний ряд врага —
        крайняя колонка его стороны (справа для левой команды, слева для правой).
        Пытаемся встать в тот же ряд, что и самый слабый живой враг.
        """
        c0, c1 = self._team_col_range(unit.team)
        # Определяем заднюю колонку врага (противоположная сторона)
        if c0 == 0:
            # Наша команда слева (колонки 0-4), враг справа (5-9), задний ряд = 9
            back_col = TOTAL_COLS - 1
        else:
            # Наша команда справа (колонки 5-9), враг слева (0-4), задний ряд = 0
            back_col = 0

        # Пытаемся встать в ряд самого слабого живого врага
        target_row = unit.row if unit.row is not None else BATTLE_ROWS // 2
        enemies = self._alive_enemies(unit)
        if enemies:
            weakest = min(enemies, key=lambda e: e.hp)
            target_row = weakest.row

        # Ищем свободную клетку в заднем ряду врага (сначала предпочитаемый ряд)
        rows_to_try = [target_row] + [r for r in range(BATTLE_ROWS) if r != target_row]
        for r in rows_to_try:
            if not self._cell_occupied_by_ally(unit, r, back_col):
                unit.row, unit.col = r, back_col
                unit.start_row, unit.start_col = r, back_col
                self._apply_assassin_payload(unit)
                return
        # Если все клетки заднего ряда заняты союзниками (маловероятно), ищем любую свободную
        for r in range(BATTLE_ROWS):
            for c in range(c0, c1 + 1):
                if not self._cell_occupied_by_ally(unit, r, c):
                    unit.row, unit.col = r, c
                    unit.start_row, unit.start_col = r, c
                    self._apply_assassin_payload(unit)
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

    def _taunt_target(self, unit: Unit) -> Unit | None:
        """Если юнит проверован (KIND_TAUNT) и кастер жив — вернуть кастера.

        Проверованный юнит должен атаковать/идти к источнику провокации."""
        source_id = unit.taunt_source_id()
        if source_id is None:
            return None
        source = self._find_unit(source_id)
        if source is None or not source.alive or source.team == unit.team:
            return None
        return source

    def _enemies_in_radius(self, unit: Unit, radius: int) -> list[Unit]:
        """Цели урона по области: враги в радиусе `radius` около ближайшей цели.

        Основная цель — ближайший живой враг в радиусе атаки (range_).
        Все враги в радиусе `radius` вокруг этой цели получают урон.
        Возвращаем до `cap` ближайших к основной цели.
        """
        enemies = self._alive_enemies(unit)
        if not enemies:
            return []
        nearest = min(enemies, key=lambda e: self.distance(unit, e))
        if unit.range_ < self.distance(unit, nearest):
            return []  # кастер не достаёт до ближайшего врага
        cap = MAX_AOE_TARGETS.get(radius, MAX_AOE_TARGETS_DEFAULT)
        in_radius = sorted(
            [e for e in enemies if self.distance(nearest, e) <= radius],
            key=lambda e: self.distance(nearest, e),
        )
        return in_radius[:cap]

    def _find_targets(self, event: dict) -> list[Unit]:
        """Найти цели для атаки: ближайший живой враг в радиусе range_.

        Ассасины выбирают самого слабого живого врага в радиусе, а не ближнего.
        """
        attacker = self._find_unit(event["attacker_id"])
        if not attacker or not attacker.alive:
            return []

        enemies = self._alive_enemies(attacker)
        if not enemies:
            return []

        # Таунт: проверенный юнит бьёт/идёт к источнику провокации.
        taunt_target = self._taunt_target(attacker)
        if taunt_target is not None:
            if attacker.range_ >= self.distance(attacker, taunt_target):
                return [taunt_target]
            return []

        radius = event.get("aoe_radius", 0)
        if radius and radius > 0:
            return self._enemies_in_radius(attacker, radius)

        # Ассасин: бить самого слабого живого врага в радиусе атаки
        if getattr(attacker, "assassin_target_weakest", False):
            in_range = [
                e for e in enemies
                if attacker.range_ >= self.distance(attacker, e)
            ]
            if in_range:
                return [min(in_range, key=lambda e: e.hp)]
            return []  # нет цели в радиусе

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
            # Уклонение (эльфы): только против автоатаки, не DoT/абилок — гарантированный промах.
            if target.evasion_pct > 0 and self.rng.random() < target.evasion_pct / 100.0:
                damage_events.append({
                    "type": "miss",
                    "tick": self.tick_count,
                    "attacker_id": event["attacker_id"],
                    "target_id": target.unit_id,
                    "damage": 0,
                    "target_hp": target.hp,
                })
                continue

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
            elif target.just_revived:
                # Восстание (нежить): вместо убийства — воскрешение, сбросить флаг.
                devent["type"] = "revive"
                devent["revived_team"] = target.team
                devent["revive_hp"] = target.hp
                target.just_revived = False

            damage_events.append(devent)

            # Вампиризм (демоны): хил атакующего от реально нанесённого урона автоатакой.
            # Только автоатаки (не DoT/абилок), криты считаются полностью.
            attacker = self._find_unit(event["attacker_id"])
            if attacker and attacker.lifesteal_pct > 0:
                heal = target.last_damage * attacker.lifesteal_pct / 100.0
                if heal > 0:
                    attacker.hp = min(attacker.max_hp, attacker.hp + heal)
                    damage_events.append({
                        "type": "lifesteal",
                        "tick": self.tick_count,
                        "attacker_id": attacker.unit_id,
                        "target_id": target.unit_id,
                        "heal": round(heal, 1),
                        "target_hp": attacker.hp,
                    })

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
                # damage_bonus_pct — процентный бафф урона союзникам (Вождь орков "Крик войны")
                if eff.get("damage_bonus_pct"):
                    ally.add_status(
                        KIND_DAMAGE_BONUS_PCT,
                        eff.get("duration", 20),
                        pct=eff.get("damage_bonus_pct", 0),
                    )
                # damage_reduction_pct — щит союзникам (Рыцарь "Щитовая стена")
                if eff.get("damage_reduction_pct"):
                    ally.add_status(
                        KIND_DAMAGE_REDUCTION,
                        eff.get("duration", 20),
                        pct=eff.get("damage_reduction_pct", 30),
                    )
                # attack_speed_pct — бафф скорости атаки союзникам (Баффер)
                if eff.get("attack_speed_pct"):
                    ally.add_status(
                        KIND_SPEED_PCT,
                        eff.get("duration", 20),
                        pct=eff.get("attack_speed_pct", 0),
                    )
                # crit_chance_bonus — бафф шанса крита союзникам (Баффер демонов)
                if eff.get("crit_chance_bonus"):
                    ally.add_status(
                        KIND_CRIT_CHANCE,
                        eff.get("duration", 20),
                        amount=eff.get("crit_chance_bonus", 0),
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
            # damage_reduction_pct — дебафф на ближайшего живого врага (Суккуб "Проклятие"):
            # снижает ИСХОДЯЩИЙ урон цели, а не входящий (иначе это был бы щит врагу).
            if eff.get("damage_reduction_pct"):
                enemies = self._alive_enemies(unit)
                if enemies:
                    target = min(enemies, key=lambda e: self.distance(unit, e))
                    target.add_status(
                        KIND_DAMAGE_DEALT_PCT,
                        eff.get("duration", 10),
                        pct=eff.get("damage_reduction_pct", 25),
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

        elif atype == "heal":
            heal_amount = eff.get("heal", 0)
            events += self._apply_heal(unit, heal_amount)
            targets = [unit.unit_id]
            events.append(self._record_ability(unit, targets))

        elif atype == "shield":
            shield_amt = eff.get("shield", 0)
            duration = eff.get("duration", 10)
            targets_units = self._shield_targets(unit, eff)
            for t in targets_units:
                self._add_shield_status(t, shield_amt, duration)
            events.append(self._record_ability(unit, [t.unit_id for t in targets_units]))

        elif atype == "dot":
            dpt = eff.get("damage_per_tick", 0)
            duration = eff.get("duration", 5)
            targets_units = self._dot_targets(unit, eff)
            for t in targets_units:
                t.add_status(KIND_DOT, duration, damage_per_tick=dpt)
            events.append(self._record_ability(unit, [t.unit_id for t in targets_units]))

        elif atype == "stun":
            duration = eff.get("duration", 5)
            radius = eff.get("radius", 1)
            targets_units = [e for e in self._alive_enemies(unit)
                             if self.distance(unit, e) <= radius]
            for t in targets_units:
                t.add_status(KIND_STUN, duration)
            events.append(self._record_ability(unit, [t.unit_id for t in targets_units]))

        elif atype == "taunt":
            duration = eff.get("duration", 5)
            radius = eff.get("radius", 2)
            targets_units = [e for e in self._alive_enemies(unit)
                             if self.distance(unit, e) <= radius]
            for t in targets_units:
                t.add_status(KIND_TAUNT, duration, source_id=unit.unit_id)
            events.append(self._record_ability(unit, [t.unit_id for t in targets_units]))

        elif atype == "heal_over_time":
            hpt = eff.get("heal_per_tick", 0)
            duration = eff.get("duration", 5)
            targets_units = self._hot_targets(unit, eff)
            for t in targets_units:
                t.add_status(KIND_HEAL_OVER_TIME, duration, heal_per_tick=hpt)
            events.append(self._record_ability(unit, [t.unit_id for t in targets_units]))

        elif atype == "execute":
            damage = eff.get("damage", 0)
            threshold = eff.get("execute_threshold_pct", 0)
            bonus = eff.get("bonus_vs_low_pct", 0)
            enemies = self._alive_enemies(unit)
            target_ids = []
            if enemies:
                target = min(enemies, key=lambda e: e.hp)
                dmg = float(damage)
                if threshold and target.hp < target.max_hp * threshold / 100.0:
                    dmg = dmg * (1 + bonus / 100.0)
                rolled = dmg * (0.9 + self.rng.random() * 0.2)
                target.take_damage(rolled)
                target_ids = [target.unit_id]
            events.append(self._record_ability(unit, target_ids))

        elif atype == "assassin_teleport":
            # Инициализация ассасина: установить время ожидания и флаг цели на слабого.
            # Payload прибытия (arrival_damage/stun/dot/execute_threshold) применяется
            # в _teleport_assassin, когда ассасин появляется у цели.
            eff = ability.get("effect", {})
            if unit.assassin_teleported:
                # Уже телепортировался — больше не перекастовываем способность
                return []
            unit.assassin_wait = eff.get("wait_ticks", 60)
            unit.assassin_target_weakest = eff.get("target_weakest", True)
            unit.assassin_payload = dict(eff)
            unit.ability_cooldown = -1  # Никогда больше не перекастовывается
            targets = [unit.unit_id]
            events.append(self._record_ability(unit, targets))

        return events

    # ── Цели новых типов способностей ──────────────────────────────────────

    def _shield_targets(self, unit: Unit, eff: dict) -> list[Unit]:
        """Цели поглощающего щита: self / lowest_ally / all_allies."""
        target_kind = eff.get("targets", "self")
        allies = [a for a in self.teams.get(unit.team, []) if a.alive]
        if target_kind == "all_allies":
            return allies
        if target_kind == "lowest_ally" and allies:
            return [min(allies, key=lambda a: a.hp / max(a.max_hp, 1))]
        return [unit]

    def _add_shield_status(self, target: Unit, amount: int, duration: int) -> None:
        """Наложить щит: суммировать amount с существующим, обновить duration."""
        for s in target.statuses:
            if s["kind"] == KIND_SHIELD:
                s["amount"] = s.get("amount", 0) + amount
                s["ticks"] = max(s.get("ticks", 0), duration)
                return
        target.add_status(KIND_SHIELD, duration, amount=amount)

    def _dot_targets(self, unit: Unit, eff: dict) -> list[Unit]:
        """Цели DoT: 'single' — ближайший в радиусе, иначе все враги в радиусе."""
        radius = eff.get("radius", 1)
        target_kind = eff.get("targets", "enemies_in_radius")
        in_radius = [e for e in self._alive_enemies(unit)
                     if self.distance(unit, e) <= radius]
        if target_kind == "single" and in_radius:
            return [min(in_radius, key=lambda e: self.distance(unit, e))]
        return in_radius

    def _hot_targets(self, unit: Unit, eff: dict) -> list[Unit]:
        """Цели HoT: lowest_ally / all_allies / self."""
        target_kind = eff.get("targets", "self")
        allies = [a for a in self.teams.get(unit.team, []) if a.alive]
        if target_kind == "all_allies":
            return allies
        if target_kind == "lowest_ally" and allies:
            return [min(allies, key=lambda a: a.hp / max(a.max_hp, 1))]
        return [unit]

    def _apply_assassin_payload(self, unit: Unit) -> None:
        """Применить payload прибытия ассасина к цели в точке телепорта."""
        eff = getattr(unit, "assassin_payload", None) or {}
        enemies = self._alive_enemies(unit)
        if not enemies:
            return
        target_weakest = eff.get("target_weakest", True)
        target = (min(enemies, key=lambda e: e.hp) if target_weakest
                  else min(enemies, key=lambda e: self.distance(unit, e)))

        arrival_damage = eff.get("arrival_damage")
        if arrival_damage:
            rolled = arrival_damage * (0.9 + self.rng.random() * 0.2)
            target.take_damage(rolled)
            self._ability_events.append({
                "tick": self.tick_count,
                "caster_id": unit.unit_id,
                "caster_team": unit.team,
                "ability_name": (unit.active_ability or {}).get("name", ""),
                "ability_type": "assassin_teleport",
                "targets": [target.unit_id],
                "damage": rolled,
            })

        arrival_stun = eff.get("arrival_stun")
        if arrival_stun:
            target.add_status(KIND_STUN, int(arrival_stun))

        arrival_dot = eff.get("arrival_dot")
        if arrival_dot:
            target.add_status(
                KIND_DOT,
                arrival_dot.get("duration", 5),
                damage_per_tick=arrival_dot.get("damage_per_tick", 0),
            )

        # execute_threshold_pct: если цель ниже порога при прибытии — это execute
        # (урон arrival_damage уже применён выше; порог фиксирует факт добивания).
        _ = eff.get("execute_threshold_pct")

    # ── АOE-урон ───────────────────────────────────────────────────────────

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

        ability = caster.active_ability or {}
        eff = ability.get("effect", {})
        ability_name = ability.get("name", "Способность")

        # Вампиризм: лечим кастера на heal_pct от реально нанесённого урона (Лич "Касание смерти")
        heal_pct = eff.get("heal_pct", 0)
        if heal_pct and target.last_damage > 0:
            heal = target.last_damage * heal_pct / 100.0
            caster.hp = min(caster.max_hp, caster.hp + heal)

        event = {
            "type": "ability_hit",
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "target_id": target.unit_id,
            "damage": round(target.last_damage, 1),
            "target_hp": target.hp,
            "ability_name": ability_name,
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
            "ability_name": ability_name,
            "ability_type": "single_target_critical",
            "damage": damage,
            "targets": [target.unit_id],
        })

        return events

    def _apply_heal(self, caster: Unit, heal_amount: float) -> list[dict]:
        """Лечить союзника с наименьшим процентом HP (целитель)."""
        events = []
        if not caster.alive or heal_amount <= 0:
            return events

        allies = [u for u in self.teams.get(caster.team, []) if u.alive]
        if not allies:
            return events

        # Цель — союзник с наименьшим % HP (ниже всего шкала здоровья)
        target = min(allies, key=lambda u: u.hp / max(u.max_hp, 1))

        if target.hp >= target.max_hp:
            return events  # все уже с полным HP

        old_hp = target.hp
        target.hp = min(target.max_hp, target.hp + heal_amount)
        actual_heal = target.hp - old_hp
        if actual_heal <= 0:
            return events

        ability = caster.active_ability or {}
        ability_name = ability.get("name", "Целение")

        event = {
            "type": "ability_heal",
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "target_id": target.unit_id,
            "heal": round(actual_heal, 1),
            "target_hp": target.hp,
            "ability_name": ability_name,
            "ability_type": "heal",
        }
        events.append(event)

        self._ability_events.append({
            "tick": self.tick_count,
            "caster_id": caster.unit_id,
            "caster_team": caster.team,
            "ability_name": ability_name,
            "ability_type": "heal",
            "heal": heal_amount,
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

            # Kil trackers for this tick: {attacker_id: [target_ids]}
            kills_this_tick: dict[int, list[int]] = {}
            log_start = len(self.log)  # чтобы не сканировать весь лог каждый тик

            for unit in all_units:
                if not unit.alive:
                    continue

                # 1. Истечение временных эффектов
                unit.tick_statuses()

                # 1.5. Регенерация HP (расовый бонус нежити, hp_regen_pct)
                if unit.hp_regen_pct > 0 and unit.alive:
                    heal = unit.max_hp * unit.hp_regen_pct / 100.0
                    if heal > 0:
                        unit.hp = min(unit.max_hp, unit.hp + heal)

                # 1.6. DoT: урон по времени от эффекта на носителе (через take_damage)
                dot = next((s for s in unit.statuses if s["kind"] == KIND_DOT), None)
                if dot is not None and unit.alive:
                    dpt = dot.get("damage_per_tick", 0)
                    if dpt > 0:
                        unit.take_damage(dpt)
                if not unit.alive:
                    continue

                # 1.7. HoT: лечение со временем от эффекта на носителе
                hot = next((s for s in unit.statuses if s["kind"] == KIND_HEAL_OVER_TIME), None)
                if hot is not None and unit.alive:
                    hpt = hot.get("heal_per_tick", 0)
                    if hpt > 0:
                        unit.hp = min(unit.max_hp, unit.hp + hpt)

                # 1.8. Оглушение: пропуск хода (движение, атака и способность)
                if unit.is_stunned():
                    continue

                # 2. Кулдаун способности
                if unit.active_ability and unit.ability_cooldown > 0:
                    unit.ability_cooldown -= 1

                # 2.5. Ассасин: ожидание перед телепортом в задние ряды противника
                if getattr(unit, "assassin_wait", 0) > 0:
                    unit.assassin_wait -= 1
                    if unit.assassin_wait == 0:
                        self._teleport_assassin(unit)
                        unit.assassin_teleported = True
                        # Записываем ивент способности (UI покажет эффект телепорта)
                        self.log.append(self._record_ability(unit, [unit.unit_id]))
                    continue  # пропускаем движение, атаку и способность этого тика

                # 3. Проверяем, есть ли цель в радиусе ДО движения — иначе
                # юнит из заднего ряда «тратит» перезарядкуattack, пока идёт
                # к врагу, и бьёт одновременно с передовой, что ломает баланс.
                taunt_target = self._taunt_target(unit)
                can_attack = self._has_target_in_range(unit)
                if taunt_target is not None:
                    can_attack = self.distance(unit, taunt_target) <= unit.range_

                # 3. Движение к цели / удержание дистанции
                enemies = self._alive_enemies(unit)
                if enemies:
                    move_target = taunt_target if taunt_target is not None else min(
                        enemies, key=lambda e: self.distance(unit, e))
                    dist = self.distance(unit, move_target)
                    if unit.range_ <= 1:
                        # Мили: approaches up to distance 1
                        if dist > 1:
                            self._move_towards(unit, move_target.row, move_target.col)
                    else:
                        # Дальние: держать дистанцию range_
                        if dist < unit.range_:
                            self._move_away(unit, move_target)
                        elif dist > unit.range_:
                            self._move_towards(unit, move_target.row, move_target.col)

                # 4. Атака (по таймеру) — только если есть цель в радиусе
                if can_attack:
                    unit.attack_timer -= 1
                    if unit.attack_timer <= 0:
                        for event in unit.tick(self.rng):
                            self.log.extend(self._apply_attack(event))
                        unit.attack_timer = unit._ticks_per_attack()

                # 5. Способность (когда готова)
                if unit.alive and unit.active_ability and unit.ability_cooldown == 0:
                    # Ассасин с телепортом срабатывает один раз — не перекастовываем
                    if unit.active_ability.get("type") == "assassin_teleport" and unit.assassin_teleported:
                        pass
                    else:
                        self.log.extend(self._cast_ability(unit))
                        unit.ability_cooldown = unit.active_ability.get("cooldown", 3)

            # Собрать киллы за этот тик из новых событий лога
            for evt in self.log[log_start:]:
                if evt.get("type") in ("kill", "ability_kill"):
                    killer_id = evt.get("attacker_id") or evt.get("caster_id")
                    if killer_id is not None:
                        kills_this_tick.setdefault(killer_id, []).append(evt.get("target_id"))

            # Ускорение к/д способности за килл (mana_per_kill, магия)
            for unit in all_units:
                if not unit.alive:
                    continue
                if unit.mana_per_kill > 0 and unit.unit_id in kills_this_tick:
                    if unit.active_ability and unit.ability_cooldown > 0:
                        unit.ability_cooldown = max(
                            0, unit.ability_cooldown - unit.mana_per_kill * len(kills_this_tick[unit.unit_id])
                        )

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
                u.base_crit_chance = data.get("base_crit_chance", u.base_crit_chance)
                u.statuses = [dict(s) for s in data.get("statuses", [])]
                u.row = data.get("row", u.row)
                u.col = data.get("col", u.col)
                u.closing = data.get("closing", 0)
                u.assassin_wait = data.get("assassin_wait", 0)
                u.assassin_teleported = data.get("assassin_teleported", False)
                u.assassin_target_weakest = data.get("assassin_target_weakest", False)
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
