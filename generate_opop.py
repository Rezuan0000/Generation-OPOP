"""
Генерация документа ОПОП на основе шаблона Word и данных из JSON.

Перед использованием установите зависимость:
    pip install python-docx

В шаблоне используйте метки вида {{ключ}}, где ключ — это имя
поля из JSON-файла.
Например: {{direction_code}}, {{direction_name}}, {{profile_full}} и т.д.

Для динамических таблиц используйте маркеры:
    {{START_TABLE:universal}} / {{END_TABLE:universal}} - для таблицы УК
    {{START_TABLE:professional}} / {{END_TABLE:professional}} - для таблицы ОПК
"""

import json
from pathlib import Path
from copy import deepcopy

from docx import Document
from zipfile import BadZipFile


def load_opop_data(json_path: str | Path = "opop_data.json") -> dict:
    """
    Загружает данные из JSON-файла.
    
    :param json_path: путь к JSON-файлу с данными
    :return: словарь с данными
    """
    json_path = Path(json_path)
    
    if not json_path.exists():
        raise FileNotFoundError(
            f"Не найден файл с данными: {json_path.resolve()}. "
            "Убедитесь, что файл opop_data.json существует."
        )
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Ошибка при разборе JSON-файла: {json_path.resolve()}. "
            f"Проверьте корректность JSON-формата. Ошибка: {e}"
        ) from e


def parse_competencies_from_string(comp_string: str, prefix: str) -> list[dict]:
    """
    Преобразует строку с компетенциями в структурированный список.
    
    Формат строки: "УК-1 - Текст компетенции\nУК-2 - Текст компетенции"
    
    :param comp_string: строка с компетенциями
    :param prefix: префикс компетенций (УК, ОПК, ПК)
    :return: список словарей с компетенциями
    """
    competencies = []
    
    if not comp_string:
        return competencies
    
    # Разбиваем по строкам
    lines = comp_string.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Ищем разделитель " - " или "-"
        if ' - ' in line:
            code, description = line.split(' - ', 1)
        elif ' -' in line:
            code, description = line.split(' -', 1)
        elif '- ' in line:
            code, description = line.split('- ', 1)
        else:
            # Если разделитель не найден, используем всю строку как компетенцию
            code = line
            description = ""
        
        competencies.append({
            "category": "",  # Категорию можно заполнить позже при необходимости
            "competence": f"{code.strip()} - {description.strip()}" if description else code.strip(),
            "indicators": ""  # Индикаторы пока оставляем пустыми
        })
    
    return competencies


def replace_placeholders_in_paragraphs(doc: Document, data: dict[str, str]) -> None:
    """Замена меток в параграфах документа."""
    for paragraph in doc.paragraphs:
        if not paragraph.text:
            continue
        new_text = paragraph.text
        for key, value in data.items():
            placeholder = f"{{{{{key}}}}}"  # из key делаем {{key}}
            if placeholder in new_text:
                new_text = new_text.replace(placeholder, value)
        if new_text != paragraph.text:
            paragraph.text = new_text


def replace_placeholders_in_tables(doc: Document, data: dict[str, str]) -> None:
    """Замена меток в ячейках таблиц документа."""
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if not cell.text:
                    continue
                new_text = cell.text
                for key, value in data.items():
                    placeholder = f"{{{{{key}}}}}"  # из key делаем {{key}}
                    if placeholder in new_text:
                        new_text = new_text.replace(placeholder, value)
                if new_text != cell.text:
                    cell.text = new_text


def replace_placeholders(doc: Document, data: dict[str, str]) -> None:
    """Общая функция замены меток во всём документе."""
    replace_placeholders_in_paragraphs(doc, data)
    replace_placeholders_in_tables(doc, data)


def fill_competencies_table(doc: Document, start_marker: str, end_marker: str, 
                           competencies_data: list[dict]) -> None:
    """
    Универсальная функция заполнения таблицы компетенций.
    
    :param doc: документ Word
    :param start_marker: маркер начала таблицы (например, {{START_TABLE:universal}})
    :param end_marker: маркер конца таблицы (например, {{END_TABLE:universal}})
    :param competencies_data: список словарей с данными компетенций
    """
    target_table = None
    template_row = None
    template_row_index = -1
    
    # Поиск таблицы, содержащей маркер начала
    for table in doc.tables:
        for i, row in enumerate(table.rows):
            row_text = ' '.join(cell.text for cell in row.cells)
            if start_marker in row_text:
                target_table = table
                template_row = row
                template_row_index = i
                break
        if target_table:
            break
    
    if target_table is None:
        print(f"Предупреждение: не найдена таблица с маркером {start_marker}")
        return
    
    # Находим строку с маркером конца
    end_row_index = -1
    for i, row in enumerate(target_table.rows):
        row_text = ' '.join(cell.text for cell in row.cells)
        if end_marker in row_text:
            end_row_index = i
            break
    
    # Очищаем шаблонную строку от маркеров
    for cell in template_row.cells:
        cell.text = cell.text.replace(start_marker, "").replace(end_marker, "")
    
    # Сохраняем копии шаблонной строки для каждой компетенции
    new_rows_data = []
    for comp_data in competencies_data:
        # Копируем шаблонную строку
        new_row = deepcopy(template_row._tr)
        # Сохраняем данные для этой строки
        new_rows_data.append({
            "row_element": new_row,
            "category": comp_data.get("category", ""),
            "competence": comp_data.get("competence", ""),
            "indicators": comp_data.get("indicators", "")
        })
    
    # Удаляем исходную шаблонную строку и все строки до end_row включительно
    # (удаляем с конца, чтобы не сбивать индексы)
    for i in range(end_row_index, template_row_index - 1, -1):
        if i < len(target_table.rows):
            row_to_remove = target_table.rows[i]
            row_to_remove._tr.getparent().remove(row_to_remove._tr)
    
    # Вставляем все новые строки
    if template_row_index < len(target_table.rows):
        # Вставляем перед текущей строкой
        reference_row = target_table.rows[template_row_index]
        for item in reversed(new_rows_data):  # В обратном порядке, чтобы сохранить порядок
            reference_row._tr.addprevious(item["row_element"])
    else:
        # Если строк нет, добавляем в конец
        for item in new_rows_data:
            target_table._tbl.append(item["row_element"])
    
    # Заполняем ячейки в новых строках
    row_counter = 0
    for i in range(template_row_index, len(target_table.rows)):
        if row_counter < len(new_rows_data):
            current_row = target_table.rows[i]
            data_item = new_rows_data[row_counter]
            if len(current_row.cells) >= 3:
                current_row.cells[0].text = data_item["category"]
                current_row.cells[1].text = data_item["competence"]
                current_row.cells[2].text = data_item["indicators"]
            row_counter += 1


