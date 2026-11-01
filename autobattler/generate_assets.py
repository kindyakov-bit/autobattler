"""
Генерация пиксель-арт ассетов через ComfyUI API.
Генерирует спрайты юнитов, фон поля и текстуру панели магазина.
"""
import json
import os
import shutil
import time
import urllib.request
import urllib.error
from pathlib import Path

COMFY_URL = "http://localhost:8188"
WORKFLOW_PATH = Path(
    r"C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI"
    r"\ComfyUI\custom_nodes\comfy-mcp-server\workflow\pixel_art_flux_alpha_final.json"
)

# Папка вывода ComfyUI (где сохраняются сгенерированные изображения)
COMFY_OUTPUT_DIR = Path(
    r"C:\Users\kindy\AppData\Local\Comfy-Desktop\ComfyUI-Shared\output"
)

# Папки сохранения внутри проекта
PROJECT_ROOT = Path(__file__).resolve().parent
UNITS_DIR = PROJECT_ROOT / "assets" / "units"
UI_DIR = PROJECT_ROOT / "assets" / "ui"
UNITS_DIR.mkdir(parents=True, exist_ok=True)
UI_DIR.mkdir(parents=True, exist_ok=True)


def load_workflow():
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def queue_prompt(workflow, retries=3):
    """Отправляет промпт в ComfyUI, возвращает prompt_id."""
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{COMFY_URL}/prompt",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            return result["prompt_id"]
        except Exception as e:
            last_err = e
            print(f"  Попытка {attempt + 1}/{retries} не удалась: {e}")
            time.sleep(3)
    raise last_err


