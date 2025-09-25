# test_generator_gui.py
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import os
from test_image_generator import TextTestGenerator

class TestGeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Генератор тестовых изображений для проверки типографии")
        self.root.geometry("600x500")
        
        self.generator = TextTestGenerator()
        self.setup_ui()
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Заголовок
        title = ttk.Label(
            main_frame, 
            text="Генератор тестовых изображений", 
            font=("Arial", 16, "bold")
        )
        title.pack(pady=(0, 15))
        
        # Описание
        desc_frame = ttk.LabelFrame(main_frame, text="Описание тестов", padding="10")
        desc_frame.pack(fill=tk.X, pady=(0, 15))
        
        desc_text = scrolledtext.ScrolledText(desc_frame, height=8, wrap=tk.WORD)
        desc_text.pack(fill=tk.BOTH, expand=True)
        
        test_cases = """ТЕКСТОВЫЕ ТЕСТЫ (14 изображений):
✓ 01-09: Разное расположение текста относительно границ
✓ 10: Изображение без текста (контрольный)
✓ 11: Низкое DPI (150) с текстом
✓ 12: RGB вместо CMYK с текстом
✓ 13: Неправильный размер с текстом
✓ 14: Сложный текст (разный размер, цифры)

ТЕХНИЧЕСКИЕ ТЕСТЫ (5 изображений):
✓ Правильные CMYK 300/350 DPI
✓ Ошибочные (RGB, низкое DPI, неправильный размер)

ВСЕГО: 19 тестовых изображений"""
        
        desc_text.insert(tk.END, test_cases)
        desc_text.config(state=tk.DISABLED)
        
        # Прогресс
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=(0, 10))
        
        # Статус
        self.status_label = ttk.Label(main_frame, text="Готов к генерации тестовых изображений")
        self.status_label.pack(pady=(0, 15))
        
        # Кнопки
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        ttk.Button(
            button_frame, 
            text="📁 Сгенерировать ВСЕ тесты", 
            command=self.generate_all_tests
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame, 
            text="🔤 Только текстовые тесты", 
            command=self.generate_text_tests
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame, 
            text="⚙️ Только технические тесты", 
            command=self.generate_technical_tests
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        # Кнопки управления
        manage_frame = ttk.Frame(main_frame)
        manage_frame.pack(fill=tk.X, pady=(15, 0))
        
        ttk.Button(
            manage_frame, 
            text="📂 Открыть папку с изображениями", 
            command=self.open_folder
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            manage_frame, 
            text="🗑️ Очистить папку", 
            command=self.clear_folder
        ).pack(side=tk.LEFT)
        
        # Информация о папке
        folder_info = ttk.Label(
            main_frame, 
            text=f"Папка назначения: {os.path.abspath(self.generator.output_folder)}",
            font=("Arial", 9)
        )
        folder_info.pack(pady=(10, 0))
    
    def generate_all_tests(self):
        """Запускает генерацию всех тестов"""
        self.start_generation(self.generator.generate_all_test_images)
    
    def generate_text_tests(self):
        """Запускает генерацию только текстовых тестов"""
        self.start_generation(self.generator.generate_text_test_images)
    
    def generate_technical_tests(self):
        """Запускает генерацию только технических тестов"""
        self.start_generation(self.generator.generate_technical_test_images)
    
    def start_generation(self, generation_function):
        """Запускает генерацию в отдельном потоке"""
        if not self.check_folder_writable():
            return
        
        self.progress.start()
        self.status_label.config(text="Генерация изображений...")
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=lambda: self.run_generation(generation_function))
        thread.daemon = True
        thread.start()
    
    def run_generation(self, generation_function):
        """Выполняет генерацию в отдельном потоке"""
        try:
            generation_function()
            self.root.after(0, self.generation_complete)
        except Exception as e:
            self.root.after(0, lambda: self.generation_error(str(e)))
    
    def generation_complete(self):
        """Вызывается при успешной генерации"""
        self.progress.stop()
        self.status_label.config(text="Генерация завершена успешно!")
        
        # Подсчет файлов
        count = len([f for f in os.listdir(self.generator.output_folder) 
                    if f.endswith(('.tiff', '.jpg', '.png'))])
        
        messagebox.showinfo(
            "Успех", 
            f"Тестовые изображения успешно созданы!\n\n"
            f"Создано файлов: {count}\n"
            f"Папка: {os.path.abspath(self.generator.output_folder)}"
        )
    
    def generation_error(self, error):
        """Вызывается при ошибке генерации"""
        self.progress.stop()
        self.status_label.config(text="Ошибка генерации")
        messagebox.showerror("Ошибка", f"Ошибка при генерации:\n{error}")
    
    def check_folder_writable(self):
        """Проверяет доступность папки для записи"""
        try:
            test_file = os.path.join(self.generator.output_folder, "test_write.tmp")
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return True
        except Exception as e:
            messagebox.showerror("Ошибка", f"Невозможно записать в папку:\n{e}")
            return False
    
    def open_folder(self):
        """Открывает папку с изображениями"""
        try:
            import subprocess
            subprocess.Popen(f'explorer "{os.path.abspath(self.generator.output_folder)}"')
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку:\n{e}")
    
    def clear_folder(self):
        """Очищает папку с изображениями"""
        if not messagebox.askyesno("Подтверждение", "Удалить все тестовые изображения?"):
            return
        
        try:
            for filename in os.listdir(self.generator.output_folder):
                if filename.lower().endswith(('.tiff', '.jpg', '.png', '.tmp')):
                    os.remove(os.path.join(self.generator.output_folder, filename))
            
            self.status_label.config(text="Папка очищена")
            messagebox.showinfo("Успех", "Папка с тестовыми изображениями очищена")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка при очистке папки:\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    app = TestGeneratorGUI(root)
    root.mainloop()