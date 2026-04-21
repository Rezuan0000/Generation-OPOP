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

Ручной ввод (значения в JSON: manual_fields["ключ"]):
    {{MANUAL:ключ}}  — например {{MANUAL:normative_docs}}
"""

import json
import re
import zipfile
from pathlib import Path
from copy import deepcopy
from typing import Any

from docx.shared import Pt
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn

from docx import Document
from zipfile import BadZipFile

# Ручной ввод в шаблоне: {{MANUAL:имя_поля}} (латиница, цифры, подчёркивание).
MANUAL_PLACEHOLDER_RE = re.compile(r"\{\{MANUAL:([a-zA-Z0-9_]+)\}\}")


def _set_paragraph_text_preserve_first_run_style(paragraph, new_text: str) -> None:
    """
    Записывает новый текст в абзац и сохраняет базовый стиль первого run.
    Это уменьшает риск "скачка" шрифта после подстановки.
    """
    runs = list(paragraph.runs)
    if not runs:
        paragraph.add_run(new_text)
        return

    first = runs[0]
    first.text = new_text
    for r in runs[1:]:
        r._element.getparent().remove(r._element)


def _normalize_manual_text(value: str) -> str:
    """Нормализует текст из textarea для вставки в Word."""
    normalized = value.replace("\t", " ")
    lines = normalized.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    lines = [line.lstrip() for line in lines]
    return "\n".join(lines)


def _set_paragraph_multiline_text_preserve_style(paragraph, new_text: str) -> None:
    """
    Записывает многострочный текст в исходный абзац через line break внутри run.
    Так сохраняется исходный стиль и исчезают "плавающие" отступы между строками.
    """
    runs = list(paragraph.runs)
    if not runs:
        run = paragraph.add_run()
    else:
        run = runs[0]
        for r in runs[1:]:
            r._element.getparent().remove(r._element)

    parts = new_text.split("\n")
    run.text = parts[0] if parts else ""
    for part in parts[1:]:
        run.add_break(WD_BREAK.LINE)
        run.add_text(part)


def _manual_lines(value: str) -> list[str]:
    normalized = _normalize_manual_text(value or "")
    lines = normalized.split("\n")
    return lines if lines else [""]


def _replace_manual_placeholders_in_row(table, row_idx: int, manual: dict[str, str], keys: set[str]) -> None:
    row = table.rows[row_idx]
    for cell in row.cells:
        for paragraph in cell.paragraphs:
            if not paragraph.text:
                continue
            text = paragraph.text
            replaced = text
            changed = False
            for key in keys:
                placeholder = f"{{{{MANUAL:{key}}}}}"
                if placeholder in replaced:
                    replaced = replaced.replace(placeholder, _normalize_manual_text(manual.get(key, "")))
                    changed = True
            if changed:
                paragraph.paragraph_format.first_line_indent = Pt(0)
                _set_paragraph_multiline_text_preserve_style(paragraph, replaced)


def _expand_manual_rows_in_tables(doc: Document, manual: dict[str, str]) -> None:
    """
    Расширяет строки таблиц с {{MANUAL:key}}:
    - если в значениях есть несколько строк, создаёт несколько строк таблицы;
    - строка N берёт N-ю строку из каждого manual-поля (если нет — пусто).
    """
    for table in doc.tables:
        i = 0
        while i < len(table.rows):
            row = table.rows[i]
            row_text = " ".join(cell.text for cell in row.cells)
            matches = list(MANUAL_PLACEHOLDER_RE.finditer(row_text))
            if not matches:
                i += 1
                continue

            row_keys = {m.group(1) for m in matches}
            lines_by_key: dict[str, list[str]] = {k: _manual_lines(manual.get(k, "")) for k in row_keys}
            row_count = max((len(v) for v in lines_by_key.values()), default=1)

            if row_count <= 1:
                # Нет размножения — обычная подстановка в текущую строку.
                _replace_manual_placeholders_in_row(table, i, manual, row_keys)
                i += 1
                continue

            # Вставляем row_count копий перед исходной строкой.
            for _ in range(row_count):
                clone = deepcopy(row._tr)
                row._tr.addprevious(clone)

            # Находим текущий индекс исходной (шаблонной) строки после вставки.
            original_idx = -1
            for idx2, r2 in enumerate(table.rows):
                if r2._tr is row._tr:
                    original_idx = idx2
                    break
            if original_idx == -1:
                i += 1
                continue

            # Заполняем вставленные строки построчно.
            start_idx = original_idx - row_count
            for offset in range(row_count):
                row_values = {
                    key: (vals[offset] if offset < len(vals) else "")
                    for key, vals in lines_by_key.items()
                }
                _replace_manual_placeholders_in_row(table, start_idx + offset, row_values, row_keys)

            # Удаляем исходную шаблонную строку с плейсхолдерами.
            row._tr.getparent().remove(row._tr)

            # Продолжаем после вставленного диапазона.
            i = start_idx + row_count


def _force_run_times_new_roman(run) -> None:
    """Принудительно задаёт Times New Roman для run (включая кириллицу)."""
    run.font.name = "Times New Roman"
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), "Times New Roman")
    rfonts.set(qn("w:hAnsi"), "Times New Roman")
    rfonts.set(qn("w:cs"), "Times New Roman")
    rfonts.set(qn("w:eastAsia"), "Times New Roman")


def enforce_times_new_roman(doc: Document) -> None:
    """Приводит весь текст документа к шрифту Times New Roman."""
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            _force_run_times_new_roman(run)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        _force_run_times_new_roman(run)


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


def _find_table_range(doc: Document, start_marker: str, end_marker: str):
    def _contains_marker(text: str, marker: str) -> bool:
        if marker in text:
            return True
        # Word иногда вносит лишние пробелы/переносы в тексте ячейки.
        norm_text = "".join(text.split())
        norm_marker = "".join(marker.split())
        return norm_marker in norm_text

    target_table = None
    template_row = None
    template_row_index = -1
    end_row_index = -1

    for table in doc.tables:
        for i, row in enumerate(table.rows):
            row_text = " ".join(cell.text for cell in row.cells)
            if _contains_marker(row_text, start_marker):
                target_table = table
                template_row = row
                template_row_index = i
                break
        if target_table:
            break

    if target_table is None or template_row is None:
        return None, None, -1, -1

    for i, row in enumerate(target_table.rows):
        row_text = " ".join(cell.text for cell in row.cells)
        if _contains_marker(row_text, end_marker):
            end_row_index = i
            break

    return target_table, template_row, template_row_index, end_row_index


def _replace_table_range_with_rows(
    target_table,
    template_row,
    template_row_index: int,
    end_row_index: int,
    rows_values: list[list[str]],
) -> None:
    # Удаляем маркеры из шаблонной строки
    for cell in template_row.cells:
        # Убираем любые START/END-маркеры, включая секционные (:06, :activity_1 и т.п.)
        cell.text = re.sub(r"\{\{(?:START_TABLE|END_TABLE):[^}]+\}\}", "", cell.text)

    if end_row_index == -1:
        end_row_index = template_row_index

    # Готовим новые строки
    new_rows = []
    for values in rows_values:
        new_row = deepcopy(template_row._tr)
        new_rows.append((new_row, values))

    # Удаляем шаблонный диапазон
    for i in range(end_row_index, template_row_index - 1, -1):
        if i < len(target_table.rows):
            row_to_remove = target_table.rows[i]
            row_to_remove._tr.getparent().remove(row_to_remove._tr)

    # Вставляем строки
    if not new_rows:
        return

    if template_row_index < len(target_table.rows):
        reference_row = target_table.rows[template_row_index]
        for row_element, _ in reversed(new_rows):
            reference_row._tr.addprevious(row_element)
    else:
        for row_element, _ in new_rows:
            target_table._tbl.append(row_element)

    # Заполняем значения
    start_idx = template_row_index
    for offset, (_, values) in enumerate(new_rows):
        row_idx = start_idx + offset
        if row_idx >= len(target_table.rows):
            break
        current_row = target_table.rows[row_idx]
        for col_idx, value in enumerate(values):
            if col_idx < len(current_row.cells):
                current_row.cells[col_idx].text = value


def _fill_table_section_rows(
    doc: Document,
    start_marker: str,
    end_marker: str,
    rows_values: list[list[str]],
) -> bool:
    target_table, template_row, template_row_index, end_row_index = _find_table_range(
        doc, start_marker, end_marker
    )
    if target_table is None or template_row is None:
        return False
    _replace_table_range_with_rows(target_table, template_row, template_row_index, end_row_index, rows_values)
    return True


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
            _set_paragraph_text_preserve_first_run_style(paragraph, new_text)


def replace_placeholders_in_tables(doc: Document, data: dict[str, str]) -> None:
    """Замена меток в ячейках таблиц документа."""
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if not paragraph.text:
                        continue
                    new_text = paragraph.text
                    for key, value in data.items():
                        placeholder = f"{{{{{key}}}}}"  # из key делаем {{key}}
                        if placeholder in new_text:
                            new_text = new_text.replace(placeholder, value)
                    if new_text != paragraph.text:
                        _set_paragraph_text_preserve_first_run_style(paragraph, new_text)


def replace_placeholders(doc: Document, data: dict[str, str]) -> None:
    """Общая функция замены меток во всём документе."""
    replace_placeholders_in_paragraphs(doc, data)
    replace_placeholders_in_tables(doc, data)


def scan_manual_template_keys(template_path: str | Path) -> list[str]:
    """
    Находит в шаблоне все метки вида {{MANUAL:key}} по XML Word (надёжнее, чем только python-docx).
    Порядок — по первому появлению в XML.
    """
    template_path = Path(template_path)
    if not template_path.exists():
        return []
    seen: set[str] = set()
    keys: list[str] = []
    try:
        with zipfile.ZipFile(template_path) as zf:
            for name in zf.namelist():
                if not name.startswith("word/") or not name.endswith(".xml"):
                    continue
                if "media" in name:
                    continue
                try:
                    xml = zf.read(name).decode("utf-8")
                except Exception:
                    continue
                for m in MANUAL_PLACEHOLDER_RE.finditer(xml):
                    k = m.group(1)
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
    except (OSError, zipfile.BadZipFile):
        return []
    return keys


def replace_manual_placeholders_in_paragraphs(doc: Document, manual: dict[str, str]) -> None:
    for paragraph in doc.paragraphs:
        if not paragraph.text:
            continue
            
        original_text = paragraph.text
        new_text = original_text
        
        # Проверяем наличие меток
        has_placeholder = False
        for key, value in manual.items():
            placeholder = f"{{{{MANUAL:{key}}}}}"
            if placeholder in new_text:
                new_text = new_text.replace(placeholder, _normalize_manual_text(value or ""))
                has_placeholder = True
        
        if not has_placeholder:
            continue
            
        # Если текст изменился, обновляем текущий абзац с сохранением формата.
        if new_text != original_text:
            paragraph.paragraph_format.first_line_indent = Pt(0)
            _set_paragraph_multiline_text_preserve_style(paragraph, new_text)


def replace_manual_placeholders_in_tables(doc: Document, manual: dict[str, str]) -> None:
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if not paragraph.text:
                        continue
                    
                    original_text = paragraph.text
                    new_text = original_text
                    
                    has_placeholder = False
                    for key, value in manual.items():
                        placeholder = f"{{{{MANUAL:{key}}}}}"
                        if placeholder in new_text:
                            new_text = new_text.replace(placeholder, _normalize_manual_text(value or ""))
                            has_placeholder = True
                    
                    if not has_placeholder:
                        continue
                    
                    if new_text != original_text:
                        paragraph.paragraph_format.first_line_indent = Pt(0)
                        _set_paragraph_multiline_text_preserve_style(paragraph, new_text)


def replace_manual_placeholders(doc: Document, manual: dict[str, Any]) -> None:
    if not isinstance(manual, dict):
        return
    flat: dict[str, str] = {str(k): ("" if v is None else str(v)) for k, v in manual.items()}
    _expand_manual_rows_in_tables(doc, flat)
    replace_manual_placeholders_in_paragraphs(doc, flat)
    replace_manual_placeholders_in_tables(doc, flat)


def fill_competencies_table(doc: Document, start_marker: str, end_marker: str, 
                           competencies_data: list[dict]) -> None:
    """
    Универсальная функция заполнения таблицы компетенций.
    
    :param doc: документ Word
    :param start_marker: маркер начала таблицы (например, {{START_TABLE:universal}})
    :param end_marker: маркер конца таблицы (например, {{END_TABLE:universal}})
    :param competencies_data: список словарей с данными компетенций
    """
    target_table, template_row, template_row_index, end_row_index = _find_table_range(
        doc, start_marker, end_marker
    )
    if target_table is None or template_row is None:
        print(f"Предупреждение: не найдена таблица с маркером {start_marker}")
        return

    rows_values = []
    for comp_data in competencies_data:
        rows_values.append(
            [
                str(comp_data.get("category", "")),
                str(comp_data.get("competence", "")),
                str(comp_data.get("indicators", "")),
            ]
        )
    _replace_table_range_with_rows(target_table, template_row, template_row_index, end_row_index, rows_values)


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


def _parse_prof_standards_table(opop_data: dict[str, Any]) -> list[dict[str, str]]:
    # Новый формат (предпочтительный): массив объектов
    raw = opop_data.get("prof_standards_table")
    if isinstance(raw, list):
        rows = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            area = str(item.get("area", ""))
            area_code = str(item.get("area_code", "")).strip()
            if not area_code:
                if area.strip().startswith("06"):
                    area_code = "06"
                elif area.strip().startswith("40"):
                    area_code = "40"
            rows.append(
                {
                    "area_code": area_code,
                    "area": area,
                    "standard": str(item.get("standard", "")),
                    "generalized_functions": str(item.get("generalized_functions", "")),
                }
            )
        if rows:
            return rows

    # Старый формат: area_06/area_40 + prof_standard_1..N (fallback-заглушка)
    areas = [str(opop_data.get("area_06", "")), str(opop_data.get("area_40", ""))]
    standards = [
        str(opop_data.get("prof_standard_1", "")),
        str(opop_data.get("prof_standard_2", "")),
        str(opop_data.get("prof_standard_3", "")),
    ]
    rows = []
    if areas[0]:
        for s in standards[:2]:
            if s:
                rows.append({"area": areas[0], "standard": s})
    if areas[1] and standards[2]:
        rows.append({"area": areas[1], "standard": standards[2]})
    for r in rows:
        if "06 " in r.get("area", ""):
            r["area_code"] = "06"
        elif "40 " in r.get("area", ""):
            r["area_code"] = "40"
        else:
            r["area_code"] = ""
        r.setdefault("generalized_functions", "")
    return rows


def fill_prof_standards_table(doc: Document, opop_data: dict[str, Any]) -> None:
    rows = _parse_prof_standards_table(opop_data)
    by_area: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_area.setdefault(r.get("area_code", ""), []).append(r)

    # Новый режим: отдельные секции по коду области (как на вашем шаблоне 06/40).
    # В секциях заполняются 1-2 столбцы: профстандарт + обобщенные трудовые функции.
    used_sectional = False
    for area_code, items in by_area.items():
        if not area_code:
            continue
        start = f"{{{{START_TABLE:prof_standards:{area_code}}}}}"
        end = f"{{{{END_TABLE:prof_standards:{area_code}}}}}"
        section_rows: list[list[str]] = []
        # Для каждого профстандарта создаём свои manual-ключи, чтобы можно было
        # вводить "трудовые функции" и "уровень квалификации" раздельно.
        for idx, item in enumerate(items, start=1):
            tf_key = f"ps_{area_code}_{idx}_tf"
            lvl_key = f"ps_{area_code}_{idx}_lvl"
            section_rows.append(
                [
                    item.get("standard", ""),
                    item.get("generalized_functions", ""),
                    f"{{{{MANUAL:{tf_key}}}}}",
                    f"{{{{MANUAL:{lvl_key}}}}}",
                ]
            )
        ok = _fill_table_section_rows(doc, start, end, section_rows)
        used_sectional = used_sectional or ok

    if used_sectional:
        return

    # Совместимость со старым единым маркером.
    start_marker = "{{START_TABLE:prof_standards}}"
    end_marker = "{{END_TABLE:prof_standards}}"
    rows_values = [[r.get("area", ""), r.get("standard", "")] for r in rows]
    if not _fill_table_section_rows(doc, start_marker, end_marker, rows_values):
        print(f"Предупреждение: не найдена таблица с маркерами {start_marker} / {end_marker}")


def _parse_pk_table(opop_data: dict[str, Any]) -> list[dict[str, str]]:
    # Новый формат (предпочтительный):
    # [
    #   {"task_type":"...", "pk_code":"ПК-1", "pk_description":"...", "indicators":"..."},
    #   ...
    # ]
    raw = opop_data.get("pk_table")
    if isinstance(raw, list):
        rows = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "task_type_key": str(item.get("task_type_key", "")),
                    "task_type": str(item.get("task_type", "")),
                    "pk_code": str(item.get("pk_code", "")),
                    "pk_description": str(item.get("pk_description", "")),
                    "indicators": str(item.get("indicators", "")),
                }
            )
        if rows:
            return rows

    # Fallback: из текстовой строки professional_competencies
    # В этом случае группировка по типам задач недоступна, всё уходит в "Не указан тип".
    fallback = parse_competencies_from_string(str(opop_data.get("professional_competencies", "")), "ПК")
    rows = []
    for c in fallback:
        comp = str(c.get("competence", ""))
        code = comp.split(" - ", 1)[0].strip() if comp else ""
        desc = comp.split(" - ", 1)[1].strip() if " - " in comp else ""
        rows.append(
            {
                "task_type_key": "",
                "task_type": "Не указан тип задач профессиональной деятельности",
                "pk_code": code,
                "pk_description": desc,
                "indicators": "",
            }
        )
    return rows


def fill_pk_table(doc: Document, opop_data: dict[str, Any]) -> None:
    rows = _parse_pk_table(opop_data)
    # Если task_type_key не задан, пробуем вывести из activity_1..activity_3.
    activity_map = {
        str(opop_data.get("activity_1", "")).strip(): "activity_1",
        str(opop_data.get("activity_2", "")).strip(): "activity_2",
        str(opop_data.get("activity_3", "")).strip(): "activity_3",
    }
    for r in rows:
        if not r.get("task_type_key"):
            r["task_type_key"] = activity_map.get(str(r.get("task_type", "")).strip(), "")

    # Новый режим: отдельные секции PK под каждым типом задач.
    # В секции заполняем: col3=ПК (код+наименование), col4=индикаторы.
    grouped: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        key = r.get("task_type_key", "")
        grouped.setdefault(key, []).append(r)

    used_sectional = False
    for key, items in grouped.items():
        if not key:
            continue
        start = f"{{{{START_TABLE:pk:{key}}}}}"
        end = f"{{{{END_TABLE:pk:{key}}}}}"
        section_rows: list[list[str]] = []
        for i in items:
            code = i.get("pk_code", "")
            desc = i.get("pk_description", "")
            pk_text = f"{code} - {desc}".strip(" -")
            # 5 колонок таблицы на скрине: 1/2/5 пока пустые.
            section_rows.append(["", "", pk_text, i.get("indicators", ""), ""])
        ok = _fill_table_section_rows(doc, start, end, section_rows)
        used_sectional = used_sectional or ok

    if used_sectional:
        return

    # Совместимость со старым единым маркером.
    start_marker = "{{START_TABLE:pk}}"
    end_marker = "{{END_TABLE:pk}}"
    # Группируем по task_type: первый столбец заполняем только у первой строки группы.
    rows_values: list[list[str]] = []
    prev_task_type = None
    for r in rows:
        task_type = r.get("task_type", "")
        col_task_type = task_type if task_type != prev_task_type else ""
        code = r.get("pk_code", "")
        desc = r.get("pk_description", "")
        pk_text = f"{code} - {desc}".strip(" -")
        indicators = r.get("indicators", "")
        rows_values.append([col_task_type, pk_text, indicators])
        prev_task_type = task_type

    if not _fill_table_section_rows(doc, start_marker, end_marker, rows_values):
        print(f"Предупреждение: не найдена таблица с маркерами {start_marker} / {end_marker}")


def generate_opop_document(
    template_path: str | Path = "template.docx",
    data_path: str | Path = "opop_data.json",
    output_path: str | Path = "ОПОП-ПМ_тестовый.docx",
    *,
    skip_manual_replace: bool = False,
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
    excluded_keys = {
        "universal_competencies",
        "opk_competencies",
        "professional_competencies",
        "prof_standards_table",
        "pk_table",
        "manual_fields",
    }
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

    fill_prof_standards_table(doc, opop_data)
    fill_pk_table(doc, opop_data)

    # Ручные поля: {{MANUAL:key}} — подставляем после таблиц (можно отключить для черновика).
    if not skip_manual_replace:
        replace_manual_placeholders(doc, opop_data.get("manual_fields", {}))

    # Единый шрифт для всего документа: Times New Roman.
    enforce_times_new_roman(doc)

    doc.save(output_path)
    return output_path


if __name__ == "__main__":
    try:
        result = generate_opop_document()
        print(f"Документ успешно сгенерирован: {result.resolve()}")
    except Exception as e:
        print(f"Ошибка при генерации документа: {e}")