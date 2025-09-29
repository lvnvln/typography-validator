# app.py
"""
Графический интерфейс (Gradio) для:
1) проверки изображений по требованиям типографии и подготовки карточек 110×80 мм (100×70 + вылеты 5 мм) @ 300 dpi;
2) сборки макетов A4 (альбом) из подготовленных карточек с пунктирной линией обреза и «уголковыми» метками;
3) генерации тестовых картинок (цветные фигуры) и их скачивания ZIP;
4) выбора режима CMYK: DeviceCMYK (без профиля) или Embed ICC профиль (поле загрузки видно только при выборе режима);
5) формирования лог-отчёта (CSV/XLSX) по кнопке.
"""

from __future__ import annotations
import os
import zipfile
import tempfile
import math
from io import BytesIO
from typing import List, Optional

import pandas as pd
import gradio as gr
from PIL import Image, ImageCms

from validator import ImagePreparer
from imposer import A4Imposer, A4LayoutSettings, a4_size_mm, mm_to_px

# Что можно загружать во входное окно
SUPPORTED = (".jpg", ".jpeg", ".tif", ".tiff", ".png", ".bmp", ".webp", ".psd", ".eps", ".zip")

# Геометрия карточки (включая вылеты 5 мм по каждой стороне)
CARD_W_MM = 110.0
CARD_H_MM = 80.0

# Фиксированная ориентация листа (самая выгодная для горизонтальной карточки)
A4_ORIENTATION = "landscape"


