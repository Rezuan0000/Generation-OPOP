from __future__ import annotations

import html as html_lib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pypandoc
import pytinytex
from flask import Flask, abort, flash, redirect, render_template, request, send_file, url_for


# Совпадает с generate_opop.MANUAL_PLACEHOLDER_RE (для подстановки textarea в HTML).
_MANUAL_HTML_RE = re.compile(r"\{\{MANUAL:([a-zA-Z0-9_]+)\}\}")


def _inject_manual_fields_into_html(html: str, manual_fields: dict[str, str]) -> str:
    """Заменяет в HTML текстовые {{MANUAL:key}} на поля ввода."""

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = manual_fields.get(key, "") or ""
        esc = html_lib.escape(val)
        return (
            f'<textarea class="form-control manual-field my-1" name="manual_{key}" '
            f'rows="8" style="width:100%;max-width:100%;">{esc}</textarea>'
        )

    return _MANUAL_HTML_RE.sub(repl, html)

from generate_opop import generate_opop_document, scan_manual_template_keys
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


def _convert_docx_to_html(docx_path: Path, html_path: Path) -> None:
    """
    Конвертирует сгенерированный .docx в HTML для предпросмотра.
    """
    try:
        # Встраиваем изображения/ресурсы прямо в HTML, чтобы они корректно отображались в браузере.
        html = pypandoc.convert_file(
            str(docx_path),
            to="html5",
            format="docx",
            extra_args=["--embed-resources"],
        )
    except OSError as e:
        raise RuntimeError(
            "Не удалось выполнить конвертацию через pypandoc. "
            "Установите Pandoc (https://pandoc.org/installing.html) или настройте его путь."
        ) from e
    except RuntimeError as e:
        raise RuntimeError(f"Ошибка конвертации DOCX в HTML: {e}") from e

    html_path.write_text(html, encoding="utf-8")


