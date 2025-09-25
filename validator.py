"""
Модуль валидации изображений для типографии.
Содержит классы для проверки соответствия изображений требованиям печати.
"""

import os
from PIL import Image, ImageCms
import numpy as np
import easyocr
import warnings

# Игнорирование предупреждений PyTorch
warnings.filterwarnings("ignore", category=UserWarning, module="torch.utils.data.dataloader")

class TextDetector:
    """Класс для обнаружения и анализа текста на изображениях"""
    
    def __init__(self):
        """
        Инициализация детектора текста с настройками по умолчанию
        """
        self.min_text_height = 8  # Минимальная высота текста в пикселях
        self.min_confidence = 0.3  # Минимальная уверенность распознавания
        self.min_safe_margin_mm = 5  # Минимальный безопасный отступ в мм
        self.reader = None  # Инициализация читателя EasyOCR
        self._initialize_reader()
    
    def _initialize_reader(self):
        """Инициализация EasyOCR для распознавания русского и английского текста"""
        try:
            self.reader = easyocr.Reader(['ru', 'en'], gpu=False)
            print("EasyOCR инициализирован успешно")
        except ImportError:
            print("Ошибка: EasyOCR не установлен. Установите: pip install easyocr")
            self.reader = None
        except Exception as e:
            print(f"Ошибка инициализации EasyOCR: {e}")
            self.reader = None
    
    def mm_to_pixels(self, mm, dpi):
        """
        Конвертирует миллиметры в пиксели с учетом DPI
        
        Args:
            mm: Значение в миллиметрах
            dpi: Разрешение изображения (точек на дюйм)
            
        Returns:
            int: Значение в пикселях
        """
        return int(mm / 25.4 * dpi)
    
    def detect_text_regions(self, image_path, dpi):
        """
        Обнаруживает текстовые области на изображении
        
        Args:
            image_path: Путь к файлу изображения
            dpi: Разрешение изображения
            
        Returns:
            list: Список обнаруженных текстовых областей
        """
        if self.reader is None:
            print("Ошибка: EasyOCR не инициализирован")
            return []
            
        try:
            # Проверка существования файла
            if not os.path.exists(image_path):
                print(f"Ошибка: файл {image_path} не существует")
                return []
                
            # Распознавание текста на изображении
            results = self.reader.readtext(image_path, paragraph=False)
            print(f"Найдено {len(results)} текстовых элементов")
            
            text_regions = []
            min_safe_margin_px = self.mm_to_pixels(self.min_safe_margin_mm, dpi)
            
            # Обработка результатов распознавания
            for (bbox, text, confidence) in results:
                clean_text = text.strip()
                # Пропуск пустого текста или текста с низкой уверенностью
                if len(clean_text) < 1 or confidence < self.min_confidence:
                    continue
                    
                try:
                    points = np.array(bbox).astype(int)
                    if points.shape != (4, 2):
                        print(f"Некорректный формат bbox: {bbox}")
                        continue
                        
                    # Вычисление границ текстовой области
                    x_coords = points[:, 0]
                    y_coords = points[:, 1]
                    
                    x1, x2 = min(x_coords), max(x_coords)
                    y1, y2 = min(y_coords), max(y_coords)
                    height = y2 - y1
                    
                    # Фильтрация по минимальной высоте текста
                    if height >= self.min_text_height:
                        text_regions.append({
                            'text': clean_text,
                            'bbox': (x1, y1, x2, y2),
                            'confidence': confidence,
                            'safe_margin_px': min_safe_margin_px
                        })
                        
                except Exception as e:
                    print(f"Ошибка обработки bbox {bbox}: {e}")
                    continue
            
            print(f"Отфильтровано {len(text_regions)} регионов")
            return text_regions
            
        except Exception as e:
            print(f"Ошибка детекции текста: {e}")
            return []
    
    def check_text_margins(self, text_regions, image_width, image_height, bleed_px, target_width_px, target_height_px):
        """
        Проверяет отступы текста от границ обрезной зоны
        
        Args:
            text_regions: Список текстовых областей
            image_width: Ширина изображения в пикселях
            image_height: Высота изображения в пикселях
            bleed_px: Размер вылета в пикселях
            target_width_px: Ширина обрезной зоны в пикселях
            target_height_px: Высота обрезной зоны в пикселях
            
        Returns:
            list: Список нарушений расположения текста
        """
        violations = []
        
        for region in text_regions:
            x1, y1, x2, y2 = region['bbox']
            
            # Вычисление минимального расстояния до границ обрезной зоны
            min_distance = self.calculate_min_distance_to_crop(x1, y1, x2, y2, 
                                                            bleed_px, target_width_px, target_height_px)
            
            # Проверка нарушения отступов
            if min_distance < region['safe_margin_px']:
                distance_mm = (abs(min_distance) * 25.4) / self.mm_to_pixels(1, 300)
                
                violation_type = "малое расстояние" if min_distance >= 0 else "выход за обрезную зону"
                
                violations.append({
                    'text': region['text'],
                    'bbox': region['bbox'],
                    'distance_to_crop_mm': round(distance_mm, 2),
                    'min_distance_px': min_distance,
                    'required_distance_px': region['safe_margin_px'],
                    'violation_type': violation_type
                })
        
        return violations
    
    def calculate_min_distance_to_crop(self, x1, y1, x2, y2, bleed_px, target_width_px, target_height_px):
        """
        Вычисляет минимальное расстояние от текста до границ обрезной зоны
        
        Args:
            x1, y1, x2, y2: Координаты текстовой области
            bleed_px: Размер вылета в пикселях
            target_width_px: Ширина обрезной зоны
            target_height_px: Высота обрезной зоны
            
        Returns:
            int: Минимальное расстояние в пикселях (отрицательное если текст выходит за границы)
        """
        # Границы обрезной зоны (белой области)
        crop_left = bleed_px
        crop_right = bleed_px + target_width_px
        crop_top = bleed_px
        crop_bottom = bleed_px + target_height_px
        
        # Проверка выхода текста за обрезную зону
        if (x1 < crop_left or x2 > crop_right or y1 < crop_top or y2 > crop_bottom):
            # Расчет перекрытия за границами обрезной зоны
            overlap_left = max(0, crop_left - x1)
            overlap_right = max(0, x2 - crop_right)
            overlap_top = max(0, crop_top - y1)
            overlap_bottom = max(0, y2 - crop_bottom)
            
            max_overlap = max(overlap_left, overlap_right, overlap_top, overlap_bottom)
            return -max_overlap  # Отрицательное значение = текст выходит за обрезную зону
        
        # Текст внутри обрезной зоны - вычисление расстояний до границ
        dist_to_left = x1 - crop_left
        dist_to_right = crop_right - x2
        dist_to_top = y1 - crop_top
        dist_to_bottom = crop_bottom - y2
        
        # Минимальное расстояние до границ обрезной зоны
        return min(dist_to_left, dist_to_right, dist_to_top, dist_to_bottom)


