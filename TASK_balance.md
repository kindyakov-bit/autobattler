# Задание для OpenCode: баланс рас/классов, скейл способностей от звёзд и тиров, уникальные абилки

Самодостаточное ТЗ. Роли: OpenCode — реализация батчами; Qoder — ревью на контрольной точке.
Не коммитить без просьбы. Общение/доки — на русском.
Сюита до правок: `PYTHONIOENCODING=utf-8 python -m pytest tests/ -q` → **266 passed**.

---

## 0. Текущее состояние (диагноз, подтверждено чтением кода и данных)

Ростер: `data/units.json` → 76 юнитов; ключи верхнего уровня: `synergies` (классы),
`races` (базовые расовые бонусы), `race_synergies` (пороги 2/4 расы), `units`.

- **Нежить имбалансна с старта.** `races.undead.bonuses.hp_regen_pct = 2` применяется
  **безусловно к каждому undead-юниту** (`game/core/team.py:76`) и лечит **2% max HP КАЖДЫЙ тик**
  (`game/battle/engine.py:1085-1089`). За бой это сотни процентов HP. Плюс у нежити **4 юнита t1**
  (`undead_assassin_shadow`, `undead_bone_shaman`, `undead_mage_bone`, `undead_warrior_skeleton`)
  → синергия 4-piece (`damage_reduction_pct 20`) собирается слишком рано.
- **У демонов нет фронтлайна.** В расе demon **вообще нет класса warrior**: только
  archer/assassin/buffer/healer/mage, все мягкие (t1 imp hp=250, totem hp=300). Ранняя игра = одни задники.
- **Способности не скейлятся от звёзд.** `build_combat_team` копирует `active` как есть
  (`game/core/team.py:98-99`); `_cast_ability` читает `effect` напрямую (`engine.py:767-886`).
  ★2/★3 бьют способностью той же силы, что ★1. Пассивки тоже не скейлятся
  (`game/core/synergies.py:143-166`).
- **Тиры слабо различаются.** Диапазоны статов пересекаются: t1 hp=240..500, t5 hp=300..1000;
  t1 dmg до 130, t5 dmg от 80. t1 может перебить t5 по статам.
- **Абилки — заглушки.** Все 76 пассивок = один тип `synergy_buff`; активки шаблонны по классу
  (17× `assassin_teleport`, 11× `heal`, 12× `buff_allies`, 26× вообще без active).
  Уникальности per-unit нет. Движок умеет только 9 типов (`engine.py:22-32`): нет щита-поглотителя,
  DoT, стана, таунта, heal-over-time, execute.

## 1. Целевые решения (баланс-рычаги)

### 1.1 Нерф нежити (точечно, не ломая контракты)
- `races.undead.bonuses`: **убрать `hp_regen_pct`**; `damage_reduction_pct` оставить **5**
  (на нём держатся тесты `tests/test_review_regressions.py:208,220` — не менять).
- `race_synergies.undead.bonuses`: `2` → добавить `hp_regen_pct: 0.3` (к существующему
  `damage_reduction_pct 10`); `4` → добавить `hp_regen_pct: 0.6` (к `damage_reduction_pct 20`).
  Реген теперь **только по порогу** и в ~6 раз слабее.
- `game/core/synergies.py:apply_race_bonuses` (~212+): научиться **накапливать `hp_regen_pct`**
  в поле юнита (прибавлять к уже установленному базовому), иначе пороговый реген не доедет до движка.
- Замедлить раннюю 4-piece: `undead_bone_shaman` cost 1→2 и `undead_mage_bone` cost 1→2
  (остаётся 2 undead t1: shadow, skeleton).

### 1.2 Фронтлайн демонов
- Добавить **двух новых warrior-юнитов расы demon** (data-only, движок/магазин/UI подхватят сами):
  - `demon_warrior_imp_guard` t1: hp≈400, dmg≈41, as=0.9, class=warrior, race=demon (ранний танк).
  - `demon_warrior_pit_lord` t3: hp≈750, dmg≈82, as=0.9, class=warrior, race=demon (мид-гейм танк).
  Статы — по формуле тиров из §1.3 (role=warrior). Абилки — из таблицы §3.
- Пул/ролл/магазин считаются от `units.json` автоматически (`Pool(COPIES_BY_COST[cost])`),
  отдельного кода не нужно. Спрайт: `draw_unit_sprite(class="warrior", race="demon")` — фолбэк есть.

