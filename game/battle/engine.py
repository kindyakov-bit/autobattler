"""Боевой движок: детерминированный тик + seeded RNG.

Каждый тик = 1 секунда игрового времени.
Юниты атакуют по таймеру (ticks_per_attack = ceil(60 / attack_speed)).
Целевание: ближайший живой враг; после смерти — перетаргетинг.
Синергии применяются при формировании состава команды.

Активные способности:
  - Каждая способность имеет cooldown (в тиках)
  - Способность активируется автоматически когда timer == 0
  - Поддерживаемые типы: aoe_damage, single_target_critical, buff_allies,
    aoe_damage_buff, aoe_damage_slow, buff_next_attack

Использование:
    sim = BattleSimulator(seed=42)
    sim.add_team("player", team_data)
    sim.add_team("enemy", enemy_data)
    result = sim.run()  # возвращает dict с итогами боя
"""

import math
import random


class Unit:
    """Юнит на поле боя."""

    def __init__(self, name: str, hp: int, damage: float, attack_speed: float,
                 range_: int, team: str, unit_id: int):
        self.name = name
        self.max_hp = hp
        self.hp = hp
        self.damage = damage
        self.attack_speed = attack_speed  # атак в секунду (тик)
        self.range_ = range_
        self.team = team
        self.unit_id = unit_id
        self.alive = True
        # Таймер до следующей атаки (в тиках). Каждый тик уменьшается на 1.
        ticks_per_attack = max(1, math.ceil(60 / attack_speed))
        self.attack_timer = ticks_per_attack
        
        # Активная способность
        self.active_ability = None  # dict с данными способности
        self.ability_cooldown = 0  # оставшиеся тики до готовности

    def take_damage(self, amount: float) -> bool:
        """Нанести урон. Возвращает True если юнит умер."""
        self.hp -= amount
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            return True
        return False

    def tick(self) -> list[dict]:
        """Обработка одного тика юнитом. Возвращает список событий атак."""
        events = []
        if not self.alive:
            return events

        # Таймер уже уменьшен в BattleSimulator.run() — проверяем только условие
        if self.attack_timer <= 0:
            events.append({
                "type": "attack",
                "attacker_id": self.unit_id,
                "attacker_team": self.team,
                "damage": self.damage,
                "range_": self.range_,
            })

        return events


