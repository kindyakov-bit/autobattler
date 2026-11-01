# SESSION_README — Полное руководство по текущему проекту

> Этот файл создан для быстрого старта в новом диалоге. Читайте его полностью, чтобы понять состояние проекта без необходимости pesquisывать все файлы.

---

## 1. ОБЗОР ПРОЕКТА

### Что сделано
Интеграция игрового проекта **Autobattler** с генерацией игровых спрайтов через **SpriteCook MCP** (облако) и **ComfyUI-MCP** (локально). В игре реализованы спрайты с прозрачным фоном через локальную генерацию.

### Используемые технологии
- **OpenCode** — основная среда разработки
- **ComfyUI-MCP** — локальный сервер генерации через ComfyUI на GPU RTX 5070
- **ComfyUI** — läuft на `http://localhost:8188`
- **Autobattler** — игра на Python + Pygame, папка `C:\AI\OpenCode Projects\autobattler\`
- **any_txt_parser** — MCP-сервер для навигации по коду, `C:\AI\OpenCode Projects\tools\any_txt_parser.exe`

---

## 2. СТРУКТУРА ПРОЕКТА

### Основные директории
```
C:\AI\OpenCode Projects\                          <- Рабочая папка OpenCode
├── autobattler\                                  — Игра (Python + Pygame)
│   ├── ui/
│   │   ├── game_ui.py                            — Основной интерфейс игры
│   │   ├── sprites.py                            — Отрисовка спрайтов (обновлён: загружает PNG)
│   │   └── assets/
│   │       └── sprites\                          # Загруженные спрайты PNG с прозрачным фоном
│   │           ├── warrior.png
│   │           ├── archer.png
│   │           ├── mage.png
│   │           └── skeleton.png
│   ├── data/
│   │   ├── units.json                            — Конфигурация юнитов
│   │   └── items.json                            — Конфигурация предметов
│   ├── game/core/
│   │   ├── shop.py                               — Логика магазина (кэширование предметов)
│   │   ├── draft.py                              — Фаза драфта
│   │   └── player.py                             — Игрок (bench, board, inventory)
│   ├── run_ui.py                                 — Запуск интерфейса
│   └── run_game.bat                              — Батник запуска
├── .opencode/
│   └── agents\
├── opencode.json                                 — Конфиг OpenCode (в корне проекта)
└── SESSION_README.md                             <- Этот файл
```

### Файлы конфигурации OpenCode
`C:\Users\kindy\.config\opencode\opencode.json` — глобальный конфиг
`C:\AI\OpenCode Projects\opencode.json` — локальный конфиг проекта (если есть)

### Рабочие процессы ComfyUI
`C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfy-mcp-server\workflow\`

| Файл | Назначение |
|------|-----------|
| `pixel_art_flux_alpha_final.json` | Финальный workflow для спрайтов с прозрачным фоном |
| `pixel_art_flux_archer.json` | Спрайт лучника |
| `pixel_art_flux_mage.json` | Спрайт мага |
| `pixel_art_flux_grabcut.json` | Спрайт через AutoGrabCutRemover |
| `pixel_art_flux_transparent.json` | Спрайт с прозрачным фоном (ранняя версия) |
| `pixel_art_flux_knight.json` | Спрайт рыцаря |
| `pixel_art_sprite.json` | Базовый спрайт пиксель-арта |
| `pixel_art_sprite_flux.json` | Спрайт спрайта Flux |
| `pixel_art_flux_knight.json` | Альтернативный спрайт рыцаря |

---

## 3. КОНФИГУРАЦИЯ OpenCode

### `C:\Users\kindy\.config\opencode\opencode.json`

Раздел `mcp` должен содержать:

```json
{
  "mcp": {
    "comfyui-mcp": {
      "type": "local",
      "command": ["cmd", "/c", "C:\\tools\\comfy-pilot\\run_comfy_mcp.bat"],
      "enabled": true
    },
    "any_txt_parser": {
      "type": "local",
      "command": ["C:\\AI\\OpenCode Projects\\tools\\any_txt_parser.exe", "mcp", "--root", "C:\\AI\\OpenCode Projects"],
      "enabled": true
    }
  }
}
```

### `C:\tools\comfy-pilot\run_comfy_mcp.bat`

```batch
@echo off
set COMFY_URL=http://127.0.0.1:8188
set COMFY_WORKFLOW_JSON_FILE=C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfy-mcp-server\workflow\pixel_art_flux_alpha_final.json
set PROMPT_NODE_ID=5
set OUTPUT_NODE_ID=10
set COMFY_MAX_POLL_ATTEMPTS=120
set COMFY_POLL_INTERVAL=0.5
set PYTHONPATH=C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfy-mcp-server\src
python -m comfy_mcp_server
```

### Что подключено
- **ComfyUI-MCP** — локальный сервер через ComfyUI, доступен через инструменты `comfyui-mcp.*`
- **any_txt_parser** — MCP-сервер для навигации по коду, инструменты `any_txt_parser.*` (symbols, find_symbol, read_lines, search_text, map и др.)
- **Навыки SpriteCook удалены** — папка `skills/` пуста, сервер spritecook отключён

---

## 4. СТАТУС РАБОТЫ

### ✅ Завершено
- [x] Установлен OpenCode
- [x] Установлен и настроен SpriteCook MCP сервер
- [x] Установлен и настроен ComfyUI-MCP сервер
- [x] ComfyUI запущен на `http://localhost:8188` (RTX 5070, 12 ГБ VRAM)
- [x] 4 спрайта сгенерированы с прозрачным фоном:
  - `warrior.png` — воин (синие доспехи, меч)
  - `archer.png` — лучник (оранжево-красная броня, лук)
  - `mage.png` — маг (синий капюст, посох)
  - `skeleton.png` — скелет (серо-красная броня)
