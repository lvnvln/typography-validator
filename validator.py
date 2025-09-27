# validator.py
"""
Валидация изображений для типографии (Tesseract).
СНАЧАЛА проверяются физические требования → затем OCR.
Отступ текста меряем от линии обреза (границы вылета), а не от краёв изображения.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageCms
import pytesseract

MM_PER_INCH = 25.4


@dataclass
class Requirements:
    file_size_mb_max: int = 100
    color_space: str = "CMYK"          # только валидация, без автоконвертации
    target_w_mm: int = 100             # обрезной размер
    target_h_mm: int = 70
    bleed_mm: int = 5                  # вылет с каждой стороны
    min_dpi: int = 300
    min_text_margin_mm: int = 5        # минимальный отступ от линии обреза


def mm_to_px(mm: float, dpi: float) -> int:
    return int(round(mm / MM_PER_INCH * dpi))


def px_to_mm(px: float, dpi: float) -> float:
    return float(px) * MM_PER_INCH / float(dpi) if dpi else 0.0


class TesseractTextDetector:
    """Лёгкий детектор текста на базе pytesseract.image_to_data."""
    def __init__(self, min_confidence: int = 30, lang: str = "rus+eng") -> None:
        self.min_confidence = int(min_confidence)   # 0..100
        self.lang = lang

    def detect(self, image: Image.Image) -> List[Dict[str, Any]]:
        data = pytesseract.image_to_data(image, lang=self.lang, output_type=pytesseract.Output.DICT)
        n = len(data.get("text", []))
        regions: List[Dict[str, Any]] = []
        for i in range(n):
            txt = (data["text"][i] or "").strip()
            conf_raw = data["conf"][i]
            try:
                conf = float(conf_raw)
            except Exception:
                conf = -1.0
            if not txt or conf < self.min_confidence:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            regions.append(
                {"text": txt, "bbox": (int(x), int(y), int(x + w), int(y + h)), "confidence": conf / 100.0}
            )
        return regions


class ImageValidator:
    """
    Порядок:
      1) базовые/физические проверки (размер, цвет, DPI, геометрия/вылеты);
      2) если ОК — OCR и проверка отступа текста от линии обреза.
    """
    def __init__(self, req: Requirements | None = None) -> None:
        self.req = req or Requirements()
        self.requirements: Dict[str, Any] = {
            "file_size_mb_max": self.req.file_size_mb_max,
            "color_space": self.req.color_space,
            "target_w_mm": self.req.target_w_mm,
            "target_h_mm": self.req.target_h_mm,
            "bleed_mm": self.req.bleed_mm,
            "min_dpi": self.req.min_dpi,
            "min_text_margin_mm": self.req.min_text_margin_mm,
        }
        self.text_detector = TesseractTextDetector()

    # ---------- helpers ----------

    def _get_dpi(self, im: Image.Image) -> Tuple[int, int]:
        candidates = [
            im.info.get("dpi"),
            im.info.get("resolution"),
            im.info.get("jpeg_res"),
        ]
        for dpi in candidates:
            if not dpi:
                continue
            if isinstance(dpi, tuple) and len(dpi) >= 1:
                xdpi = int(dpi[0])
                ydpi = int(dpi[1] if len(dpi) > 1 else dpi[0])
                return xdpi, ydpi
            if isinstance(dpi, (int, float)):
                return int(dpi), int(dpi)
        return self.req.min_dpi, self.req.min_dpi

    def _check_color_space(self, im: Image.Image) -> Tuple[bool, str]:
        mode = (im.mode or "").upper()
        if mode == "CMYK":
            return True, "OK (mode=CMYK)"
        icc = im.info.get("icc_profile")
        if icc:
            try:
                profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                desc = (ImageCms.getProfileName(profile) or "").upper()
                if "CMYK" in desc:
                    return True, f"OK (ICC={desc})"
                return False, f"ICC={desc}"
            except Exception as e:
                return False, f"ICC read error: {e!s}"
        return False, f"mode={im.mode}"

    # ---------- public ----------

    def validate_file(self, path: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "filename": os.path.basename(path),
            "path": path,
            "printable": False,
            "violations": [],
            "text_regions": [],
            "text_violations": [],
            "text_violations_count": 0,
            "mode": "unknown",
            "color_space": None,
            "dpi": None,
            "size_px": None,
            "width_mm": None,
            "height_mm": None,
            "file_mb": None,
        }

        # 0) размер файла
        try:
            file_mb = os.path.getsize(path) / (1024 ** 2)
            result["file_mb"] = round(file_mb, 2)
            if file_mb > self.req.file_size_mb_max:
                result["violations"].append(
                    f"Размер файла {file_mb:.1f} МБ > {self.req.file_size_mb_max} МБ"
                )
        except Exception as e:
            result["violations"].append(f"Не удалось прочитать размер файла: {e!s}")

        # 1) открытие изображения
        try:
            with Image.open(path) as im:
                result["mode"] = im.mode
                result["color_space"] = im.mode

                xdpi, ydpi = self._get_dpi(im)
                dpi = min(xdpi, ydpi)
                result["dpi"] = int(dpi)

                w, h = im.size
                result["size_px"] = (w, h)
                result["width_mm"] = round(px_to_mm(w, dpi), 1) if dpi else None
                result["height_mm"] = round(px_to_mm(h, dpi), 1) if dpi else None

                # 2) цвет
                ok_cs, cs_note = self._check_color_space(im)
                if not ok_cs:
                    result["violations"].append(f"Цветовое пространство не CMYK ({cs_note})")

                # 3) DPI
                if dpi < self.req.min_dpi:
                    result["violations"].append(f"DPI={dpi} < {self.req.min_dpi}")

                # 4) геометрия + вылеты
                expected_w = mm_to_px(self.req.target_w_mm + 2 * self.req.bleed_mm, dpi)
                expected_h = mm_to_px(self.req.target_h_mm + 2 * self.req.bleed_mm, dpi)
                tol = 2  # допуск округления
                if abs(w - expected_w) > tol or abs(h - expected_h) > tol:
                    result["violations"].append(
                        f"Размер с вылетами должен быть {expected_w}×{expected_h}px (при {dpi} dpi), по факту {w}×{h}px"
                    )

                # 5) если уже есть нарушения — НЕ запускаем OCR
                if result["violations"]:
                    result["printable"] = False
                    return result

                # 6) OCR
                try:
                    regions = self.text_detector.detect(im.convert("RGB"))
                except Exception as e:
                    regions = []
                    result["violations"].append(f"Ошибка детекции текста: {e!s}")
                    result["printable"] = False
                    return result

                result["text_regions"] = regions

                # 7) проверка отступа от ЛИНИИ ОБРЕЗА (границы вылета)
                bleed_px = mm_to_px(self.req.bleed_mm, dpi)
                target_w_px = mm_to_px(self.req.target_w_mm, dpi)
                target_h_px = mm_to_px(self.req.target_h_mm, dpi)

                # координаты линии обреза (внутренняя граница вылета)
                crop_left, crop_top = bleed_px, bleed_px
                crop_right, crop_bottom = bleed_px + target_w_px, bleed_px + target_h_px

                min_margin_px = mm_to_px(self.req.min_text_margin_mm, dpi)

                text_violations: List[Dict[str, Any]] = []
                for r in regions:
                    x1, y1, x2, y2 = r["bbox"]

                    # Минимальная "подписанная" дистанция до линий обреза:
                    # если bbox пересекает линию или находится ближе чем min_margin_px с любой стороны (внутри или снаружи),
                    # это нарушение. Мы НЕ отбрасываем боксы, которые целиком в вылете.
                    dx_left = x1 - crop_left
                    dx_right = crop_right - x2
                    dy_top = y1 - crop_top
                    dy_bottom = crop_bottom - y2

                    min_dist_px = min(dx_left, dx_right, dy_top, dy_bottom)

                    if min_dist_px < min_margin_px:
                        # Для отчёта показываем абсолютное расстояние (0, если линия пересекается)
                        abs_mm = round(px_to_mm(max(min_dist_px, 0), dpi), 2)
                        text_violations.append(
                            {
                                "text": r.get("text", ""),
                                "bbox": r["bbox"],
                                "distance_to_crop_mm": abs_mm,
                            }
                        )

                result["text_violations"] = text_violations
                result["text_violations_count"] = len(text_violations)
                result["printable"] = (len(result["violations"]) == 0) and (len(text_violations) == 0)
                return result

        except Exception as e:
            # Ошибка открытия/чтения изображения
            result["violations"].append(f"Не удалось открыть изображение: {e!s}")
            result["printable"] = False
            return result