def wait_for_completion(prompt_id, max_wait=600):
    """Ждёт завершения генерации, возвращает историю."""
    start = time.time()
    while time.time() - start < max_wait:
        try:
            req = urllib.request.Request(f"{COMFY_URL}/history/{prompt_id}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                hist = json.loads(resp.read().decode())
            if prompt_id in hist:
                entry = hist[prompt_id]
                if entry.get("status", {}).get("completed"):
                    return entry
                if entry.get("status", {}).get("status_str") == "failed":
                    raise RuntimeError(f"Generation failed for {prompt_id}")
        except Exception as e:
            print(f"  Ошибка при опросе истории: {e}")
        time.sleep(2.0)
    raise TimeoutError(f"Prompt {prompt_id} не завершился за {max_wait}с")


def find_latest_output(prefix, wait_seconds=30):
    """Находит самый свежий файл в выходной папке ComfyUI с данным префиксом."""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        matches = []
        for f in COMFY_OUTPUT_DIR.iterdir():
            if f.name.startswith(prefix) and f.suffix.lower() in (".png", ".jpg", ".webp"):
                matches.append(f)
        if matches:
            # Возвращаем самый свежий
            return max(matches, key=lambda p: p.stat().st_mtime)
        time.sleep(1.0)
    return None


def copy_to_assets(src_path, out_path):
    """Копирует сгенерированный файл в папку ассетов проекта."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, out_path)
    print(f"  Скопировано: {out_path} (источник: {src_path.name})")


def generate_unit_sprite(unit_key, display_name, prompt_text, out_filename):
    """Генерирует один спрайт юнита."""
    out_path = UNITS_DIR / out_filename
    if out_path.exists():
        print(f"\n=== Пропускаю {display_name} ({unit_key}) — файл уже существует: {out_filename} ===")
        return
    print(f"\n=== Генерирую спрайт: {display_name} ({unit_key}) ===")
    print(f"  Промпт: {prompt_text}")

    wf = load_workflow()
    wf["5"]["inputs"]["text"] = prompt_text
    wf["13"]["inputs"]["filename_prefix"] = f"unit_{unit_key}"
    wf["8"]["inputs"]["seed"] = int(time.time() * 1000) % (2**31)

    prompt_id = queue_prompt(wf)
    print(f"  Prompt ID: {prompt_id}")
    entry = wait_for_completion(prompt_id)

    # Ищем сгенерированный файл на диске
    src = find_latest_output(f"unit_{unit_key}_")
    if src is None:
        print(f"  ОШИБКА: не найден сгенерированный файл для {unit_key}")
        return

    copy_to_assets(src, UNITS_DIR / out_filename)


def generate_board_texture(prompt_text, out_filename):
    """Генерирует текстуру фона игрового поля."""
    print(f"\n=== Генерирую фон поля: {out_filename} ===")
    print(f"  Промпт: {prompt_text}")

    wf = load_workflow()
    wf["5"]["inputs"]["text"] = prompt_text
    wf["13"]["inputs"]["filename_prefix"] = f"board_bg"
    wf["8"]["inputs"]["seed"] = int(time.time() * 1000) % (2**31)

    prompt_id = queue_prompt(wf)
    entry = wait_for_completion(prompt_id)

    src = find_latest_output("board_bg_")
    if src is None:
        print(f"  ОШИБКА: не найден сгенерированный файл для фона поля")
        return

    copy_to_assets(src, UI_DIR / out_filename)


def generate_panel_texture(prompt_text, out_filename):
    """Генерирует текстуру панели магазина/скамейки."""
    print(f"\n=== Генерирую текстуру панели: {out_filename} ===")
    print(f"  Промпт: {prompt_text}")

    wf = load_workflow()
    wf["5"]["inputs"]["text"] = prompt_text
    wf["13"]["inputs"]["filename_prefix"] = f"panel_bg"
    wf["8"]["inputs"]["seed"] = int(time.time() * 1000) % (2**31)

    prompt_id = queue_prompt(wf)
    entry = wait_for_completion(prompt_id)

    src = find_latest_output("panel_bg_")
    if src is None:
        print(f"  ОШИБКА: не найден сгенерированный файл для панели")
        return

    copy_to_assets(src, UI_DIR / out_filename)


if __name__ == "__main__":
    # 1. Юниты — пиксель-арт спрайты с прозрачным фоном
    generate_unit_sprite(
        "skeleton",
        "Скелет",
        "pixel art sprite, 16-bit game asset, a skeleton warrior holding a rusty sword, "
        "floating in the air, isolated character, no ground, plain white background, "
        "bone armor, red glowing eyes, fantasy undead",
        "skeleton.png",
    )

    generate_unit_sprite(
        "imp",
        "Бес",
        "pixel art sprite, 16-bit game asset, a small red demon imp with horns and tail, "
        "casting fire magic, floating in the air, isolated character, no ground, "
        "plain white background, cute demon, fantasy",
        "imp.png",
    )

    generate_unit_sprite(
        "freshman",
        "Новобранец",
        "pixel art sprite, 16-bit game asset, a human recruit warrior with leather armor "
        "and wooden sword, floating in the air, isolated character, no ground, "
        "plain white background, fantasy soldier",
        "freshman.png",
    )

    generate_unit_sprite(
        "ranger",
        "Следопыт",
        "pixel art sprite, 16-bit game asset, a human ranger archer with hooded cloak "
        "and bow, floating in the air, isolated character, no ground, plain white "
        "background, fantasy archer",
        "ranger.png",
    )

    generate_unit_sprite(
        "elf_ranger",
        "Эльф-следопыт",
        "pixel art sprite, 16-bit game asset, an elf archer with pointed ears, green "
        "cloak and bow, floating in the air, isolated character, no ground, plain white "
        "background, fantasy elf",
        "elf_ranger.png",
    )

    # Юниты-воины (warrior)
    generate_unit_sprite(
        "warrior_veteran",
        "Ветеран",
        "pixel art sprite, 16-bit game asset, a human veteran warrior in steel armor "
        "with sword and shield, floating in the air, isolated character, no ground, "
        "plain white background, fantasy soldier",
        "warrior_veteran.png",
    )

    generate_unit_sprite(
        "warrior_champion",
        "Чемпион",
        "pixel art sprite, 16-bit game asset, a human champion warrior in golden armor "
        "with glowing sword, floating in the air, isolated character, no ground, "
        "plain white background, fantasy elite warrior",
        "warrior_champion.png",
    )

    generate_unit_sprite(
        "warrior_knight",
        "Рыцарь",
        "pixel art sprite, 16-bit game asset, a human knight in heavy plate armor with "
        "greatsword, floating in the air, isolated character, no ground, plain white "
        "background, fantasy knight tank",
        "warrior_knight.png",
    )

    generate_unit_sprite(
        "orc_warrior_berserker",
        "Берсерк",
        "pixel art sprite, 16-bit game asset, an orc berserker warrior with fur armor "
        "and double axe, floating in the air, isolated character, no ground, plain white "
        "background, fantasy orc warrior",
        "orc_berserker.png",
    )

    generate_unit_sprite(
        "orc_warrior_chief",
        "Вождь орков",
        "pixel art sprite, 16-bit game asset, an orc chieftain warrior with horned "
        "helmet and warhammer, floating in the air, isolated character, no ground, "
        "plain white background, fantasy orc chief",
        "orc_chief.png",
    )

    # Маги (mage)
    generate_unit_sprite(
        "mage_acolyte",
        "Послушник",
        "pixel art sprite, 16-bit game asset, a human mage acolyte with blue robe and "
        "staff, floating in the air, isolated character, no ground, plain white "
        "background, fantasy mage apprentice",
        "mage_acolyte.png",
    )

    generate_unit_sprite(
        "mage_sorcerer",
        "Маг-чародей",
        "pixel art sprite, 16-bit game asset, a human sorcerer with dark red robe and "
        "fire magic staff, floating in the air, isolated character, no ground, plain "
        "white background, fantasy dark mage",
        "mage_sorcerer.png",
    )

    generate_unit_sprite(
        "mage_archmage",
        "Архимаг",
        "pixel art sprite, 16-bit game asset, a human archmage with purple robe and "
        "crystal staff, floating in the air, isolated character, no ground, plain white "
        "background, fantasy archmage",
        "mage_archmage.png",
    )

    generate_unit_sprite(
        "mage_sage",
        "Мудрец",
        "pixel art sprite, 16-bit game asset, a human sage wizard with white beard and "
        "grey robe, floating in the air, isolated character, no ground, plain white "
        "background, fantasy wise wizard",
        "mage_sage.png",
    )

    generate_unit_sprite(
        "demon_mage_succubus",
        "Суккуб",
        "pixel art sprite, 16-bit game asset, a demon succubus with red skin, horns, "
        "wings and dark dress, floating in the air, isolated character, no ground, "
        "plain white background, fantasy demon",
        "demon_succubus.png",
    )

    generate_unit_sprite(
        "undead_warrior_lich",
        "Лич",
        "pixel art sprite, 16-bit game asset, an undead lich with skeleton body, "
        "dark robe and necromancy staff, floating in the air, isolated character, no "
        "ground, plain white background, fantasy undead lich",
        "undead_lich.png",
    )

    # Лучники (archer)
    generate_unit_sprite(
        "archer_scout",
        "Скаут",
        "pixel art sprite, 16-bit game asset, a human scout archer with leather armor "
        "and short bow, floating in the air, isolated character, no ground, plain white "
        "background, fantasy scout",
        "archer_scout.png",
    )

    generate_unit_sprite(
        "archer_marksman",
        "Снайпер",
        "pixel art sprite, 16-bit game asset, a human marksman archer with hood and "
        "longbow, floating in the air, isolated character, no ground, plain white "
        "background, fantasy marksman",
        "archer_marksman.png",
    )

    generate_unit_sprite(
        "archer_battleheart",
        "Боевое Сердце",
        "pixel art sprite, 16-bit game asset, a human legendary archer with ornate "
        "armor and enchanted bow, floating in the air, isolated character, no ground, "
        "plain white background, fantasy legendary archer",
        "archer_battleheart.png",
    )

    generate_unit_sprite(
        "elf_archer_hunter",
        "Эльф-охотник",
        "pixel art sprite, 16-bit game asset, an elf hunter with pointed ears, green "
        "cloak and bow, floating in the air, isolated character, no ground, plain white "
        "background, fantasy elf hunter",
        "elf_hunter.png",
    )

    # 2. Фон игрового поля (5x5)
    generate_board_texture(
        "pixel art game board background, dark fantasy stone tiles, 5x5 grid, "
        "cobblestone dungeon floor, moss and cracks, seamless texture, "
        "dark atmospheric, top-down view, game asset",
        "board_bg.png",
    )

    # 3. Текстура панели магазина/скамейки
    generate_panel_texture(
        "pixel art UI panel background, dark wood with golden trim, fantasy game "
        "interface, ornate carved edges, metal corners, seamless texture, "
        "shop panel background, tavern style",
        "panel_bg.png",
    )

    # Иконки для экрана результатов боя
    generate_unit_sprite(
        "icon_damage",
        "Иконка урона",
        "pixel art icon, 16-bit game asset, crossed swords and fireball, "
        "floating in the air, isolated character, no ground, plain white background, "
        "fantasy damage icon, glowing",
        "icon_damage.png",
    )

    generate_unit_sprite(
        "icon_kills",
        "Иконка киллов",
        "pixel art icon, 16-bit game asset, skull and crossbones, "
        "floating in the air, isolated character, no ground, plain white background, "
        "fantasy kills icon, red",
        "icon_kills.png",
    )

    print("\n=== ВСЕ АССЕТЫ СГЕНЕРИРОВАНЫ ===")