- [x] **76 юнитов в данных (5 тиров, по 2+ представителя каждой расы и класса в каждом тире):**
  - Тир 1 (1 золото): 14 юнитов
  - Тир 2 (2 золота): 16 юнитов
  - Тир 3 (3 золота): 17 юнитов
  - Тир 4 (4 золота): 14 юнитов
  - Тир 5 (5 золота): 15 юнитов
- [x] **41 новый спрайт сгенерирован через ComfyUI с прозрачным фоном** — все загружены в `autobattler/assets/units/` и проверены в pygame
- [x] **Новые классы:** хилеры (лечат союзника с наименьшим % HP), бафферы (баффят союзников), ассасины (телепорт в задние ряды, бьют слабого)
- [x] **Новые class-синергии:** healer, buffer, assassin (пороги 2/4)
- [x] **Новые типы способностей в движке:** `heal`, `assassin_teleport`, crit_chance бафф
- [x] **Исправлены баги новых механик:**
  - Ассасин больше не «залипает» в ожидании — способность `assassin_teleport` срабатывает один раз, после чего ассасин атакует самого слабого врага в задние ряды
  - Ивент способности ассасина записывается в лог боя (UI показывает эффект телепорта)
  - Классовые бонусы работают для всех 6 классов (включая healer/buffer/assassin) через `build_combat_team`
- [x] **Изменён баланс доски:** изначально 2 слота на доске, +1 слот за уровень магазина, максимум 6
- [x] **Автоматический рост магазина:** уровень +1 раз в два раунда (раунды 3, 5, 7)
- [x] **Рандомизация стартового закупа:** магазин теперь использует свой независимый случайный seed (не связанный с battle seed), так что при каждом запуске продаются разные юниты
- [x] **Система уровней и опыта игрока:**
  - `Player.level` (начинается с 1), `Player.xp`, `Player.xp_to_next_level`
  - Лимит юнитов на доске = `level + 1`
  - Таблица XP: Ур 1→2: 2 XP, 2→3: 6 XP, 3→4: 10 XP, 4→5: 20 XP, 5→6: 36 XP, 6→7: 60 XP, 7→8: 90 XP, 8→9: 130 XP
  - В начале каждого раунда автоматически +2 XP
  - Кнопка "Level Up ($4)" в магазине — покупка 4 XP за 4 золота (достижима в UI и через код `player.buy_xp()`)
