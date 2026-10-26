"""Звук автобатлера: процедурная генерация, без файлов-ассетов.

Всё синтезируется через numpy прямо в памяти — не нужны ни wav-файлы, ни
внешние зависимости. Если звуковое устройство недоступно (headless-тесты,
сервер без аудио), SoundBank молча выключается и игра работает без звука.
"""

import math

import pygame

try:
    import numpy as np
    HAS_NUMPY = True
except Exception:                                    # pragma: no cover
    HAS_NUMPY = False

SAMPLE_RATE = 44100


def _simple_decay(n, decay_time):
    """Экспоненциальная огибающая с длительностью decay_time в секундах."""
    t = np.arange(n) / SAMPLE_RATE
    return np.exp(-t / max(decay_time, 1e-4))


def _noise_burst(duration=0.12, decay=0.08, lowpass=0.25):
    """Фильтрованный шумовой удар — основа для 'попаданий'."""
    n = int(duration * SAMPLE_RATE)
    rng = np.random.default_rng(7)
    x = rng.uniform(-1, 1, n)
    # однополюсный lowpass по накоплению — без цикла на питоне
    acc = np.cumsum(x) * lowpass
    y = acc - np.concatenate(([0.0], acc[:-1]))
    return y * _simple_decay(n, decay)


def _sine(freq, duration=0.15, decay=0.1, phase=0.0):
    n = int(duration * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    return np.sin(2 * math.pi * freq * t + phase) * _simple_decay(n, decay)


def _sweep(f0, f1, duration=0.25, decay=0.18):
    """Частотный свип — «ктош» для способностей."""
    n = int(duration * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    phase = 2 * math.pi * (f0 * t + (f1 - f0) * t ** 2 / (2 * duration))
    return np.sin(phase) * _simple_decay(n, decay)


def _arp(notes, step=0.09, decay=0.25):
    """Короткая арпеджио — победа/поражение."""
    out = []
    for f in notes:
        seg = _sine(f, duration=step + decay, decay=decay)
        # обрезаем «хвост» предыдущей ноты, чтобы шло одна за другой
        out.append(seg)
    total = int((step * len(notes) + decay) * SAMPLE_RATE)
    buf = np.zeros(total)
    for i, seg in enumerate(out):
        start = int(i * step * SAMPLE_RATE)
        buf[start:start + len(seg)] += seg
    return buf


def _mix(*signals):
    """Сложить сигналы разной длины (короткие дополняются нулями)."""
    if not signals:
        return np.zeros(1)
    n = max(len(s) for s in signals)
    out = np.zeros(n)
    for s in signals:
        s = np.asarray(s, dtype=np.float64)
        out[:len(s)] += s
    return out


def _to_sound(arr, volume=0.35):
    """Нормализуем и пакуем в 16-бит. Миксер может быть стерео — дублируем канал."""
    arr = np.asarray(arr, dtype=np.float64)
    peak = np.max(np.abs(arr)) or 1.0
    arr = arr / peak * volume
    pcm = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
    try:
        channels = pygame.mixer.get_init()[2]
    except Exception:
        channels = 1
    if channels and channels > 1:
        pcm = np.column_stack([pcm] * channels)
    return pygame.sndarray.make_sound(pcm)


class SoundBank:
    """Звуки боя. Любой сбой инициализации = тихий режим, не падение."""

    def __init__(self, enabled: bool = True, volume: float = 0.5):
        self.enabled = False
        self.volume = volume
        self.sounds: dict[str, object] = {}
        if not enabled or not HAS_NUMPY:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
        except Exception:
            return                                  # нет аудио — играем без звука
        try:
            self._build()
            self.enabled = True
        except Exception:
            self.enabled = False

    def _build(self):
        self.sounds = {
            # удар: тупой шумовой хлопок
            "hit": _to_sound(_noise_burst(0.10, 0.06, 0.22), 0.30),
            # крит: ярче и звонче
            "crit": _to_sound(_mix(
                _noise_burst(0.09, 0.05, 0.35) * 0.7,
                _sine(880, 0.10, 0.05) * 0.8,
                _sine(1320, 0.08, 0.04) * 0.5), 0.34),
            # смерть: падающий тон
            "kill": _to_sound(_sweep(420, 90, 0.28, 0.20), 0.32),
            # способность: восходящий свип
            "ability": _to_sound(_sweep(220, 900, 0.30, 0.24), 0.28),
            # золото: два быстрых блипа
            "gold": _to_sound(_mix(_sine(1180, 0.07, 0.05),
                                   _sine(1560, 0.09, 0.06)), 0.22),
            # покупка
            "buy": _to_sound(_mix(_sine(700, 0.05, 0.04),
                                  _sine(1050, 0.06, 0.05)), 0.20),
            # клик интерфейса
            "click": _to_sound(_sine(520, 0.04, 0.03), 0.14),
            # победа / поражение
            "win": _to_sound(_arp([523, 659, 784, 1047]), 0.30),
            "lose": _to_sound(_arp([392, 330, 262, 196], step=0.13), 0.30),
        }

    def play(self, name: str, volume_scale: float = 1.0):
        """Проиграть звук, если звук включён."""
        if not self.enabled:
            return
        snd = self.sounds.get(name)
        if snd is None:
            return
        try:
            snd.set_volume(max(0.0, min(1.0, self.volume * volume_scale)))
            snd.play()
        except Exception:
            pass
