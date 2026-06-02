"""
Сборка JSON для POST http://math.nosu.ru/api_project/post_json из opop_data и manual_fields.
Поле competence и числовые id не отправляются.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from generate_opop import parse_competencies_from_string

_LABOR_CODE_RE = re.compile(r"([A-ZА-Я]/\d+\.\d+)")
# УК-2.3. Описание / ОПК-3.1. Знает: ... / ПК-1.1. Знает ...
_COMPETENCY_CODE_RE = re.compile(
    r"^((?:УК|ОПК|ПК)-\d+(?:\.\d+)?)\.\s*(.+)$",
    re.IGNORECASE,
)
_STANDARD_NUMBER_RE = re.compile(r"^(\d+\.\d+)\.?\s*(.*)$")
_GEN_FUNCTION_RE = re.compile(r"^([A-ZА-Я])\.\s*(.+)$")
_LABOR_LINE_RE = re.compile(r"^([A-ZА-Я]/\d+\.\d+)\s+(.+)$")


def _manual(opop_data: dict[str, Any]) -> dict[str, str]:
    raw = opop_data.get("manual_fields")
    if not isinstance(raw, dict):
        raw = {}
    manual = {str(k): str(v or "") for k, v in raw.items()}
    snapshot = opop_data.get("_api_snapshot")
    if isinstance(snapshot, dict):
        seed = snapshot.get("manual_fields_seed")
        if isinstance(seed, dict):
            for key, value in seed.items():
                if value and not manual.get(key):
                    manual[key] = str(value)
    return manual


def _export_seed(opop_data: dict[str, Any]) -> dict[str, Any]:
    snapshot = opop_data.get("_api_snapshot")
    if isinstance(snapshot, dict):
        seed = snapshot.get("export_seed")
        if isinstance(seed, dict):
            return seed
    return {}


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _split_lines(text: str) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return [ln.strip() for ln in normalized.split("\n") if ln.strip()]


def _parse_standard_cell(standard: str) -> tuple[str, str]:
    s = (standard or "").strip().rstrip(".")
    m = _STANDARD_NUMBER_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip().rstrip(".")
    if ". " in s:
        num, name = s.split(". ", 1)
        return num.strip(), name.strip().rstrip(".")
    return s, ""


def _parse_generalized_function(text: str) -> tuple[str, str]:
    s = (text or "").strip()
    m = _GEN_FUNCTION_RE.match(s)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", s


def _parse_labor_title(line: str) -> str:
    """Только название трудовой функции (без кода D/02.6)."""
    s = line.strip()
    if not s:
        return ""
    m = _LABOR_LINE_RE.match(s)
    if m:
        return m.group(2).strip()
    code_m = _LABOR_CODE_RE.search(s)
    if code_m:
        return s[code_m.end() :].strip()
    return s


def _normalize_competency_code(code: str) -> str:
    c = code.strip()
    u = c.upper()
    if u.startswith("ОПК"):
        return "ОПК" + c[3:]
    if u.startswith("УК"):
        return "УК" + c[2:]
    if u.startswith("ПК"):
        return "ПК" + c[2:]
    return c


def _parse_competency_line(line: str) -> dict[str, str] | None:
    """
    УК-2.3. Имеет ...  → code УК-2.3, description «Имеет ...»
    ОПК-3.1. Знает: ... → code ОПК-3.1, description «Знает: ...»
    """
    s = line.strip()
    if not s:
        return None
    m = _COMPETENCY_CODE_RE.match(s)
    if m:
        return {
            "code": _normalize_competency_code(m.group(1)),
            "description": m.group(2).strip(),
        }
    if " - " in s:
        code, desc = s.split(" - ", 1)
        return {"code": _normalize_competency_code(code), "description": desc.strip()}
    return None


def _dedupe_competencies(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        code = item.get("code", "")
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(item)
    return out


def _competency_codes_from_text(text: str) -> list[str]:
    codes: list[str] = []
    for line in _split_lines(text):
        parsed = _parse_competency_line(line)
        if parsed and parsed.get("code"):
            codes.append(parsed["code"])
    return codes


def _extract_labor_function_code(*texts: str) -> str:
    for t in texts:
        m = _LABOR_CODE_RE.search(t or "")
        if m:
            return m.group(1)
    return ""


def build_normative_documents(manual: dict[str, str], opop_data: dict[str, Any]) -> dict[str, Any]:
    lines = _split_lines(manual.get("normative_docs", ""))
    if not lines:
        raw = _export_seed(opop_data).get("normative_documents")
        if isinstance(raw, dict):
            base = raw.get("normative_base")
            if isinstance(base, list):
                lines = [_to_str(x).strip() for x in base if _to_str(x).strip()]
    return {"normative_documents": {"normative_base": lines}}


def build_professional_activities(manual: dict[str, str], opop_data: dict[str, Any]) -> dict[str, Any]:
    objects_list = manual.get("subject_areas", "").strip()
    if not objects_list:
        raw = _export_seed(opop_data).get("professional_activities")
        if isinstance(raw, dict):
            objects_list = _to_str(raw.get("objects_list")).strip()
    return {"professional_activities": {"objects_list": objects_list}}


def build_title_plan_prof_standards(
    opop_data: dict[str, Any], manual: dict[str, str]
) -> list[dict[str, Any]]:
    table = opop_data.get("prof_standards_table")
    if not isinstance(table, list):
        return []

    by_area: dict[str, list[dict[str, str]]] = {}
    for row in table:
        if not isinstance(row, dict):
            continue
        area_code = str(row.get("area_code", "")).strip()
        by_area.setdefault(area_code, []).append(row)

    result: list[dict[str, Any]] = []
    for area_code in sorted(by_area.keys()):
        items = by_area[area_code]
        for idx, item in enumerate(items, start=1):
            number_in_group, standard_name = _parse_standard_cell(str(item.get("standard", "")))
            gen_raw = str(item.get("generalized_functions", "")).strip()
            _, gen_goal = _parse_generalized_function(gen_raw)
            professional_activity_goal = gen_goal or gen_raw

            tf_key = f"ps_{area_code}_{idx}_tf"
            lvl_key = f"ps_{area_code}_{idx}_lvl"
            tf_lines = _split_lines(manual.get(tf_key, ""))
            lvl_lines = _split_lines(manual.get(lvl_key, ""))

            labor_functions: list[dict[str, str]] = []
            for i, tf_line in enumerate(tf_lines):
                title = _parse_labor_title(tf_line)
                if not title:
                    continue
                level = lvl_lines[i] if i < len(lvl_lines) else (lvl_lines[-1] if len(lvl_lines) == 1 else "")
                labor_functions.append(
                    {
                        "title": title,
                        "qualification_level": level,
                    }
                )

            result.append(
                {
                    "standard_name": standard_name.upper() if standard_name else "",
                    "number_in_group": number_in_group,
                    "professional_activity_goal": professional_activity_goal,
                    "labor_functions": labor_functions,
                }
            )
    return result


def build_competencies(opop_data: dict[str, Any], manual: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []

    uk_count = len(parse_competencies_from_string(str(opop_data.get("universal_competencies", "")), "УК"))
    for i in range(1, uk_count + 1):
        for line in _split_lines(manual.get(f"uk_{i}_ind", "")):
            parsed = _parse_competency_line(line)
            if parsed:
                items.append(parsed)

    opk_count = len(parse_competencies_from_string(str(opop_data.get("opk_competencies", "")), "ОПК"))
    for i in range(1, opk_count + 1):
        for line in _split_lines(manual.get(f"opk_{i}_ind", "")):
            parsed = _parse_competency_line(line)
            if parsed:
                items.append(parsed)

    pk_table = opop_data.get("pk_table")
    if isinstance(pk_table, list):
        for key_group in ("activity_1", "activity_2", "activity_3"):
            row_idx = 0
            for row in pk_table:
                if not isinstance(row, dict):
                    continue
                if str(row.get("task_type_key", "")).strip() != key_group:
                    continue
                row_idx += 1
                for line in _split_lines(manual.get(f"pk_{key_group}_{row_idx}_ind", "")):
                    parsed = _parse_competency_line(line)
                    if parsed:
                        items.append(parsed)

    items = _dedupe_competencies(items)
    if items:
        return items

    raw = _export_seed(opop_data).get("competencies")
    if isinstance(raw, list):
        out: list[dict[str, str]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            code = _to_str(row.get("code")).strip()
            if not code:
                continue
            out.append({"code": code, "description": _to_str(row.get("description")).strip()})
        return _dedupe_competencies(out)
    return items


def build_mandatory_professional_competencies(
    opop_data: dict[str, Any], manual: dict[str, str]
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    pk_table = opop_data.get("pk_table")
    if not isinstance(pk_table, list):
        return rows_out

    counters: dict[str, int] = {}
    for row in pk_table:
        if not isinstance(row, dict):
            continue
        key = str(row.get("task_type_key", "")).strip()
        if not key:
            continue
        counters[key] = counters.get(key, 0) + 1
        row_idx = counters[key]

        cat1 = manual.get(f"pk_{key}_{row_idx}_cat1", "").strip()
        cat2 = manual.get(f"pk_{key}_{row_idx}_cat2", "").strip()
        ind = manual.get(f"pk_{key}_{row_idx}_ind", "").strip()
        cat5 = manual.get(f"pk_{key}_{row_idx}_cat5", "").strip()

        competency_codes = _competency_codes_from_text(ind)

        if not any((cat1, cat2, competency_codes)):
            continue

        entry: dict[str, Any] = {
            "task": cat1,
            "object_or_knowledge": cat2,
            "competency_codes": competency_codes,
        }
        labor_code = _extract_labor_function_code(cat1, cat2, ind, cat5)
        if labor_code:
            entry["labor_function_code"] = labor_code
        rows_out.append(entry)

    if rows_out:
        return rows_out

    raw = _export_seed(opop_data).get("mandatory_professional_competencies")
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    return rows_out


def build_api_export_payload(opop_data: dict[str, Any]) -> dict[str, Any]:
    manual = _manual(opop_data)
    payload: dict[str, Any] = {}
    payload.update(build_normative_documents(manual, opop_data))
    payload.update(build_professional_activities(manual, opop_data))
    payload["title_plan_prof_standards"] = build_title_plan_prof_standards(opop_data, manual)
    if not payload["title_plan_prof_standards"]:
        raw = _export_seed(opop_data).get("title_plan_prof_standards")
        if isinstance(raw, list):
            payload["title_plan_prof_standards"] = raw
    payload["competencies"] = build_competencies(opop_data, manual)
    payload["mandatory_professional_competencies"] = build_mandatory_professional_competencies(
        opop_data, manual
    )
    return payload


def resolve_api_post_url(defaults_path: Path | None = None) -> str:
    env_url = os.environ.get("OPOP_API_POST_JSON_URL", "").strip()
    if env_url:
        return env_url
    path = defaults_path or Path(__file__).resolve().parent / "opop_defaults.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                url = str(data.get("api_post_json_url", "")).strip()
                if url:
                    return url
        except Exception:
            pass
    return ""


def post_api_export_payload(
    payload: dict[str, Any],
    url: str,
    *,
    timeout_sec: int = 60,
) -> tuple[bool, str]:
    if not url:
        return False, "URL API не задан (opop_defaults.json → api_post_json_url или OPOP_API_POST_JSON_URL)."

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.status and resp.status >= 400:
                return False, f"HTTP {resp.status}: {raw[:500]}"
            return True, raw[:500] if raw else "OK"
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        return False, f"HTTP {e.code}: {detail or e.reason}"
    except URLError as e:
        return False, str(e.reason if hasattr(e, "reason") else e)


def save_and_post_export(
    opop_data: dict[str, Any],
    job_dir: Path,
    *,
    defaults_path: Path | None = None,
) -> tuple[Path, bool, str]:
    payload = build_api_export_payload(opop_data)
    export_path = job_dir / "api_export.json"
    export_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    url = resolve_api_post_url(defaults_path)
    ok, message = post_api_export_payload(payload, url)
    return export_path, ok, message
