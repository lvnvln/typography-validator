# test_image_generator.py
"""
Генератор цветных тестовых изображений (CMYK) без текстов и пунктирных линий.
Цель — быстро получить разные случаи для проверки валидатора/импозитора:
- идеальное изображение,
- больше нормы (нужен даунскейл),
- чуть меньше (апскейл ≤ 1.5),
- слишком маленькое (апскейл > 1.5 → Reject),
- неправильные пропорции (cover + crop),
- низкий dpi (200) — пикселей реально меньше (должен требовать апскейл ≈1.5),
- RGB — должен быть отклонён по цветовому пространству,
- ровно 100×70 мм без вылетов,
- очень крупное (стресс тест даунскейла).

ВАЖНО: мы БОЛЬШЕ НЕ создаём README-файл. Функция generate_all возвращает:
(created_paths, output_dir)
"""

import os
from typing import Tuple, List
import numpy as np
from PIL import Image, ImageDraw
import random
import math

MM_PER_INCH = 25.4
TARGET_W_MM = 100.0
TARGET_H_MM = 70.0
BLEED_MM = 5.0
OUT_DPI = 300

def mm_to_px(mm: float, dpi: int = OUT_DPI) -> int:
    """Миллиметры → пиксели при заданном dpi."""
    return int(round(mm / MM_PER_INCH * dpi))

# Карточка с вылетами 5 мм: 110 × 80 мм @ 300 dpi (в пикселях)
CARD_W_PX = mm_to_px(TARGET_W_MM + 2 * BLEED_MM, OUT_DPI)  # 110 мм
CARD_H_PX = mm_to_px(TARGET_H_MM + 2 * BLEED_MM, OUT_DPI)  # 80  мм

# ---------- графические утилиты ----------

def _rng(seed: int):
    """Детерминированный генератор случайных чисел для воспроизводимости."""
    r = random.Random(seed)
    return r

def _rand_cmyk(r: random.Random, pastel=False):
    """Случайный CMYK-цвет. pastel=True — мягкие светлые тона."""
    if pastel:
        c = r.randint(0, 120)
        m = r.randint(0, 120)
        y = r.randint(0, 120)
        k = r.randint(0, 40)
    else:
        c = r.randint(0, 255)
        m = r.randint(0, 255)
        y = r.randint(0, 255)
        k = r.randint(0, 180)
    return (c, m, y, k)

def _rand_rgb(r: random.Random, pastel=False):
    """Случайный RGB-цвет."""
    if pastel:
        return (r.randint(150, 255), r.randint(150, 255), r.randint(150, 255))
    return (r.randint(0, 255), r.randint(0, 255), r.randint(0, 255))

def _lerp(a, b, t):
    """Линейная интерполяция целочисленных компонент."""
    return int(round(a + (b - a) * t))

def _background_gradient(im: Image.Image, r: random.Random):
    """Вертикальный градиент в текущем цветовом пространстве (CMYK или RGB)."""
    w, h = im.size
    dr = ImageDraw.Draw(im)
    pastel = True
    if im.mode == "CMYK":
        c1 = _rand_cmyk(r, pastel=pastel)
        c2 = _rand_cmyk(r, pastel=pastel)
        for y in range(h):
            t = y / max(1, h - 1)
            col = tuple(_lerp(c1[i], c2[i], t) for i in range(4))
            dr.line([(0, y), (w, y)], fill=col, width=1)
    else:
        c1 = _rand_rgb(r, pastel=pastel)
        c2 = _rand_rgb(r, pastel=pastel)
        for y in range(h):
            t = y / max(1, h - 1)
            col = tuple(_lerp(c1[i], c2[i], t) for i in range(3))
            dr.line([(0, y), (w, y)], fill=col, width=1)

