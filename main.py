#!/usr/bin/env python3
"""
Главный модуль приложения для проверки изображений для типографии.
Запускает графический интерфейс пользователя.
"""

from gui import PrintValidatorApp
import tkinter as tk

def main():
    """Основная функция запуска приложения"""
    try:
        # Проверка наличия необходимых библиотек
        from PIL import Image, ImageCms
        import pandas as pd
        import cv2
        import easyocr
    except ImportError as e:
        print("Необходимо установить библиотеки:")
        print("pip install Pillow pandas openpyxl opencv-python easyocr")
        return
    
    # Создание и запуск главного окна приложения
    root = tk.Tk()
    app = PrintValidatorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()