### 1.3 Тиры: явные полосы статов (перегенерировать hp/damage всех юнитов)
Формула (округлять до int):
```
HP_BASE  = {1:320, 2:450, 3:600, 4:760, 5:950}
DMG_BASE = {1:55,  2:80,  3:110, 4:145, 5:190}
HP_ROLE  = {warrior:1.25, buffer:1.05, healer:1.0, assassin:0.85, mage:0.8, archer:0.85}
DMG_ROLE = {warrior:0.75, buffer:0.7,  healer:0.6, assassin:1.25, mage:1.25, archer:1.2}
hp     = round(HP_BASE[cost]  * HP_ROLE[class])
damage = round(DMG_BASE[cost] * DMG_ROLE[class])
```
`attack_speed` оставить как есть (ролевой flavor). Это убирает пересечение t1/t5 и закрепляет
роли (танк живучий/слабый урон, dps хрупкий/сильный). Применить ко **всем** юнитам включая новых.
Контракт-тест: средние hp/damage монотонно растут по тирам; ни один t1 не превышает медиану t5.

### 1.4 Скейл способностей от звёзд и тиров
- В `game/core/team.py` при копировании `active` (98-99) масштабировать **числовые «силовые»**
  поля effect множителем `star_multiplier(star) * TIER_ABILITY_MULT[cost]`:
  ```
  TIER_ABILITY_MULT = {1:1.0, 2:1.25, 3:1.5, 4:1.8, 5:2.2}
  ABILITY_SCALABLE_KEYS = {"damage","heal","shield","bonus_damage",
                           "damage_per_tick","heal_per_tick","absorb","arrival_damage"}
  ```
  НЕ масштабировать duration/percent/radius/wait_ticks. `star_multiplier` не менять
  (закреплён `tests/test_review_regressions.py:60-63`).
- Пассивки: в `calculate_passive_bonuses` (`synergies.py:143-166`) умножать `bonus_value`
  на `star_multiplier(unit.get("star",1))`.
- Разнести пассивки по ролям (чтобы не были одинаковыми): warrior → `hp_bonus_pct_per_ally`
  или `damage_reduction_pct_per_ally`; mage/archer/assassin → `damage_bonus_pct_per_ally`;
  healer/buffer → `speed_bonus_pct_per_ally` или `hp_bonus_pct_per_ally`. Значения per-ally varied.

## 2. Новые типы способностей в движке (расширить `SUPPORTED_ABILITY_TYPES`, engine.py:22-32)

Добавить типы и механику. Интеграционные точки:
- **`shield`** — поглощающий щит. effect `{shield:N, duration:T, targets:"self"|"lowest_ally"|"all_allies"}`.
  Новый статус `KIND_SHIELD` (amount=поглощение). В `Unit.take_damage` (`engine.py:216-225`)
  **сначала** гасить урон щитом, остаток — в hp (после damage_reduction). Щит не стакается бесконечно
  (суммировать amount, но обновлять duration).
- **`dot`** — урон по времени. effect `{damage_per_tick:N, duration:T, radius:R, targets:"single"|"enemies_in_radius"}`.
  Статус `KIND_DOT`; в тик-лупе (`engine.py:1085+`) наносить `damage_per_tick` каждый тик носителя
  (через take_damage, чтобы учитывалось снижение).
- **`stun`** — оглушение. effect `{duration:T, radius:R}`. Статус `KIND_STUN`; в тик-лупе если носитель
  оглушён — пропустить движение/атаку/способность (как assassin-wait `continue`, engine.py:1103).
- **`taunt`** — провокация. effect `{duration:T, radius:R}`. Статус `KIND_TAUNT` на врагах в радиусе
  (хранит id кастера); в выборе цели (`engine.py:704`, а также 650/667/1113) если у атакующего есть
  живой taunt-источник — атаковать/идти к нему, иначе обычная логика.
- **`heal_over_time`** — реген союзников. effect `{heal_per_tick:N, duration:T, targets:...}`.
  Статус `KIND_HEAL_OVER_TIME`; в тик-лупе лечить носителя (не выше max_hp).
- **`execute`** — добивание. effect `{damage:N, execute_threshold_pct:P, bonus_vs_low_pct:B}`.
  Single-target (самый слабый/ближайший): если hp цели < P% max_hp — урон ×(1+B/100).
- **Расширить `assassin_teleport`** payload'ом прибытия (уникальность ассасинов):
  effect `{wait_ticks, target_weakest, arrival_damage?, arrival_stun?, arrival_dot?:{damage_per_tick,duration},
  execute_threshold_pct?}`. В `_teleport_assassin` применить payload к цели прибытия.

