"""Единый разбор имён юнитов и множители звёзд.

Формат имени: ``base`` (★1) или ``base★2`` / ``base★3``.
Раньше парсинг был скопирован в shop/player/round/ui и в части мест
использовал неверный срез ``[1:]`` (падал на ``int("")``). Теперь все
обращаются сюда.
"""

STAR_MULTIPLIERS = {1: 1.0, 2: 1.5, 3: 2.0}


def base_name(name: str) -> str:
    """Имя без суффикса звезды: ``warrior★2`` -> ``warrior``."""
    return name.split("★")[0]


def star_level(name: str) -> int:
    """Звезда из имени: ``warrior★2`` -> 2, ``warrior`` -> 1."""
    if "★" not in name:
        return 1
    suffix = name.split("★")[1]
    return int(suffix) if suffix.isdigit() else 1


def star_multiplier(star: int) -> float:
    """Множитель статов для звезды (★2 = ×1.5, ★3 = ×2.0)."""
    return STAR_MULTIPLIERS.get(star, 1.0)