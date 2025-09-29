# imposer.py
"""
Сборка макетов A4 из подготовленных карточек 110×80 мм @ 300 dpi (CMYK).
Поддержка:
- пунктирной линии по линии обреза (100×70 мм внутри карточки 110×80 мм),
- уголковых меток реза по углам каждой карточки,
- сохранение страниц в TIFF (LZW) или JPEG,
- режим CMYK: DeviceCMYK (без профиля) или встраивание загруженного ICC-профиля (без цветоконвертации).

ВНИМАНИЕ: никакой цветовой конвертации здесь нет. Если выбран Embed ICC, профиль просто встраивается
в сохранённый файл для корректной типографской интерпретации, но цвета не пересчитываются.
"""

from __future__ import annotations
import os
import io
import math
import zipfile
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

from PIL import Image, ImageDraw

# ---------- геометрия и единицы ----------

MM_PER_INCH = 25.4

def mm_to_px(mm: float, dpi: int = 300) -> int:
    """Перевод мм в пиксели, округление до ближайшего int."""
    return int(round(mm / MM_PER_INCH * dpi))

def a4_size_mm(orientation: str = "landscape") -> Tuple[float, float]:
    """Размер листа A4 в мм. orientation: 'landscape' | 'portrait'."""
    W, H = 210.0, 297.0
    if orientation == "landscape":
        return (297.0, 210.0)
    return (W, H)

# Целевая карточка: 110×80 мм (100×70 обрезной + по 5 мм вылет)
CARD_W_MM = 110.0
CARD_H_MM = 80.0

# Внутренний обрезной прямоугольник (100×70 мм) — для пунктира
TRIM_W_MM = 100.0
TRIM_H_MM = 70.0
BLEED_MM = 5.0  # отступ от внешнего края карточки до линии обреза


@dataclass
class A4LayoutSettings:
    """Параметры сетки и оформления листа A4."""
    orientation: str = "landscape"   # фиксируем в проекте на landscape
    rows: int = 2
    cols: int = 2
    margin_mm: float = 10.0          # поля по периметру листа
    gutter_x_mm: float = 5.0         # интервалы между карточками по X
    gutter_y_mm: float = 5.0         # интервалы между карточками по Y
    crop_mark_len_mm: float = 3.0    # длина уголковой метки (и длина штриха пунктира)
    out_format: str = "TIFF_LZW"     # "TIFF_LZW" | "JPEG"
    cmyk_profile_path: Optional[str] = None  # путь к .icc/.icm, если нужно встраивать
    dpi: int = 300

    # визуальные параметры линий
    crop_mark_stroke_px: int = 3
    draw_trim_dashed: bool = True
    trim_dash_len_mm: Optional[float] = None  # если None — берём crop_mark_len_mm
    trim_dash_gap_mm: Optional[float] = None  # если None — берём crop_mark_len_mm
    trim_dash_stroke_px: int = 3
    corner_brackets: bool = True


