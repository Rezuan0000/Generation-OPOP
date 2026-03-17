"""
Генерация документа ОПОП на основе шаблона Word и тестовых данных.

Перед использованием установите зависимость:
    pip install python-docx

В шаблоне используйте метки вида {{ключ}}, где ключ — это имя
поля из словаря OPOP_DATA в модуле opop_data.py.
Например: {{direction_code}}, {{direction_name}}, {{profile_full}} и т.д.
"""

from pathlib import Path

from docx import Document
from zipfile import BadZipFile

from opop_data import OPOP_DATA


def replace_placeholders_in_paragraphs(doc: Document, data: dict[str, str]) -> None:
    """
    Простая замена меток в параграфах документа.

    ВАЖНО: если метка {{key}} разбита на несколько "runs"
    (например, часть текста жирная, часть обычная),
    этот простой вариант может её не найти. Для первых тестов этого
    обычно достаточно, а при необходимости можно будет доработать.
    """
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
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in new_text:
                        new_text = new_text.replace(placeholder, value)
                if new_text != cell.text:
                    cell.text = new_text


def replace_placeholders(doc: Document, data: dict[str, str]) -> None:
    """Общая функция замены меток во всём документе."""
    replace_placeholders_in_paragraphs(doc, data)
    replace_placeholders_in_tables(doc, data)


def generate_opop_document(
    template_path: str | Path = "template.docx",
    output_path: str | Path = "ОПОП-ПМ_тестовый.docx",
) -> Path:
    """
    Создаёт документ ОПОП на основе шаблона и тестовых данных.

    :param template_path: путь к шаблону Word (.docx)
    :param output_path: путь для сохранения сгенерированного документа
    :return: путь к созданному файлу
    """
    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.exists():
        raise FileNotFoundError(
            f"Не найден файл шаблона: {template_path.resolve()}. "
            "Создайте template.docx и добавьте в него метки вида {{direction_code}} и т.п."
        )

    # python-docx умеет открывать только настоящий .docx (это zip-архив, начинается с 'PK').
    # Частая ошибка: файл .doc сохранён с расширением .docx — тогда будет BadZipFile.
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
    replace_placeholders(doc, OPOP_DATA)
    doc.save(output_path)

    return output_path


if __name__ == "__main__":
    result = generate_opop_document()
    print(f"Документ успешно сгенерирован: {result.resolve()}")

