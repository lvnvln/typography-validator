"""
Модуль графического интерфейса пользователя для приложения проверки изображений.
Содержит классы для создания и управления UI элементами.
"""

import os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from validator import ImageValidator
import pandas as pd

class PrintValidatorApp:
    """Основной класс приложения для проверки изображений с графическим интерфейсом"""
    
    def __init__(self, root):
        """
        Инициализация главного окна приложения
        
        Args:
            root: Корневое окно Tkinter
        """
        self.root = root
        self.root.title("Проверка изображений для типографии")
        self.root.geometry("1000x800")
        
        # Инициализация валидатора изображений
        self.validator = ImageValidator()
        self.results = []  # Список для хранения результатов проверки
        
        self.setup_ui()
    
    def setup_ui(self):
        """Создание и настройка элементов пользовательского интерфейса"""
        # Основной фрейм
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Настройка весов для адаптивного изменения размеров
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        # Заголовок приложения
        title_label = ttk.Label(main_frame, 
                               text="Проверка изображений для типографии", 
                               font=("Arial", 14, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 10))
        
        # Блок с требованиями
        req_text = self._get_requirements_text()
        req_label = ttk.Label(main_frame, text=req_text, justify=tk.LEFT)
        req_label.grid(row=1, column=0, columnspan=3, pady=(0, 10), sticky=tk.W)
        
        # Секция выбора папки
        self._create_folder_selection_section(main_frame, row=2)
        
        # Кнопка запуска проверки
        ttk.Button(main_frame, 
                  text="Проверить изображения", 
                  command=self.validate_images).grid(row=3, column=0, columnspan=3, pady=10)
        
        # Прогресс-бар
        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        
        # Секция результатов
        self._create_results_section(main_frame, row=5)
        
        # Секция детальной информации
        self._create_detail_section(main_frame, row=6)
        
        # Панель кнопок экспорта
        self._create_export_buttons(main_frame, row=7)
        
        # Настройка растягивания основного фрейма
        main_frame.rowconfigure(5, weight=1)
    
    def _get_requirements_text(self):
        """Возвращает текст с требованиями типографии"""
        return """Требования типографии:
- Размер файла: не более 100 МБ
- Цветовое пространство: CMYK
- Обрезной размер: 100×70 мм
- Вылеты: по 5 мм с каждой стороны
- Итоговый размер с вылетами: 110×80 мм
- Разрешение: не менее 300 DPI
- Текст: не ближе 5 мм к обрезному формату"""
    
    def _create_folder_selection_section(self, parent, row):
        """Создает секцию выбора папки с изображениями"""
        ttk.Label(parent, text="Папка с изображениями:").grid(row=row, column=0, sticky=tk.W, pady=5)
        
        self.folder_path = tk.StringVar()
        ttk.Entry(parent, textvariable=self.folder_path, width=60).grid(
            row=row, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 0))
        
        ttk.Button(parent, text="Выбрать папку", command=self.select_folder).grid(
            row=row, column=2, pady=5, padx=(5, 0))
    
    def _create_results_section(self, parent, row):
        """Создает секцию отображения результатов проверки"""
        results_frame = ttk.LabelFrame(parent, text="Результаты проверки", padding="5")
        results_frame.grid(row=row, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        # Таблица результатов
        columns = ('Файл', 'Статус', 'Цвет', 'DPI', 'Размер (px)', 'Текст', 'Нарушения')
        self.tree = ttk.Treeview(results_frame, columns=columns, show='headings', height=12)
        
        # Настройка колонок таблицы
        column_widths = {'Файл': 150, 'Статус': 100, 'Цвет': 80, 'DPI': 60, 
                        'Размер (px)': 100, 'Текст': 80, 'Нарушения': 120}
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=column_widths.get(col, 100))
        
        # Скроллбар для таблицы
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    
    def _create_detail_section(self, parent, row):
        """Создает секцию детальной информации о выбранном изображении"""
        detail_frame = ttk.LabelFrame(parent, text="Детальная информация", padding="5")
        detail_frame.grid(row=row, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=5)
        detail_frame.columnconfigure(0, weight=1)
        
        self.detail_text = tk.Text(detail_frame, height=10, width=100)
        self.detail_text.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        detail_scrollbar = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scrollbar.set)
        detail_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        # Привязка события выбора в таблице
        self.tree.bind('<<TreeviewSelect>>', self.show_details)
    
    def _create_export_buttons(self, parent, row):
        """Создает панель кнопок для экспорта результатов"""
        button_frame = ttk.Frame(parent)
        button_frame.grid(row=row, column=0, columnspan=3, pady=10)
        
        ttk.Button(button_frame, text="Сохранить отчет в Excel", 
                  command=self.export_to_excel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Сохранить отчет в CSV", 
                  command=self.export_to_csv).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Очистить результаты", 
                  command=self.clear_results).pack(side=tk.LEFT, padx=5)
    
    def select_folder(self):
        """Обработчик выбора папки с изображениями"""
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path.set(folder)
    
    def validate_images(self):
        """Основная функция проверки изображений в выбранной папке"""
        folder = self.folder_path.get()
        if not folder or not os.path.exists(folder):
            messagebox.showerror("Ошибка", "Выберите существующую папку")
            return
        
        # Поиск поддерживаемых форматов изображений
        supported_formats = ('.jpg', '.jpeg', '.tiff', '.tif', '.png', '.psd', '.eps')
        image_files = [os.path.join(folder, f) for f in os.listdir(folder) 
                      if f.lower().endswith(supported_formats)]
        
        if not image_files:
            messagebox.showinfo("Информация", "В выбранной папке не найдено поддерживаемых изображений")
            return
        
        # Очистка предыдущих результатов
        self._clear_previous_results()
        
        # Настройка прогресс-бара
        self.progress['maximum'] = len(image_files)
        
        # Проверка каждого изображения
        for i, file_path in enumerate(image_files):
            result = self.validator.check_image(file_path)
            self.results.append(result)
            self._add_result_to_table(result, i)
            self.progress['value'] = i + 1
            self.root.update_idletasks()
        
        # Показ статистики проверки
        self._show_validation_statistics()
    
    def _clear_previous_results(self):
        """Очищает результаты предыдущей проверки"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.detail_text.delete(1.0, tk.END)
        self.results = []
    
    def _add_result_to_table(self, result, index):
        """Добавляет результат проверки в таблицу"""
        status = "✓ Можно печатать" if result['printable'] else "✗ Нельзя печатать"
        size_px = f"{result['width_px']}×{result['height_px']}"
        text_info = f"{len(result['text_regions'])} обл." if result['text_regions'] else "Нет"
        violations_count = len(result['violations']) + result['text_violations_count']
        
        self.tree.insert('', 'end', values=(
            result['filename'],
            status,
            result['color_space'],
            result['dpi'],
            size_px,
            text_info,
            violations_count
        ))
    
    def _show_validation_statistics(self):
        """Показывает статистику по результатам проверки"""
        printable_count = sum(1 for r in self.results if r['printable'])
        total_count = len(self.results)
        
        messagebox.showinfo("Проверка завершена", 
                          f"Проверено изображений: {total_count}\n"
                          f"Можно печатать: {printable_count}\n"
                          f"Нельзя печатать: {total_count - printable_count}")
    
    def show_details(self, event):
        """Показывает детальную информацию о выбранном изображении"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        index = self.tree.index(item)
        result = self.results[index]
        
        self.detail_text.delete(1.0, tk.END)
        self._format_detailed_info(result)
    
    def _format_detailed_info(self, result):
        """Форматирует детальную информацию для отображения"""
        # Основная информация
        self.detail_text.insert(tk.END, f"Файл: {result['filename']}\n")
        self.detail_text.insert(tk.END, f"Статус: {'Можно печатать' if result['printable'] else 'Нельзя печатать'}\n")
        self.detail_text.insert(tk.END, f"Цветовое пространство: {result['color_space']}\n")
        self.detail_text.insert(tk.END, f"DPI: {result['dpi']}\n")
        self.detail_text.insert(tk.END, f"Размер в пикселях: {result['width_px']} × {result['height_px']}\n")
        
        if 'width_mm' in result:
            self.detail_text.insert(tk.END, f"Размер в мм: {result['width_mm']:.1f} × {result['height_mm']:.1f}\n")
        
        self.detail_text.insert(tk.END, f"Размер файла: {result['file_size_mb']:.1f} МБ\n")
        self.detail_text.insert(tk.END, f"Найдено текстовых областей: {len(result['text_regions'])}\n")
        self.detail_text.insert(tk.END, f"Нарушений по тексту: {len(result['text_violations'])}\n\n")
        
        # Нарушения
        if result['violations']:
            self.detail_text.insert(tk.END, "Нарушения:\n")
            for violation in result['violations']:
                self.detail_text.insert(tk.END, f"• {violation}\n")
        
        # Детали текстовых нарушений
        if result['text_violations']:
            self.detail_text.insert(tk.END, "\nНарушения расположения текста:\n")
            for i, violation in enumerate(result['text_violations'][:5]):
                self.detail_text.insert(tk.END, 
                    f"{i+1}. Текст: '{violation['text']}' - "
                    f"отступ {violation['distance_to_crop_mm']:.1f} мм "
                    f"(требуется: {self.validator.requirements['min_text_margin_mm']} мм)\n")
            
            if len(result['text_violations']) > 5:
                self.detail_text.insert(tk.END, f"... и еще {len(result['text_violations']) - 5} нарушений\n")
    
    def export_to_excel(self):
        """Экспортирует результаты проверки в Excel файл"""
        if not self.results:
            messagebox.showwarning("Предупреждение", "Нет данных для экспорта")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                export_data = self._prepare_export_data()
                df = pd.DataFrame(export_data)
                df.to_excel(file_path, index=False)
                messagebox.showinfo("Успех", f"Отчет сохранен в {file_path}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка при сохранении Excel: {e}")
    
    def export_to_csv(self):
        """Экспортирует результаты проверки в CSV файл"""
        if not self.results:
            messagebox.showwarning("Предупреждение", "Нет данных для экспорта")
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        
        if file_path:
            try:
                export_data = self._prepare_export_data()
                df = pd.DataFrame(export_data)
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
                messagebox.showinfo("Успех", f"Отчет сохранен в {file_path}")
            except Exception as e:
                messagebox.showerror("Ошибка", f"Ошибка при сохранении CSV: {e}")
    
    def _prepare_export_data(self):
        """Подготавливает данные для экспорта"""
        export_data = []
        for result in self.results:
            text_violations_info = ""
            if result['text_violations']:
                text_violations_info = f"{len(result['text_violations'])} нарушений"
            
            export_data.append({
                'Файл': result['filename'],
                'Статус': 'Можно печатать' if result['printable'] else 'Нельзя печатать',
                'Цветовое пространство': result['color_space'],
                'DPI': result['dpi'],
                'Ширина (px)': result['width_px'],
                'Высота (px)': result['height_px'],
                'Ширина (мм)': f"{result.get('width_mm', 0):.1f}",
                'Высота (мм)': f"{result.get('height_mm', 0):.1f}",
                'Размер файла (МБ)': f"{result['file_size_mb']:.1f}",
                'Текстовых областей': len(result['text_regions']),
                'Нарушений по тексту': len(result['text_violations']),
                'Всего нарушений': len(result['violations']) + len(result['text_violations']),
                'Нарушения': '; '.join(result['violations']),
                'Текстовые нарушения': text_violations_info
            })
        return export_data
    
    def clear_results(self):
        """Очищает все результаты проверки"""
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.detail_text.delete(1.0, tk.END)
        self.results = []
        self.progress['value'] = 0