- [x] **Динамический магазин (Shop Slots):**
  - `shop.shop_slots`: ур 1-6 → 5 карточек, ур 7-8 → 6, ур 9 → 7
  - `shop.TIER_ODDS`: шансы выпадения юнитов по стоимости для каждого уровня (例如 ур 1: 100% 1-cost, ур 5: 40%/35%/20%/5%/0%, ур 9: 5%/15%/30%/30%/20%)
  - `shop.roll()` использует tier odds для определения стоимости каждой карточки, затем выбирает случайного юнита этой стоимости из пула
- [x] **UI:** HUD показывает "Уровень: X (Y/Z XP)" рядом с золотом; кнопка "Level Up ($4)" рядом с рулеткой магазина
- [x] `ui/sprites.py` обновлён — 76 ключей в `_UNIT_TO_FILE`, цвета для классов healer/buffer/assassin
- [x] `ui/game_ui.py` обновлён — 76 ключей в preload_unit_sprites

### 🎨 Исправления UI (верстка и отображение)

1. **Правая панель магазина** — переверстана:
   - Кнопка "Reroll ($1)" вверху
   - Кнопка "XP ($4)" (Level Up) под ней
   - Индикатор уровня игрока "Lvl X (Y/Z XP)" над кнопками
   - Иконка уровня магазина внизу панели
   - Ничего не наезжает друг на друга

2. **Заголовок поля боя** — убран текст "ПОЛЕ 5×5 — клик: поставить/убрать", заменён на динамический "ПОЛЕ (N/M)" где M = `player.level + 1`

3. **Счетчик юнитов на доске** — теперь динамический: показывает `player.level + 1` вместо хардкода "6" (например, "3/3" на уровне 2)

4. **Синергии** — выводятся только если количество юнитов >= 2 (порог активации). Показываются классовые синергии (warrior/mage/archer/healer/buffer/assassin) и расовые (human/orc/demon/elf/undead) — включая эльфийскую «Лесные» (+скорость атаки при 2+ эльфах).

5. **Сетка скамейки** — переделана с 5×2 (10 ячеек) на 3×3 (9 ячеек), симметрично вписана в рамку

6. **Кнопка "Начать раунд (Enter)"** — расширена с 160×36 до 200×44 пикселей, текст не обрезается

### 🐛 Исправление бага: уровень магазина/доски сбрасывался после раунда

**Проблема:** после каждого раунда `Player.level` сбрасывался на 1, поэтому `max_board = level + 1` всегда был 2, даже когда магазин был на 4-м уровне. На поле показывалось `(3/2)` — 3 юнита, но места только для 2.

**Причина:** в `_run_interactive_draft()` каждый раунд создавался новый `Player(gold=gold)`, теряя `player.level` и `player.xp`. Только `self.shop_level` persistil между раундами.

**Исправление:**
- `_run_interactive_draft()` теперь возвращает `player.level` и `player.xp` как 6-е и 7-е значения
- `run_interactive_match()` сохраняет их в `existing` dict и передаёт в следующий раунд
- При создании `Player` уровень и опыт восстанавливаются из сохранённого состояния

Теперь `Player.level` растёт вместе с магазином, и `max_board = level + 1` увеличивается правильно.

### 🔄 В процессе / Требует внимания
- Тестирование игры с новыми спрайтами в боевом режиме
- Балансировка новых юнитов (урон, HP, кд способностей)

### ❌ Не начато
- Генерация спрайтов для вражеских юнитов (если потребуются отдельные)

---

## 5. КАК ЗАПУСТИТЬ ВСЁ (Чек-лист для нового диалога)

### Шаг 1: Запустить ComfyUI
Убедитесь, что ComfyUI запущен на `http://localhost:8188`.
Проверка: `http://localhost:8188/system_stats`

### Шаг 2: Запустить MCP-сервер
```
cd C:\tools\comfy-pilot
run_comfy_mcp.bat
```