Каждый новый тип добавить в `SUPPORTED_ABILITY_TYPES` — этого требует контракт
`tests/test_ability_effects.py:73` (все active юнитов обязаны быть поддерживаемым типом).
Временные эффекты класть через `add_status`/`tick_statuses` (`engine.py:158-169`), не изобретать
параллельный механизм. Детерминизм (seeded RNG) и `MAX_DAMAGE_REDUCTION_PCT` не ломать.

## 3. Уникальные абилки per-unit (таблица назначений)

Каждый юнит получает **свой** active (уникальное имя + уникальная сигнатура type+effect).
Пассивка остаётся расово-классовой аурой (§1.4), уникальность несёт active.
Числа ниже — база t★1; скейл от звёзд/тиров применит §1.4 автоматически.

### Human
- warrior_freshman t1: shield «Стойка новобранца» {shield:60, duration:12, targets:self}
- warrior_veteran t2: taunt «Провокация» {duration:10, radius:2}
- warrior_champion t3: shield «Щит чемпиона» {shield:140, duration:14, targets:self}
- human_warrior_paladin t4: shield «Благословлённый щит» {shield:120, duration:14, targets:lowest_ally}
- warrior_knight t5: taunt «Щитовая стена» {duration:14, radius:3}
- mage_acolyte t1: aoe_damage «Искра» {damage:50, radius:1}
- mage_sorcerer t2: dot «Ожог» {damage_per_tick:12, duration:8, radius:1}
- mage_archmage t3: aoe_damage_slow «Ледяная нова» {damage:90, radius:2, slow_pct:30, slow_duration:8}
- human_mage_holy t4: stun «Святая кара» {duration:6, radius:1}
- mage_sage t5: aoe_damage «Метеор» {damage:200, radius:2}
- archer_scout t1: buff_next_attack «Прицельный выстрел» {bonus_damage:40, radius:1, duration:30}
- archer_ranger t2: single_target_critical «Меткий выстрел» {damage:90}
- archer_marksman t3: execute «Снайпер» {damage:110, execute_threshold_pct:35, bonus_vs_low_pct:60}
- human_archer_longbow t4: dot «Ядовитая стрела» {damage_per_tick:16, duration:9, radius:1, targets:single}
- archer_battleheart t5: aoe_damage «Залп» {damage:160, radius:2}
- human_assassin_knife t1: assassin_teleport «Удар из тени» {wait_ticks:30, target_weakest:true, arrival_damage:50}
- human_assassin_blade t2: assassin_teleport «Вскрытие» {wait_ticks:35, target_weakest:true, arrival_dot:{damage_per_tick:10,duration:6}}
- human_assassin_dark_blade t3: assassin_teleport «Тёмный клинок» {wait_ticks:40, target_weakest:true, arrival_damage:90}
- human_assassin_spy t4: assassin_teleport «Шпионский удар» {wait_ticks:45, target_weakest:true, arrival_stun:5}
- human_healer_priest t2: shield «Оберег» {shield:90, duration:12, targets:lowest_ally}
- human_healer_holy_priest t4: heal «Молитва» {heal:120, targets:all_allies}
- human_buffer_bard t3: buff_allies «Боевая песня» {attack_speed_pct:25, duration:15}

### Orc
- orc_warrior_berserker t2: buff_next_attack «Ярость» {bonus_damage:70, radius:1, duration:30}
- orc_warrior_axe_bearer t3: aoe_damage «Рассекающий удар» {damage:100, radius:1}
- orc_warrior_chief t4: buff_allies «Крик войны» {damage_bonus_pct:25, duration:15}
- orc_warrior_warlord t5: taunt «Вызов вождя» {duration:14, radius:3}
- orc_archer_slinger t1: single_target_critical «Камень» {damage:60}
- orc_archer_war_bow t5: aoe_damage «Боевой залп» {damage:170, radius:2}
- orc_assassin_axe t2: assassin_teleport «Бросок топора» {wait_ticks:35, target_weakest:true, arrival_damage:70}
- orc_assassin_war_axe t3: assassin_teleport «Кровавый топор» {wait_ticks:40, target_weakest:true, arrival_dot:{damage_per_tick:12,duration:7}}
- orc_assassin_raider t4: assassin_teleport «Набег» {wait_ticks:45, target_weakest:true, arrival_damage:110}
- orc_healer_witch t1: heal_over_time «Ведьмин отвар» {heal_per_tick:8, duration:10, targets:lowest_ally}
- orc_healer_shaman t2: shield «Духовный щит» {shield:80, duration:12, targets:all_allies}
- orc_healer_war_shaman t5: heal «Исцеление предков» {heal:160, targets:all_allies}
- orc_buffer_warchief_advisor t4: buff_allies «Совет вождя» {damage_bonus_pct:20, duration:15}
- orc_mage_shadow_shaman t5: aoe_damage_slow «Теневой град» {damage:150, radius:2, slow_pct:35, slow_duration:8}