class ImageValidator:
    """Основной класс для проверки изображений на соответствие требованиям типографии"""
    
    def __init__(self):
        """
        Инициализация валидатора с установкой требований типографии
        """
        self.requirements = {
            'max_file_size': 100 * 1024 * 1024,  # 100 МБ
            'color_space': 'CMYK',  # Требуемое цветовое пространство
            'target_width_mm': 100,  # Ширина обрезного формата в мм
            'target_height_mm': 70,  # Высота обрезного формата в мм
            'bleed_mm': 5,  # Размер вылетов в мм
            'min_dpi': 300,  # Минимальное разрешение
            'min_text_margin_mm': 5  # Минимальный отступ текста
        }
        
        # Инициализация детектора текста
        self.text_detector = TextDetector()
        
        # Расчет общих размеров с учетом вылетов
        self.total_width_mm = self.requirements['target_width_mm'] + 2 * self.requirements['bleed_mm']
        self.total_height_mm = self.requirements['target_height_mm'] + 2 * self.requirements['bleed_mm']
    
    def mm_to_pixels(self, mm, dpi):
        """
        Конвертирует мм в пиксели с учетом DPI
        
        Args:
            mm: Значение в миллиметрах
            dpi: Разрешение изображения
            
        Returns:
            int: Значение в пикселях
        """
        inches = mm / 25.4
        return int(inches * dpi)
    
    def get_color_space(self, image):
        """
        Определяет цветовое пространство изображения
        
        Args:
            image: Объект изображения PIL
            
        Returns:
            str: Название цветового пространства
        """
        try:
            # Попытка определить цветовое пространство через ICC профиль
            if hasattr(image, 'icc_profile') and image.icc_profile:
                try:
                    import io
                    icc_profile = ImageCms.ImageCmsProfile(io.BytesIO(image.icc_profile))
                    color_space = ImageCms.getProfileDescription(icc_profile).upper()
                    if 'CMYK' in color_space:
                        return 'CMYK'
                    elif 'RGB' in color_space or 'SRGB' in color_space:
                        return 'RGB'
                    else:
                        return color_space
                except:
                    return image.mode
            else:
                return image.mode
        except:
            return image.mode
    
    def check_basic_requirements(self, file_path):
        """
        Быстрая проверка основных требований (без OCR)
        
        Args:
            file_path: Путь к файлу изображения
            
        Returns:
            dict: Результаты базовой проверки
        """
        violations = []
        
        try:
            # Проверка размера файла
            file_size = os.path.getsize(file_path)
            if file_size > self.requirements['max_file_size']:
                violations.append(f"Размер файла {file_size/(1024*1024):.1f} МБ превышает 100 МБ")
            
            # Открытие и анализ изображения
            with Image.open(file_path) as img:
                # Проверка цветового пространства
                color_space = self.get_color_space(img)
                if color_space != self.requirements['color_space']:
                    violations.append(f"Цветовое пространство: {color_space} (требуется: {self.requirements['color_space']})")
                
                # Получение DPI изображения
                dpi = img.info.get('dpi', (72, 72))[0]
                if dpi < self.requirements['min_dpi']:
                    violations.append(f"Разрешение: {dpi} DPI (требуется: {self.requirements['min_dpi']}+ DPI)")
                
                # Расчет требуемых размеров в пикселях
                required_width_px = self.mm_to_pixels(self.total_width_mm, dpi)
                required_height_px = self.mm_to_pixels(self.total_height_mm, dpi)
                
                # Проверка размеров изображения
                if img.width < required_width_px or img.height < required_height_px:
                    violations.append(f"Размер изображения: {img.width}×{img.height}px (требуется: {required_width_px}×{required_height_px}px с учетом вылетов)")
                
                return {
                    'filename': os.path.basename(file_path),
                    'color_space': color_space,
                    'dpi': dpi,
                    'width_px': img.width,
                    'height_px': img.height,
                    'file_size_mb': file_size / (1024 * 1024),
                    'violations': violations,
                    'printable': len(violations) == 0
                }
                
        except Exception as e:
            return {
                'filename': os.path.basename(file_path),
                'color_space': 'Ошибка',
                'dpi': 0,
                'width_px': 0,
                'height_px': 0,
                'file_size_mb': 0,
                'violations': [f"Ошибка открытия файла: {str(e)}"],
                'printable': False
            }
    
    def check_image(self, file_path):
        """
        Полная проверка изображения на соответствие требованиям
        
        Args:
            file_path: Путь к файлу изображения
            
        Returns:
            dict: Полные результаты проверки
        """
        # Быстрая проверка основных требований
        basic_result = self.check_basic_requirements(file_path)
        
        # Если уже есть нарушения - возврат без OCR проверки
        if not basic_result['printable']:
            basic_result.update({
                'text_regions': [],
                'text_violations': [],
                'text_violations_count': 0
            })
            return basic_result
        
        # Проверка текста если основные требования выполнены
        violations = basic_result['violations'].copy()
        text_violations = []
        text_regions = []
        
        try:
            with Image.open(file_path) as img:
                dpi = img.info.get('dpi', (72, 72))[0]
                
                # Расчет размеров в пикселях
                bleed_px = self.mm_to_pixels(self.requirements['bleed_mm'], dpi)
                target_width_px = self.mm_to_pixels(self.requirements['target_width_mm'], dpi)
                target_height_px = self.mm_to_pixels(self.requirements['target_height_mm'], dpi)
                
                # Проверка текста (только если DPI достаточный для OCR)
                if dpi >= 150:
                    # Детекция текстовых областей
                    text_regions = self.text_detector.detect_text_regions(file_path, dpi)
                    
                    if text_regions:
                        # Проверка отступов текста
                        text_violations = self.text_detector.check_text_margins(
                            text_regions, img.width, img.height, bleed_px, 
                            target_width_px, target_height_px
                        )
                        
                        if text_violations:
                            violations.append(f"Текст ближе {self.requirements['min_text_margin_mm']} мм к обрезному формату")
                
                # Формирование полного результата проверки
                info = {
                    'filename': basic_result['filename'],
                    'color_space': basic_result['color_space'],
                    'dpi': basic_result['dpi'],
                    'width_px': basic_result['width_px'],
                    'height_px': basic_result['height_px'],
                    'width_mm': basic_result['width_px'] / dpi * 25.4 if dpi > 0 else 0,
                    'height_mm': basic_result['height_px'] / dpi * 25.4 if dpi > 0 else 0,
                    'file_size_mb': basic_result['file_size_mb'],
                    'violations': violations,
                    'text_regions': text_regions,
                    'text_violations': text_violations,
                    'text_violations_count': len(text_violations),
                    'printable': len(violations) == 0
                }
                
                return info
                
        except Exception as e:
            basic_result['violations'].append(f"Ошибка проверки текста: {str(e)}")
            basic_result['printable'] = False
            basic_result.update({
                'text_regions': [],
                'text_violations': [],
                'text_violations_count': 0
            })
            return basic_result