### Шаг 3: Запустить OpenCode
Открыть OpenCode с рабочей папкой `C:\AI\OpenCode Projects`.

### Шаг 4: Проверить подключение MCP
В OpenCode должны быть доступны инструменты:
- `comfyui-mcp.generate_image({prompt: "..."})`
- `any_txt_parser.symbols({path: "autobattler/ui/game_ui.py"})`
- `any_txt_parser.read_lines({path: "autobattler/ui/game_ui.py", start: 1, end: 50})`
- `any_txt_parser.search_text({path: "autobattler/", pattern: "some text"})`

### Шаг 5: Запустить игру
```
cd C:\AI\OpenCode Projects\autobattler
python run_ui.py
```
Или через батник: `run_game.bat`

---

## 6. КЛЮЧЕВЫЕ ИНСТРУКЦИИ ПО РАБОТЕ С GENERACIEЙ

### Генерация спрайта через ComfyUI-MCP
```python
tools["comfyui-mcp"].generate_image({prompt: "pixel art sprite, 16-bit, game asset, a brave knight holding a sword, floating in the air, isolated character, no ground, plain white background"})
```

**Важные настройки промпта:**
- НЕ добавляйте "transparent background" в позитивный промпт (FLUX нарисует шахматную доску)
- Используйте `isolated on white background` или `solid white background`
- В негативный промпт добавьте: `transparent background, grid, checkerboard, blurry, photorealistic, 3d, realistic, gradient, noisy, noise, artifacts, floating pixels, solid background`

### Конвейер удаления фона (работающий)
1. `get_workflow()` — получить текущий workflow
2. `ComfyUI-MCP` создаёт изображение
3. `AutoGrabCutRemover` — отделяет объект от фона
4. `InvertMask` — инвертирует маску (персонаж белый, фон чёрный)
5. `JoinImageWithAlpha` — объединяет изображение с альфа-каналом
6. `SaveImage` — сохраняет PNG с альфа-каналом

### Параметры AutoGrabCutRemover (рабочие):
```
unet_name: flux3-image-klein-base-nvfp4.safetensors
clip_name: qwen3vl_4b_int8_convrot.safetensors
vae_name: flux2-vae.safetensors
lora_name: pytorch_lora_weights.safetensors (strength 0.8)
steps: 20, cfg: 3.5, sampler: euler, scheduler: normal
confidence_threshold: 0.35
grabcut_iterations: 10
margin_pixels: 10
edge_refinement: 1.0
edge_blur_amount: 0.0
binary_threshold: 200
scaling_method: NEAREST
output_size: ORIGINAL
```

---

## 7. РЕШЕННЫЕ ПРОБЛЕМЫ (ДЛЯ ССЫЛКИ В БУДУЩЕМ)

| Проблема | Решение |
|----------|---------|
| `head` команда не найдена в PowerShell | Используйте `Get-Content` или `Get-ChildItem` |
| `printf` не работает в PowerShell | Используйте `echo`, `Write-Output` или pipe |
| `head` не найден | Используйте альтернативы PowerShell |
| `head` не найден | Используйте альтернативы PowerShell |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `head` не найден в PowerShell | Используйте `Get-Content` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| `printf` не найден в PowerShell | Используйте `echo` или `Write-Output` |
| Вещи с проданного/удалённого юнита исчезали | `Shop.sell(..., from_board=True)` возвращает `unit["items"]` в `player.items`; `_remove_copies` при слиянии возвращает вещи с доски; `board_format` хранит и восстанавливает `items` (и бонусы) между раундами |

### Проблема с ComfyUI-MCP
- **Не использовать `Comfy Pilot` (jaijia/comfy-pilot-opencode)** — требует плагин в браузере `/claude-code/` endpoint который не работает
- **Использовать `comfy-mcp-server` (dseditor)** — работает напрямую с ComfyUI API

### Проблема с генерацией спрайтов (ComfyUI)
- **FLUX не понимает `transparent background` в промпте** — нарисует шахматную доску
- **Использовать `isolated on white background`** + удалить фон через `AutoGrabCutRemover` + `InvertMask` + `JoinImageWithAlpha`
- **Не использовать `ImageColorToMask` с белым цветом** — FLUX рисует не чистый белый, а серые оттенки

