# _ARCHITECTURE.md — полная архитектура проекта Автобатлер

Этот файл **не читается автоматически** при старте новой сессии. Читай его только если нужно понять детали реализации или исправить баг.

## Структура файлов

```
autobattler/
├── data/
│   ├── units.json          # Определения юнитов, синергий, способностей
│   └── items.json          # Предметы (armor, weapon, accessory, legendary)
├── game/
│   ├── core/
│   │   ├── state.py        # Состояние игры (позиции, HP, snapshot)
│   │   ├── economy.py      # Экономика: interest (+1 за каждые 10 золота, до +5)
│   │   ├── synergies.py    # Расчёт бонусов синергий от состава команды
│   │   ├── round.py        # Game class: цикл раундов (4 крип + 4 PvP)
│   │   ├── bots.py         # SimpleBot AI (EASY/MEDIUM/HARD)
│   │   ├── shop.py         # Магазин: buy/sell/roll/merge ★1→★2→★3 + предметы
│   │   ├── pool.py         # Пул копий юнитов (ограничение 4 копии каждого)
│   │   ├── player.py       # Player: gold, reserve, board, items[]
│   │   └── draft.py        # DraftPhase: управление фазой драфта
│   └── battle/
│       └── engine.py       # BattleSimulator (детерминированный тик + seeded RNG)
├── ui/
│   └── game_ui.py          # Pygame UI с анимацией и визуальными эффектами
├── run_ui.py               # Точка входа для интерактивного режима
└── tests/                  # pytest (88+ тестов, все проходят ✅)
    ├── test_battle.py      # Боевой движок
    ├── test_economy.py     # Экономика и interest
    ├── test_items.py       # Предметы + ★3 merge из 3★2
    ├── test_round.py       # Петля раундов
    ├── test_shop.py        # Магазин и merge
    └── test_visual_effects.py  # Визуальные эффекты и snapshot
```

## Ключевые классы и их зависимости

### BattleSimulator (engine.py)
- **add_team(name, units_data)** — добавляет команду с юнитами
- **run(max_ticks=600)** — запускает бой, возвращает результат
- Поддерживает: item_bonuses, active abilities, visual events
- **get_attack_events(up_to_tick)** — события атак для UI
- **get_ability_events(up_to_tick)** — события способностей для UI

### Game (round.py)
- **run_round(player_gold, player_units, enemy_units, synergy_data)** — один раунд
- Сохраняет BattleSimulator в self.all_sims для UI
- Применяет синергии и пассивки перед боем

### Shop (shop.py)
- **buy(player, name, cost)** — покупка с авто-мержем ★1→★2→★3
- **_maybe_merge()** — три пути: 3×★1→★2, 2×★2→★3, 3×★2→★3
- **buy_item(player, item_name)** — покупка предмета в инвентарь
- **apply_item_to_unit(player, item_idx, unit_idx)** — применение к юниту

### Player (player.py)
- **reserve** — bench для нерасставленных юнитов
- **board** — доска с расставленными юнитами (до 6)
- **items** — инвентарь предметов
- **get_team_stats()** — конвертирует board в формат для боя

### Synergies (synergies.py)
- **calculate_synergy_bonuses(team, synergy_data)** → {class: bonus}
- **apply_synergy_hp_bonuses(team, bonuses)** → modified team with HP buffs
- Поддерживает пороги 2/4 для каждого класса

### GameUI (game_ui.py)
- **init()** — инициализация pygame и шрифтов
- **run(game_instance)** — запуск анимации боя с pause/speed control
- **_draw_battle_scene(sim, effects)** — отрисовка с визуальными эффектами
- Поддерживает: AttackLine, DamageNumber, DeathEffect

## Как добавить новый юнит

1. Добавить определение в `data/units.json`:
```json
{
  "unit_key": {
    "name": "Имя",
    "cost": 3,
    "class": "warrior|mage|archer",
    "hp": 900,
    "damage": 75,
    "attack_speed": 0.9,
    "range": 1,
    "description": "Описание",
    "passive": {
      "name": "Название пассивки",
      "desc": "Описание",
      "type": "synergy_buff",
      "class": "warrior|mage|archer",
      "effect": {"hp_bonus_pct_per_ally": 10}
    },
    "active": {
      "name": "Название активки",
      "type": "aoe_damage|single_target_critical|...",
      "cooldown": 3,
      "effect": {"damage": 80, "radius": 2}
    }
  }
}
```

2. Пассивки автоматически применяются через `calculate_passive_bonuses()` в round.py
3. Активки автоматически обрабатываются в BattleSimulator.run()

## Как добавить новую способность

В `engine.py` в методе `run()`:
1. Добавить тип способности в `_apply_aoe_damage` или создать новый метод (например, `_apply_heal`)
2. Добавить условие проверки типа способности
3. Добавить событие в self.log для UI

## Система визуальных эффектов

### В BattleSimulator:
- **_attack_events** — события атак (для AttackLine)
- **_ability_events** — события способностей (для вспышек)
- **log** — список всех событий боя (для DamageNumber)

### В GameUI:
- **AttackLine** — линия от атакующего к цели (life=8 кадров)
- **DamageNumber** — плавающее число урона (life=40 кадров)
- **DeathEffect** — частицы при смерти юнита (life=30 кадров)

### Как работает:
1. BattleSimulator.run() сохраняет snapshot'ы в _tick_history
2. GameUI.restore_from_snapshot() восстанавливает состояние для каждого кадра
3. get_attack_events() и get_ability_events() возвращают события по тикам
4. Для каждого нового события создаётся визуальный эффект

## Как запустить

```bash
# Консольный бой
python run_battle.py --seed 42 --verbose

# Интерактивный UI
python run_ui.py
```

## Тесты

```bash
# Все тесты
pytest tests/ -v

# Только боевой движок
pytest tests/test_battle.py -v

# Только визуальные эффекты
pytest tests/test_visual_effects.py -v
```

## Ловушки и важные моменты

1. **Не начинать с UI** — сначала код, потом графика
2. **Абилки — по одной** — добавлять одну способность за раз, тестировать отдельно
3. **Таргетинг «ближайший + перетаргет после смерти»** — при атаке выбирается ближайший живой враг, после его смерти — следующий
4. **Синергии считать на изменение состава** — не каждый тик, а перед боем
5. **Детерминированный бой** — seed задаёт весь ход боя, можно воспроизвести по seed