### Elf
- elf_warrior_blade_apprentice t1: buff_next_attack «Ученический выпад» {bonus_damage:45, radius:1, duration:30}
- elf_warrior_blade_dancer t5: aoe_damage_slow «Танец клинков» {damage:150, radius:2, slow_pct:30, slow_duration:8}
- elf_archer_ranger t2: buff_next_attack «Лесная меткость» {bonus_damage:60, radius:1, duration:30}
- elf_archer_hunter t4: execute «Охотничий выстрел» {damage:130, execute_threshold_pct:40, bonus_vs_low_pct:70}
- elf_archer_star_bow t5: aoe_damage_slow «Звёздный дождь» {damage:170, radius:2, slow_pct:25, slow_duration:8}
- elf_assassin_leaf_blade t2: assassin_teleport «Листовой клинок» {wait_ticks:30, target_weakest:true, arrival_dot:{damage_per_tick:9,duration:6}}
- elf_assassin_wind_blade t3: assassin_teleport «Ветровой клинок» {wait_ticks:35, target_weakest:true, arrival_damage:80}
- elf_assassin_shadow_walker t4: assassin_teleport «Теневой шаг» {wait_ticks:40, target_weakest:true, arrival_stun:6}
- elf_healer_spirit t1: heal «Дух леса» {heal:60, targets:lowest_ally}
- elf_healer_dryad t2: heal_over_time «Сок дерева» {heal_per_tick:10, duration:10, targets:lowest_ally}
- elf_healer_star_druid t5: heal «Звёздное исцеление» {heal:150, targets:all_allies}
- elf_mage_star_apprentice t2: single_target_critical «Звёздная искра» {damage:80}
- elf_mage_star_mage t5: stun «Звёздные оковы» {duration:7, radius:2}
- elf_buffer_forest_guardian t3: buff_allies «Кора-оберег» {damage_reduction_pct:25, duration:15}

### Undead
- undead_warrior_skeleton t1: shield «Костяная броня» {shield:60, duration:12, targets:self}
- undead_warrior_bone_guard t3: taunt «Костяная стена» {duration:12, radius:2}
- undead_assassin_shadow t1: assassin_teleport «Тень» {wait_ticks:25, target_weakest:true, arrival_damage:45}
- undead_assassin_bone_blade t2: assassin_teleport «Костяное лезвие» {wait_ticks:30, target_weakest:true, arrival_dot:{damage_per_tick:10,duration:6}}
- undead_assassin_death_edge t3: assassin_teleport «Грань смерти» {wait_ticks:35, target_weakest:true, arrival_damage:85}
- undead_assassin_death_stalker t5: assassin_teleport «Жнец» {wait_ticks:40, target_weakest:true, arrival_damage:120, execute_threshold_pct:30}
- undead_archer_bone_bow t3: single_target_critical «Костяная стрела» {damage:100}
- undead_mage_bone t2: single_target_critical «Костяной шип» {damage:85}
- undead_warrior_lich t4 (class=mage): single_target_critical «Касание смерти» {damage:140, heal_pct:50}
- undead_healer_necromancer t3: heal «Массовое сшивание» {heal:100, targets:all_allies}
- undead_bone_shaman t2: buff_allies «Костяной оберег» {damage_reduction_pct:20, duration:15}
- undead_bone_buff t2: buff_allies «Сила могилы» {damage_bonus_pct:18, duration:15}
- undead_buffer_ghost_chieftain t4: buff_allies «Призрачная скорость» {attack_speed_pct:22, duration:15}
- undead_buffer_death_aura t5: aura «Аура смерти» {bonus_damage_per_ally:20, duration:15}