---

## 8. КОД ДЛЯ БЫСТРОГО ЗАПУСКА (Готовые скрипты)

### Запуск генерации спрайта (пример)
```python
import json, urllib.request, urllib.error, time

# Загрузить workflow
with open('C:/Users/kindy/AppData/Local/Comfy-Desktop/ComfyUI-Installs/ComfyUI/ComfyUI/custom_nodes/comfy-mcp-server/workflow/pixel_art_flux_alpha_final.json', 'r') as f:
    workflow = json.load(f)

# Изменить промпт
workflow['5']['inputs']['text'] = 'pixel art sprite, 16-bit, game asset, a brave knight holding a sword, floating in the air, isolated character, no ground, plain white background'

# Отправить
data = json.dumps({'prompt': workflow}).encode('utf-8')
req = urllib.request.Request('http://localhost:8188/prompt', data=data, headers={'Content-Type': 'application/json'}, method='POST')
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode())
prompt_id = result['prompt_id']

# Ожидать результат
for i in range(60):
    time.sleep(1)
    hist_req = urllib.request.Request(f'http://localhost:8188/history/{prompt_id}')
    hist_resp = urllib.request.urlopen(hist_req, timeout=10)
    hist_data = json.loads(hist_resp.read())
    if prompt_id in hist_data:
        entry = hist_data[prompt_id]
        if entry.get('status', {}).get('completed'):
            print('Готово!')
            break
    if i % 10 == 0:
        print(f'Ожидание... ({i}s)')
```

---

## 9. ГДЕ НАЙТИ ВСЁ

| Что | Где |
|-----|-----|
| Конфиг OpenCode | `C:\Users\kindy\.config\opencode\opencode.json` |
| Рабочий конфиг игры | `C:\AI\OpenCode Projects\opencode.json` |
| Рабочая папка | `C:\AI\OpenCode Projects\` |
| Игра | `C:\AI\OpenCode Projects\autobattler\` |
| Спрайты игры | `C:\AI\OpenCode Projects\autobattler\ui\assets\sprites\` |
| Скрипт запуска MCP | `C:\tools\comfy-pilot\run_comfy_mcp.bat` |
| Рабочие процессы ComfyUI | `C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfy-mcp-server\workflow\` |
| any_txt_parser (MCP) | `C:\AI\OpenCode Projects\tools\any_txt_parser.exe` |
| Навыки (Skills) | `C:\Users\kindy\.config\opencode\skills\` (пуста) |
| Документация рабочего процесса | `C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes\comfy-mcp-server\workflow\README_PIXEL_ART_WORKFLOW.md` |

---

## 10. ПОДСКАЗКИ ДЛЯ БУДУЩЕГО

1. **Всегда проверяйте, что ComfyUI запущен** (`http://localhost:8188/system_stats`) перед генерацией спрайтов.
2. **Используйте `AutoGrabCutRemover`** для удаления фона — он работает лучше всего с пиксель-артом.
3. **Никогда не используйте `transparent background` в позитивном промпте** для Flux.
4. **Всегда используйте `type: "flux3"`** для CLIPLoader при работе с Flux моделью.
5. **Пакет `comfy-mcp-server` (dseditor)** — это тот, что работает с ComfyUI.
6. **Всегда сохраняйте workflow в JSON** перед запуском генерации, чтобы можно было повторить.
7. **Игра запускается через `run_ui.py`** в папке `autobattler/`.
8. **any_txt_parser** — используйте `symbols`, `find_symbol`, `read_lines`, `search_text` для навигации по большим файлам (например, `ui/game_ui.py` имеет 3600+ строк), вместо чтения файла целиком.

---

**Дата создания:** 29.10.2026  
**Статус:** Готово к работе  
**Следующий шаг:** Запустить игру (`python run_ui.py`), опробовать новых юнитов (хилеров, бафферов, ассасинов) в бою, проверить систему уровней и опыта