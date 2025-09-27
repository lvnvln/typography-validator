# app.py
"""
Главный модуль приложения для проверки изображений для типографии с использованием Gradio.
Вариант №2: пользователь может загрузить файлы/ZIP прямо в UI (без обязательного монтирования /data).
"""

import os
import io
import shutil
import zipfile
import tempfile
import pandas as pd
import gradio as gr

from validator import ImageValidator
from test_image_generator import TextTestGenerator

# Колонки таблицы (используем везде для пустых состояний)
COLUMNS = ['Файл', 'Статус', 'Цвет', 'DPI', 'Размер (px)', 'Текст', 'Нарушения']


class GradioPrintValidator:
    """Класс приложения с интерфейсом на Gradio"""

    def __init__(self):
        self.validator = ImageValidator()
        self.test_generator = TextTestGenerator()
        self.current_results = []
        self.interface = None
        self.setup_interface()

    # ---------- Текст требований ----------

    def get_requirements_text(self):
        """Возвращает текст с требованиями типографии"""
        return """**Требования типографии:**
- Размер файла: не более 100 МБ
- Цветовое пространство: CMYK
- Обрезной размер: 100×70 мм
- Вылеты: по 5 мм с каждой стороны
- Итоговый размер с вылетами: 110×80 мм
- Разрешение: не менее 300 DPI
- Текст: не ближе 5 мм к линии обрезного формата"""

    # ---------- Основная проверка папки ----------

    def validate_images_interface(self, folder_path, progress=gr.Progress()):
        """Интерфейсная функция для проверки изображений (устойчива к пустой папке/ошибкам)."""
        # 0) Проверка пути
        if not folder_path or not os.path.isdir(folder_path):
            empty_df = pd.DataFrame(columns=COLUMNS)
            return gr.update(value="**Ошибка:** Выберите существующую папку"), empty_df, ""

        # 1) Собираем поддерживаемые файлы (рекурсивно)
        supported = ('.jpg', '.jpeg', '.tiff', '.tif', '.png', '.psd', '.eps', '.bmp', '.webp')
        image_files = []
        try:
            for root, _, files in os.walk(folder_path):
                for f in files:
                    if f.lower().endswith(supported):
                        image_files.append(os.path.join(root, f))
        except Exception as e:
            empty_df = pd.DataFrame(columns=COLUMNS)
            return gr.update(value=f"**Ошибка доступа к папке:** {e!s}"), empty_df, ""

        # 2) Нет подходящих файлов
        if not image_files:
            empty_df = pd.DataFrame(columns=COLUMNS)
            return gr.update(value="**Информация:** В выбранной папке не найдено поддерживаемых изображений"), empty_df, ""

        # 3) Проверка каждого изображения
        self.current_results = []
        rows = []
        for file_path in progress.tqdm(image_files, desc="Проверка изображений"):
            name = os.path.basename(file_path)
            try:
                # Наш tesseract-валидатор
                if hasattr(self.validator, "validate_file"):
                    res = self.validator.validate_file(file_path)
                else:
                    res = self.validator.check_image(file_path)
            except Exception:
                res = None

            # Гарантия словаря результата
            if not isinstance(res, dict):
                res = {
                    "filename": name,
                    "printable": False,
                    "violations": ["Ошибка при обработке файла"],
                    "text_regions": [],
                    "text_violations": [],
                    "text_violations_count": -1,
                    "dpi": None,
                    "size_px": None,
                    "file_mb": None,
                    "mode": "unknown",
                    "color_space": "unknown",
                }

            self.current_results.append(res)

            status = "✓ Можно печатать" if res.get('printable') else "✗ Нельзя печатать"
            color_space = res.get('mode') or res.get('color_space') or "—"
            dpi = res.get('dpi')

            size_px = res.get('size_px')
            if not size_px and all(k in res for k in ("width_px", "height_px")):
                size_px = (res.get("width_px"), res.get("height_px"))
            size_px_text = f"{size_px[0]}×{size_px[1]}" if isinstance(size_px, (list, tuple)) and len(size_px) == 2 else "—"

            text_regions = res.get('text_regions') or []
            text_info = f"{len(text_regions)} обл." if text_regions else "Нет"

            violations = res.get('violations') or []
            tv_count = res.get('text_violations_count')
            if tv_count is None:
                tv_count = len(res.get('text_violations') or [])
            total_viol = len(violations) + (tv_count if isinstance(tv_count, int) and tv_count > 0 else 0)

            rows.append([
                res.get('filename', name),
                status,
                color_space,
                dpi if dpi is not None else "—",
                size_px_text,
                text_info,
                total_viol
            ])

        # 4) Статистика и таблица
        printable_count = sum(1 for r in self.current_results if r.get('printable'))
        total_count = len(self.current_results)
        stats_text = (
            f"**Проверка завершена:**\n"
            f"- Проверено изображений: {total_count}\n"
            f"- Можно печатать: {printable_count}\n"
            f"- Нельзя печатать: {total_count - printable_count}"
        )
        df = pd.DataFrame(rows, columns=COLUMNS)
        return gr.update(value=stats_text), df, ""

    # ---------- Проверка загруженных файлов/ZIP ----------

    def validate_uploaded_files(self, files, progress=gr.Progress()):
        """
        Принимает список путей от gr.Files (или ZIP), складывает во временную папку
        и запускает ту же проверку, что и по обычному пути.
        """
        empty_df = pd.DataFrame(columns=COLUMNS)

        if not files:
            return gr.update(value="**Информация:** Файлы не выбраны"), empty_df, ""

        tmp_dir = tempfile.mkdtemp(prefix="upload_")
        try:
            for f in files:
                p = str(f)  # gr.Files -> путь во временный файл
                if p.lower().endswith(".zip"):
                    try:
                        with zipfile.ZipFile(p, 'r') as zf:
                            zf.extractall(tmp_dir)
                    except Exception as e:
                        return gr.update(value=f"**Ошибка распаковки ZIP:** {e!s}"), empty_df, ""
                else:
                    try:
                        dst = os.path.join(tmp_dir, os.path.basename(p))
                        shutil.copy2(p, dst)
                    except Exception as e:
                        return gr.update(value=f"**Ошибка копирования файла:** {e!s}"), empty_df, ""

            # Проводим обычную проверку по временной папке
            status, df, details = self.validate_images_interface(tmp_dir, progress)
            return status, df, details

        finally:
            # Чистить tmp_dir сразу нельзя, иначе потеряем файлы к моменту чтения.
            # Оставим на усмотрение ОС (временные каталоги периодически чистятся).
            # Если очень нужно — можно добавить кнопку «Очистить загрузки».
            pass

    # ---------- Детальная информация по строке таблицы ----------

    def show_detailed_info(self, evt: gr.SelectData):
        """Показывает детальную информацию о выбранном изображении"""
        if not evt.index or not self.current_results:
            return ""

        index = evt.index[0]  # индекс выбранной строки
        if index >= len(self.current_results):
            return "Ошибка: неверный индекс"

        result = self.current_results[index]

        detailed_info = f"**Файл:** {result.get('filename','')} \n"
        detailed_info += f"**Статус:** {'✓ Можно печатать' if result.get('printable') else '✗ Нельзя печатать'}\n"
        detailed_info += f"**Цветовое пространство:** {result.get('color_space')}\n"
        detailed_info += f"**DPI:** {result.get('dpi')}\n"

        size_px = result.get('size_px')
        if not size_px and all(k in result for k in ("width_px", "height_px")):
            size_px = (result.get("width_px"), result.get("height_px"))
        if size_px:
            detailed_info += f"**Размер в пикселях:** {size_px[0]} × {size_px[1]}\n"

        if 'width_mm' in result and result.get('width_mm') and result.get('height_mm'):
            detailed_info += f"**Размер в мм:** {result.get('width_mm'):.1f} × {result.get('height_mm'):.1f}\n"

        if 'file_mb' in result and result.get('file_mb') is not None:
            detailed_info += f"**Размер файла:** {result.get('file_mb'):.1f} МБ\n"

        text_regions = result.get('text_regions') or []
        text_violations = result.get('text_violations') or []
        detailed_info += f"**Найдено текстовых областей:** {len(text_regions)}\n"
        detailed_info += f"**Нарушений по тексту:** {len(text_violations)}\n\n"

        # Нарушения
        violations = result.get('violations') or []
        if violations:
            detailed_info += "**Нарушения:**\n"
            for violation in violations:
                detailed_info += f"• {violation}\n"

        # Детали текстовых нарушений
        if text_violations:
            detailed_info += "\n**Нарушения расположения текста:**\n"
            for i, violation in enumerate(text_violations[:5]):
                detailed_info += (f"{i+1}. Текст: '{violation.get('text','')}' - "
                                  f"отступ {violation.get('distance_to_crop_mm', 0):.1f} мм "
                                  f"(требуется: {self.validator.requirements['min_text_margin_mm']} мм)\n")
            if len(text_violations) > 5:
                detailed_info += f"... и еще {len(text_violations) - 5} нарушений\n"

        return detailed_info

    # ---------- Экспорт ----------

    def _prepare_export_data(self):
        """Подготавливает данные для экспорта"""
        export_data = []
        for result in self.current_results:
            text_violations_info = ""
            if result.get('text_violations'):
                text_violations_info = f"{len(result['text_violations'])} нарушений"

            size_px = result.get('size_px')
            if not size_px and all(k in result for k in ("width_px", "height_px")):
                size_px = (result.get("width_px"), result.get("height_px"))

            export_data.append({
                'Файл': result.get('filename'),
                'Статус': 'Можно печатать' if result.get('printable') else 'Нельзя печатать',
                'Цветовое пространство': result.get('color_space'),
                'DPI': result.get('dpi'),
                'Ширина (px)': size_px[0] if size_px else "",
                'Высота (px)': size_px[1] if size_px else "",
                'Ширина (мм)': f"{result.get('width_mm', 0):.1f}" if result.get('width_mm') else "",
                'Высота (мм)': f"{result.get('height_mm', 0):.1f}" if result.get('height_mm') else "",
                'Размер файла (МБ)': f"{result.get('file_mb'):.1f}" if result.get('file_mb') is not None else "",
                'Текстовых областей': len(result.get('text_regions') or []),
                'Нарушений по тексту': len(result.get('text_violations') or []),
                'Всего нарушений': len(result.get('violations') or []) + len(result.get('text_violations') or []),
                'Нарушения': '; '.join(result.get('violations') or []),
                'Текстовые нарушения': text_violations_info
            })
        return export_data

    def export_to_excel(self):
        """Экспортирует результаты в Excel"""
        if not self.current_results:
            return gr.update(value="**Предупреждение:** Нет данных для экспорта")
        try:
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp_file:
                export_data = self._prepare_export_data()
                df = pd.DataFrame(export_data)
                df.to_excel(tmp_file.name, index=False)
                return tmp_file.name
        except Exception as e:
            return gr.update(value=f"**Ошибка:** {str(e)}")

    def export_to_csv(self):
        """Экспортирует результаты в CSV"""
        if not self.current_results:
            return gr.update(value="**Предупреждение:** Нет данных для экспорта")
        try:
            with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tmp_file:
                export_data = self._prepare_export_data()
                df = pd.DataFrame(export_data)
                df.to_csv(tmp_file.name, index=False, encoding='utf-8-sig')
                return tmp_file.name
        except Exception as e:
            return gr.update(value=f"**Ошибка:** {str(e)}")

    # ---------- Сброс ----------

    def clear_results(self):
        """Очищает результаты и возвращает пустую таблицу корректного формата."""
        self.current_results = []
        empty_df = pd.DataFrame(columns=COLUMNS)
        return gr.update(value=""), empty_df, ""

    # ---------- Генератор тестов ----------

    def generate_test_images(self, test_type, progress=gr.Progress()):
        """Генерирует тестовые изображения"""
        try:
            if test_type == "all":
                self.test_generator.generate_all_test_images()
            elif test_type == "text":
                self.test_generator.generate_text_test_images()
            elif test_type == "technical":
                self.test_generator.generate_technical_test_images()

            count = len([f for f in os.listdir(self.test_generator.output_folder)
                         if f.lower().endswith(('.tiff', '.tif', '.jpg', '.jpeg', '.png'))])
            return f"**Успех:** Создано {count} тестовых изображений в папке '{self.test_generator.output_folder}'"
        except Exception as e:
            return f"**Ошибка:** {str(e)}"

    # ---------- UI ----------

    def setup_interface(self):
        """Настраивает интерфейс Gradio"""

        with gr.Blocks(title="Проверка изображений для типографии", theme=gr.themes.Soft()) as self.interface:
            gr.Markdown("# 🖨️ Проверка изображений для типографии")

            with gr.Tabs():
                # ===== Вкладка проверки изображений =====
                with gr.TabItem("🔍 Проверка изображений"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown("## Требования типографии")
                            gr.Markdown(self.get_requirements_text())

                            # Загрузка файлов/ZIP
                            with gr.Row():
                                gr.Markdown("**Загрузите файлы / ZIP:**")
                            with gr.Row():
                                files_input = gr.Files(
                                    label="Файлы изображений или архив ZIP",
                                    file_count="multiple",
                                    type="filepath"
                                )
                            with gr.Row():
                                validate_upload_btn = gr.Button("📤 Проверить загруженные", variant="secondary")

                            with gr.Row():
                                export_excel_btn = gr.Button("💾 Excel")
                                export_csv_btn = gr.Button("💾 CSV")

                            status_output = gr.Markdown("Готов к проверке...")

                        with gr.Column(scale=2):
                            results_table = gr.Dataframe(
                                headers=COLUMNS,
                                value=pd.DataFrame(columns=COLUMNS),
                                interactive=False
                            )

                            detailed_info = gr.Textbox(
                                label="Детальная информация",
                                placeholder="Выберите изображение в таблице для просмотра детальной информации...",
                                lines=10,
                                max_lines=15
                            )

                    # Хендлеры на кнопки и таблицу
                    validate_upload_btn.click(
                        fn=self.validate_uploaded_files,
                        inputs=[files_input],
                        outputs=[status_output, results_table, detailed_info]
                    )

                    results_table.select(
                        fn=self.show_detailed_info,
                        outputs=[detailed_info]
                    )

                    export_excel_btn.click(
                        fn=self.export_to_excel,
                        outputs=gr.File(label="Скачать Excel отчет")
                    )

                    export_csv_btn.click(
                        fn=self.export_to_csv,
                        outputs=gr.File(label="Скачать CSV отчет")
                    )

                # ===== Вкладка генерации тестов =====
                with gr.TabItem("🛠️ Генератор тестовых изображений"):
                    gr.Markdown("## Генератор тестовых изображений")

                    with gr.Row():
                        with gr.Column():
                            gr.Markdown("""
                            **Доступные тесты:**
                            - **Все тесты:** 13 изображений (текстовые + технические)
                            - **Только текстовые:** 8 изображений с разным расположением текста
                            - **Только технические:** 5 изображений (цвет, DPI, размер)
                            """)

                            test_type = gr.Radio(
                                choices=["all", "text", "technical"],
                                label="Тип тестовых изображений",
                                value="all",
                                info="Выберите какие тесты сгенерировать"
                            )

                            generate_btn = gr.Button("🔄 Сгенерировать тесты", variant="primary")
                            open_folder_btn = gr.Button("📂 Открыть папку с тестами")

                            test_status = gr.Markdown("Готов к генерации...")

                        with gr.Column():
                            gr.Markdown("""
                            **Описание тестов:**
                            
                            **Текстовые тесты (13 изображений):**
                            - 01-08: Разное расположение текста относительно границ
                            
                            **Технические тесты (5 изображений):**
                            - Правильные CMYK 300/350 DPI
                            - Ошибочные (RGB, низкое DPI, неправильный размер)
                            """)

                    generate_btn.click(
                        fn=self.generate_test_images,
                        inputs=[test_type],
                        outputs=[test_status]
                    )

                    open_folder_btn.click(
                        fn=lambda: gr.update(value=os.path.abspath(self.test_generator.output_folder)),
                        outputs=gr.Textbox(label="Путь к папке с тестами")
                    )

    def launch(self, **kwargs):
        """Запускает приложение"""
        return self.interface.launch(**kwargs)


# ---- Запуск ----

def main():
    """Основная функция запуска приложения (универсальная: локально и в Docker)"""
    import os
    try:
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
        import pandas  # noqa: F401

        server_name = os.getenv("SERVER_NAME", "localhost")  # в Docker переопределяется на 0.0.0.0
        port = int(os.getenv("PORT", "7860"))
        inbrowser_env = os.getenv("INBROWSER", "1")
        inbrowser = inbrowser_env not in ("0", "false", "False")

        print("Запуск приложения проверки изображений для типографии...")
        if inbrowser:
            print(f"Откроется автоматически: http://{server_name}:{port}")
        else:
            print(f"Откройте в браузере: http://localhost:{port}")

        app = GradioPrintValidator()
        app.launch(
            server_name=server_name,
            server_port=port,
            share=False,
            show_error=True,
            inbrowser=inbrowser
        )

    except ImportError as e:
        print(f"Ошибка импорта: {e}")
        print("Убедитесь, что зависимости установлены: pip install -r requirements.txt")


if __name__ == "__main__":
    main()