class GradioPrintA4:
    def __init__(self):
        # Подготовка/валидация
        self.prep = ImagePreparer()
        self.results: List[dict] = []               # результаты проверки (по одному на файл)
        self.prepared_cards: List[Image.Image] = [] # PIL CMYK 110×80 @300dpi

        # Макет/страницы (временные артефакты)
        self.tmp_layout_dir: Optional[str] = None   # временная папка со страницами A4
        self.tmp_pages: List[str] = []              # пути к итоговым страницам
        self.a4_previews: List[str] = []            # PNG-превью страниц
        self.a4_zip: Optional[str] = None           # ZIP макетов (по кнопке)

        # Тестовые изображения
        self.last_generated_dir: Optional[str] = None
        self.tests_zip: Optional[str] = None        # ZIP тестов (по кнопке)

        # Файлы логов (только по кнопке)
        self.log_csv_path: Optional[str] = None
        self.log_xlsx_path: Optional[str] = None

    # ---------------- Утилиты ----------------

    def _collect_mixed(self, files) -> List[str]:
        """
        Принимает список путей/объектов gr.File (или один объект),
        разворачивает ZIP, копирует одиночные изображения во временную папку
        и возвращает список путей к файлам-изображениям.
        """
        if not files:
            return []
        workdir = tempfile.mkdtemp(prefix="cal_mix_")
        acc: List[str] = []

        seq = files if isinstance(files, list) else [files]
        for item in seq:
            path = item if isinstance(item, str) else getattr(item, "name", None)
            if not path:
                continue
            ext = os.path.splitext(path)[1].lower()
            if ext == ".zip":
                try:
                    with zipfile.ZipFile(path, "r") as zf:
                        zf.extractall(workdir)
                    for root, _, names in os.walk(workdir):
                        for n in names:
                            if os.path.splitext(n)[1].lower() in (".jpg",".jpeg",".tif",".tiff",".png",".bmp",".webp",".psd",".eps"):
                                acc.append(os.path.join(root, n))
                except Exception:
                    # игнорируем битый zip
                    pass
            elif ext in (".jpg",".jpeg",".tif",".tiff",".png",".bmp",".webp",".psd",".eps"):
                dst = os.path.join(workdir, os.path.basename(path))
                try:
                    with open(path, "rb") as src, open(dst, "wb") as out:
                        out.write(src.read())
                    acc.append(dst)
                except Exception:
                    pass

        # уникализируем
        uniq, seen = [], set()
        for p in acc:
            if p not in seen:
                seen.add(p); uniq.append(p)
        return uniq

    def _sanitize_num(self, value, min_v, max_v, default_v, name, unit=""):
        """Числовые (float) параметры с автоподстановкой дефолта при некорректном вводе."""
        try:
            x = float(value)
            if math.isnan(x) or math.isinf(x) or x < min_v or x > max_v:
                return float(default_v), f"Поле «{name}» было некорректным, установлено по умолчанию: {default_v}{unit}."
            return x, None
        except Exception:
            return float(default_v), f"Поле «{name}» было некорректным, установлено по умолчанию: {default_v}{unit}."

    def _sanitize_int(self, value, min_v, max_v, default_v, name):
        """Целочисленные параметры с автоподстановкой дефолта."""
        try:
            x = int(value)
            if x < min_v or x > max_v:
                return int(default_v), f"Поле «{name}» было некорректным, установлено по умолчанию: {default_v}."
            return x, None
        except Exception:
            return int(default_v), f"Поле «{name}» было некорректным, установлено по умолчанию: {default_v}."

    @staticmethod
    def _force_exact_card_size(img: Image.Image, target_w_px: int, target_h_px: int) -> Image.Image:
        """Гарантируем точный размер карточки по пикселям (под сетку)."""
        if img.width == target_w_px and img.height == target_h_px:
            return img
        return img.resize((int(target_w_px), int(target_h_px)), resample=Image.LANCZOS)

    @staticmethod
    def _format_wh(x) -> str:
        try:
            if isinstance(x, (list, tuple)) and len(x) == 2:
                return f"{int(round(float(x[0])))}×{int(round(float(x[1])))}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _to_float_or_empty(x):
        try:
            return float(x)
        except Exception:
            return ""

    @staticmethod
    def _probe_icc_profile(image_path: str) -> tuple[bool, Optional[str]]:
        """Вернёт (есть ли ICC, имя профиля)."""
        try:
            with Image.open(image_path) as im:
                icc_bytes = im.info.get("icc_profile")
                if not icc_bytes:
                    return False, None
                prof = ImageCms.ImageCmsProfile(BytesIO(icc_bytes))
                return True, ImageCms.getProfileName(prof)
        except Exception:
            return False, None

    def _compute_max_grid(self, margin_mm: float, gx_mm: float, gy_mm: float):
        """Максимально возможные кол-ва колонок/строк для текущих полей/интервалов."""
        a4_w, a4_h = a4_size_mm(A4_ORIENTATION)
        avail_w = max(0.0, a4_w - 2*max(0.0, margin_mm))
        avail_h = max(0.0, a4_h - 2*max(0.0, margin_mm))
        W, H = CARD_W_MM, CARD_H_MM
        GX, GY = max(0.0, gx_mm), max(0.0, gy_mm)
        max_cols = 0 if W <= 0 else int((avail_w + GX) // (W + GX)) if (W + GX) > 0 else 0
        max_rows = 0 if H <= 0 else int((avail_h + GY) // (H + GY)) if (H + GY) > 0 else 0
        return max_cols, max_rows

    def _reset_runtime(self):
        """Сбрасываем все временные артефакты сборки/логов."""
        self.tmp_layout_dir = None
        self.tmp_pages = []
        self.a4_previews = []
        self.a4_zip = None
        self.log_csv_path = None
        self.log_xlsx_path = None

    # ---------------- Проверка / подготовка ----------------

    def validate_from_inputs(self, mixed_files):
        """Кнопка «Проверить и подготовить» — загруженные файлы и/или ZIP."""
        paths = []
        if isinstance(mixed_files, list):
            paths = [p if isinstance(p, str) else getattr(p, "name", None) for p in mixed_files]
        elif mixed_files:
            paths = [mixed_files if isinstance(mixed_files, str) else getattr(mixed_files, "name", None)]

        sources = self._collect_mixed(paths)
        if not sources:
            return gr.update(value="Инфо: загрузите изображения и/или ZIP с изображениями."), pd.DataFrame(), ""

        # сброс состояния
        self.results.clear()
        self.prepared_cards.clear()
        self._reset_runtime()

        rows = []
        for p in sources:
            r = self.prep.prepare_card(p)
            ok = r["ok"]
            reasons = "; ".join(r.get("reasons", []))
            note = r.get("notes", "")
            info = r.get("info", {})
            scale_used = info.get("scale_used", None)

            rows.append({
                "Файл": os.path.basename(p),
                "Статус": "OK" if ok else "Нельзя",
                "Причина/примечание": reasons or note,
                "Mode": info.get("mode") or "",
                "DPI": (self._to_float_or_empty(info.get("dpi")[0]) if isinstance(info.get("dpi"), (list, tuple))
                        else self._to_float_or_empty(info.get("dpi"))),
                "Исх. размер (px)": self._format_wh(info.get("src_size_px")),
                "Целевой (px)": self._format_wh(info.get("target_px")),
                "Масштаб": f"{(scale_used if scale_used else 1.0):.3f}" if ok else "",
            })
            if ok and r.get("prepared") is not None:
                self.prepared_cards.append(r["prepared"])
            self.results.append({"path": p, **r})

        ok_cnt = sum(1 for x in self.results if x["ok"])
        status = f"Готово: найдено {len(sources)} файлов; подготовлено {ok_cnt}; отклонено {len(sources)-ok_cnt}."
        df = pd.DataFrame(rows)
        return gr.update(value=status), df, ""

    def validate_from_generated(self):
        """Использовать последний набор сгенерированных тестов для проверки."""
        folder = self.last_generated_dir
        files = []
        if folder and os.path.isdir(folder):
            files = [os.path.join(folder, f) for f in os.listdir(folder)
                     if os.path.splitext(f)[1].lower() in (".jpg",".jpeg",".tif",".tiff",".png",".bmp",".webp",".psd",".eps")]
        if not files:
            return gr.update(value="Инфо: сперва сгенерируйте тестовые изображения."), pd.DataFrame(), ""

        self.results.clear()
        self.prepared_cards.clear()
        self._reset_runtime()

        rows = []
        for p in files:
            r = self.prep.prepare_card(p)
            ok = r["ok"]
            reasons = "; ".join(r.get("reasons", []))
            note = r.get("notes", "")
            info = r.get("info", {})
            scale_used = info.get("scale_used", None)

            rows.append({
                "Файл": os.path.basename(p),
                "Статус": "OK" if ok else "Нельзя",
                "Причина/примечание": reasons or note,
                "Mode": info.get("mode") or "",
                "DPI": (self._to_float_or_empty(info.get("dpi")[0]) if isinstance(info.get("dpi"), (list, tuple))
                        else self._to_float_or_empty(info.get("dpi"))),
                "Исх. размер (px)": self._format_wh(info.get("src_size_px")),
                "Целевой (px)": self._format_wh(info.get("target_px")),
                "Масштаб": f"{(scale_used if scale_used else 1.0):.3f}" if ok else "",
            })
            if ok and r.get("prepared") is not None:
                self.prepared_cards.append(r["prepared"])
            self.results.append({"path": p, **r})

        ok_cnt = sum(1 for x in self.results if x["ok"])
        status = f"Готово (тесты): найдено {len(files)} файлов; подготовлено {ok_cnt}; отклонено {len(files)-ok_cnt}."
        df = pd.DataFrame(rows)
        return gr.update(value=status), df, ""

    def show_details(self, evt: gr.SelectData):
        """Клик по строке таблицы — подробности (без Markdown-форматирования)."""
        if not self.results or evt is None:
            return ""
        idx = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        if idx is None or not (0 <= idx < len(self.results)):
            return ""
        r = self.results[idx]
        info = r.get("info", {})
        lines = []
        lines.append(f"Файл: {os.path.basename(r.get('path',''))}")
        lines.append(f"Статус: {'OK' if r.get('ok') else 'Нельзя'}")
        lines.append(f"Режим (Mode): {info.get('mode') or ''}")

        dpi_val = info.get("dpi")
        if isinstance(dpi_val, (list, tuple)) and dpi_val:
            dpi_show = self._to_float_or_empty(dpi_val[0])
        else:
            dpi_show = self._to_float_or_empty(dpi_val)
        lines.append(f"DPI: {dpi_show}")

        lines.append(f"Исходный размер (px): {self._format_wh(info.get('src_size_px'))}")
        tp = info.get("target_px")
        if r.get("ok") and tp:
            lines.append(f"Целевой размер (px): {self._format_wh(tp)} @ 300 dpi")

        scale_used = info.get("scale_used")
        if isinstance(scale_used, (int, float)):
            if scale_used > 1.0:
                lines.append(f"Преобразование: увеличение ×{scale_used:.3f} (≤ 1.5)")
            elif scale_used < 1.0:
                lines.append(f"Преобразование: уменьшение ×{scale_used:.3f}")
        if info.get("cover_crop"):
            lines.append("Преобразование: вписка с обрезкой по центру (cover+crop)")
        if info.get("cropped"):
            lines.append("Преобразование: кроп по центру")

        reasons = r.get("reasons", [])
        if reasons:
            lines.append("Причины/заметки:")
            for v in reasons:
                lines.append(f"- {v}")
        else:
            note = r.get("notes")
            if note:
                lines.append(f"Примечание: {note}")
        return "\n".join(lines)

    # ---------------- Лог-отчёт (по кнопке) ----------------

    def _build_log_rows(self) -> List[dict]:
        rows: List[dict] = []
        for item in self.results:
            src = os.path.basename(item.get("path","")) or os.path.basename(item.get("src",""))
            ok = bool(item.get("ok"))
            reasons_list = item.get("reasons", []) or []
            info = item.get("info", {}) or {}
            transforms: List[str] = []
            scale = info.get("scale_used", None)
            if isinstance(scale, (int, float)):
                if scale > 1.0:
                    transforms.append(f"увеличение ×{scale:.3f}")
                elif scale < 1.0:
                    transforms.append(f"уменьшение ×{scale:.3f}")
            if info.get("cover_crop"):
                transforms.append("вписка с обрезкой по центру (cover+crop)")
            if info.get("cropped"):
                transforms.append("кроп по центру")
            if info.get("adapt_bleed"):
                transforms.append("добавлены/нормализованы вылеты")

            dpi_val = info.get("dpi")
            if isinstance(dpi_val, (list, tuple)) and dpi_val:
                dpi_out = self._to_float_or_empty(dpi_val[0])
            else:
                dpi_out = self._to_float_or_empty(dpi_val)

            rows.append({
                "Файл": src,
                "Соответствует требованиям": "Да" if ok else "Нет",
                "Причина отказа": "; ".join(reasons_list) if not ok else "",
                "Выполненные преобразования": "; ".join(transforms) if ok and transforms else ("" if ok else "-"),
                "Режим (Mode)": info.get("mode") or "",
                "DPI": dpi_out if dpi_out != "" else "",
                "Исх. размер (px)": self._format_wh(info.get("src_size_px")),
                "Целевой размер (px)": self._format_wh(info.get("target_px")) if ok else "",
                "Масштаб (scale)": (f"{(scale if scale else 1.0):.3f}" if isinstance(scale, (int, float)) else ("1.000" if ok else "")),
                "Примечание": item.get("notes", "") or "",
            })
        return rows

    def generate_log(self):
        """Сформировать CSV и XLSX во временных файлах — по кнопке."""
        if not self.results:
            return gr.update(value="Нет данных для лога. Сначала выполните проверку."), None, None
        rows = self._build_log_rows()
        if not rows:
            return gr.update(value="Лог пуст."), None, None

        df = pd.DataFrame(rows)

        # CSV
        with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as fcsv:
            df.to_csv(fcsv.name, index=False, encoding="utf-8-sig")
            csv_path = fcsv.name

        # XLSX
        with tempfile.NamedTemporaryFile("wb", suffix=".xlsx", delete=False) as fxlsx:
            df.to_excel(fxlsx.name, index=False)
            xlsx_path = fxlsx.name

        self.log_csv_path = csv_path
        self.log_xlsx_path = xlsx_path
        return gr.update(value="Лог сформирован. Файлы готовы к скачиванию."), csv_path, xlsx_path

    # ---------------- Генератор тестов ----------------

    def generate_tests(self, out_dir: str):
        """Создаёт набор тестовых изображений. Скачивание — отдельной кнопкой."""
        try:
            import test_image_generator as tig
        except Exception as e:
            return gr.update(value=f"Ошибка: модуль test_image_generator недоступен: {e!s}"), gr.update()

        out_dir = (out_dir or "test_images").strip()
        abs_dir = os.path.abspath(out_dir)
        try:
            created, folder = tig.generate_all(abs_dir)
            self.last_generated_dir = folder
            self.tests_zip = None  # сброс старого ZIP, если был
            msg = (f"Успех: создано {len(created)} файлов.\nПапка: `{folder}`\n"
                   f"Можно нажать «📦 Скачать ZIP тестов» или «📥 Использовать тесты для проверки».")
            return gr.update(value=msg), gr.update(value=folder)
        except Exception as e:
            return gr.update(value=f"Ошибка генерации: {e!s}"), gr.update()

    def download_tests_zip(self):
        """Упаковка сгенерированных тестов в ZIP и отдача файла."""
        if not self.last_generated_dir or not os.path.isdir(self.last_generated_dir):
            return gr.update(value="Нет тестов. Сначала нажмите «🔄 Сгенерировать тесты»."), None

        exts = {".jpg",".jpeg",".tif",".tiff",".png",".bmp",".webp"}
        files = []
        for root, _, names in os.walk(self.last_generated_dir):
            for n in names:
                if os.path.splitext(n)[1].lower() in exts:
                    files.append(os.path.join(root, n))
        if not files:
            return gr.update(value="Папка тестов пуста. Сначала сгенерируйте тесты."), None

        with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as fzip:
            with zipfile.ZipFile(fzip.name, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for p in files:
                    arc = os.path.relpath(p, start=self.last_generated_dir)
                    z.write(p, arcname=arc)
            self.tests_zip = fzip.name

        return gr.update(value=f"ZIP тестов готов: {os.path.basename(self.tests_zip)}"), self.tests_zip

    # ---------------- Сборка A4  ----------------

    def build_a4_layouts(self, rows, cols, margin_mm, gx_mm, gy_mm, crop_len_mm, out_format,
                         cmyk_mode, icc_file):
        """Собирает страницы A4 во временную папку. Возвращает статус, превью, (файл не возвращаем)."""
        try:
            if not self.prepared_cards:
                return gr.update(value="Сначала подготовьте изображения (должны быть одобрены)."), None, None

            DEFAULT_ROWS, DEFAULT_COLS = 2, 2
            DEFAULT_MARGIN, DEFAULT_GX, DEFAULT_GY = 10.0, 5.0, 5.0
            DEFAULT_CROP = 3.0
            notes = []

            rows_in, note = self._sanitize_int(rows, 1, 1000, DEFAULT_ROWS, "Строк (rows)");                  notes += [note] if note else []
            cols_in, note = self._sanitize_int(cols, 1, 1000, DEFAULT_COLS, "Колонок (cols)");                notes += [note] if note else []
            margin_mm, note = self._sanitize_num(margin_mm, 0.0, 50.0, DEFAULT_MARGIN, "Поля"," мм");        notes += [note] if note else []
            gx_mm, note = self._sanitize_num(gx_mm, 0.0, 50.0, DEFAULT_GX, "Интервал X"," мм");              notes += [note] if note else []
            gy_mm, note = self._sanitize_num(gy_mm, 0.0, 50.0, DEFAULT_GY, "Интервал Y"," мм");              notes += [note] if note else []
            crop_len_mm, note = self._sanitize_num(crop_len_mm, 0.5, 5.0, DEFAULT_CROP, "Длина меток реза"," мм"); notes += [note] if note else []

            # Поддержка видимости меток: делаем поля не меньше длины метки + 1 мм
            min_margin = crop_len_mm + 1.0
            if margin_mm < min_margin:
                margin_mm = min_margin
                notes.append(f"Поля увеличены до {margin_mm:.1f} мм, чтобы метки/пунктир были видимы.")

            max_cols, max_rows = self._compute_max_grid(margin_mm, gx_mm, gy_mm)
            if max_cols == 0 or max_rows == 0:
                msg = ("Ошибка: при заданных полях/интервалах на A4 не помещается ни одна карточка.\n"
                       "Уменьшите поля/интервалы.")
                if notes: msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
                return gr.update(value=msg), None, None

            rows_eff = max(1, min(rows_in, max_rows))
            cols_eff = max(1, min(cols_in, max_cols))
            if rows_eff != rows_in:
                notes.append(f"Строк уменьшено до {rows_eff} (макс {max_rows}).")
            if cols_eff != cols_in:
                notes.append(f"Колонок уменьшено до {cols_eff} (макс {max_cols}).")

            # Режим CMYK / профиль
            icc_path = None
            attach_icc = False
            if isinstance(cmyk_mode, str) and cmyk_mode.startswith("Embed"):
                if icc_file and isinstance(icc_file, str) and os.path.isfile(icc_file):
                    icc_path = icc_file
                    attach_icc = True
                else:
                    notes.append("Выбран режим «Embed ICC профиль», но файл не загружен — будет DeviceCMYK.")

            # Настройки импозиции
            s = A4LayoutSettings(
                orientation=A4_ORIENTATION,
                rows=rows_eff,
                cols=cols_eff,
                margin_mm=float(margin_mm),
                gutter_x_mm=float(gx_mm),
                gutter_y_mm=float(gy_mm),
                crop_mark_len_mm=float(crop_len_mm),
                out_format="TIFF_LZW" if out_format == "TIFF (LZW)" else "JPEG",
                cmyk_profile_path=icc_path,
                crop_mark_stroke_px=3,
                draw_trim_dashed=True,
                trim_dash_len_mm=None,
                trim_dash_gap_mm=None,
                trim_dash_stroke_px=3,
                corner_brackets=True,
            )

            # Пересчёт мм → px и проверка помещаемости после округлений
            a4_w_mm, a4_h_mm = a4_size_mm(s.orientation)
            dpi = getattr(s, "dpi", 300)  # на всякий случай, если в настройках dpi не задан
            card_w_px = mm_to_px(CARD_W_MM, dpi)
            card_h_px = mm_to_px(CARD_H_MM, dpi)
            margin_px = mm_to_px(s.margin_mm, dpi)
            gx_px = mm_to_px(s.gutter_x_mm, dpi)
            gy_px = mm_to_px(s.gutter_y_mm, dpi)

            total_w = margin_px*2 + s.cols*card_w_px + (s.cols-1)*gx_px
            total_h = margin_px*2 + s.rows*card_h_px + (s.rows-1)*gy_px
            sheet_w_px = mm_to_px(a4_w_mm, dpi)
            sheet_h_px = mm_to_px(a4_h_mm, dpi)
            if total_w > sheet_w_px or total_h > sheet_h_px:
                msg = ("Ошибка: сетка не помещается на A4 после округления пикселей. "
                       "Уменьшите строки/колонки или поля/интервалы.")
                if notes: msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
                return gr.update(value=msg), None, None

            # Гарантируем точный размер каждой карточки
            cards_for_layout = []
            for im in self.prepared_cards:
                im2 = self._force_exact_card_size(im, card_w_px, card_h_px)
                if im2.mode != "CMYK":
                    im2 = im2.convert("CMYK")
                cards_for_layout.append(im2)

            # Рендер во временную папку
            self._reset_runtime()
            self.tmp_layout_dir = tempfile.mkdtemp(prefix="a4_pages_")
            imposer = A4Imposer(s)
            res = imposer.impose(cards_for_layout, self.tmp_layout_dir, attach_icc=attach_icc)

            self.a4_previews = res.get("previews", [])
            self.tmp_pages = res.get("pages", []) or []
            if not self.tmp_pages:
                msg = "Ошибка: не удалось создать страницы макета."
                if notes: msg += "\n\n" + "\n".join(f"- {n}" for n in notes)
                return gr.update(value=msg), None, None

            # Проверим ICC на всех страницах
            if attach_icc:
                ok_pages = 0
                names = []
                missing_idx = []
                for i, pth in enumerate(self.tmp_pages, start=1):
                    has_icc, prof_name = self._probe_icc_profile(pth)
                    if has_icc:
                        ok_pages += 1
                        if prof_name:
                            names.append(prof_name)
                    else:
                        missing_idx.append(i)
                uniq_names = sorted(set([n for n in names if n]))
                if ok_pages == len(self.tmp_pages):
                    icc_note = f"Профиль встроен во все {len(self.tmp_pages)} страницы: {uniq_names[0] if len(uniq_names)==1 else ', '.join(uniq_names) or '—'}."
                else:
                    icc_note = f"Профиль встроен в {ok_pages} из {len(self.tmp_pages)} страниц. Без профиля: {missing_idx}."
            else:
                icc_note = "CMYK: DeviceCMYK (без профиля)."

            status = (f"Собрано страниц: {len(self.tmp_pages)} (во временной папке). "
                      f"Для скачивания нажмите «📦 Скачать ZIP макетов».\n{icc_note}")
            if notes:
                status += "\n\nПримечания:\n" + "\n".join(f"- {n}" for n in notes)

            preview_img = self.a4_previews[0] if self.a4_previews else None
            return gr.update(value=status), preview_img, None

        except Exception as e:
            return gr.update(value=f"Ошибка: {e!s}"), None, None

    def make_zip_on_demand(self):
        """Упаковать итоговые страницы макета в ZIP (по кнопке)."""
        if not self.tmp_pages:
            return gr.update(value="Нет страниц для упаковки. Сначала соберите макет."), None
        try:
            with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as fzip:
                with zipfile.ZipFile(fzip.name, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    for p in self.tmp_pages:
                        z.write(p, arcname=os.path.basename(p))
                self.a4_zip = fzip.name
            return gr.update(value=f"ZIP готов: {os.path.basename(self.a4_zip)}. Можно скачивать."), self.a4_zip
        except Exception as e:
            return gr.update(value=f"Ошибка упаковки: {e!s}"), None

    # ---------------- UI ----------------

    def build(self):
        with gr.Blocks(title="Проверка изображений и A4 макеты", theme=gr.themes.Soft()) as demo:
            gr.Markdown("# 🖨️ Проверка изображений и сборка A4 макетов")
            gr.Markdown("Карточка: **110×80 мм** (100×70 + вылеты 5 мм), лист: **A4 альбом**, **300 dpi**.")

            with gr.Tabs():
                # --- Вкладка 1: Проверка и Макет ---
                with gr.TabItem("🔍 Проверка и 📄 Макет A4"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown("## Требования")
                            gr.Markdown(
                                "- Цветовое пространство: **CMYK** (без автоконвертации)\n"
                                "- Обрезной: **100×70 мм**, вылет **5 мм** → карточка **110×80 мм**\n"
                                "- Печатный формат: **A4 альбом**, **300 dpi**, файл ≤ **100 МБ**\n"
                                "- Увеличение: **не более 50%**\n"
                                "- Пунктир по резу + уголковые метки"
                            )
                            mixed = gr.File(label="Изображения и/или ZIP (несколько)",
                                            file_count="multiple", type="filepath",
                                            file_types=["image", ".zip"])
                            with gr.Row():
                                btn_check = gr.Button("🔍 Проверить и подготовить", variant="primary")
                                btn_clear = gr.Button("🗑️ Очистить")
                            status_md = gr.Markdown("Готово к работе.")
                        with gr.Column(scale=2):
                            table = gr.Dataframe(
                                headers=["Файл","Статус","Причина/примечание","Mode","DPI","Исх. размер (px)","Целевой (px)","Масштаб"],
                                interactive=False, wrap=True
                            )
                            details = gr.Textbox(label="Детали", lines=10)

                    with gr.Accordion("Лог-отчёт (по запросу)", open=False):
                        log_status = gr.Markdown("")
                        with gr.Row():
                            btn_log = gr.Button("📑 Сформировать лог-отчёт")
                            log_csv = gr.File(label="CSV")
                            log_xlsx = gr.File(label="Excel (XLSX)")

                    with gr.Accordion("Параметры A4 макета", open=True):
                        with gr.Row():
                            with gr.Column(scale=1):
                                rows = gr.Number(value=2, precision=0, label="Строк (rows)")
                                cols = gr.Number(value=2, precision=0, label="Колонок (cols)")
                                margin = gr.Number(value=10, label="Поля, мм (≥0)")
                                gx = gr.Number(value=5, label="Интервал X, мм (≥0)")
                                gy = gr.Number(value=5, label="Интервал Y, мм (≥0)")
                                crop_len = gr.Number(value=3, label="Длина меток реза, мм (0.5–5)")
                                out_fmt = gr.Radio(choices=["TIFF (LZW)", "JPEG"], value="TIFF (LZW)", label="Формат вывода")

                                cmyk_mode = gr.Radio(
                                    choices=["DeviceCMYK (без профиля)", "Embed ICC профиль"],
                                    value="DeviceCMYK (без профиля)",
                                    label="CMYK режим сохранения"
                                )
                                # Появится только при выборе Embed ICC
                                icc_file = gr.File(
                                    label="ICC профиль (.icc/.icm)",
                                    file_count="single",
                                    type="filepath",
                                    file_types=[".icc", ".icm"],
                                    visible=False
                                )

                                btn_build = gr.Button("📄 Собрать A4 макет", variant="primary")
                                a4_status = gr.Markdown("")
                            with gr.Column(scale=2):
                                # тип filepath — чтобы можно было возвращать путь к превью
                                preview = gr.Image(label="Предпросмотр листа (уменьшенный)", interactive=False, type="filepath")
                                with gr.Row():
                                    btn_zip = gr.Button("📦 Скачать ZIP макетов")
                                    out_zip = gr.File(label="ZIP страниц")

                # --- Вкладка 2: Генератор тестовых изображений ---
                with gr.TabItem("🛠️ Генератор тестовых изображений"):
                    gr.Markdown("## Создать набор тестов (цветные фигуры, CMYK, 110×80 мм @ 300 dpi)")
                    with gr.Row():
                        gen_out = gr.Textbox(label="Папка для тестов", value="test_images")
                        gen_btn = gr.Button("🔄 Сгенерировать тесты", variant="primary")
                        btn_use_gen = gr.Button("📥 Использовать тесты для проверки")
                    with gr.Row():
                        btn_zip_tests = gr.Button("📦 Скачать ZIP тестов")
                        tests_zip = gr.File(label="ZIP тестов")
                    gen_status = gr.Markdown("")

            # --- wiring ---
            btn_check.click(self.validate_from_inputs, inputs=[mixed], outputs=[status_md, table, details])
            btn_clear.click(self._reset_gradio, outputs=[status_md, table, details, a4_status, preview, out_zip, log_csv, log_xlsx, gen_status])

            table.select(self.show_details, outputs=[details])

            btn_log.click(self.generate_log, outputs=[log_status, log_csv, log_xlsx])

            btn_build.click(self.build_a4_layouts,
                            inputs=[rows, cols, margin, gx, gy, crop_len, out_fmt, cmyk_mode, icc_file],
                            outputs=[a4_status, preview, out_zip])

            btn_zip.click(self.make_zip_on_demand, outputs=[a4_status, out_zip])

            gen_btn.click(self.generate_tests, inputs=[gen_out], outputs=[gen_status, gen_out])
            btn_use_gen.click(self.validate_from_generated, outputs=[status_md, table, details])
            btn_zip_tests.click(self.download_tests_zip, outputs=[gen_status, tests_zip])

            # Показ/скрытие поля ICC при смене режима
            cmyk_mode.change(self._toggle_icc_visibility, inputs=[cmyk_mode], outputs=[icc_file])

        return demo

    def _reset_gradio(self):
        """Сброс UI-состояния и внутренних буферов."""
        self.results.clear()
        self.prepared_cards.clear()
        self._reset_runtime()
        self.last_generated_dir = None
        self.tests_zip = None
        return (gr.update(value="Очищено."), pd.DataFrame(), "",  # статус, таблица, детали
                gr.update(value=""), None, None,                  # a4_status, preview, out_zip
                None, None,                                       # log_csv, log_xlsx
                gr.update(value=""))                              # gen_status

    @staticmethod
    def _toggle_icc_visibility(choice: str):
        """Показываем загрузку ICC только при выборе Embed ICC профиль."""
        show = isinstance(choice, str) and choice.startswith("Embed")
        return gr.update(visible=show, value=None)


# ---- Точка входа ----

def main():
    try:
        # читаем окружение
        server_name = os.getenv("SERVER_NAME", "0.0.0.0")   # внутри контейнера слушаем на всех интерфейсах
        port = int(os.getenv("PORT", "7860"))               # внутренний порт приложения

        # что показывать пользователю в логах (внешний адрес/порт)
        public_host = os.getenv("PUBLIC_HOST", "localhost")
        public_port = os.getenv("PUBLIC_PORT", str(port))   

        inbrowser_env = os.getenv("INBROWSER", "0")
        inbrowser = inbrowser_env not in ("0", "false", "False")

        print("Запуск приложения…")
        print(f"Открой в браузере: http://{public_host}:{public_port}")

        app = GradioPrintA4().build()
        app.launch(server_name=server_name, server_port=port,
                   share=False, show_error=True, inbrowser=inbrowser)
    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        print("Установите зависимости: pip install -r requirements.txt")


if __name__ == "__main__":
    main()
