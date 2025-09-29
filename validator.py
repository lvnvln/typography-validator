# validator.py
"""
Проверка и допустимая подготовка изображений под карточку 110×80 мм @ 300 dpi.

Требования:
- Цветовое пространство только CMYK (без автоконвертации).
- Разрешён даунскейл (уменьшение).
- Разрешён апскейл не более чем на 50% (×1.5).
- Если пропорции не совпадают — выполняется cover-масштабирование и центрированная обрезка.
- В финале изображение должно быть в CMYK и ровно целевого пиксельного размера (соответствующего 110×80 мм @ 300 dpi).

Выход функции prepare_card(path):
{
  "ok": bool,
  "prepared": PIL.Image | None,   # готовая карточка CMYK нужного размера @ 300 dpi
  "info": {...},                  # метаданные (исходный размер, scale_used и пр.)
  "reasons": [..],                # причины отказа
  "notes": str                    # текстовая заметка о выполненных преобразованиях
}
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple, Dict, Any, Optional
from PIL import Image

MM_PER_INCH = 25.4

def mm_to_px(mm: float, dpi: int) -> int:
    """Миллиметры → пиксели при заданном dpi."""
    return int(round(mm / MM_PER_INCH * dpi))

@dataclass
class PrepRequirements:
    # ФИЗИЧЕСКИЕ ТРЕБОВАНИЯ (обрезной + вылеты)
    crop_w_mm: float = 100.0
    crop_h_mm: float = 70.0
    bleed_mm: float = 5.0            # с каждой стороны
    dpi: int = 300

    # ПРАВИЛА ПРЕОБРАЗОВАНИЙ
    max_upscale: float = 1.5         # жёсткий запрет апскейла > 50%
    require_cmyk: bool = True        # RGB не трогаем, помечаем как неподходящие

    # СПРАВОЧНО (контроль 100 МБ делается на этапе сборки листа при сохранении)
    max_output_mb: float = 100.0

    @property
    def target_w_px(self) -> int:
        """Ширина целевой карточки (включая вылеты) в пикселях @ dpi."""
        return mm_to_px(self.crop_w_mm + 2 * self.bleed_mm, self.dpi)

    @property
    def target_h_px(self) -> int:
        """Высота целевой карточки (включая вылеты) в пикселях @ dpi."""
        return mm_to_px(self.crop_h_mm + 2 * self.bleed_mm, self.dpi)

    @property
    def target_ratio(self) -> float:
        """Отношение сторон целевой карточки (для справки)."""
        return self.target_w_px / self.target_h_px


class ImagePreparer:
    """
    Валидатор/подготовщик изображений.
    Никакой цветовой конвертации не выполняется — только CMYK-исходники допускаются.
    """

    def __init__(self, req: Optional[PrepRequirements] = None):
        self.req = req or PrepRequirements()

    # ---------- helpers ----------

    def _open_image(self, path: str) -> Image.Image:
        """Открытие изображения PIL с принудительной загрузкой данных (load())."""
        im = Image.open(path)
        try:
            im.load()
        except Exception:
            pass
        return im

    def _get_mode(self, im: Image.Image) -> str:
        """Возвращает режим; считаем корректным только 'CMYK'."""
        return "CMYK" if im.mode == "CMYK" else im.mode

    def _calc_cover_scale(self, src_w: int, src_h: int, tgt_w: int, tgt_h: int) -> float:
        """
        Минимальный масштаб (cover), чтобы и ширина, и высота цели оказались покрыты источником.
        Возможен как даунскейл (<1), так и апскейл (>1).
        """
        return max(tgt_w / src_w, tgt_h / src_h)

    def _resize(self, im: Image.Image, size: Tuple[int, int]) -> Image.Image:
        """Масштабирование с хорошим ресемплером."""
        return im.resize(size, Image.Resampling.LANCZOS)

    def _center_crop(self, im: Image.Image, tw: int, th: int) -> Image.Image:
        """Центрированная обрезка до нужного пиксельного размера."""
        w, h = im.size
        x0 = max(0, (w - tw) // 2)
        y0 = max(0, (h - th) // 2)
        return im.crop((x0, y0, x0 + tw, y0 + th))

    # ---------- public ----------

    def prepare_card(self, path: str) -> Dict[str, Any]:
        """
        Проверяет и при необходимости готовит исходное изображение под карточку 110×80 мм @ 300 dpi.
        Допустимые операции: даунскейл / апскейл ≤ 1.5 / cover + центрированная обрезка.
        Цветовое пространство: ТОЛЬКО CMYK. DPI метаданные проставляются как 300×300.
        """
        out: Dict[str, Any] = {"ok": False, "prepared": None, "info": {}, "reasons": [], "notes": ""}

        # 0) открыть
        try:
            im = self._open_image(path)
        except Exception as e:
            out["reasons"].append(f"Не удалось открыть изображение: {e}")
            return out

        mode = self._get_mode(im)
        w, h = im.size
        dpi_meta = im.info.get("dpi", None)  # может быть (x, y) или None

        tgt_w, tgt_h = self.req.target_w_px, self.req.target_h_px
        out["info"] = {
            "mode": mode,
            "dpi": dpi_meta[0] if isinstance(dpi_meta, tuple) else dpi_meta,
            "src_size_px": (w, h),
            "target_px": (tgt_w, tgt_h),
            "scale_used": 1.0
        }

        # 1) цветовое пространство — никаких автоконверсий
        if self.req.require_cmyk and mode != "CMYK":
            out["reasons"].append("Цветовое пространство не CMYK (автоконвертация запрещена).")
            return out

        # 2) минимально необходимый cover-масштаб
        scale = self._calc_cover_scale(w, h, tgt_w, tgt_h)
        if scale > 1.0 and scale > self.req.max_upscale:
            out["reasons"].append(f"Требуется увеличение ×{scale:.2f} (> {self.req.max_upscale}).")
            return out

        # 3) масштабирование (downscale или допустимый upscale ≤ 1.5)
        new_w = max(tgt_w, int(round(w * scale)))
        new_h = max(tgt_h, int(round(h * scale)))
        try:
            im2 = self._resize(im, (new_w, new_h))
        except Exception as e:
            out["reasons"].append(f"Ошибка масштабирования: {e}")
            return out

        # 4) привести строго к целевому размеру пикселей (центр-кроп)
        if im2.size != (tgt_w, tgt_h):
            im2 = self._center_crop(im2, tgt_w, tgt_h)

        # 5) снова проверяем режим (мы его не меняли — но если исходник не CMYK, отклоняем)
        if im2.mode != "CMYK":
            out["reasons"].append("Получился не CMYK после чтения (конвертация запрещена).")
            return out

        # 6) проставить метаданные DPI=300 (это не цветовая конвертация)
        im2.info["dpi"] = (self.req.dpi, self.req.dpi)

        out["ok"] = True
        out["prepared"] = im2
        out["info"]["scale_used"] = scale
        if scale < 1.0:
            out["notes"] = f"Уменьшено до {tgt_w}×{tgt_h}px (включая вылет)."
        elif scale > 1.0:
            out["notes"] = f"Увеличено ×{scale:.3f} до {tgt_w}×{tgt_h}px (включая вылет)."
        else:
            out["notes"] = "Без масштабирования; приведено к целевому размеру (включая вылет)."
        return out
