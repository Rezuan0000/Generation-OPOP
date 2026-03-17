"""
Скрипт: загрузить структуру БД + данные из двух SQL-файлов и извлечь реквизиты ОПОП.

Вход:
  - SQL со структурой (CREATE TABLE ...)
  - SQL с данными (INSERT ...)

Выход:
  - переменная OPOP_DATA: dict[str, str]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sql_processor import SQLProcessor


def _iso_date_to_ru(d: str) -> str:
    # В дампах даты вида YYYY-MM-DD, иногда встречается '0000-00-00'
    if not d or d.startswith("0000-00-00"):
        return ""
    yyyy, mm, dd = d.split("-", 2)
    return f"{dd}.{mm}.{yyyy}"


def _fio_to_initials(surname: str, name: str, patronymic: str) -> str:
    n = (name or "").strip()
    p = (patronymic or "").strip()
    s = (surname or "").strip()
    n0 = (n[:1] + ".") if n else ""
    p0 = (p[:1] + ".") if p else ""
    dots = "".join([n0, p0])
    return f"{dots} {s}".strip()


def _query_one_str(cur, sql: str, params: tuple = ()) -> Optional[str]:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return None
    val = row[0]
    return None if val is None else str(val)


@dataclass(frozen=True)
class ExtractParams:
    year: int
    speciality_code: str


def build_opop_data(structure_sql_path: str, data_sql_path: str, *, params: ExtractParams) -> dict[str, str]:
    processor = SQLProcessor()

    ok, msg = processor.load_sql_file(structure_sql_path)
    if not ok:
        raise RuntimeError(f"Не удалось загрузить структуру: {msg}")

    ok, msg = processor.load_sql_file(data_sql_path)
    if not ok:
        raise RuntimeError(f"Не удалось загрузить данные: {msg}")

    cur = processor.conn.cursor()

    # 1) Направление (берем бакалавриат: edu_level_id = 1)
    cur.execute(
        """
        SELECT id, code, title, profile
        FROM speciality
        WHERE code = ? AND edu_level_id = 1
        LIMIT 1
        """,
        (params.speciality_code,),
    )
    spec_row = cur.fetchone()
    if not spec_row:
        raise RuntimeError(f"В БД не найдена speciality для кода {params.speciality_code}")

    spec_id, direction_code, direction_name, profile = spec_row
    direction_code = str(direction_code)
    direction_name = str(direction_name)
    profile = str(profile or "")

    # 2) Титульный лист учебного плана: протокол/ФГОС/кафедра.
    # Сначала пытаемся взять по году набора. Если запись "пустая" (0001-01-01 / номер 0),
    # то берём ближайшую валидную запись по этому направлению.

    def _fetch_title_plan_row(where_sql: str, where_params: tuple) -> Optional[tuple]:
        cur.execute(
            f"""
            SELECT
              id,
              date_uchsovet,
              number_uchsovet,
              date_fgos,
              number_fgos,
              department_id,
              date_enter
            FROM title_plan
            WHERE {where_sql}
            ORDER BY date_enter DESC, current_year DESC
            LIMIT 1
            """,
            where_params,
        )
        return cur.fetchone()

    tp = _fetch_title_plan_row("date_enter = ? AND spec_id = ? AND included = '1'", (params.year, spec_id))
    if tp and (str(tp[1]).startswith("0001-") or int(tp[2]) == 0):
        tp = None

    if not tp:
        tp = _fetch_title_plan_row(
            "spec_id = ? AND included = '1' AND number_uchsovet <> 0 AND date_uchsovet NOT LIKE '0001-%'",
            (spec_id,),
        )

    if not tp:
        raise RuntimeError(f"В БД не найден валидный title_plan для spec_id={spec_id}")

    _tp_id, date_uchsovet, number_uchsovet, date_fgos, number_fgos, department_id, _date_enter = tp
    order_date = _iso_date_to_ru(str(date_fgos))
    order_number = f"№ {number_fgos}"
    protocol_date = _iso_date_to_ru(str(date_uchsovet))
    protocol_date = f"{protocol_date} г." if protocol_date else ""
    protocol_number = f"№ {number_uchsovet}"

    # 3) Ответственные лица:
    # - 1) заведующий кафедрой, указанной в title_plan.department_id
    # - 2) декан факультета (в ваших данных faculty id=1)
    def _fetch_department_head_fio(dept_id: int) -> Optional[str]:
        cur.execute(
            """
            SELECT e.surname, e.name, e.patronimyc
            FROM departments d
            JOIN employees e ON e.id = d.head_id
            WHERE d.id = ?
            """,
            (dept_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        fio = _fio_to_initials(*row)
        return fio or None

    first_responsible_fio = _fetch_department_head_fio(int(department_id)) if department_id is not None else None
    if not first_responsible_fio:
        # Фолбэк для ваших данных: часто встречается department_id, которого нет в departments.
        # Тогда берём кафедру ПМИ (id=1), если она есть.
        first_responsible_fio = _fetch_department_head_fio(1) or ""

    cur.execute(
        """
        SELECT e.surname, e.name, e.patronimyc
        FROM faculties f
        JOIN employees e ON e.id = f.dean_id
        WHERE f.id = 1
        """,
    )
    dean = cur.fetchone()
    second_responsible_fio = _fio_to_initials(*(dean or ("", "", "")))

    # 4) Собираем финальный словарь (часть текстов — константы из требования)
    opop_data: dict[str, str] = {
        # Основные реквизиты
        "direction_code": direction_code,
        "direction_name": direction_name,

        # Номер и дата приказа об утверждении ОПОП (берем из title_plan.*_fgos)
        "order_date": order_date,
        "order_number": order_number,

        # Номер и дата протокола заседания (берем из title_plan.*_uchsovet)
        "protocol_number": protocol_number,
        "protocol_date": protocol_date,

        # ФИО ответственных лиц
        "first_responsible_fio": first_responsible_fio,
        "second_responsible_fio": second_responsible_fio,

        # Направление с профилем
        "profile_full": f"{direction_code} {direction_name}, профиль «{profile}»",

        # Области и виды деятельности
        "area_06": (
            "06 Связь, информационные и коммуникационные технологии "
            "(в сфере проектирования, разработки и тестирования программного обеспечения, "
            "в сфере разработки и обслуживания информационных систем)"
        ),
        "area_40": (
            "40 Сквозные виды профессиональной деятельности в промышленности "
            "(в сфере научно-исследовательских разработок и опытно-конструкторских разработок)"
        ),

        # Трудовые функции / обобщённые виды деятельности
        "activity_1": (
            "участие в научно-исследовательских проектах в соответствии "
            "с профилем объекта профессиональной деятельности"
        ),
        "activity_2": (
            "применение наукоемких технологий и пакетов программ для решения прикладных задач "
            "в естественных науках, промышленности и бизнесе"
        ),
        "activity_3": (
            "разработка архитектуры, алгоритмических и программных решений "
            "прикладного программного обеспечения"
        ),
        "activity_4": (
            "изучение и использование различных языков программирования, алгоритмов, библиотек "
            "и пакетов программ при разработке программного обеспечения"
        ),
        "activity_5": (
            "разработка программного и информационного обеспечения компьютерных систем, "
            "автоматизированных систем, сервисов и распределенных баз данных"
        ),

        # Профессиональные стандарты
        "prof_standard_1": (
            "профессиональный стандарт 06.001. Программист "
            "(утвержден приказом Министерства труда и социальной защиты РФ "
            "от 22.07.2022 № 424н)"
        ),
        "prof_standard_2": (
            "профессиональный стандарт 06.015. Специалист по информационным системам "
            "(утвержден приказом Министерства труда и социальной защиты РФ "
            "от 18.11.2014 № 896н (ред. от 12.12.2016))"
        ),
        "prof_standard_3": (
            "профессиональный стандарт 40.011. Специалист по научно-исследовательским "
            "и опытно-конструкторским разработкам "
            "(утвержден приказом Министерства труда и социальной защиты РФ "
            "от 4.03.2014 № 121н (ред. от 12.12.2016))"
        ),
    }

    processor.close()
    return opop_data


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Извлечь OPOP_DATA из пары SQL-дампов (структура + данные).")
    p.add_argument("--structure", default="math.sql", help="SQL со структурой (CREATE TABLE ...)")
    p.add_argument("--data", default="dump.sql", help="SQL с данными (INSERT ...)")
    p.add_argument("--year", type=int, default=2023, help="Год набора (title_plan.date_enter)")
    p.add_argument("--code", default="01.03.02", help="Код направления (speciality.code)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    OPOP_DATA: dict[str, str] = build_opop_data(
        args.structure,
        args.data,
        params=ExtractParams(year=args.year, speciality_code=args.code),
    )
    # Печать в stdout, чтобы можно было проверить результат
    from pprint import pprint

    pprint(OPOP_DATA, sort_dicts=False)
