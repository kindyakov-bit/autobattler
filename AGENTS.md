# AGENTS.md — правила для агентов в этом репозитории

Автобатлер (клон TFT/Underlords): Python 3.14 + pygame-ce, pytest.
Общение и документация — на русском.

## Роли
- **OpenCode** (локальная модель, практически безлимит, лимит запросов/час) — исполнитель.
- **Qoder** (кредиты) — ревьювер/архитектор на контрольных точках.
- Цикл и экономия кредитов: `WORKFLOW.md`. Узкие задачи: `.opencode/agents/worker.md`.

## Слои (не смешивать)
- `game/core` — правила: магазин, пул, игрок, экономика, синергии, сборка команды.
- `game/battle` — детерминированный тик-симулятор (seeded RNG), без pygame.
- `ui` — pygame-рендер и ввод; игровой логики здесь нет.
- `data` — JSON-конфиг (units / items / synergies / races).

## Инварианты (единые источники)
- Имена юнитов: `base` / `base★2` / `base★3`. Парсить только через
  `game/core/unit_name.py` (`base_name`, `star_level`, `star_multiplier`).
  Не писать `split("★")[1][1:]`.
- Боевая команда собирается ТОЛЬКО `game/core/team.py:build_combat_team`
  (звёзды + предметы + расы + синергии + пассивки). `item_bonuses` применяются там
  один раз; в engine их не пробрасывать и не применять повторно.
- `BENCH_MAX` — из `game/core/player`. Учёт пула — `shop.POOL_COST_BY_STAR`.
- PvP-урон — `economy.pvp_round_damage(round, winner_survivors)`.
- Уровень магазина = уровень игрока (апгрейд отключён).

## Команды
- Тесты: `python -m pytest tests/ -q`.
  **НЕ голый `pytest`**: в `_scratch/` лежат старые `test_*.py`, открывающие pygame
  на импорте → коллекция зависает.
- Windows cp1251: `PYTHONIOENCODING=utf-8`.
- Headless-проверка UI:
  `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy PYTHONPATH=. python _scratch/render_draft_layout.py [W H]`
  → `_scratch/layout_WxH.png`; смотреть картинку, а не «на глаз».
- Запуск игры: `python run_ui.py` (или `run_game.bat`).

## Git-хуки
- Общие хуки лежат в закоммиченной папке `.githooks/` и активируются через
  `core.hooksPath`. **Одноразовая настройка после клона:**
  `git config core.hooksPath .githooks`.
- `pre-commit` (~8с): `python -m pytest tests/ -q` — блокирует коммит при упавших тестах.
- `pre-push` (~37с): тесты + headless-рендер на 2 разрешениях + стресс боевого
  рендера (`_scratch/stress_battle_ui.py`, 138 боёв) — ловит краши UI, не видимые pytest.
  UI-проверки зависят от gitignored `_scratch/`: если харнесов нет (свежий клон),
  они пропускаются с WARN, тесты всё равно прогоняются.
- Не обходить через `--no-verify` без крайней нужды.

## UI-layout
- Константы сеток — вверху `ui/game_ui.py`. Геометрия отрисовки и обработчиков
  клика/драга должна считаться одинаково (одни формулы), иначе хит-ректы расходятся.
- После правок layout — headless-рендер минимум на двух разрешениях.

## Тесты-контракт
- На каждый исправленный баг — регрессия в `tests/test_review_regressions.py`.
- Сюита должна оставаться зелёной до и после правок.

## Документация-передача
- После изменений обновлять `REVIEW_FIXES.md` (и `PROJECT_STATE` / `MINI_STATE`
  при смене состояния проекта).
- Формат описания бага: **Было → Стало → Почему → Где (file:line) → Тест**.

## Запреты
- Не коммитить без явной просьбы.
- Не удалять `package.json` / `package-lock.json` (инструментарий OpenCode).
- Не рефакторить и не добавлять фичи сверх задачи.
- Комментарии — только когда WHY неочевиден; по умолчанию без комментариев.