### Demon
- demon_warrior_imp_guard t1 (NEW): shield «Адский дозор» {shield:70, duration:12, targets:self}
- demon_warrior_pit_lord t3 (NEW): taunt «Владыка ямы» {duration:12, radius:2}
- demon_mage_imp t1: dot «Поджог» {damage_per_tick:10, duration:7, radius:1}
- demon_mage_succubus t3: buff_next_attack «Проклятие» {bonus_damage:0, damage_reduction_pct:25, duration:10}
- demon_mage_fire_lord t4: dot «Огненная буря» {damage_per_tick:20, duration:9, radius:2}
- demon_archer_fire_bow t3: dot «Горящая стрела» {damage_per_tick:14, duration:8, radius:1, targets:single}
- demon_assassin_shadow_blade t2: assassin_teleport «Смертельная тень» {wait_ticks:40, target_weakest:true, arrival_damage:75}
- demon_assassin_shadow_edge t3: assassin_teleport «Теневая грань» {wait_ticks:40, target_weakest:true, arrival_dot:{damage_per_tick:12,duration:7}}
- demon_assassin_shadow_killer t5: assassin_teleport «Убийца теней» {wait_ticks:45, target_weakest:true, arrival_damage:130}
- demon_healer_blood_priest t3: shield «Кровавый барьер» {shield:100, duration:12, targets:self}
- demon_healer_soul_priest t4: heal_over_time «Душевное тепло» {heal_per_tick:12, duration:10, targets:all_allies}
- demon_fire_totem t1: buff_allies «Огненная сила» {attack_speed_pct:20, duration:10}
- demon_buffer_hell_priest t2: buff_allies «Аура критов» {crit_chance_bonus:15, duration:15}
- demon_buffer_demon_lord t5: buff_allies «Власть демонов» {damage_bonus_pct:30, duration:15}

Контракт уникальности: у каждого юнита есть active; `active.name` уникален глобально;
сигнатура `(type, нормализованный effect)` уникальна глобально (разные числа = разные сигнатуры).

## 4. Батчи (порядок реализации, каждый = отдельный прогон тестов)

1. **Data-баланс**: §1.1 (undead), §1.2 (новые demon warrior, статы), §1.3 (полосы тиров).
   Тесты: реген нежити только по порогу и ≤0.6/тик; у demon есть warrior t1; полосы тиров монотонны.
2. **Скейл звёзд/тиров**: §1.4 (team.py + synergies.py). Тесты: ★2 ability damage = 1.5×★1 при том же
   тире; t5 ability сильнее t1; пассивка скейлится от звезды; item_bonuses не двоится.
3. **Движок: новые типы**: §2 (shield/dot/stun/taunt/heal_over_time/execute + assassin payload).
   Тест на каждый тип (щит гасит урон до hp; dot тикает; стан пропускает ход; таунт форсит цель;
   hot лечит; execute добивает ниже порога). Обновить `SUPPORTED_ABILITY_TYPES`.
4. **Уникальные абилки (data)**: таблица §3. Тесты: уникальность имён/сигнатур; все active поддерживаемых
   типов (`test_ability_effects.py:73` зелёный); каждый юнит имеет active.
5. **Баланс-харнес + верификация**: `_scratch/balance_report.py` — моно-расовые команды равного
   тира/числа, прогон N seeds через `build_combat_team`+`BattleSimulator`, матрица винрейтов.
   Приёмка: нежить не доминирует (винрейт против поля ≤ ~60%), демон с новым фронтлайном не авто-луз
   на ранних тирах (≥ ~40%). Прогнать pytest, headless-рендер, обновить доки.

## 5. Самопроверка перед сдачей каждого батча
```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONPATH=. python _scratch/render_draft_layout.py 1200 800
```
Смотреть PNG, не «на глаз». НЕ голый `pytest` (зависает на `_scratch/`).
Баланс-харнес: `PYTHONIOENCODING=utf-8 python _scratch/balance_report.py`.

## 6. Документация-передача
`REVIEW_FIXES.md` / `PROJECT_STATE` / `MINI_STATE` — раздел «Баланс»:
**Было → Стало → Почему → Где (file:line) → Тест**. Приложить матрицу винрейтов до/после.

## 7. Запреты
- Не коммитить без просьбы; не удалять `package.json`/`package-lock.json`.
- Не менять `star_multiplier` значения, `MAX_DAMAGE_REDUCTION_PCT`, детерминизм RNG.
- `build_combat_team` — единственная сборка; `item_bonuses` применять один раз (не двоить).
- Не рефакторить сверх задачи; комментарии только где WHY неочевиден.
- Не трогать UI-логику; абилки data-driven, тултипы уже читают `active.desc` из JSON.
- Существующие контракты, которые НЕ должны сломаться: `test_review_regressions.py:60-63`
  (star_multiplier), `:208,220` (undead base damage_reduction=5), `test_ability_effects.py:73`
  (типы active). Если баланс-правка осознанно меняет старый контракт — обновить тест и пояснить в доке.