def _convert_docx_to_pdf(docx_path: Path, pdf_path: Path) -> None:
    """
    Конвертирует .docx в PDF для максимально точного предпросмотра в браузере.
    (Может требовать доп. окружение для PDF-движка, поэтому ошибки подавляются на уровне вызова.)
    """
    # 1) Сначала пробуем pandoc + pdflatex (если движок доступен через TinyTeX).
    pandoc_error: Exception | None = None
    try:
        try:
            pdflatex_path = str(pytinytex.get_engine("pdflatex"))
            tinytex_bin = str(Path(pdflatex_path).parent)
        except Exception:
            pdflatex_path = ""
            tinytex_bin = ""

        extra_args = []
        if pdflatex_path:
            extra_args = [f"--pdf-engine={pdflatex_path}"]

        old_path = os.environ.get("PATH", "")
        try:
            if tinytex_bin:
                os.environ["PATH"] = f"{tinytex_bin}{os.pathsep}{old_path}"
            pypandoc.convert_file(
                str(docx_path),
                to="pdf",
                format="docx",
                outputfile=str(pdf_path),
                extra_args=extra_args,
            )
            return
        finally:
            os.environ["PATH"] = old_path
    except Exception as e:
        pandoc_error = e

    # 2) На Windows fallback через Word (docx2pdf), чтобы предпросмотр работал даже без LaTeX.
    if os.name == "nt":
        try:
            from docx2pdf import convert as docx2pdf_convert

            docx2pdf_convert(str(docx_path), str(pdf_path))
            return
        except Exception as e:
            word_hint = (
                " Для fallback через docx2pdf на Windows нужен установленный и зарегистрированный "
                "Microsoft Word (COM Automation). Если Word установлен, попробуйте открыть его один раз "
                "вручную и выполнить восстановление Office."
            )
            docx2pdf_error = e
    else:
        docx2pdf_error = None

    # 3) Fallback через LibreOffice (soffice --headless).
    # Работает на Windows/Linux/macOS при установленном LibreOffice.
    soffice = shutil.which("soffice") or shutil.which("soffice.com")
    if not soffice and os.name == "nt":
        # Частые пути установки LibreOffice на Windows
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "LibreOffice"
            / "program"
            / "soffice.com",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "LibreOffice"
            / "program"
            / "soffice.com",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "LibreOffice"
            / "program"
            / "soffice.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "LibreOffice"
            / "program"
            / "soffice.exe",
        ]
        for c in candidates:
            if c.exists():
                soffice = str(c)
                break

    if soffice:
        with tempfile.TemporaryDirectory(prefix="opop_pdf_") as tmpdir:
            outdir = Path(tmpdir)
            cmd = [
                soffice,
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(docx_path),
            ]
            # LibreOffice пишет вывод в stdout/stderr, иногда долго стартует — дадим запас по времени.
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if proc.returncode == 0:
                produced = outdir / (docx_path.stem + ".pdf")
                if produced.exists():
                    pdf_path.parent.mkdir(parents=True, exist_ok=True)
                    if pdf_path.exists():
                        pdf_path.unlink()
                    # Path.replace() не умеет перенос между дисками на Windows (C: -> E:),
                    # поэтому используем shutil.move().
                    shutil.move(str(produced), str(pdf_path))
                    return
            lo_err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(
                "LibreOffice не смог конвертировать DOCX в PDF. "
                f"code={proc.returncode}. details={lo_err[:800]}"
            )

    lo_hint = (
        " Установите LibreOffice и убедитесь, что `soffice` доступен в PATH "
        "или установлен в стандартную папку (Program Files)."
    )
    if os.name == "nt":
        raise RuntimeError(
            "Ошибка конвертации DOCX в PDF. "
            f"Pandoc: {pandoc_error}. "
            f"Fallback docx2pdf: {docx2pdf_error}.{word_hint if docx2pdf_error else ''} "
            f"Fallback LibreOffice: soffice not found.{lo_hint}"
        )

    raise RuntimeError(f"Ошибка конвертации DOCX в PDF: {pandoc_error}")


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
        draft_docx_path = jdir / "document_draft.docx"
        docx_path = jdir / "ОПОП.docx"
        html_preview_path = jdir / "preview.html"
        edit_preview_path = jdir / "edit_preview.html"
        pdf_preview_path = jdir / "preview.pdf"

        try:
            opop_data = build_opop_data(
                str(structure_path),
                str(data_path),
                params=ExtractParams(year=year, speciality_code=speciality_code, edu_level_id=edu_level_id),
            )
            manual_keys = scan_manual_template_keys(template_path)
            mf: dict[str, str] = {}
            if isinstance(opop_data.get("manual_fields"), dict):
                mf = {str(k): str(v or "") for k, v in opop_data["manual_fields"].items()}
            for k in manual_keys:
                mf.setdefault(k, "")
            opop_data["manual_fields"] = mf
            json_path.write_text(json.dumps(opop_data, ensure_ascii=False, indent=2), encoding="utf-8")

            if not manual_keys:
                # Нет ручных меток — сразу финальный документ и предпросмотр.
                generate_opop_document(
                    template_path=template_path,
                    data_path=json_path,
                    output_path=docx_path,
                    skip_manual_replace=False,
                )
                _convert_docx_to_html(docx_path, html_preview_path)
                pdf_error: str | None = None
                try:
                    _convert_docx_to_pdf(docx_path, pdf_preview_path)
                except Exception as e:
                    pdf_error = str(e)
                job_meta = {
                    "job_id": job_id,
                    "upload_id": upload_id,
                    "created_at": _now_utc().isoformat(),
                    "params": asdict(
                        ExtractParams(year=year, speciality_code=speciality_code, edu_level_id=edu_level_id)
                    ),
                    "json_path": str(json_path),
                    "draft_docx_path": str(draft_docx_path),
                    "docx_path": str(docx_path),
                    "html_preview_path": str(html_preview_path),
                    "edit_preview_path": str(edit_preview_path),
                    "pdf_preview_path": str(pdf_preview_path),
                    "pdf_error": pdf_error,
                    "manual_keys": manual_keys,
                    "stage": "final",
                }
                (jdir / "meta.json").write_text(json.dumps(job_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                return redirect(url_for("preview", job_id=job_id))

            generate_opop_document(
                template_path=template_path,
                data_path=json_path,
                output_path=draft_docx_path,
                skip_manual_replace=True,
            )
            raw_html_path = jdir / "draft_raw.html"
            _convert_docx_to_html(draft_docx_path, raw_html_path)
            raw_html = raw_html_path.read_text(encoding="utf-8")
            injected = _inject_manual_fields_into_html(raw_html, mf)
            edit_preview_path.write_text(injected, encoding="utf-8")
            try:
                raw_html_path.unlink(missing_ok=True)
            except OSError:
                pass

            job_meta = {
                "job_id": job_id,
                "upload_id": upload_id,
                "created_at": _now_utc().isoformat(),
                "params": asdict(
                    ExtractParams(year=year, speciality_code=speciality_code, edu_level_id=edu_level_id)
                ),
                "json_path": str(json_path),
                "draft_docx_path": str(draft_docx_path),
                "docx_path": str(docx_path),
                "html_preview_path": str(html_preview_path),
                "edit_preview_path": str(edit_preview_path),
                "pdf_preview_path": str(pdf_preview_path),
                "pdf_error": None,
                "manual_keys": manual_keys,
                "stage": "edit",
            }
            (jdir / "meta.json").write_text(json.dumps(job_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as e:
            flash(f"Ошибка генерации: {e}", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))

        return redirect(url_for("edit_manual", job_id=job_id))

    def _load_job_meta(job_id: str) -> dict[str, Any]:
        jdir = _job_dir(job_id)
        meta_path = jdir / "meta.json"
        if not meta_path.exists():
            abort(404)
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _save_manual_from_form(opop_data: dict[str, Any], manual_keys: list[str]) -> None:
        mf = opop_data.get("manual_fields")
        if not isinstance(mf, dict):
            mf = {}
        # 1) Сохраняем все поля, реально пришедшие из формы.
        # Это защищает от кейса, когда scan_manual_template_keys() пропустил
        # часть {{MANUAL:...}} из-за разбиения метки Word-раном.
        prefix = "manual_"
        for form_key in request.form.keys():
            if not form_key.startswith(prefix):
                continue
            manual_key = form_key[len(prefix) :]
            if not manual_key:
                continue
            mf[manual_key] = request.form.get(form_key, "") or ""

        # 2) Для заранее найденных ключей гарантируем наличие значения.
        for k in manual_keys:
            mf.setdefault(k, request.form.get(f"manual_{k}", "") or "")
        opop_data["manual_fields"] = mf

    @app.get("/edit/<job_id>")
    def edit_manual(job_id: str):
        meta = _load_job_meta(job_id)
        if meta.get("stage") != "edit":
            return redirect(url_for("preview", job_id=job_id))
        jdir = _job_dir(job_id)
        edit_path = Path(meta.get("edit_preview_path", ""))
        if not edit_path.exists():
            abort(404)
        preview_html = edit_path.read_text(encoding="utf-8")
        return render_template(
            "edit.html",
            job_id=job_id,
            params=meta["params"],
            preview_html=preview_html,
            manual_keys=meta.get("manual_keys", []),
        )

    @app.post("/edit/<job_id>")
    def edit_manual_post(job_id: str):
        meta = _load_job_meta(job_id)
        if meta.get("stage") != "edit":
            return redirect(url_for("preview", job_id=job_id))
        jdir = _job_dir(job_id)
        json_path = Path(meta["json_path"])
        template_path = APP_ROOT / "template.docx"
        manual_keys = list(meta.get("manual_keys", []))
        opop_data = json.loads(json_path.read_text(encoding="utf-8"))
        _save_manual_from_form(opop_data, manual_keys)
        json_path.write_text(json.dumps(opop_data, ensure_ascii=False, indent=2), encoding="utf-8")

        action = (request.form.get("action") or "finalize").strip()
        mf = opop_data.get("manual_fields", {})
        if not isinstance(mf, dict):
            mf = {}
        mf_str = {str(k): str(v or "") for k, v in mf.items()}

        if action == "preview":
            draft_docx = Path(meta["draft_docx_path"])
            raw_html_path = jdir / "draft_raw.html"
            _convert_docx_to_html(draft_docx, raw_html_path)
            raw_html = raw_html_path.read_text(encoding="utf-8")
            injected = _inject_manual_fields_into_html(raw_html, mf_str)
            edit_preview_path = Path(meta["edit_preview_path"])
            edit_preview_path.write_text(injected, encoding="utf-8")
            try:
                raw_html_path.unlink(missing_ok=True)
            except OSError:
                pass
            flash("Предпросмотр обновлён по введённому тексту.", "success")
            return redirect(url_for("edit_manual", job_id=job_id))

        # finalize
        docx_path = Path(meta["docx_path"])
        html_preview_path = Path(meta["html_preview_path"])
        pdf_preview_path = Path(meta["pdf_preview_path"])
        try:
            generate_opop_document(
                template_path=template_path,
                data_path=json_path,
                output_path=docx_path,
                skip_manual_replace=False,
            )
            _convert_docx_to_html(docx_path, html_preview_path)
            try:
                pdf_preview_path.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as e:
            flash(f"Ошибка при создании документа: {e}", "danger")
            return redirect(url_for("edit_manual", job_id=job_id))

        meta["stage"] = "final"
        meta["pdf_error"] = None
        (jdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        flash("Документ сформирован. При необходимости создайте PDF отдельной кнопкой.", "success")
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
        html_preview_path = Path(meta.get("html_preview_path", ""))
        pdf_preview_path = Path(meta.get("pdf_preview_path", ""))
        if meta.get("stage") == "edit":
            return redirect(url_for("edit_manual", job_id=job_id))

        if not json_path.exists() or not docx_path.exists():
            abort(404)

        opop_data = json.loads(json_path.read_text(encoding="utf-8"))
        preview_html = ""
        if html_preview_path.exists():
            preview_html = html_preview_path.read_text(encoding="utf-8")

        return render_template(
            "preview.html",
            job_id=job_id,
            opop_data=opop_data,
            params=meta["params"],
            preview_html=preview_html,
            has_pdf_preview=pdf_preview_path.exists(),
            pdf_error=meta.get("pdf_error"),
            stage=meta.get("stage", "final"),
        )

    @app.post("/build-pdf/<job_id>")
    def build_pdf(job_id: str):
        jdir = _job_dir(job_id)
        meta = _load_job_meta(job_id)
        if meta.get("stage") != "final":
            flash("Сначала завершите ввод текста и сформируйте документ.", "warning")
            return redirect(url_for("edit_manual", job_id=job_id))
        docx_path = Path(meta["docx_path"])
        pdf_preview_path = Path(meta.get("pdf_preview_path", str(jdir / "preview.pdf")))
        if not docx_path.exists():
            abort(404)
        try:
            _convert_docx_to_pdf(docx_path, pdf_preview_path)
            meta["pdf_error"] = None
            meta["pdf_preview_path"] = str(pdf_preview_path)
        except Exception as e:
            meta["pdf_error"] = str(e)
        (jdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        if meta.get("pdf_error"):
            flash(f"Не удалось создать PDF: {meta['pdf_error']}", "danger")
        else:
            flash("PDF создан.", "success")
        return redirect(url_for("preview", job_id=job_id))

    @app.get("/preview-pdf/<job_id>")
    def preview_pdf(job_id: str):
        jdir = _job_dir(job_id)
        meta = _load_job_meta(job_id)
        if meta.get("stage") != "final":
            abort(404)
        pdf_preview_path = Path(meta.get("pdf_preview_path", str(jdir / "preview.pdf")))
        if not pdf_preview_path.exists():
            abort(404)
        return send_file(pdf_preview_path, mimetype="application/pdf", as_attachment=False)

    @app.get("/download/<job_id>")
    def download(job_id: str):
        jdir = _job_dir(job_id)
        meta = _load_job_meta(job_id)
        if meta.get("stage") != "final":
            flash("Сначала завершите ввод и сформируйте итоговый документ.", "warning")
            return redirect(url_for("edit_manual", job_id=job_id))
        docx_path = Path(meta["docx_path"])
        if not docx_path.exists():
            abort(404)
        return send_file(docx_path, as_attachment=True, download_name=docx_path.name)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=False, host="127.0.0.1", port=5000)

