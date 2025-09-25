# test_image_generator.py
import os
from PIL import Image, ImageDraw, ImageFont
import numpy as np

class TextTestGenerator:
    def __init__(self, output_folder="test_images"):
        self.output_folder = output_folder
        os.makedirs(output_folder, exist_ok=True)
        
        # Основные параметры согласно требованиям типографии
        self.bleed_mm = 5
        self.target_width_mm = 100
        self.target_height_mm = 70
        self.min_text_margin_mm = 5
        self.min_dpi = 300
        
        self.total_width_mm = self.target_width_mm + 2 * self.bleed_mm
        self.total_height_mm = self.target_height_mm + 2 * self.bleed_mm
        
        # Попытка загрузки шрифтов
        try:
            self.font_large = ImageFont.truetype("arial.ttf", 40)
            self.font_small = ImageFont.truetype("arial.ttf", 20)
        except:
            try:
                self.font_large = ImageFont.truetype("arial.ttf", 40)
                self.font_small = ImageFont.truetype("arial.ttf", 20)
            except:
                print("Предупреждение: Используются стандартные шрифты")
                self.font_large = ImageFont.load_default()
                self.font_small = ImageFont.load_default()
    
    def mm_to_pixels(self, mm, dpi):
        """Конвертирует мм в пиксели"""
        return int(mm / 25.4 * dpi)
    
    def create_cmyk_image(self, width_px, height_px, dpi=300):
        """Создает CMYK изображение"""
        image = Image.new('CMYK', (width_px, height_px), (0, 0, 0, 0))
        return image
    
    def create_rgb_image(self, width_px, height_px, dpi=300):
        """Создает RGB изображение"""
        image = Image.new('RGB', (width_px, height_px), (255, 255, 255))
        return image
    
    def add_guidelines(self, draw, width_px, height_px, bleed_px, dpi):
        """Добавляет направляющие линии на изображение"""
        # Линии обрезного формата - красные
        draw.line([bleed_px, 0, bleed_px, height_px], fill=(255, 0, 0, 255), width=2)
        draw.line([width_px-bleed_px, 0, width_px-bleed_px, height_px], fill=(255, 0, 0, 255), width=2)
        draw.line([0, bleed_px, width_px, bleed_px], fill=(255, 0, 0, 255), width=2)
        draw.line([0, height_px-bleed_px, width_px, height_px-bleed_px], fill=(255, 0, 0, 255), width=2)
        
        # Безопасная зона для текста - синие пунктирные линии
        safe_margin_px = self.mm_to_pixels(self.min_text_margin_mm, dpi)
        safe_x1 = bleed_px + safe_margin_px
        safe_y1 = bleed_px + safe_margin_px
        safe_x2 = width_px - bleed_px - safe_margin_px
        safe_y2 = height_px - bleed_px - safe_margin_px
        
        # Пунктирные линии для безопасной зоны
        for i in range(0, width_px, 20):
            if i % 40 == 0:
                draw.line([i, safe_y1, min(i+20, width_px), safe_y1], fill=(0, 0, 255, 255), width=1)
                draw.line([i, safe_y2, min(i+20, width_px), safe_y2], fill=(0, 0, 255, 255), width=1)
        
        for i in range(0, height_px, 20):
            if i % 40 == 0:
                draw.line([safe_x1, i, safe_x1, min(i+20, height_px)], fill=(0, 0, 255, 255), width=1)
                draw.line([safe_x2, i, safe_x2, min(i+20, height_px)], fill=(0, 0, 255, 255), width=1)
    
    def add_text_with_info(self, draw, text, x_mm_from_crop, y_mm_from_crop, dpi, bleed_px, 
                        color=(0, 0, 0, 255), description="", anchor="center"):
        """Исправленная функция с поддержкой anchor позиционирования"""
        
        # Конвертируем координаты
        x_px_from_crop = self.mm_to_pixels(x_mm_from_crop, dpi)
        y_px_from_crop = self.mm_to_pixels(y_mm_from_crop, dpi)
        x_px_absolute = bleed_px + x_px_from_crop
        y_px_absolute = bleed_px + y_px_from_crop
        
        # Получаем размеры основного текста
        bbox = draw.textbbox((0, 0), text, font=self.font_large)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Корректируем позицию для anchor
        if anchor == "center":
            x_px_absolute -= text_width // 2
            y_px_absolute -= text_height // 2
        elif anchor == "top":
            x_px_absolute -= text_width // 2
        elif anchor == "bottom":
            x_px_absolute -= text_width // 2
            y_px_absolute -= text_height
        elif anchor == "left":
            y_px_absolute -= text_height // 2
        elif anchor == "right":
            x_px_absolute -= text_width
            y_px_absolute -= text_height // 2
        
        # Рисуем основной текст
        draw.text((x_px_absolute, y_px_absolute), text, fill=color, font=self.font_large)
        
        # Информационная подпись (выравнивается по тому же anchor)
        if description:
            desc_bbox = draw.textbbox((0, 0), description, font=self.font_small)
            desc_height = desc_bbox[3] - desc_bbox[1]
            
            desc_y = y_px_absolute + text_height + 10
            if anchor == "center":
                desc_x = x_px_absolute + text_width // 2 - draw.textlength(description, font=self.font_small) // 2
            elif anchor in ["top", "bottom"]:
                desc_x = x_px_absolute + text_width // 2 - draw.textlength(description, font=self.font_small) // 2
            else:
                desc_x = x_px_absolute
                
            draw.text((desc_x, desc_y), description, fill=(255, 0, 0, 255), font=self.font_small)
        
        return (x_px_absolute, y_px_absolute)
    
    def create_test_image(self, filename, dpi=300, color_space='CMYK', 
                         correct_size=True, add_guides=True, text_positions=[]):
        """Создает тестовое изображение с заданными параметрами"""
        
        # Расчет размеров
        if correct_size:
            width_px = self.mm_to_pixels(self.total_width_mm, dpi)
            height_px = self.mm_to_pixels(self.total_height_mm, dpi)
        else:
            # Неправильный размер - на 20% меньше
            width_px = self.mm_to_pixels(self.total_width_mm * 0.8, dpi)
            height_px = self.mm_to_pixels(self.total_height_mm * 0.8, dpi)
        
        bleed_px = self.mm_to_pixels(self.bleed_mm, dpi)
        target_width_px = self.mm_to_pixels(self.target_width_mm, dpi)
        target_height_px = self.mm_to_pixels(self.target_height_mm, dpi)
        
        # Создаем изображение в нужном цветовом пространстве
        if color_space == 'CMYK':
            image = self.create_cmyk_image(width_px, height_px, dpi)
        else:
            image = self.create_rgb_image(width_px, height_px, dpi)
        
        draw = ImageDraw.Draw(image)
        
        # Фон
        if color_space == 'CMYK':
            draw.rectangle([0, 0, width_px, height_px], fill=(5, 5, 5, 0))  # Светло-серый CMYK
            draw.rectangle([bleed_px, bleed_px, width_px-bleed_px, height_px-bleed_px], 
                          fill=(0, 0, 0, 0))  # Белый в обрезной зоне
        else:
            draw.rectangle([0, 0, width_px, height_px], fill=(240, 240, 240))  # Светло-серый RGB
            draw.rectangle([bleed_px, bleed_px, width_px-bleed_px, height_px-bleed_px], 
                          fill=(255, 255, 255))  # Белый в обрезной зоне
        
        # Добавляем направляющие
        if add_guides:
            self.add_guidelines(draw, width_px, height_px, bleed_px, dpi)
        
        # Добавляем текст с ИСПРАВЛЕННЫМИ координатами
        for text_info in text_positions:
            if len(text_info) == 3:
                text, x_mm_from_crop, y_mm_from_crop = text_info
                description = f"{x_mm_from_crop}×{y_mm_from_crop}мм от обреза"
            else:
                text, x_mm_from_crop, y_mm_from_crop, description = text_info
            
            self.add_text_with_info(draw, text, x_mm_from_crop, y_mm_from_crop, dpi, 
                                  bleed_px, description=description)
        
        # Сохраняем с правильным DPI
        image.save(os.path.join(self.output_folder, filename), dpi=(dpi, dpi))
        print(f"Создано: {filename} (DPI: {dpi}, Цвет: {color_space}, Размер: {width_px}×{height_px}px)")
        
        return os.path.join(self.output_folder, filename)
    
    def generate_text_test_images(self):
        """Генерирует изображения с ПРАВИЛЬНОЙ логикой безопасных зон"""
        print("=== Генерация тестовых изображений с текстом ===")
        
        # Безопасная зона: 5мм от границ обрезной зоны
        # Обрезная зона: 100×70мм, начинается с координат (5мм, 5мм) от края изображения
        
        # 1. Идеальное изображение - весь текст в безопасной зоне (отступ >5мм)
        safe_texts = [
            ("Безопасный", 15, 10, "center"),     # 15мм от левого края обрезной зоны (отступ 15мм)
            ("Заголовок", 50, 10, "top"),         # Центр по X, 10мм от верха обрезной зоны
            ("Текст2024", 50, 60, "bottom")       # Центр по X, 60мм от верха обрезной зоны
        ]
        self.create_test_image("01_text_perfect.tiff", dpi=300, text_positions=safe_texts)
        
        # 2. Текст слишком близко к ЛЕВОМУ краю обрезной зоны (2мм вместо 5мм)
        left_edge_texts = [
            ("Опасный", 2, 35, "left"),          # 2мм от левого края обрезной зоны
            ("Безопасный", 50, 35, "center")     # Для сравнения
        ]
        self.create_test_image("02_text_close_left.tiff", dpi=300, text_positions=left_edge_texts)
        
        # 3. Текст слишком близко к ПРАВОМУ краю обрезной зоны (2мм вместо 5мм)
        right_edge_texts = [
            ("Опасный", 98, 35, "right"),        # 98мм от левого края обрезной зоны (100-2=98)
            ("Безопасный", 50, 35, "center")
        ]
        self.create_test_image("03_text_close_right.tiff", dpi=300, text_positions=right_edge_texts)
        
        # 4. Текст слишком близко к ВЕРХНЕМУ краю обрезной зоны (2мм вместо 5мм)
        top_edge_texts = [
            ("Опасный", 50, 2, "top"),           # 2мм от верхнего края обрезной зоны
            ("Безопасный", 50, 35, "center")
        ]
        self.create_test_image("04_text_close_top.tiff", dpi=300, text_positions=top_edge_texts)
        
        # 5. Текст слишком близко к НИЖНЕМУ краю обрезной зоны (2мм вместо 5мм)
        bottom_edge_texts = [
            ("Опасный", 50, 68, "bottom"),       # 68мм от верхнего края обрезной зоны (70-2=68)
            ("Безопасный", 50, 35, "center")
        ]
        self.create_test_image("05_text_close_bottom.tiff", dpi=300, text_positions=bottom_edge_texts)
        
        # 6. Текст ВЫХОДИТ ЗА обрезную зону (критическая ошибка)
        outside_texts = [
            ("ВНЕ ЗОНЫ", -3, 35, "left"),        # Текст залезает на bleed-зону
            ("ОБРЕЗ", 102, 35, "right"),         # Текст за правой границей обрезной зоны
            ("Безопасный", 50, 35, "center")     # Для сравнения
        ]
        self.create_test_image("06_text_outside_crop.tiff", dpi=300, text_positions=outside_texts)
        
        # 7. Текст точно на границе безопасной зоны (ровно 5мм)
        borderline_texts = [
            ("Граница5мм", 5, 5, "top_left"),    # Ровно 5мм от левого и верхнего краев
            ("Норма5мм", 95, 65, "bottom_right") # Ровно 5мм от правого и нижнего краев
        ]
        self.create_test_image("07_text_borderline.tiff", dpi=300, text_positions=borderline_texts)
        
        # 8. Разные варианты расположения
        multi_texts = [
            ("Безопасно", 20, 15, "center"),     # 20мм от левого края обрезной зоны
            ("Опасно", 3, 40, "left"),           # 3мм от левого края
            ("Норма", 80, 60, "bottom_right"),   # 80мм от левого, 60мм от верха
            ("Риск", 97, 10, "top_right")        # 97мм от левого края
        ]
        self.create_test_image("08_text_various.tiff", dpi=300, text_positions=multi_texts)
        
        print("\n✅ Генерация тестовых изображений с правильной логикой завершена!")
    
    def generate_technical_test_images(self):
        """Генерирует технические тестовые изображения (без текста)"""
        print("\n=== Генерация технических тестовых изображений ===")
        
        # Правильные изображения
        self.create_test_image("correct_cmyk_300dpi.tiff", dpi=300, color_space='CMYK', text_positions=[])
        self.create_test_image("correct_cmyk_350dpi.tiff", dpi=350, color_space='CMYK', text_positions=[])
        
        # Изображения с ошибками
        self.create_test_image("error_rgb_300dpi.tiff", dpi=300, color_space='RGB', text_positions=[])
        self.create_test_image("error_low_dpi.tiff", dpi=200, color_space='CMYK', text_positions=[])
        self.create_test_image("error_wrong_size.tiff", dpi=300, color_space='CMYK', correct_size=False, text_positions=[])
        
        print("✅ Генерация технических тестовых изображений завершена!")
    
    def generate_all_test_images(self):
        """Генерирует все тестовые изображения"""
        self.generate_text_test_images()
        self.generate_technical_test_images()
        
        total_files = len([f for f in os.listdir(self.output_folder) if f.endswith(('.tiff', '.jpg', '.png'))])
        print(f"\n🎉 Всего создано тестовых изображений: {total_files}")
        print(f"📁 Папка: {os.path.abspath(self.output_folder)}")

if __name__ == "__main__":
    generator = TextTestGenerator()
    generator.generate_all_test_images()