def fill_universal_competencies_table(doc: Document, competencies_string: str) -> None:
    """Заполняет таблицу универсальных компетенций."""
    competencies_data = parse_competencies_from_string(competencies_string, "УК")
    fill_competencies_table(
        doc,
        start_marker="{{START_TABLE:universal}}",
        end_marker="{{END_TABLE:universal}}",
        competencies_data=competencies_data
    )


def fill_professional_competencies_table(doc: Document, competencies_string: str) -> None:
    """Заполняет таблицу общепрофессиональных компетенций (ОПК)."""
    competencies_data = parse_competencies_from_string(competencies_string, "ОПК")
    fill_competencies_table(
        doc,
        start_marker="{{START_TABLE:professional}}",
        end_marker="{{END_TABLE:professional}}",
        competencies_data=competencies_data
    )


def generate_opop_document(
    template_path: str | Path = "template.docx",
    data_path: str | Path = "opop_data.json",
    output_path: str | Path = "ОПОП-ПМ_тестовый.docx",
) -> Path:
    """
    Создаёт документ ОПОП на основе шаблона и данных из JSON.
    
    :param template_path: путь к шаблону Word (.docx)
    :param data_path: путь к JSON-файлу с данными
    :param output_path: путь для сохранения сгенерированного документа
    :return: путь к созданному файлу
    """
    template_path = Path(template_path)
    data_path = Path(data_path)
    output_path = Path(output_path)
    
    # Проверка существования файлов
    if not template_path.exists():
        raise FileNotFoundError(
            f"Не найден файл шаблона: {template_path.resolve()}. "
            "Создайте template.docx и добавьте в него метки вида {{direction_code}} и т.п."
        )
    
    # Загружаем данные из JSON
    opop_data = load_opop_data(data_path)
    
    # Проверка, что файл шаблона является корректным .docx
    with template_path.open("rb") as f:
        signature = f.read(8)
    if not signature.startswith(b"PK"):
        raise ValueError(
            "Файл шаблона не является корректным .docx (zip-архивом). "
            f"Путь: {template_path.resolve()}. "
            "Откройте шаблон в Word и выполните 'Сохранить как' → 'Документ Word (*.docx)'. "
            "Если у вас сейчас формат .doc, переименования расширения недостаточно."
        )
    
    try:
        doc = Document(template_path)
    except BadZipFile as e:
        raise ValueError(
            "Не удалось открыть шаблон как .docx (файл повреждён или не является zip-архивом). "
            f"Путь: {template_path.resolve()}."
        ) from e
    
    # 1. Заменяем простые метки (все строковые значения из JSON)
    # Исключаем поля, которые используются для динамических таблиц
    excluded_keys = {"universal_competencies", "opk_competencies", "professional_competencies"}
    simple_data = {k: v for k, v in opop_data.items() if k not in excluded_keys and isinstance(v, str)}
    replace_placeholders(doc, simple_data)
    
    # 2. Заполняем динамические таблицы
    if "universal_competencies" in opop_data:
        fill_universal_competencies_table(doc, opop_data["universal_competencies"])
    else:
        print("Предупреждение: в JSON-файле не найдены универсальные компетенции")
    
    if "opk_competencies" in opop_data:
        fill_professional_competencies_table(doc, opop_data["opk_competencies"])
    else:
        print("Предупреждение: в JSON-файле не найдены общепрофессиональные компетенции")
    
    # ПК пока не обрабатываем, данные остаются в JSON но не используются
    
    doc.save(output_path)
    return output_path


if __name__ == "__main__":
    try:
        result = generate_opop_document()
        print(f"Документ успешно сгенерирован: {result.resolve()}")
    except Exception as e:
        print(f"Ошибка при генерации документа: {e}")