from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _iso_date_to_ru(d: str) -> str:
    if not d or d.startswith("0000-00-00") or d.startswith("0001-00-00"):
        return ""
    try:
        yyyy, mm, dd = d.split("-", 2)
        return f"{dd}.{mm}.{yyyy}"
    except Exception:
        return ""


def _fio_to_initials(surname: str, name: str, patronymic: str) -> str:
    n = (name or "").strip()
    p = (patronymic or "").strip()
    s = (surname or "").strip()
    n0 = (n[:1] + ".") if n else ""
    p0 = (p[:1] + ".") if p else ""
    dots = "".join([n0, p0])
    return f"{dots} {s}".strip()


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (float, int)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


@dataclass(frozen=True)
class ExtractParams:
    speciality_id: int
    year: int | None = None


def parse_db_json_text(text: str) -> dict[str, Any]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Ожидается JSON-объект верхнего уровня.")
    if not isinstance(parsed.get("tables"), dict):
        raise ValueError("Ожидается ключ 'tables' с объектом таблиц.")
    return parsed


def load_db_json_file(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    return parse_db_json_text(text)


def parse_optional_headers_json(raw: str) -> dict[str, str]:
    """
    Разбирает необязательный JSON-объект с HTTP-заголовками:
    {"Accept": "application/json", "X-Custom": "1"}.
    """
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Доп. заголовки: невалидный JSON ({e}).") from e
    if not isinstance(obj, dict):
        raise ValueError("Доп. заголовки: ожидается JSON-объект {\"Имя-заголовка\": \"значение\"}.")
    out: dict[str, str] = {}
    for k, v in obj.items():
        name = _to_str(k).strip()
        if not name:
            raise ValueError("Доп. заголовки: пустое имя заголовка недопустимо.")
        if v is None:
            out[name] = ""
        elif isinstance(v, (str, int, float, bool)):
            out[name] = _to_str(v)
        else:
            raise ValueError(f"Доп. заголовки: для «{name}» ожидается строка или число, не объект/массив.")
    return out


def resolve_api_get_json_url(defaults_path: Path | None = None) -> str:
    env_url = os.environ.get("OPOP_API_GET_JSON_URL", "").strip()
    if env_url:
        return env_url
    path = defaults_path or Path(__file__).resolve().parent / "opop_defaults.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                url = str(data.get("api_get_json_url", "")).strip()
                if url:
                    return url
        except Exception:
            pass
    return ""


def fetch_db_json(
    url: str,
    *,
    timeout_sec: int = 40,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | bytes | None = None,
) -> dict[str, Any]:
    """
    Загружает JSON по HTTP. Поддерживаются GET, POST, PUT.
    Для POST/PUT при непустом теле по умолчанию выставляется Content-Type: application/json.
    """
    m = (method or "GET").strip().upper()
    if m not in ("GET", "POST", "PUT"):
        raise ValueError("Поддерживаются только HTTP-методы GET, POST и PUT.")

    hdrs: dict[str, str] = {}
    if headers:
        hdrs.update(headers)

    data: bytes | None = None
    if m in ("POST", "PUT"):
        if body is None:
            data = b""
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
        if data:
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    elif body is not None and str(body).strip():
        raise ValueError("Тело запроса допустимо только для методов POST и PUT.")

    req = Request(url, data=data, headers=hdrs, method=m)
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read()
    except HTTPError as e:
        detail = ""
        try:
            chunk = e.read()
            if chunk:
                detail = chunk.decode("utf-8", errors="replace")[:800]
        except Exception:
            pass
        msg = f"HTTP {e.code}"
        if detail:
            msg += f": {detail}"
        raise RuntimeError(f"Не удалось получить JSON по URL ({msg}).") from e
    except URLError as e:
        raise RuntimeError(f"Не удалось получить JSON по URL: {e}") from e

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")
    return parse_db_json_text(text)


def _table_data(payload: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    tables = payload.get("tables", {})
    table = tables.get(table_name, {})
    data = table.get("data", [])
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def get_specialities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    title_plan_rows = _table_data(payload, "title_plan")
    spec_with_title_plan = {
        int(r.get("spec_id") or 0)
        for r in title_plan_rows
        if int(r.get("spec_id") or 0) > 0 and _to_str(r.get("included")) == "1"
    }
    if not spec_with_title_plan:
        spec_with_title_plan = {int(r.get("spec_id") or 0) for r in title_plan_rows if int(r.get("spec_id") or 0) > 0}

    levels = {int(r["id"]): _to_str(r.get("title")) for r in _table_data(payload, "edu_levels") if "id" in r}
    items: list[dict[str, Any]] = []
    for row in _table_data(payload, "speciality"):
        try:
            sid = int(row.get("id"))
        except Exception:
            continue
        if sid not in spec_with_title_plan:
            continue
        level_id = int(row.get("edu_level_id") or 0)
        code = _to_str(row.get("cod") or row.get("code"))
        title = _to_str(row.get("title"))
        profile = _to_str(row.get("profile"))
        items.append(
            {
                "id": sid,
                "edu_level_id": level_id,
                "edu_level_title": levels.get(level_id, ""),
                "code": code,
                "title": title,
                "profile": profile,
                "label": f"{code} - {title}" + (f" (профиль: {profile})" if profile else ""),
            }
        )
    items.sort(key=lambda x: (x["edu_level_id"], x["code"], x["title"]))
    return items


def _latest_year_key(row: dict[str, Any]) -> tuple[int, int]:
    def _safe_int(v: Any) -> int:
        try:
            return int(v)
        except Exception:
            return -1

    return (_safe_int(row.get("date_enter")), _safe_int(row.get("current_year")))


_MODULE_DIR = Path(__file__).resolve().parent

# Резерв, если в JSON нет строк title_plan_prof_standards / title_plan_activities для выбранного УП.
_FALLBACK_AREA_06 = (
    "06 Связь, информационные и коммуникационные технологии "
    "(в сфере проектирования, разработки и тестирования программного обеспечения, "
    "в сфере разработки и обслуживания информационных систем)"
)
_FALLBACK_AREA_40 = (
    "40 Сквозные виды профессиональной деятельности в промышленности "
    "(в сфере научно-исследовательских разработок и опытно-конструкторских разработок)"
)
_FALLBACK_PROF_STANDARD_NARRATIVES = (
    (
        "профессиональный стандарт 06.001. Программист "
        "(утвержден приказом Министерства труда и социальной защиты РФ от 22.07.2022 № 424н)"
    ),
    (
        "профессиональный стандарт 06.015. Специалист по информационным системам "
        "(утвержден приказом Министерства труда и социальной защиты РФ от 18.11.2014 № 896н (ред. от 12.12.2016))"
    ),
    (
        "профессиональный стандарт 40.011. Специалист по научно-исследовательским "
        "и опытно-конструкторским разработкам "
        "(утвержден приказом Министерства труда и социальной защиты РФ от 4.03.2014 № 121н (ред. от 12.12.2016))"
    ),
)
_FALLBACK_GENERALIZED_LABOR = (
    "D. Разработка требований и проектирование программного обеспечения."
)
_FALLBACK_ACTIVITIES_LIST = (
    "научно-исследовательский (основной), проектный, производственно-технологический"
)
_FALLBACK_ACTIVITY_1 = "Научно-исследовательский"
_FALLBACK_ACTIVITY_2 = "Проектный"
_FALLBACK_ACTIVITY_3 = "Производственно-технологический"


def _load_opop_defaults() -> dict[str, Any]:
    """Опциональный `opop_defaults.json` рядом с этим модулем (переопределение текстов без правки кода)."""
    path = _MODULE_DIR / "opop_defaults.json"
    if not path.is_file():
        return {}
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def _defaults_area_texts(defaults: dict[str, Any]) -> dict[str, str]:
    raw = defaults.get("area_texts")
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): _to_str(v) for k, v in raw.items() if str(k).strip()}