class BattleSimulator:
    """Симулятор боя: два отряда, детерминированный тик."""

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self._next_id = 0
        self.teams: dict[str, list[Unit]] = {}
        self.log: list[dict] = []
        self.tick_count = 0
        self._tick_history: list[dict] = []  # snapshot'ы состояния для анимации
        self._attack_events: list[dict] = []  # события атак для визуальных эффектов
        self._ability_events: list[dict] = []  # события способностей

    def add_team(self, name: str, units_data: list[dict]) -> None:
        """Добавить команду. units_data — список словарей с полями юнитов.
        
        Поддерживает дополнительные поля:
            - item_bonuses: dict с бонусами от предметов {"hp_bonus": 200, "damage_bonus": 25, ...}
            - ability: dict с активной способностью (если у юнита есть активка)
        """
        team_units = []
        for ud in units_data:
            # Применяем бонусы от предметов к базовым статам
            hp = int(ud["hp"]) + ud.get("item_bonuses", {}).get("hp_bonus", 0)
            damage = float(ud["damage"]) + ud.get("item_bonuses", {}).get("damage_bonus", 0)
            attack_speed = float(ud["attack_speed"])
            
            # Применяем процентные бонусы от скорости
            speed_pct = ud.get("item_bonuses", {}).get("speed_bonus_pct", 0)
            if speed_pct:
                base_speed = float(ud["attack_speed"])
                attack_speed = base_speed * (1 + speed_pct / 100)
            
            u = Unit(
                name=ud["name"],
                hp=hp,
                damage=damage,
                attack_speed=attack_speed,
                range_=int(ud["range"] if "range" in ud else ud["range_"]),
                team=name,
                unit_id=self._next_id,
            )
            
            # Поддерживаем разные форматы имени юнита
            name_base = ud.get("name", "").split("★")[0]
            
            # Проверяем active способность из данных юнита
            ability = ud.get("active")
            if ability and ability.get("type") in ("aoe_damage", "aoe_damage_buff", 
                                                    "aoe_damage_slow", "single_target_critical"):
                u.active_ability = dict(ability)
                u.ability_cooldown = ability.get("cooldown", 3)
            
            self._next_id += 1
            team_units.append(u)
        self.teams[name] = team_units

    def _find_targets(self, event: dict) -> list[Unit]:
        """Найти цели для атаки: ближайший живой враг в радиусе."""
        attacker = None
        for team in self.teams.values():
            for u in team:
                if u.unit_id == event["attacker_id"]:
                    attacker = u
                    break

        if not attacker or not attacker.alive:
            return []

        enemy_team = [u for t, u_list in self.teams.items()
                      if t != attacker.team for u in u_list]
        alive_enemies = [u for u in enemy_team if u.alive]

        # Сортируем по расстоянию (для ближнего боя все на расстоянии 1)
        # Для дальних — приоритет ближайшему (здесь упрощённо: первый в списке)
        return [alive_enemies[0]] if alive_enemies else []

    def _apply_attack(self, event: dict) -> list[dict]:
        """Применить событие атаки: найти цели и нанести урон."""
        damage_events = []
        targets = self._find_targets(event)

        # Записываем событие атаки для визуальных эффектов (линии атак)
        self._attack_events.append({
            "tick": self.tick_count,
            "attacker_id": event["attacker_id"],
            "attacker_team": event["attacker_team"],
            "damage": event["damage"],
            "targets": [t.unit_id for t in targets],
        })

        for target in targets:
            # Небольшая вариативность урона (±10%) — но детерминированная от seed+tick
            variance = 0.9 + self.rng.random() * 0.2  # [0.9, 1.0]
            actual_damage = event["damage"] * variance
            died = target.take_damage(actual_damage)

            devent = {
                "type": "hit",
                "tick": self.tick_count,
                "attacker_id": event["attacker_id"],
                "target_id": target.unit_id,
                "damage": round(actual_damage, 1),
                "target_hp": target.hp,
            }
            if died:
                devent["type"] = "kill"
                devent["killer_team"] = event["attacker_team"]

            damage_events.append(devent)

        return damage_events

    def _apply_aoe_damage(self, caster_id: int, caster_team: str, 
                          damage: int, radius: int) -> list[dict]:
        """Применить урон по области ко всем врагам в радиусе.
        
        Args:
            caster_id: ID юнита-катчера
            caster_team: команда катчера
            damage: базовый урон способности
            radius: радиус эффекта (1=только ближайший, 2=все ближние, 3=все)
        
        Returns:
            Список событий урона.
        """
        events = []
        caster = None
        for team in self.teams.values():
            for u in team:
                if u.unit_id == caster_id and u.alive:
                    caster = u
                    break
        
        if not caster:
            return events
        
        # Находим всех живых врагов
        enemy_team = [u for t, u_list in self.teams.items()
                      if t != caster_team for u in u_list]
        alive_enemies = [u for u in enemy_team if u.alive]
        
        # Определяем радиус (3 = все враги на поле)
        if radius >= 3:
            targets = alive_enemies[:5]  # максимум 5 целей для баланса
        elif radius == 2:
            targets = alive_enemies[:3]  # ближайшие 3
        else:
            targets = [alive_enemies[0]] if alive_enemies else []
        
        for target in targets:
            actual_damage = damage * (0.9 + self.rng.random() * 0.2)
            died = target.take_damage(actual_damage)
            
            event = {
                "type": "ability_hit",
                "tick": self.tick_count,
                "caster_id": caster_id,
                "caster_team": caster_team,
                "target_id": target.unit_id,
                "damage": round(actual_damage, 1),
                "target_hp": target.hp,
                "ability_name": caster.active_ability["name"],
            }
            if died:
                event["type"] = "ability_kill"
                event["killer_team"] = caster_team
            
            events.append(event)
        
        # Записываем событие способности для визуальных эффектов
        self._ability_events.append({
            "tick": self.tick_count,
            "caster_id": caster_id,
            "caster_team": caster_team,
            "ability_name": caster.active_ability["name"],
            "damage": damage,
            "targets": [t.unit_id for t in targets],
        })
        
        return events

    def _apply_single_target_critical(self, caster_id: int, caster_team: str,
                                      damage: int) -> list[dict]:
        """Применить гарантированный критический удар по самому слабому врагу.
        
        Returns:
            Список событий урона.
        """
        events = []
        
        enemy_team = [u for t, u_list in self.teams.items()
                      if t != caster_team for u in u_list]
        alive_enemies = [u for u in enemy_team if u.alive]
        
        # Находим самого слабого врага (по HP)
        if not alive_enemies:
            return events
        
        target = min(alive_enemies, key=lambda u: u.hp)
        
        actual_damage = damage * (0.9 + self.rng.random() * 0.2)
        died = target.take_damage(actual_damage)
        
        event = {
            "type": "ability_hit",
            "tick": self.tick_count,
            "caster_id": caster_id,
            "caster_team": caster_team,
            "target_id": target.unit_id,
            "damage": round(actual_damage, 1),
            "target_hp": target.hp,
            "ability_name": "Выстрел смерти",
        }
        if died:
            event["type"] = "ability_kill"
            event["killer_team"] = caster_team
        
        events.append(event)
        
        self._ability_events.append({
            "tick": self.tick_count,
            "caster_id": caster_id,
            "caster_team": caster_team,
            "ability_name": "Выстрел смерти",
            "damage": damage,
            "targets": [target.unit_id],
        })
        
        return events

    def _check_result(self) -> dict | None:
        """Проверить условие конца боя. Возвращает результат или None."""
        alive = {}
        for name, units in self.teams.items():
            alive[name] = [u for u in units if u.alive]

        # Если одна команда полностью уничтожена — другая победила
        dead_teams = [n for n, u in alive.items() if len(u) == 0]
        live_teams = [n for n, u in alive.items() if len(u) > 0]

        if len(dead_teams) == 1 and len(live_teams) == 1:
            return {
                "winner": live_teams[0],
                "reason": "annihilation",
                "ticks": self.tick_count,
                "team_hp": {n: sum(u.hp for u in units)
                            for n, units in self.teams.items()},
            }

        # Если обе команды уничтожены одновременно — ничья (побеждает первая команда)
        if len(dead_teams) == 2:
            first_team = list(self.teams.keys())[0]
            return {
                "winner": first_team,
                "reason": "simultaneous_death",
                "ticks": self.tick_count,
                "team_hp": {n: sum(u.hp for u in units)
                            for n, units in self.teams.items()},
            }

        return None

    def run(self, max_ticks: int = 600) -> dict:
        """Запустить бой. max_ticks — лимит (по умолчанию 10 минут).
        Возвращает результат боя."""
        self.log = []
        self.tick_count = 0
        self._tick_history = []
        self._attack_events = []
        self._ability_events = []

        while self.tick_count < max_ticks:
            # Каждый тик обрабатываем каждого живого юнита по порядку
            all_units = [u for team in self.teams.values() for u in team]

            for unit in all_units:
                if not unit.alive:
                    continue

                # Уменьшаем таймер способности
                if unit.active_ability and unit.ability_cooldown > 0:
                    unit.ability_cooldown -= 1
                
                # Уменьшаем таймер атаки
                unit.attack_timer -= 1
                
                # Проверяем атаку
                if unit.attack_timer <= 0:
                    events = unit.tick()
                    for event in events:
                        hits = self._apply_attack(event)
                        self.log.extend(hits)

                    # Сбрасываем таймер после атаки
                    ticks_per_attack = max(1, math.ceil(60 / unit.attack_speed))
                    unit.attack_timer = ticks_per_attack
                
                # Проверяем способность (когда готова)
                if (unit.active_ability and 
                    unit.ability_cooldown == 0):
                    ability = unit.active_ability
                    
                    # Применяем способность
                    if ability["type"] == "aoe_damage":
                        events = self._apply_aoe_damage(
                            caster_id=unit.unit_id,
                            caster_team=unit.team,
                            damage=ability["effect"]["damage"],
                            radius=ability["effect"].get("radius", 2),
                        )
                        self.log.extend(events)
                    elif ability["type"] == "aoe_damage_buff":
                        # Наносим урон, потом баффаем себя
                        events = self._apply_aoe_damage(
                            caster_id=unit.unit_id,
                            caster_team=unit.team,
                            damage=ability["effect"]["damage"],
                            radius=ability["effect"].get("radius", 2),
                        )
                        self.log.extend(events)
                        # Применяем бафф скорости на себя (через временное увеличение attack_speed)
                        original_speed = unit.attack_speed
                        unit.attack_speed *= (1 + ability["effect"]["speed_bonus_pct"] / 100)
                        unit._speed_buff_timer = ability["effect"]["speed_bonus_pct"]
                    elif ability["type"] == "aoe_damage_slow":
                        events = self._apply_aoe_damage(
                            caster_id=unit.unit_id,
                            caster_team=unit.team,
                            damage=ability["effect"]["damage"],
                            radius=ability["effect"].get("radius", 2),
                        )
                        self.log.extend(events)
                    elif ability["type"] == "single_target_critical":
                        events = self._apply_single_target_critical(
                            caster_id=unit.unit_id,
                            caster_team=unit.team,
                            damage=ability["effect"]["damage"],
                        )
                        self.log.extend(events)
                    
                    # Устанавливаем cooldown после каста
                    unit.ability_cooldown = ability.get("cooldown", 3)

            # Сохраняем snapshot состояния для анимации
            snapshot = self._take_snapshot()
            self._tick_history.append(snapshot)

            # Проверяем условие победы/поражения
            result = self._check_result()
            if result is not None:
                return result

            self.tick_count += 1

        # Таймаут — победа у команды с большим суммарным HP
        team_hp = {}
        for name, units in self.teams.items():
            team_hp[name] = sum(u.hp for u in units)

        winner = max(team_hp, key=team_hp.get)
        return {
            "winner": winner,
            "reason": "timeout",
            "ticks": self.tick_count,
            "team_hp": team_hp,
        }

    def _take_snapshot(self) -> dict:
        """Сохранить состояние всех юнитов для анимации."""
        snapshot = {}
        for name, units in self.teams.items():
            snapshot[name] = []
            for u in units:
                snapshot[name].append({
                    "name": u.name,
                    "hp": u.hp,
                    "max_hp": u.max_hp,
                    "alive": u.alive,
                    "attack_timer": u.attack_timer,
                    "damage": u.damage,
                    "attack_speed": u.attack_speed,
                    "range_": u.range_,
                    "team": u.team,
                    "unit_id": u.unit_id,
                    "active_ability": u.active_ability,
                    "ability_cooldown": u.ability_cooldown,
                })
        return snapshot

    def get_unit_positions(self, player_units, enemy_units):
        """Calculate positions for all units on the battlefield.
        
        Returns a dict mapping unit -> (cx, cy) center position.
        Players on left, enemies on right, staggered vertically.
        """
        cx = 600  # center of screen (half of 1200)
        cy = 140
        positions = {}

        for i in range(len(player_units)):
            x = 30 + i * 160
            y = cy + i * 80
            cx_pos = x + 70
            cy_pos = y + 25
            positions[player_units[i]] = (cx_pos, cy_pos)

        for i in range(len(enemy_units)):
            x = cx + 50 + i * 160
            y = cy + i * 80
            cx_pos = x + 70
            cy_pos = y + 25
            positions[enemy_units[i]] = (cx_pos, cy_pos)

        return positions

    def restore_from_snapshot(self, snapshot: dict) -> None:
        """Восстановить состояние юнитов из snapshot'а."""
        for name, units in self.teams.items():
            if name in snapshot:
                for i, data in enumerate(snapshot[name]):
                    u = units[i]
                    u.hp = data["hp"]
                    u.max_hp = data["max_hp"]
                    u.alive = data["alive"]
                    u.attack_timer = data["attack_timer"]
                    u.active_ability = data.get("active_ability")
                    u.ability_cooldown = data.get("ability_cooldown", 0)

    def get_total_ticks(self) -> int:
        """Получить общее количество тиков в истории."""
        return len(self._tick_history)

    def get_attack_events(self, up_to_tick: int = None) -> list[dict]:
        """Получить события атак для визуальных эффектов.
        
        Args:
            up_to_tick: ограничить события этим тиком (None = все).
        
        Returns:
            Список событий атак с полями: tick, attacker_id, attacker_team, damage, targets.
        """
        if up_to_tick is not None:
            return [e for e in self._attack_events if e["tick"] <= up_to_tick]
        return list(self._attack_events)

    def get_ability_events(self, up_to_tick: int = None) -> list[dict]:
        """Получить события способностей для визуальных эффектов.
        
        Args:
            up_to_tick: ограничить события этим тиком (None = все).
        
        Returns:
            Список событий способностей с полями: tick, caster_id, caster_team, 
            ability_name, damage, targets.
        """
        if up_to_tick is not None:
            return [e for e in self._ability_events if e["tick"] <= up_to_tick]
        return list(self._ability_events)

    def _check_result(self) -> dict | None:
        """Проверить условие конца боя. Возвращает результат или None."""
        alive = {}
        for name, units in self.teams.items():
            alive[name] = [u for u in units if u.alive]

        # Если одна команда полностью уничтожена — другая победила
        dead_teams = [n for n, u in alive.items() if len(u) == 0]
        live_teams = [n for n, u in alive.items() if len(u) > 0]

        if len(dead_teams) == 1 and len(live_teams) == 1:
            return {
                "winner": live_teams[0],
                "reason": "annihilation",
                "ticks": self.tick_count,
                "team_hp": {n: sum(u.hp for u in units)
                            for n, units in self.teams.items()},
            }

        # Если обе команды уничтожены одновременно — ничья (побеждает первая команда)
        if len(dead_teams) == 2:
            first_team = list(self.teams.keys())[0]
            return {
                "winner": first_team,
                "reason": "simultaneous_death",
                "ticks": self.tick_count,
                "team_hp": {n: sum(u.hp for u in units)
                            for n, units in self.teams.items()},
            }

        return None

    def print_state(self) -> str:
        """Вывести текущее состояние поля (для консоли)."""
        lines = [f"=== Тик {self.tick_count} ==="]
        for name, units in self.teams.items():
            alive_units = [u for u in units if u.alive]
            dead_units = [u for u in units if not u.alive]
            hp_str = ", ".join(
                f"{u.name}: {u.hp}/{u.max_hp}" for u in alive_units
            )
            if dead_units:
                dead_str = ", ".join(f"☠{u.name}" for u in dead_units)
                lines.append(f"[{name}] {hp_str} | {dead_str}")
            else:
                lines.append(f"[{name}] {hp_str}")
        return "\n".join(lines)