class A4Imposer:
    """
    Импозитор, который раскладывает карточки по листам A4 и рисует разметку.
    """

    def __init__(self, settings: A4LayoutSettings):
        self.s = settings

        # Рассчитываем пиксельные размеры карточки/листа/отступов
        self.card_w_px = mm_to_px(CARD_W_MM, self.s.dpi)
        self.card_h_px = mm_to_px(CARD_H_MM, self.s.dpi)
        self.trim_w_px = mm_to_px(TRIM_W_MM, self.s.dpi)   # пунктир
        self.trim_h_px = mm_to_px(TRIM_H_MM, self.s.dpi)
        self.bleed_px  = mm_to_px(BLEED_MM, self.s.dpi)

        a4_w_mm, a4_h_mm = a4_size_mm(self.s.orientation)
        self.sheet_w_px = mm_to_px(a4_w_mm, self.s.dpi)
        self.sheet_h_px = mm_to_px(a4_h_mm, self.s.dpi)

        self.margin_px = mm_to_px(self.s.margin_mm, self.s.dpi)
        self.gx_px = mm_to_px(self.s.gutter_x_mm, self.s.dpi)
        self.gy_px = mm_to_px(self.s.gutter_y_mm, self.s.dpi)

        # Параметры пунктира
        base_len_mm = self.s.crop_mark_len_mm
        dash_len_mm = self.s.trim_dash_len_mm if self.s.trim_dash_len_mm is not None else base_len_mm
        dash_gap_mm = self.s.trim_dash_gap_mm if self.s.trim_dash_gap_mm is not None else base_len_mm
        self.trim_dash_len_px = max(1, mm_to_px(dash_len_mm, self.s.dpi))
        self.trim_dash_gap_px = max(1, mm_to_px(dash_gap_mm, self.s.dpi))

    # --------- рисование пунктирной линии по линии обреза ---------

    def _draw_dashed_rect(self, dr: ImageDraw.ImageDraw, rect: Tuple[int,int,int,int], stroke_px: int = 2):
        """
        Рисует пунктирный прямоугольник по заданной рамке.
        rect = (x1, y1, x2, y2) — координаты линии обреза.
        """
        x1, y1, x2, y2 = rect
        dash = self.trim_dash_len_px
        gap  = self.trim_dash_gap_px

        # Верхняя/нижняя стороны
        x = x1
        while x < x2:
            x_end = min(x + dash, x2)
            dr.line([(x, y1), (x_end, y1)], fill=(0,0,0,255), width=stroke_px)
            dr.line([(x, y2), (x_end, y2)], fill=(0,0,0,255), width=stroke_px)
            x += dash + gap

        # Левая/правая стороны
        y = y1
        while y < y2:
            y_end = min(y + dash, y2)
            dr.line([(x1, y), (x1, y_end)], fill=(0,0,0,255), width=stroke_px)
            dr.line([(x2, y), (x2, y_end)], fill=(0,0,0,255), width=stroke_px)
            y += dash + gap

    # --------- уголковые метки (crop marks) ---------

    def _draw_corner_marks(self, dr: ImageDraw.ImageDraw, inner: Tuple[int,int,int,int]):
        ix1, iy1, ix2, iy2 = inner
        L = mm_to_px(self.s.crop_mark_len_mm, self.s.dpi)
        w = self.s.crop_mark_stroke_px

        # левый верх (┌): горизонтальная влево, вертикальная вверх — ОТ линии обреза наружу
        dr.line([(ix1 - L, iy1), (ix1, iy1)], fill=(0,0,0,255), width=w)
        dr.line([(ix1, iy1 - L), (ix1, iy1)], fill=(0,0,0,255), width=w)

        # правый верх (┐)
        dr.line([(ix2, iy1), (ix2 + L, iy1)], fill=(0,0,0,255), width=w)
        dr.line([(ix2, iy1 - L), (ix2, iy1)], fill=(0,0,0,255), width=w)

        # правый низ (┘)
        dr.line([(ix2, iy2), (ix2 + L, iy2)], fill=(0,0,0,255), width=w)
        dr.line([(ix2, iy2), (ix2, iy2 + L)], fill=(0,0,0,255), width=w)

        # левый низ (└)
        dr.line([(ix1 - L, iy2), (ix1, iy2)], fill=(0,0,0,255), width=w)
        dr.line([(ix1, iy2), (ix1, iy2 + L)], fill=(0,0,0,255), width=w)


    # --------- страница и размещение карточек ---------

    def _new_sheet(self) -> Image.Image:
        """
        Создаёт новый чистый лист A4 в CMYK.
        Белый фон (0,0,0,0 для CMYK эквивалентно 100% белому при некоторых интерпретациях),
        поэтому зададим именно белый (0,0,0,0) — это ок для печати как «без краски».
        """
        return Image.new("CMYK", (self.sheet_w_px, self.sheet_h_px), (0, 0, 0, 0))

    def _card_bbox_on_grid(self, row: int, col: int) -> Tuple[int,int,int,int]:
        """
        Возвращает (x1,y1,x2,y2) внешней рамки карточки на листе по индексу строки/колонки.
        """
        x1 = self.margin_px + col * (self.card_w_px + self.gx_px)
        y1 = self.margin_px + row * (self.card_h_px + self.gy_px)
        x2 = x1 + self.card_w_px
        y2 = y1 + self.card_h_px
        return x1, y1, x2, y2

    def _paste_card(self, sheet: Image.Image, card: Image.Image, outer: Tuple[int,int,int,int]):
        """
        Вклеивает карточку (CMYK) на лист A4 по outer-рамке.
        """
        x1, y1, x2, y2 = outer
        if card.size != (x2 - x1, y2 - y1):
            card = card.resize((x2 - x1, y2 - y1), resample=Image.LANCZOS)
        sheet.paste(card, (x1, y1))

    def _draw_card_guides(self, sheet: Image.Image, outer: Tuple[int,int,int,int]):
        dr = ImageDraw.Draw(sheet)

        # ВНУТРЕННЯЯ ЛИНИЯ ОБРЕЗА: строго на расстоянии bleed от внешних границ,
        # чтобы избежать накопления ошибок округления
        ix1 = outer[0] + self.bleed_px
        iy1 = outer[1] + self.bleed_px
        ix2 = outer[2] - self.bleed_px
        iy2 = outer[3] - self.bleed_px
        inner = (ix1, iy1, ix2, iy2)

        # Пунктир по линии обреза
        if self.s.draw_trim_dashed:
            self._draw_dashed_rect(dr, inner, stroke_px=self.s.trim_dash_stroke_px)

        # УГОЛКОВЫЕ МЕТКИ — теперь по ЛИНИИ ОБРЕЗА
        if self.s.corner_brackets:
            self._draw_corner_marks(dr, inner)


    # --------- сохранение страниц и предпросмотры ---------

    @staticmethod
    def _save_with_icc(img: Image.Image, path: str, fmt: str, icc_bytes: Optional[bytes]):
        """
        Сохранение с/без ICC-профиля. fmt: "TIFF_LZW" | "JPEG".
        Для TIFF используем LZW; для JPEG — качество 95 без субсемплинга.
        """
        if fmt == "TIFF_LZW":
            kwargs = {"compression": "tiff_lzw"}
        else:
            kwargs = {"quality": 95, "subsampling": 0}

        if icc_bytes:
            kwargs["icc_profile"] = icc_bytes

        img.save(path, **kwargs)

    def impose(self, cards: List[Image.Image], out_dir: str, attach_icc: bool = False) -> Dict[str, List[str] | str]:
        """
        Собирает страницы A4 из списка карточек.
        Возвращает:
            {
              "pages": [пути к TIFF/JPEG],
              "previews": [пути к PNG],
              "zip": путь к архиву с pages
            }
        """
        os.makedirs(out_dir, exist_ok=True)

        # Загружаем ICC-профиль, если нужно встроить
        icc_bytes = None
        if attach_icc and self.s.cmyk_profile_path and os.path.isfile(self.s.cmyk_profile_path):
            try:
                with open(self.s.cmyk_profile_path, "rb") as f:
                    icc_bytes = f.read()
            except Exception:
                icc_bytes = None  # если не читабельно — просто не встраиваем

        pages: List[str] = []
        previews: List[str] = []

        per_page = self.s.rows * self.s.cols
        idx = 0
        page_num = 1

        while idx < len(cards):
            sheet = self._new_sheet()

            # Размещаем карточки по сетке
            for r in range(self.s.rows):
                for c in range(self.s.cols):
                    if idx >= len(cards):
                        break
                    outer = self._card_bbox_on_grid(r, c)
                    self._paste_card(sheet, cards[idx], outer)
                    self._draw_card_guides(sheet, outer)
                    idx += 1
                if idx >= len(cards):
                    break

            # Сохраняем страницу
            base = f"page_{page_num:03d}"
            ext = ".tif" if self.s.out_format == "TIFF_LZW" else ".jpg"
            page_path = os.path.join(out_dir, base + ext)
            self._save_with_icc(sheet, page_path, self.s.out_format, icc_bytes)
            pages.append(page_path)

            # Превью (PNG, уменьшенное по ширине до ~1500 px)
            preview_path = os.path.join(out_dir, base + "_preview.png")
            scale = 1500 / sheet.width
            if scale < 1.0:
                w = int(sheet.width * scale)
                h = int(sheet.height * scale)
                prev = sheet.resize((w, h), resample=Image.BICUBIC)
            else:
                prev = sheet.copy()
            prev = prev.convert("RGB")  # PNG без CMYK
            prev.save(preview_path)
            previews.append(preview_path)

            page_num += 1

        # Упаковываем страницы в ZIP
        zip_path = os.path.join(out_dir, "pages.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in pages:
                zf.write(p, arcname=os.path.basename(p))

        return {"pages": pages, "previews": previews, "zip": zip_path}