def _defaults_activities_block(defaults: dict[str, Any]) -> dict[str, str]:
    raw = defaults.get("activities")
    if not isinstance(raw, dict):
        return {}
    return {str(k): _to_str(v) for k, v in raw.items()}


def _defaults_prof_narratives(defaults: dict[str, Any]) -> list[str]:
    raw = defaults.get("prof_standard_narratives")
    if not isinstance(raw, list):
        return []
    return [_to_str(x) for x in raw]


def _area_code_from_number_in_group(number_in_group: Any) -> str:
    s = _to_str(number_in_group).strip()
    if not s:
        return ""
    return s.split(".", 1)[0].strip()


def _sorted_title_plan_prof_standards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: _to_str(r.get("number_in_group")))


def _sorted_title_plan_activities(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(r: dict[str, Any]) -> tuple[int, int]:
        main_first = 0 if int(r.get("is_main") or 0) else 1
        rid = int(r.get("id") or 0)
        return (main_first, rid)

    return sorted(rows, key=sort_key)


def _fallback_prof_standards_table() -> list[dict[str, str]]:
    """Три строки как в исторической версии генератора (до чтения из API)."""
    return [
        {
            "area_code": "06",
            "area": _FALLBACK_AREA_06,
            "standard": "06.001. Программист",
            "generalized_functions": (
                "D. Разработка требований и проектирование программного обеспечения"
            ),
        },
        {
            "area_code": "06",
            "area": _FALLBACK_AREA_06,
            "standard": "06.015. Специалист по информационным системам",
            "generalized_functions": (
                "C. Выполнение работ и управление работами по созданию (модификации) и сопровождению ИС, "
                "автоматизирующих задачи организационного управления и бизнес-процессы"
            ),
        },
        {
            "area_code": "40",
            "area": _FALLBACK_AREA_40,
            "standard": "40.011. Специалист по научно-исследовательским и опытно-конструкторским разработкам",
            "generalized_functions": (
                "A. Проведение научно-исследовательских и опытно-конструкторских разработок по отдельным разделам темы"
            ),
        },
    ]


def _prof_standard_table_row_from_api(row: dict[str, Any], area_texts: dict[str, str]) -> dict[str, str]:
    """Строка таблицы профстандартов из `title_plan_prof_standards`."""
    number_in_group = _to_str(row.get("number_in_group")).strip()
    standard_name = _to_str(row.get("standard_name")).strip()
    prof_act_name = _to_str(row.get("professional_activity_name")).strip()
    goal = _to_str(row.get("professional_activity_goal")).strip()
    area_code = _area_code_from_number_in_group(number_in_group)

    area = area_texts.get(area_code, "").strip()
    if not area:
        if area_code == "06":
            area = _FALLBACK_AREA_06
        elif area_code == "40":
            area = _FALLBACK_AREA_40
        else:
            area = prof_act_name or goal or standard_name or area_code

    std_parts = [p for p in (number_in_group, standard_name) if p]
    standard_cell = ". ".join(std_parts) if len(std_parts) > 1 else (std_parts[0] if std_parts else "")
    gen = goal or prof_act_name

    return {
        "area_code": area_code,
        "area": area,
        "standard": standard_cell,
        "generalized_functions": gen,
    }


def _title_plan_prof_standard_rows_for_tp(payload: dict[str, Any], tp_id: int) -> list[dict[str, Any]]:
    if tp_id <= 0:
        return []
    return [
        r
        for r in _table_data(payload, "title_plan_prof_standards")
        if int(r.get("title_plan_id") or 0) == tp_id
    ]


def _title_plan_activity_rows_for_tp(payload: dict[str, Any], tp_id: int) -> list[dict[str, Any]]:
    if tp_id <= 0:
        return []
    return [
        r
        for r in _table_data(payload, "title_plan_activities")
        if int(r.get("title_plan_id") or 0) == tp_id
    ]


def _resolve_prof_standards_table(
    payload: dict[str, Any],
    tp_id: int,
    defaults: dict[str, Any],
    missing_fields: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """
    Таблица профстандартов для шаблона + исходные строки API (для текстов prof_standard_1..3).
    При пустом API — встроенный fallback, в _missing_fields добавляется маркер.
    """
    api_rows = _sorted_title_plan_prof_standards(_title_plan_prof_standard_rows_for_tp(payload, tp_id))
    area_texts = _defaults_area_texts(defaults)
    if api_rows:
        return ([_prof_standard_table_row_from_api(r, area_texts) for r in api_rows], api_rows)
    missing_fields.append("title_plan_prof_standards(empty_used_builtin_fallback)")
    return (_fallback_prof_standards_table(), [])


def _resolve_activity_labels(
    payload: dict[str, Any],
    tp_id: int,
    defaults: dict[str, Any],
    missing_fields: list[str],
) -> tuple[str, str, str, str, list[str]]:
    """
    activities_list, activity_1..3, список заголовков (для цикла в pk_table).
    """
    act_block = _defaults_activities_block(defaults)
    api_rows = _sorted_title_plan_activities(_title_plan_activity_rows_for_tp(payload, tp_id))
    if not api_rows:
        missing_fields.append("title_plan_activities(empty_used_defaults_or_builtin_fallback)")
        al = act_block.get("activities_list") or _FALLBACK_ACTIVITIES_LIST
        a1 = act_block.get("activity_1") or _FALLBACK_ACTIVITY_1
        a2 = act_block.get("activity_2") or _FALLBACK_ACTIVITY_2
        a3 = act_block.get("activity_3") or _FALLBACK_ACTIVITY_3
        titles = [a1, a2, a3]
        return (al, a1, a2, a3, [t for t in titles if t])

    parts: list[str] = []
    titles_order: list[str] = []
    for r in api_rows:
        title = _to_str(r.get("activity_title")).strip()
        if not title:
            continue
        titles_order.append(title)
        low = title.lower()
        if int(r.get("is_main") or 0):
            parts.append(f"{low} (основной)")
        else:
            parts.append(low)
    activities_list = ", ".join(parts) if parts else (act_block.get("activities_list") or _FALLBACK_ACTIVITIES_LIST)

    def _slot(i: int) -> str:
        if i < len(titles_order):
            return titles_order[i]
        key = f"activity_{i + 1}"
        return act_block.get(key) or (_FALLBACK_ACTIVITY_1, _FALLBACK_ACTIVITY_2, _FALLBACK_ACTIVITY_3)[i]

    a1, a2, a3 = _slot(0), _slot(1), _slot(2)
    if len(titles_order) < 3:
        missing_fields.append("title_plan_activities(fewer_than_three_slots_padded_from_defaults_or_builtin)")
    cycle_titles = titles_order if titles_order else [a1, a2, a3]
    cycle_titles = [t for t in cycle_titles if t] or ["Не указан тип задач профессиональной деятельности"]
    return (activities_list, a1, a2, a3, cycle_titles)


def _first_area_text_for_code(table: list[dict[str, str]], code: str, fallback: str) -> str:
    for row in table:
        if _to_str(row.get("area_code")) == code:
            t = _to_str(row.get("area")).strip()
            if t:
                return t
    return fallback


def _resolve_prof_standard_narratives(
    api_rows_sorted: list[dict[str, Any]],
    prof_standards_table: list[dict[str, str]],
    defaults: dict[str, Any],
    missing_fields: list[str],
) -> tuple[str, str, str]:
    narr_defaults = _defaults_prof_narratives(defaults)
    out: list[str] = []
    for i in range(3):
        if i < len(api_rows_sorted):
            r = api_rows_sorted[i]
            num = _to_str(r.get("number_in_group")).strip()
            name = _to_str(r.get("standard_name")).strip()
            if num and name:
                out.append(f"профессиональный стандарт {num}. {name}")
            elif name:
                out.append(f"профессиональный стандарт {name}")
            elif num:
                out.append(f"профессиональный стандарт {num}")
            else:
                cell = prof_standards_table[i]["standard"] if i < len(prof_standards_table) else ""
                out.append(f"профессиональный стандарт {cell}".strip())
            continue
        if i < len(narr_defaults) and narr_defaults[i].strip():
            out.append(narr_defaults[i].strip())
            continue
        out.append(_FALLBACK_PROF_STANDARD_NARRATIVES[i])
        missing_fields.append(f"prof_standard_{i + 1}_builtin_fallback")
    return (out[0], out[1], out[2])


def _resolve_generalized_labor_functions(
    prof_standards_table: list[dict[str, str]],
    defaults: dict[str, Any],
    missing_fields: list[str],
) -> str:
    raw = defaults.get("generalized_labor_functions")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    for row in prof_standards_table:
        g = _to_str(row.get("generalized_functions")).strip()
        if g:
            return g
    missing_fields.append("generalized_labor_functions(builtin_fallback)")
    return _FALLBACK_GENERALIZED_LABOR


def _rows_for_title_plan(
    rows: list[dict[str, Any]], tp_id: int, *, field: str = "title_plan_id"
) -> list[dict[str, Any]]:
    """Строки с title_plan_id = 0 (общие) или = выбранному учебному плану."""
    filtered = [r for r in rows if int(r.get(field) or 0) in (0, tp_id)]
    return filtered if filtered else rows


def _competency_indicator_line(code: str, description: str) -> str:
    code = code.strip()
    description = description.strip()
    if code and description:
        return f"{code}. {description}"
    return code or description


def _competencies_lookup(payload: dict[str, Any], spec_id: int) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for row in _rows_for_speciality(_table_data(payload, "competencies"), spec_id):
        code = _to_str(row.get("code")).strip()
        if code:
            lookup[code] = _to_str(row.get("description")).strip()
    return lookup


def _parent_competence_codes(comp_rows: list[dict[str, Any]], prefix: str) -> list[str]:
    codes: list[str] = []
    for row in comp_rows:
        code = _to_str(row.get("code")).strip()
        if code.startswith(prefix):
            codes.append(code)
    return codes


def _collect_professional_activities_from_api(
    payload: dict[str, Any], spec_id: int, tp_id: int
) -> str:
    rows = _rows_for_speciality(_table_data(payload, "professional_activities"), spec_id)
    if tp_id > 0:
        by_tp = _rows_for_title_plan(rows, tp_id)
        if by_tp:
            rows = by_tp
    for row in rows:
        val = _to_str(
            row.get("objects_list") or row.get("subject_areas") or row.get("text")
        ).strip()
        if val:
            return val
    return ""


def _labor_functions_for_prof_standard_row(
    payload: dict[str, Any],
    tp_id: int,
    ps_row: dict[str, Any],
    labor_by_ps_id: dict[int, list[dict[str, Any]]],
    labor_by_number: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    nested = ps_row.get("labor_functions")
    if isinstance(nested, list):
        return [x for x in nested if isinstance(x, dict)]

    ps_id = int(ps_row.get("id") or 0)
    if ps_id and labor_by_ps_id.get(ps_id):
        return labor_by_ps_id[ps_id]

    number = _to_str(ps_row.get("number_in_group")).strip()
    if number and labor_by_number.get(number):
        return labor_by_number[number]
    return []


def _labor_function_lines(funcs: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    tf_lines: list[str] = []
    lvl_lines: list[str] = []
    for lf in funcs:
        title = _to_str(
            lf.get("title") or lf.get("labor_function_title") or lf.get("name")
        ).strip()
        level = _to_str(lf.get("qualification_level") or lf.get("level")).strip()
        code = _to_str(lf.get("labor_function_code") or lf.get("code")).strip()
        if code and title:
            tf_lines.append(f"{code} {title}")
        elif title:
            tf_lines.append(title)
        if level:
            lvl_lines.append(level)
    return tf_lines, lvl_lines


def _index_labor_functions(
    payload: dict[str, Any], tp_id: int
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    by_ps_id: dict[int, list[dict[str, Any]]] = {}
    by_number: dict[str, list[dict[str, Any]]] = {}
    rows = _table_data(payload, "title_plan_prof_standard_labor_functions")
    if tp_id > 0:
        rows = _rows_for_title_plan(rows, tp_id)
    for row in rows:
        ps_id = int(row.get("title_plan_prof_standard_id") or row.get("prof_standard_id") or 0)
        if ps_id:
            by_ps_id.setdefault(ps_id, []).append(row)
        number = _to_str(row.get("number_in_group")).strip()
        if number:
            by_number.setdefault(number, []).append(row)
    return by_ps_id, by_number


def _build_ps_labor_manual_fields(
    payload: dict[str, Any],
    tp_id: int,
    api_ps_rows_sorted: list[dict[str, Any]],
) -> dict[str, str]:
    manual: dict[str, str] = {}
    labor_by_ps_id, labor_by_number = _index_labor_functions(payload, tp_id)
    area_idx: dict[str, int] = {}
    for ps_row in api_ps_rows_sorted:
        area_code = _area_code_from_number_in_group(ps_row.get("number_in_group"))
        if not area_code:
            continue
        area_idx[area_code] = area_idx.get(area_code, 0) + 1
        idx = area_idx[area_code]
        funcs = _labor_functions_for_prof_standard_row(
            payload, tp_id, ps_row, labor_by_ps_id, labor_by_number
        )
        tf_lines, lvl_lines = _labor_function_lines(funcs)
        if tf_lines:
            manual[f"ps_{area_code}_{idx}_tf"] = "\n".join(tf_lines)
        if lvl_lines:
            manual[f"ps_{area_code}_{idx}_lvl"] = "\n".join(lvl_lines)
    return manual


def _build_competency_manual_fields(
    payload: dict[str, Any],
    spec_id: int,
    comp_rows: list[dict[str, Any]],
    *,
    uk_prefix: str = "uk",
    opk_prefix: str = "opk",
) -> dict[str, str]:
    manual: dict[str, str] = {}
    comp_by_id = {
        int(r["id"]): r for r in _table_data(payload, "competence") if "id" in r
    }
    child_rows = _rows_for_speciality(_table_data(payload, "competencies"), spec_id)

    def fill_for_parents(parent_codes: list[str], prefix: str) -> None:
        for i, parent_code in enumerate(parent_codes, start=1):
            parent_row = next(
                (r for r in comp_rows if _to_str(r.get("code")).strip() == parent_code),
                None,
            )
            if not parent_row:
                parent_id = next(
                    (
                        int(r["id"])
                        for r in comp_by_id.values()
                        if _to_str(r.get("code")).strip() == parent_code
                    ),
                    0,
                )
            else:
                parent_id = int(parent_row.get("id") or 0)
            if not parent_id:
                continue
            lines: list[str] = []
            for row in child_rows:
                if int(row.get("competence_code_id") or 0) != parent_id:
                    continue
                lines.append(
                    _competency_indicator_line(
                        _to_str(row.get("code")),
                        _to_str(row.get("description")),
                    )
                )
            if lines:
                manual[f"{prefix}_{i}_ind"] = "\n".join(lines)

    fill_for_parents(_parent_competence_codes(comp_rows, "УК-"), uk_prefix)
    fill_for_parents(_parent_competence_codes(comp_rows, "ОПК-"), opk_prefix)
    return manual


def _build_pk_indicator_manual_fields(
    payload: dict[str, Any],
    spec_id: int,
    comp_rows: list[dict[str, Any]],
    pk_table: list[dict[str, str]],
) -> dict[str, str]:
    manual: dict[str, str] = {}
    comp_by_id = {
        int(r["id"]): r for r in _table_data(payload, "competence") if "id" in r
    }
    child_rows = _rows_for_speciality(_table_data(payload, "competencies"), spec_id)
    code_to_id = {
        _to_str(r.get("code")).strip(): int(r["id"])
        for r in comp_rows
        if _to_str(r.get("code")).startswith("ПК-") and "id" in r
    }
    counters: dict[str, int] = {}
    for row in pk_table:
        key = str(row.get("task_type_key", "")).strip()
        if not key:
            continue
        counters[key] = counters.get(key, 0) + 1
        row_idx = counters[key]
        pk_code = _to_str(row.get("pk_code")).strip()
        parent_id = code_to_id.get(pk_code, 0)
        if not parent_id:
            parent_id = next(
                (
                    int(r["id"])
                    for r in comp_by_id.values()
                    if _to_str(r.get("code")).strip() == pk_code
                ),
                0,
            )
        lines: list[str] = []
        if parent_id:
            for child in child_rows:
                if int(child.get("competence_code_id") or 0) != parent_id:
                    continue
                lines.append(
                    _competency_indicator_line(
                        _to_str(child.get("code")),
                        _to_str(child.get("description")),
                    )
                )
        if lines:
            manual[f"pk_{key}_{row_idx}_ind"] = "\n".join(lines)
    return manual


def _mandatory_indicators_text(
    row: dict[str, Any], comp_lookup: dict[str, str]
) -> str:
    raw_ind = _to_str(row.get("indicators")).strip()
    if raw_ind:
        return raw_ind
    codes_raw = row.get("competency_codes")
    codes: list[str] = []
    if isinstance(codes_raw, list):
        codes = [_to_str(c).strip() for c in codes_raw if _to_str(c).strip()]
    elif isinstance(codes_raw, str) and codes_raw.strip():
        text = codes_raw.strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    codes = [_to_str(c).strip() for c in parsed if _to_str(c).strip()]
            except json.JSONDecodeError:
                pass
        if not codes:
            codes = [c.strip() for c in text.replace(";", ",").split(",") if c.strip()]
    lines: list[str] = []
    for code in codes:
        desc = comp_lookup.get(code, "")
        lines.append(_competency_indicator_line(code, desc))
    return "\n".join(lines)


def _collect_mandatory_professional_rows_from_api(
    payload: dict[str, Any], spec_id: int, tp_id: int
) -> list[dict[str, Any]]:
    rows = _rows_for_speciality(
        _table_data(payload, "mandatory_professional_competencies"), spec_id
    )
    if tp_id > 0:
        by_tp = _rows_for_title_plan(rows, tp_id)
        if by_tp:
            rows = by_tp
    return sorted(
        rows,
        key=lambda r: (
            int(r.get("sort_order") or 0),
            int(r.get("id") or 0),
        ),
    )


def _build_mandatory_manual_fields(
    mandatory_rows: list[dict[str, Any]],
    pk_table: list[dict[str, str]],
    comp_lookup: dict[str, str],
) -> dict[str, str]:
    manual: dict[str, str] = {}
    pk_slots: list[tuple[str, int, str]] = []
    counters: dict[str, int] = {}
    for row in pk_table:
        key = str(row.get("task_type_key", "")).strip()
        if not key:
            continue
        counters[key] = counters.get(key, 0) + 1
        pk_slots.append((key, counters[key], _to_str(row.get("pk_code")).strip()))

    used_slots: set[tuple[str, int]] = set()

    def apply_row(key: str, row_idx: int, src: dict[str, Any]) -> None:
        if not key or row_idx <= 0:
            return
        slot = (key, row_idx)
        if slot in used_slots:
            return
        used_slots.add(slot)
        manual[f"pk_{key}_{row_idx}_cat1"] = _to_str(src.get("task")).strip()
        manual[f"pk_{key}_{row_idx}_cat2"] = _to_str(
            src.get("object_or_knowledge") or src.get("object")
        ).strip()
        manual[f"pk_{key}_{row_idx}_ind"] = _mandatory_indicators_text(src, comp_lookup)
        manual[f"pk_{key}_{row_idx}_cat5"] = _to_str(
            src.get("labor_function_code") or src.get("category_5") or src.get("cat5")
        ).strip()

    for src in mandatory_rows:
        key = _to_str(src.get("task_type_key") or src.get("activity_key")).strip()
        row_idx = int(src.get("row_index") or src.get("pk_row_index") or 0)
        if key and row_idx:
            apply_row(key, row_idx, src)
            continue
        pk_code = _to_str(src.get("pk_code") or src.get("competence_code")).strip()
        if pk_code:
            for key2, idx2, code2 in pk_slots:
                if code2 == pk_code and (key2, idx2) not in used_slots:
                    apply_row(key2, idx2, src)
                    break

    remaining = [s for s in pk_slots if s[:2] not in used_slots]
    unmatched = [
        r
        for r in mandatory_rows
        if not _to_str(r.get("task_type_key") or r.get("activity_key")).strip()
        and not _to_str(r.get("pk_code") or r.get("competence_code")).strip()
    ]
    for slot, src in zip(remaining, unmatched):
        apply_row(slot[0], slot[1], src)

    return manual


def _build_manual_fields_seed(
    payload: dict[str, Any],
    *,
    spec_id: int,
    tp_id: int,
    comp_rows: list[dict[str, Any]],
    api_ps_rows_sorted: list[dict[str, Any]],
    pk_table: list[dict[str, str]],
) -> dict[str, str]:
    """
    Предзаполнение {{MANUAL:…}} из таблиц входящей выгрузки (формат будущего POST/БД).
    """
    seed: dict[str, str] = {}
    normative_base = _collect_normative_base_from_api(payload, spec_id)
    if normative_base:
        seed["normative_docs"] = "\n".join(normative_base)

    objects_list = _collect_professional_activities_from_api(payload, spec_id, tp_id)
    if objects_list:
        seed["subject_areas"] = objects_list

    seed.update(_build_ps_labor_manual_fields(payload, tp_id, api_ps_rows_sorted))
    seed.update(_build_competency_manual_fields(payload, spec_id, comp_rows))
    seed.update(_build_pk_indicator_manual_fields(payload, spec_id, comp_rows, pk_table))

    comp_lookup = _competencies_lookup(payload, spec_id)
    mandatory_rows = _collect_mandatory_professional_rows_from_api(payload, spec_id, tp_id)
    seed.update(_build_mandatory_manual_fields(mandatory_rows, pk_table, comp_lookup))
    return {k: v for k, v in seed.items() if v}


def _build_export_title_plan_prof_standards(
    api_ps_rows_sorted: list[dict[str, Any]],
    payload: dict[str, Any],
    tp_id: int,
    manual_seed: dict[str, str],
) -> list[dict[str, Any]]:
    labor_by_ps_id, labor_by_number = _index_labor_functions(payload, tp_id)
    area_idx: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    for ps_row in api_ps_rows_sorted:
        area_code = _area_code_from_number_in_group(ps_row.get("number_in_group"))
        area_idx[area_code] = area_idx.get(area_code, 0) + 1
        idx = area_idx[area_code]
        funcs = _labor_functions_for_prof_standard_row(
            payload, tp_id, ps_row, labor_by_ps_id, labor_by_number
        )
        tf_lines, lvl_lines = _labor_function_lines(funcs)
        if not tf_lines:
            tf_lines = _split_manual_lines(manual_seed.get(f"ps_{area_code}_{idx}_tf", ""))
        if not lvl_lines:
            lvl_lines = _split_manual_lines(manual_seed.get(f"ps_{area_code}_{idx}_lvl", ""))
        labor_functions = [
            {"title": tf_lines[i], "qualification_level": lvl_lines[i] if i < len(lvl_lines) else ""}
            for i in range(len(tf_lines))
        ]
        result.append(
            {
                "standard_name": _to_str(ps_row.get("standard_name")).strip().upper(),
                "number_in_group": _to_str(ps_row.get("number_in_group")).strip(),
                "professional_activity_goal": _to_str(
                    ps_row.get("professional_activity_goal")
                    or ps_row.get("professional_activity_name")
                ).strip(),
                "labor_functions": labor_functions,
            }
        )
    return result


def _split_manual_lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").replace("\r\n", "\n").split("\n") if ln.strip()]


def _build_export_mandatory_professional_competencies(
    mandatory_rows: list[dict[str, Any]], comp_lookup: dict[str, str]
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for row in mandatory_rows:
        entry: dict[str, Any] = {
            "task": _to_str(row.get("task")).strip(),
            "object_or_knowledge": _to_str(
                row.get("object_or_knowledge") or row.get("object")
            ).strip(),
            "competency_codes": [],
        }
        ind = _mandatory_indicators_text(row, comp_lookup)
        codes: list[str] = []
        for line in _split_manual_lines(ind):
            parsed_code = line.split(".", 1)[0].strip() if "." in line else line.strip()
            if parsed_code:
                codes.append(parsed_code)
        if codes:
            entry["competency_codes"] = codes
        labor_code = _to_str(row.get("labor_function_code") or row.get("cat5")).strip()
        if labor_code:
            entry["labor_function_code"] = labor_code
        if any((entry["task"], entry["object_or_knowledge"], entry["competency_codes"])):
            rows_out.append(entry)
    return rows_out


def _rows_for_speciality(
    rows: list[dict[str, Any]], spec_id: int, *, field: str = "speciality_id"
) -> list[dict[str, Any]]:
    """Строки с speciality_id = 0 (общие) или = выбранному направлению."""
    filtered = [
        r
        for r in rows
        if int(r.get(field) or 0) in (0, spec_id)
    ]
    return filtered if filtered else rows


def _collect_normative_base_from_api(payload: dict[str, Any], spec_id: int) -> list[str]:
    rows = _rows_for_speciality(_table_data(payload, "normative_documents"), spec_id)
    bases: list[str] = []
    for row in rows:
        raw = row.get("normative_base")
        if raw is None:
            continue
        if isinstance(raw, list):
            for item in raw:
                text = _to_str(item).strip()
                if text:
                    bases.append(text)
            continue
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                continue
            if text.startswith("[") or text.startswith("{"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        for item in parsed:
                            s = _to_str(item).strip()
                            if s:
                                bases.append(s)
                        continue
                except json.JSONDecodeError:
                    pass
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                line = line.strip()
                if line:
                    bases.append(line)
            continue
        text = _to_str(raw).strip()
        if text:
            bases.append(text)
    return bases


def _collect_competencies_from_api(payload: dict[str, Any], spec_id: int) -> list[dict[str, str]]:
    rows = _rows_for_speciality(_table_data(payload, "competencies"), spec_id)
    items: list[dict[str, str]] = []
    for row in rows:
        code = _to_str(row.get("code")).strip()
        if not code:
            continue
        items.append(
            {
                "code": code,
                "description": _to_str(row.get("description")).strip(),
            }
        )
    return items


def _employee_signature(employees: dict[int, dict[str, Any]], employee_id: int) -> str:
    empl = employees.get(employee_id)
    if not empl:
        return ""
    return _to_str(empl.get("signature")).strip()


def _build_api_snapshot(
    payload: dict[str, Any],
    *,
    spec_id: int,
    tp_id: int,
    department_id: int,
    comp_rows: list[dict[str, Any]],
    api_ps_rows_sorted: list[dict[str, Any]],
    pk_table: list[dict[str, str]],
    employees: dict[int, dict[str, Any]],
    departments: dict[int, dict[str, Any]],
    faculties: dict[int, dict[str, Any]],
    missing_fields: list[str],
) -> dict[str, Any]:
    """
    Данные входящей выгрузки в форме, близкой к исходящему POST JSON (api_export).
    Используются для предзаполнения manual_fields и отправки в API.
    """
    first_sig = ""
    dep = departments.get(department_id)
    if dep:
        first_sig = _employee_signature(employees, int(dep.get("head_id") or 0))

    second_sig = ""
    fac = faculties.get(1) or (next(iter(faculties.values())) if faculties else None)
    if fac:
        second_sig = _employee_signature(employees, int(fac.get("dean_id") or 0))

    normative_base = _collect_normative_base_from_api(payload, spec_id)
    competencies = _collect_competencies_from_api(payload, spec_id)
    objects_list = _collect_professional_activities_from_api(payload, spec_id, tp_id)
    manual_seed = _build_manual_fields_seed(
        payload,
        spec_id=spec_id,
        tp_id=tp_id,
        comp_rows=comp_rows,
        api_ps_rows_sorted=api_ps_rows_sorted,
        pk_table=pk_table,
    )
    mandatory_rows = _collect_mandatory_professional_rows_from_api(payload, spec_id, tp_id)
    comp_lookup = _competencies_lookup(payload, spec_id)

    if not first_sig:
        missing_fields.append("api_employee_signature(first_responsible)")
    if not second_sig:
        missing_fields.append("api_employee_signature(second_responsible)")
    if not normative_base:
        missing_fields.append("api_normative_documents(normative_base)")
    if not competencies:
        missing_fields.append("api_competencies")
    if not objects_list:
        missing_fields.append("api_professional_activities(objects_list)")
    if not manual_seed.get("normative_docs") and normative_base:
        manual_seed["normative_docs"] = "\n".join(normative_base)

    export_seed: dict[str, Any] = {
        "normative_documents": {"normative_base": normative_base},
        "professional_activities": {"objects_list": objects_list},
        "title_plan_prof_standards": _build_export_title_plan_prof_standards(
            api_ps_rows_sorted, payload, tp_id, manual_seed
        ),
        "competencies": competencies,
        "mandatory_professional_competencies": _build_export_mandatory_professional_competencies(
            mandatory_rows, comp_lookup
        ),
    }

    return {
        "employee_signatures": {
            "first_responsible": first_sig,
            "second_responsible": second_sig,
        },
        "export_seed": export_seed,
        "manual_fields_seed": manual_seed,
        "normative_documents": export_seed["normative_documents"],
        "professional_activities": export_seed["professional_activities"],
        "competencies": competencies,
    }


def _pk_table_from_pk_list(
    pk_competencies_list: list[tuple[str, str]],
    activity_titles_for_cycle: list[str],
) -> list[dict[str, str]]:
    titles = [t for t in activity_titles_for_cycle if t]
    if not titles:
        titles = ["Не указан тип задач профессиональной деятельности"]
    pk_table: list[dict[str, str]] = []
    for idx, (code, desc) in enumerate(pk_competencies_list):
        task_idx = idx % len(titles)
        task = titles[task_idx]
        task_key = f"activity_{task_idx + 1}"
        pk_table.append(
            {
                "task_type_key": task_key,
                "task_type": task,
                "pk_code": code,
                "pk_description": desc,
                "indicators": "",
            }
        )
    return pk_table


def build_opop_data(payload: dict[str, Any], *, params: ExtractParams) -> dict[str, Any]:
    missing_fields: list[str] = []
    all_edu_plan = _table_data(payload, "edu_plan")
    all_edu_sem = _table_data(payload, "edu_semesters")
    all_title_plan = _table_data(payload, "title_plan")

    specialities = {int(r["id"]): r for r in _table_data(payload, "speciality") if "id" in r}
    if params.speciality_id not in specialities:
        raise RuntimeError(f"Направление с id={params.speciality_id} не найдено в JSON.")
    spec = specialities[params.speciality_id]
    spec_id = int(spec["id"])
    direction_code = _to_str(spec.get("cod") or spec.get("code"))
    direction_name = _to_str(spec.get("title"))
    profile = _to_str(spec.get("profile"))

    plan_to_title_plan: dict[int, int] = {}
    for row in all_edu_plan:
        ep_id = int(row.get("id") or 0)
        tp_id_raw = int(row.get("title_plan_id") or 0)
        if ep_id > 0 and tp_id_raw > 0:
            plan_to_title_plan[ep_id] = tp_id_raw
    sem_count_by_tp: dict[int, int] = {}
    for row in all_edu_sem:
        ep_id = int(row.get("edu_plan_id") or 0)
        tp_id_raw = plan_to_title_plan.get(ep_id)
        if tp_id_raw:
            sem_count_by_tp[tp_id_raw] = sem_count_by_tp.get(tp_id_raw, 0) + 1

    title_plan_rows = [r for r in all_title_plan if int(r.get("spec_id") or 0) == spec_id]
    title_plan_rows = [r for r in title_plan_rows if _to_str(r.get("included")) == "1"] or title_plan_rows
    if params.year is not None:
        by_year = [r for r in title_plan_rows if _to_str(r.get("date_enter")) == str(params.year)]
        if by_year:
            title_plan_rows = by_year

    tp: dict[str, Any] = {}
    if title_plan_rows:
        def _tp_score(row: dict[str, Any]) -> tuple[int, int, int, int]:
            row_id = int(row.get("id") or 0)
            sem_count = sem_count_by_tp.get(row_id, 0)
            y1, y2 = _latest_year_key(row)
            return (1 if sem_count > 0 else 0, sem_count, y1, y2)

        title_plan_rows.sort(key=_tp_score, reverse=True)
        tp = title_plan_rows[0]
    else:
        missing_fields.extend(
            [
                "title_plan",
                "date_fgos",
                "number_fgos",
                "date_uchsovet",
                "number_uchsovet",
                "first_responsible_fio",
                "block_1_credits",
                "block_2_credits",
                "block_3_credits",
                "obligatory_part_percent",
            ]
        )

    tp_id = int(tp.get("id") or 0)
    date_uchsovet = _to_str(tp.get("date_uchsovet"))
    number_uchsovet = _to_str(tp.get("number_uchsovet"))
    date_fgos = _to_str(tp.get("date_fgos"))
    number_fgos = _to_str(tp.get("number_fgos"))
    department_id = int(tp.get("department_id") or 0)

    order_date_ru = _iso_date_to_ru(date_fgos)
    if not order_date_ru:
        missing_fields.append("date_fgos")
    order_date = order_date_ru
    order_number = f"№ {number_fgos}".strip()
    if not number_fgos:
        missing_fields.append("number_fgos")

    protocol_date_ru = _iso_date_to_ru(date_uchsovet)
    protocol_date = f"{protocol_date_ru} г." if protocol_date_ru else ""
    if not protocol_date_ru:
        missing_fields.append("date_uchsovet")
    protocol_number = f"№ {number_uchsovet}".strip()
    if not number_uchsovet or number_uchsovet == "0":
        missing_fields.append("number_uchsovet")

    employees = {int(r["id"]): r for r in _table_data(payload, "employees") if "id" in r}
    departments = {int(r["id"]): r for r in _table_data(payload, "departments") if "id" in r}
    faculties = {int(r["id"]): r for r in _table_data(payload, "faculties") if "id" in r}

    first_resp = ""
    dep = departments.get(department_id)
    if dep:
        head_id = int(dep.get("head_id") or 0)
        empl = employees.get(head_id)
        if empl:
            first_resp = _fio_to_initials(
                _to_str(empl.get("surname")),
                _to_str(empl.get("name")),
                _to_str(empl.get("patronimyc")),
            )
    if not first_resp:
        missing_fields.append("first_responsible_fio")

    second_resp = ""
    fac = faculties.get(1) or (next(iter(faculties.values())) if faculties else None)
    if fac:
        dean_id = int(fac.get("dean_id") or 0)
        empl = employees.get(dean_id)
        if empl:
            second_resp = _fio_to_initials(
                _to_str(empl.get("surname")),
                _to_str(empl.get("name")),
                _to_str(empl.get("patronimyc")),
            )
    if not second_resp:
        missing_fields.append("second_responsible_fio")

    comp_rows = _table_data(payload, "competence")
    comp_rows = [r for r in comp_rows if int(r.get("speciality_id") or 0) in (0, spec_id)]
    universal, opk, pk = [], [], []
    pk_competencies_list: list[tuple[str, str]] = []
    for row in comp_rows:
        code = _to_str(row.get("code"))
        desc = _to_str(row.get("description"))
        item = f"{code} - {desc}".strip(" -")
        if code.startswith("УК-"):
            universal.append(item)
        elif code.startswith("ОПК-"):
            opk.append(item)
        elif code.startswith("ПК-"):
            pk.append(item)
            pk_competencies_list.append((code, desc))

    if not universal:
        missing_fields.append("universal_competencies")
    if not opk:
        missing_fields.append("opk_competencies")
    if not pk:
        missing_fields.append("professional_competencies")

    block_by_id = {int(r["id"]): r for r in _table_data(payload, "block") if "id" in r}
    tp_ids_for_spec = {
        int(r.get("id") or 0)
        for r in all_title_plan
        if int(r.get("spec_id") or 0) == spec_id and int(r.get("id") or 0) > 0
    }
    edu_plan = [r for r in all_edu_plan if int(r.get("title_plan_id") or 0) == tp_id] if tp_id else []
    if not edu_plan:
        edu_plan = [r for r in all_edu_plan if int(r.get("title_plan_id") or 0) in tp_ids_for_spec]

    plan_ids = {int(r.get("id") or 0): int(r.get("block_id") or 0) for r in edu_plan}
    edu_sem = [r for r in all_edu_sem if int(r.get("edu_plan_id") or 0) in plan_ids]
    if not edu_sem and tp_ids_for_spec:
        all_plan_for_spec = [r for r in all_edu_plan if int(r.get("title_plan_id") or 0) in tp_ids_for_spec]
        plan_ids = {int(r.get("id") or 0): int(r.get("block_id") or 0) for r in all_plan_for_spec}
        edu_sem = [r for r in all_edu_sem if int(r.get("edu_plan_id") or 0) in plan_ids]

    total_1 = total_2 = total_3 = obligatory_12 = 0.0
    seen_block_1 = seen_block_2 = seen_block_3 = False

    def _block_group(block_id: int, title: str, part_title: str) -> int:
        if block_id in (1, 2, 3):
            return block_id
        t = _to_str(title).lower()
        p = _to_str(part_title).lower()
        combined = f"{t} {p}".strip()
        if ("дисциплины" in combined) or ("модули" in combined) or ("блок 1" in combined):
            return 1
        if ("практика" in combined) or ("блок 2" in combined):
            return 2
        if ("государственная итоговая аттестация" in combined) or ("гиа" in combined) or ("блок 3" in combined):
            return 3
        digits = "".join(ch for ch in combined if ch.isdigit())
        if digits and digits[0] in ("1", "2", "3"):
            return int(digits[0])
        return 0

    def _hours_from_semester(row: dict[str, Any]) -> float:
        """
        Возвращает часы по строке семестра.
        Пытаемся взять явные поля часов из API; если их нет, используем zed * 36.
        """
        components = ("lecture", "practice", "laboratory", "ind_work")
        component_sum = sum(_to_float(row.get(k)) for k in components)
        if component_sum > 0:
            return component_sum
        hour_keys = (
            "hours",
            "hour",
            "all_hours",
            "total_hours",
            "hours_total",
            "count_hours",
            "clock_hours",
            "academic_hours",
            "class_hours",
        )
        for key in hour_keys:
            val = _to_float(row.get(key))
            if val > 0:
                return val
        zed = _to_float(row.get("zed"))
        if zed > 0:
            return zed * 36.0
        return 0.0

    for row in edu_sem:
        plan_id = int(row.get("edu_plan_id") or 0)
        block_id = plan_ids.get(plan_id, 0)
        block = block_by_id.get(block_id, {})
        block_title = _to_str(block.get("block_title"))
        part_title = _to_str(block.get("part_title"))
        hours = _hours_from_semester(row)
        group = _block_group(block_id, block_title, part_title)
        if group == 1:
            seen_block_1 = True
            total_1 += hours
        elif group == 2:
            seen_block_2 = True
            total_2 += hours
        elif group == 3:
            seen_block_3 = True
            total_3 += hours
        if group in (1, 2) and "Обязательная часть" in part_title:
            obligatory_12 += hours

    def _fmt_credits(x: float) -> str:
        return str(int(round(x)))

    def _fmt_percent(x: float) -> str:
        y = round(x, 1)
        if abs(y - round(y)) < 1e-9:
            return str(int(round(y)))
        return str(y).replace(".", ",")

    denom_no_gia = total_1 + total_2
    percent_obligatory = (obligatory_12 / denom_no_gia * 100.0) if denom_no_gia else 0.0

    if not seen_block_1:
        missing_fields.append("block_1_credits")
    if not seen_block_2:
        missing_fields.append("block_2_credits")
    if not seen_block_3:
        missing_fields.append("block_3_credits")

    defaults = _load_opop_defaults()
    prof_standards_table, api_ps_rows_sorted = _resolve_prof_standards_table(
        payload, tp_id, defaults, missing_fields
    )
    activities_list, activity_1, activity_2, activity_3, activity_cycle_titles = _resolve_activity_labels(
        payload, tp_id, defaults, missing_fields
    )
    pk_table = _pk_table_from_pk_list(pk_competencies_list, activity_cycle_titles)
    prof_standard_1, prof_standard_2, prof_standard_3 = _resolve_prof_standard_narratives(
        api_ps_rows_sorted, prof_standards_table, defaults, missing_fields
    )
    area_06 = _to_str(defaults.get("area_06")).strip() or _first_area_text_for_code(
        prof_standards_table, "06", _FALLBACK_AREA_06
    )
    area_40 = _to_str(defaults.get("area_40")).strip() or _first_area_text_for_code(
        prof_standards_table, "40", _FALLBACK_AREA_40
    )
    generalized_labor_functions = _resolve_generalized_labor_functions(
        prof_standards_table, defaults, missing_fields
    )

    plan_profile = _to_str(tp.get("profile")).strip() if isinstance(tp, dict) else ""
    display_profile = plan_profile or profile
    profile_full = f"{direction_code} {direction_name}, профиль «{display_profile}»"

    api_snapshot = _build_api_snapshot(
        payload,
        spec_id=spec_id,
        tp_id=tp_id,
        department_id=department_id,
        comp_rows=comp_rows,
        api_ps_rows_sorted=api_ps_rows_sorted,
        pk_table=pk_table,
        employees=employees,
        departments=departments,
        faculties=faculties,
        missing_fields=missing_fields,
    )
    manual_fields_seed = api_snapshot.get("manual_fields_seed")
    if not isinstance(manual_fields_seed, dict):
        manual_fields_seed = {}

    opop_data: dict[str, Any] = {
        "direction_code": direction_code,
        "direction_name": direction_name,
        "order_date": order_date,
        "order_number": order_number,
        "protocol_number": protocol_number,
        "protocol_date": protocol_date,
        "first_responsible_fio": first_resp,
        "second_responsible_fio": second_resp,
        "profile_full": profile_full,
        "area_06": area_06,
        "area_40": area_40,
        "activities_list": activities_list,
        "activity_1": activity_1,
        "activity_2": activity_2,
        "activity_3": activity_3,
        "prof_standard_1": prof_standard_1,
        "prof_standard_2": prof_standard_2,
        "prof_standard_3": prof_standard_3,
        "generalized_labor_functions": generalized_labor_functions,
        "universal_competencies": "\n".join(universal),
        "opk_competencies": "\n".join(opk),
        "professional_competencies": "\n".join(pk),
        "block_1_credits": _fmt_credits(total_1),
        "block_2_credits": _fmt_credits(total_2),
        "block_3_credits": _fmt_credits(total_3),
        "program_total_credits": _fmt_credits(total_1 + total_2 + total_3),
        "obligatory_part_percent": _fmt_percent(percent_obligatory),
        "prof_standards_table": prof_standards_table,
        "pk_table": pk_table,
        "employee_signatures": api_snapshot.get("employee_signatures") or {},
        "_api_snapshot": api_snapshot,
        "_manual_fields_seed": manual_fields_seed,
        "_missing_fields": sorted(set(missing_fields)),
        "_missing_fields_text": ", ".join(sorted(set(missing_fields))),
        "_source_export_time": _to_str(payload.get("export_time")),
        "_generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return opop_data
