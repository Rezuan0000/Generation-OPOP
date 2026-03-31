from __future__ import annotations

import json
import secrets
import shutil
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for

from generate_opop import generate_opop_document
from opop_data_extractor import ExtractParams, build_opop_data
from sql_processor import SQLProcessor


APP_ROOT = Path(__file__).resolve().parent
INSTANCE_DIR = APP_ROOT / "instance"
UPLOADS_DIR = INSTANCE_DIR / "uploads"
RESULTS_DIR = INSTANCE_DIR / "results"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_old_dirs(base: Path, *, older_than_hours: int = 12) -> None:
    if not base.exists():
        return
    cutoff = _now_utc() - timedelta(hours=older_than_hours)
    for p in base.iterdir():
        try:
            if not p.is_dir():
                continue
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            continue


def _secure_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "upload.sql"
    for ch in ('"', "'", "\\", "/", ":", "*", "?", "<", ">", "|"):
        name = name.replace(ch, "_")
    return name[:180]


def _load_db_from_sql(structure_sql_path: Path, data_sql_path: Path) -> SQLProcessor:
    processor = SQLProcessor()
    ok, msg = processor.load_sql_file(str(structure_sql_path))
    if not ok:
        processor.close()
        raise RuntimeError(f"Не удалось загрузить структуру SQL: {msg}")
    ok, msg = processor.load_sql_file(str(data_sql_path))
    if not ok:
        processor.close()
        raise RuntimeError(f"Не удалось загрузить данные SQL: {msg}")
    return processor


def _get_options(structure_sql_path: Path, data_sql_path: Path) -> dict[str, Any]:
    processor = _load_db_from_sql(structure_sql_path, data_sql_path)
    cur = processor.conn.cursor()
    try:
        cur.execute("SELECT id, title FROM edu_levels ORDER BY id")
        levels = [{"id": int(r[0]), "title": str(r[1])} for r in (cur.fetchall() or [])]

        cur.execute(
            """
            SELECT edu_level_id, code, title, profile
            FROM speciality
            ORDER BY edu_level_id, code
            """
        )
        dirs_by_level: dict[int, list[dict[str, str]]] = {}
        for r in cur.fetchall() or []:
            lvl = int(r[0])
            dirs_by_level.setdefault(lvl, []).append(
                {
                    "code": str(r[1]),
                    "title": str(r[2]),
                    "profile": str(r[3] or ""),
                }
            )
        return {"levels": levels, "dirs_by_level": dirs_by_level}
    finally:
        processor.close()


def _job_dir(job_id: str) -> Path:
    return RESULTS_DIR / job_id


def _upload_dir(upload_id: str) -> Path:
    return UPLOADS_DIR / upload_id


def create_app() -> Flask:
    _ensure_dirs()
    _cleanup_old_dirs(UPLOADS_DIR, older_than_hours=12)
    _cleanup_old_dirs(RESULTS_DIR, older_than_hours=24)

    app = Flask(__name__, instance_relative_config=True)
    app.secret_key = secrets.token_hex(32)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.post("/upload")
    def upload():
        structure = request.files.get("sql_structure")
        data = request.files.get("sql_content")
        if not structure or not data:
            flash("Нужно загрузить два файла: структуру и данные (SQL).", "danger")
            return redirect(url_for("index"))

        upload_id = str(uuid.uuid4())
        udir = _upload_dir(upload_id)
        udir.mkdir(parents=True, exist_ok=True)

        structure_name = _secure_filename(structure.filename or "structure.sql")
        data_name = _secure_filename(data.filename or "data.sql")

        structure_path = udir / structure_name
        data_path = udir / data_name
        structure.save(structure_path)
        data.save(data_path)

        meta = {
            "upload_id": upload_id,
            "structure_path": str(structure_path),
            "data_path": str(data_path),
            "uploaded_at": _now_utc().isoformat(),
        }
        (udir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return redirect(url_for("select_params", upload_id=upload_id))

    @app.get("/select/<upload_id>")
    def select_params(upload_id: str):
        udir = _upload_dir(upload_id)
        meta_path = udir / "meta.json"
        if not meta_path.exists():
            abort(404)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        structure_path = Path(meta["structure_path"])
        data_path = Path(meta["data_path"])

        try:
            options = _get_options(structure_path, data_path)
        except Exception as e:
            flash(f"Ошибка при чтении SQL для формирования списков: {e}", "danger")
            return redirect(url_for("index"))

        return render_template(
            "select.html",
            upload_id=upload_id,
            levels=options["levels"],
            dirs_by_level=options["dirs_by_level"],
            default_year=2023,
        )

    @app.post("/generate/<upload_id>")
    def generate(upload_id: str):
        udir = _upload_dir(upload_id)
        meta_path = udir / "meta.json"
        if not meta_path.exists():
            abort(404)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        structure_path = Path(meta["structure_path"])
        data_path = Path(meta["data_path"])

        try:
            year = int(request.form.get("year", "2023"))
            edu_level_id = int(request.form.get("edu_level_id", "1"))
            speciality_code = str(request.form.get("speciality_code", "")).strip()
        except Exception:
            flash("Некорректные параметры формы.", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))

        if not speciality_code:
            flash("Выберите направление (код).", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))

        template_path = APP_ROOT / "template.docx"
        if not template_path.exists():
            flash(
                "Не найден `template.docx` в корне проекта. Добавьте шаблон и повторите.",
                "danger",
            )
            return redirect(url_for("select_params", upload_id=upload_id))

        job_id = str(uuid.uuid4())
        jdir = _job_dir(job_id)
        jdir.mkdir(parents=True, exist_ok=True)

        json_path = jdir / "opop_data.json"
        docx_path = jdir / "ОПОП.docx"

        try:
            opop_data = build_opop_data(
                str(structure_path),
                str(data_path),
                params=ExtractParams(year=year, speciality_code=speciality_code, edu_level_id=edu_level_id),
            )
            json_path.write_text(json.dumps(opop_data, ensure_ascii=False, indent=2), encoding="utf-8")

            generate_opop_document(
                template_path=template_path,
                data_path=json_path,
                output_path=docx_path,
            )
        except Exception as e:
            flash(f"Ошибка генерации: {e}", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))

        job_meta = {
            "job_id": job_id,
            "upload_id": upload_id,
            "created_at": _now_utc().isoformat(),
            "params": asdict(ExtractParams(year=year, speciality_code=speciality_code, edu_level_id=edu_level_id)),
            "json_path": str(json_path),
            "docx_path": str(docx_path),
        }
        (jdir / "meta.json").write_text(json.dumps(job_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return redirect(url_for("preview", job_id=job_id))

    @app.get("/preview/<job_id>")
    def preview(job_id: str):
        jdir = _job_dir(job_id)
        meta_path = jdir / "meta.json"
        if not meta_path.exists():
            abort(404)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        json_path = Path(meta["json_path"])
        docx_path = Path(meta["docx_path"])
        if not json_path.exists() or not docx_path.exists():
            abort(404)

        opop_data = json.loads(json_path.read_text(encoding="utf-8"))
        return render_template("preview.html", job_id=job_id, opop_data=opop_data, params=meta["params"])

    @app.get("/download/<job_id>")
    def download(job_id: str):
        jdir = _job_dir(job_id)
        meta_path = jdir / "meta.json"
        if not meta_path.exists():
            abort(404)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        docx_path = Path(meta["docx_path"])
        if not docx_path.exists():
            abort(404)
        return send_file(docx_path, as_attachment=True, download_name=docx_path.name)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=5000)