def _star_points(cx, cy, r_outer, r_inner, n=5, start_angle_deg=0.0):
    """Возвращает список вершин «звезды» (для рисования многоугольника-звезды)."""
    pts: List[Tuple[float, float]] = []
    ang = math.radians(start_angle_deg)
    step = math.pi / n
    for i in range(2 * n):
        rr = r_outer if i % 2 == 0 else r_inner
        x = cx + rr * math.cos(ang + i * step)
        y = cy + rr * math.sin(ang + i * step)
        pts.append((x, y))
    return pts

def _draw_shapes(im: Image.Image, r: random.Random):
    """
    Рендерит набор цветных примитивов поверх градиентного фона:
    прямоугольники, эллипсы, произвольные многоугольники, «звёзды», кольца.
    """
    w, h = im.size
    dr = ImageDraw.Draw(im)

    # 1) фоновый градиент
    _background_gradient(im, r)

    # 2) набор фигур
    count = r.randint(6, 10)
    for _ in range(count):
        shape = r.choice(["rect", "ellipse", "polygon", "star", "ring"])
        # случайная область, не слишком маленькая
        x1 = r.randint(0, int(w * 0.6))
        y1 = r.randint(0, int(h * 0.6))
        x2 = r.randint(x1 + int(w * 0.15), min(w, x1 + int(w * 0.9)))
        y2 = r.randint(y1 + int(h * 0.15), min(h, y1 + int(h * 0.9)))
        outline_w = r.randint(2, 6)

        if im.mode == "CMYK":
            fill_col = _rand_cmyk(r, pastel=False)
            outline_col = (0, 0, 0, 255)  # чёрный контур
        else:
            fill_col = _rand_rgb(r, pastel=False)
            outline_col = (0, 0, 0)

        if shape == "rect":
            dr.rectangle([x1, y1, x2, y2], fill=fill_col, outline=outline_col, width=outline_w)

        elif shape == "ellipse":
            dr.ellipse([x1, y1, x2, y2], fill=fill_col, outline=outline_col, width=outline_w)

        elif shape == "polygon":
            # произвольный многоугольник (5–8 вершин)
            n = r.randint(5, 8)
            pts = []
            for _k in range(n):
                px = r.randint(x1, x2)
                py = r.randint(y1, y2)
                pts.append((px, py))
            dr.polygon(pts, fill=fill_col, outline=outline_col)

        elif shape == "star":
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            r_outer = max(10, min((x2 - x1), (y2 - y1)) // 2)
            r_inner = max(5, r_outer // 2)
            pts = _star_points(cx, cy, r_outer, r_inner, n=r.randint(5, 7), start_angle_deg=r.randint(0, 180))
            dr.polygon(pts, fill=fill_col, outline=outline_col)

        elif shape == "ring":
            # кольцо (толстая окружность)
            dr.ellipse([x1, y1, x2, y2], outline=outline_col, width=max(6, outline_w + 4))
            inner_margin = max(8, outline_w + 6)
            dr.ellipse([x1 + inner_margin, y1 + inner_margin, x2 - inner_margin, y2 - inner_margin],
                       outline=fill_col, width=max(4, outline_w + 2))

def _mk(size_px: Tuple[int, int], mode="CMYK", dpi=OUT_DPI, seed: int = 0) -> Image.Image:
    """Создаёт изображение заданного размера/режима и рисует на нём фигуры."""
    r = _rng(seed)
    bg = (0, 0, 0, 0) if mode == "CMYK" else (255, 255, 255)
    im = Image.new(mode, size_px, bg)
    _draw_shapes(im, r)
    return im

def _save(im: Image.Image, path: str, dpi=OUT_DPI):
    """Сохраняет изображение, гарантируя существование папки, прописывает dpi."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, dpi=(dpi, dpi))

# ---------- публичное API ----------

def generate_all(output_dir="test_images"):
    """
    Генерирует набор цветных тестовых изображений.
    Больше НЕ создаёт README. Возвращает (список_файлов, путь_к_папке).
    """
    os.makedirs(output_dir, exist_ok=True)
    created = []

    # 1) Идеальное CMYK 110×80 мм @300 dpi
    im = _mk((CARD_W_PX, CARD_H_PX), "CMYK", OUT_DPI, seed=1)
    p = os.path.join(output_dir, "ok_cmyk_300dpi_110x80mm.tif"); _save(im, p); created.append(p)

    # 2) Большое (нужен даунскейл)
    big = (int(CARD_W_PX * 1.8), int(CARD_H_PX * 1.8))
    im = _mk(big, "CMYK", OUT_DPI, seed=2)
    p = os.path.join(output_dir, "ok_cmyk_big_downscale.tif"); _save(im, p); created.append(p)

    # 3) Чуть меньше (апскейл ~1.4) — допустимо
    small_ok = (int(CARD_W_PX / 1.4), int(CARD_H_PX / 1.4))
    im = _mk(small_ok, "CMYK", OUT_DPI, seed=3)
    p = os.path.join(output_dir, "ok_cmyk_small_up_to_1_5.tif"); _save(im, p); created.append(p)

    # 4) Слишком маленькое (апскейл ~2.0) — Reject
    small_bad = (int(CARD_W_PX / 2.0), int(CARD_H_PX / 2.0))
    im = _mk(small_bad, "CMYK", OUT_DPI, seed=4)
    p = os.path.join(output_dir, "bad_cmyk_too_small_upscale_over_1_5.tif"); _save(im, p); created.append(p)

    # 5) Неправильные пропорции (cover + crop), масштаб ≤1.5
    mis = (int(CARD_W_PX * 1.1), int(CARD_H_PX * 0.85))
    im = _mk(mis, "CMYK", OUT_DPI, seed=5)
    p = os.path.join(output_dir, "ok_cmyk_wrong_ratio_cover_crop.tif"); _save(im, p); created.append(p)

    # 6) Низкий dpi 200 — пикселей меньше (апскейл потребуется ~1.5×)
    low_w = mm_to_px(TARGET_W_MM + 2*BLEED_MM, dpi=200)
    low_h = mm_to_px(TARGET_H_MM + 2*BLEED_MM, dpi=200)
    im = _mk((low_w, low_h), "CMYK", 200, seed=6)
    p = os.path.join(output_dir, "bad_cmyk_low_dpi_200.tif"); _save(im, p, dpi=200); created.append(p)

    # 7) RGB @300dpi — Reject по цветовому пространству
    im = _mk((CARD_W_PX, CARD_H_PX), "RGB", OUT_DPI, seed=7)
    p = os.path.join(output_dir, "bad_rgb_300dpi.tif"); _save(im, p); created.append(p)

    # 8) Ровно 100×70 мм (без вылетов) — валидатор разрешит адаптацию
    im = _mk((mm_to_px(TARGET_W_MM), mm_to_px(TARGET_H_MM)), "CMYK", OUT_DPI, seed=8)
    p = os.path.join(output_dir, "ok_cmyk_100x70mm_no_bleed.tif"); _save(im, p); created.append(p)

    # 9) Очень большое и шумное (стресс тест даунскейла)
    big2 = (CARD_W_PX * 3, CARD_H_PX * 3)
    arr = np.random.randint(0, 25, size=(big2[1], big2[0], 4), dtype=np.uint8)
    im = Image.fromarray(arr, mode="CMYK")
    # поверх шума добавим фигуры
    from random import Random
    _draw_shapes(im, Random(9))
    p = os.path.join(output_dir, "ok_cmyk_huge_downscale_noise.tif"); _save(im, p); created.append(p)

    # README больше не создаём — просто возвращаем список и папку
    return created, os.path.abspath(output_dir)


if __name__ == "__main__":
    paths, folder = generate_all("test_images")
    print("Created:", *paths, sep="\n- ")
    print("Folder:", folder)
