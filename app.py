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


def _is_multirow_manual_key(key: str) -> bool:
    """
    Ключи табличного ручного ввода, для которых в UI даём режим +/-
    (каждый input = отдельная строка таблицы).
    """
    return bool(re.fullmatch(r"(?:ps|uk|opk|pk)_[a-zA-Z0-9_]+", key))


def _inject_manual_fields_into_html(html: str, manual_fields: dict[str, str]) -> str:
    """Заменяет в HTML текстовые {{MANUAL:key}} на поля ввода."""

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = manual_fields.get(key, "") or ""
        # Для табличных ключей удобнее вводить построчно: каждая строка ввода
        # превращается в отдельную строку таблицы
        # (см. generate_opop._expand_manual_rows_in_tables).
        if _is_multirow_manual_key(key):
            lines = val.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            if not lines:
                lines = [""]

            rows_html: list[str] = []
            for line in lines:
                esc_line = html_lib.escape(line)
                rows_html.append(
                    "<div class=\"manual-multi-row d-flex gap-1 align-items-start my-1\">"
                    f"<input class=\"form-control manual-field manual-field-line\" "
                    f"name=\"manual_{key}\" value=\"{esc_line}\" "
                    "style=\"min-width: 14rem;\" />"
                    "<button class=\"btn btn-outline-secondary btn-sm manual-add-line\" "
                    "type=\"button\" title=\"Добавить строку\">+</button>"
                    "<button class=\"btn btn-outline-danger btn-sm manual-remove-line\" "
                    "type=\"button\" title=\"Удалить строку\">−</button>"
                    "</div>"
                )

            return (
                f"<div class=\"manual-multi\" data-manual-key=\"{html_lib.escape(key)}\">"
                + "".join(rows_html)
                + "</div>"
            )

        esc = html_lib.escape(val)
        return (
            f'<textarea class="form-control manual-field my-1" name="manual_{key}" '
            f'rows="8" style="width:100%;max-width:100%;">{esc}</textarea>'
        )

    return _MANUAL_HTML_RE.sub(repl, html)

from api_export import save_and_post_export
from generate_opop import generate_opop_document, scan_manual_template_keys, _sanitize_xml_text
from json_data_extractor import (
    ExtractParams,
    build_opop_data,
    fetch_db_json,
    get_specialities,
    load_db_json_file,
    resolve_api_get_json_url,
)


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
        return "db.json"
    for ch in ('"', "'", "\\", "/", ":", "*", "?", "<", ">", "|"):
        name = name.replace(ch, "_")
    return name[:180]


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
        json_url = resolve_api_get_json_url(APP_ROOT / "opop_defaults.json")
        if not json_url:
            flash(
                "URL загрузки данных не задан (opop_defaults.json → api_get_json_url "
                "или OPOP_API_GET_JSON_URL).",
                "danger",
            )
            return redirect(url_for("index"))

        upload_id = str(uuid.uuid4())
        udir = _upload_dir(upload_id)
        udir.mkdir(parents=True, exist_ok=True)

        try:
            payload = fetch_db_json(json_url, method="GET")
        except Exception as e:
            shutil.rmtree(udir, ignore_errors=True)
            flash(f"Не удалось загрузить данные: {e}", "danger")
            return redirect(url_for("index"))

        json_path = udir / "db.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        specialities = get_specialities(payload)
        if not specialities:
            shutil.rmtree(udir, ignore_errors=True)
            flash("В JSON не найдены направления подготовки (таблица speciality / title_plan).", "danger")
            return redirect(url_for("index"))

        meta = {
            "upload_id": upload_id,
            "json_path": str(json_path),
            "source_kind": "api",
            "source_ref": "get_json.php",
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
        source_json_path = Path(meta["json_path"])
        try:
            payload = load_db_json_file(source_json_path)
            specialities = get_specialities(payload)
        except Exception as e:
            flash(f"Ошибка при чтении JSON для формирования списка направлений: {e}", "danger")
            return redirect(url_for("index"))
        return render_template(
            "select.html",
            upload_id=upload_id,
            specialities=specialities,
            default_year=2023,
        )

    @app.post("/generate/<upload_id>")
    def generate(upload_id: str):
        udir = _upload_dir(upload_id)
        meta_path = udir / "meta.json"
        if not meta_path.exists():
            abort(404)
        upload_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source_json_path = Path(upload_meta["json_path"])

        try:
            year = int(request.form.get("year", "2023"))
            speciality_id = int(request.form.get("speciality_id", "0"))
        except Exception:
            flash("Некорректные параметры формы.", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))
        if speciality_id <= 0:
            flash("Выберите направление подготовки.", "danger")
            return redirect(url_for("select_params", upload_id=upload_id))

        extract_params = ExtractParams(speciality_id=speciality_id, year=year)
        job_params_dict = asdict(extract_params)

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
            payload = load_db_json_file(source_json_path)
            opop_data = build_opop_data(payload, params=extract_params)
            manual_keys = scan_manual_template_keys(template_path)
            mf: dict[str, str] = {}
            if isinstance(opop_data.get("manual_fields"), dict):
                mf = {str(k): str(v or "") for k, v in opop_data["manual_fields"].items()}
            seed = opop_data.get("_manual_fields_seed")
            if not isinstance(seed, dict):
                seed = {}
            for k in manual_keys:
                mf.setdefault(k, str(seed.get(k, "") or ""))
            opop_data["manual_fields"] = mf
            json_path.write_text(json.dumps(opop_data, ensure_ascii=False, indent=2), encoding="utf-8")

            if not manual_keys:
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
                    "params": job_params_dict,
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
                "params": job_params_dict,
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
            # Поддерживаем множественные значения одного и того же ключа (getlist),
            # которые UI может отправить при "добавлении строк" в таблицах.
            vals = request.form.getlist(form_key)
            if len(vals) > 1:
                raw = "\n".join((v or "") for v in vals)
            else:
                raw = request.form.get(form_key, "") or ""
            mf[manual_key] = _sanitize_xml_text(raw)

        # 2) Для заранее найденных ключей гарантируем наличие значения.
        for k in manual_keys:
            if k in mf:
                continue
            vals = request.form.getlist(f"manual_{k}")
            if len(vals) > 1:
                raw = "\n".join((v or "") for v in vals)
            else:
                raw = request.form.get(f"manual_{k}", "") or ""
            mf[k] = _sanitize_xml_text(raw)
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

        try:
            export_path, api_ok, api_message = save_and_post_export(
                opop_data, jdir, defaults_path=APP_ROOT / "opop_defaults.json"
            )
            meta["api_export_path"] = str(export_path)
            meta["api_export_ok"] = api_ok
            meta["api_export_message"] = api_message
        except Exception as e:
            meta["api_export_ok"] = False
            meta["api_export_message"] = str(e)

        meta["stage"] = "final"
        meta["pdf_error"] = None
        (jdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        if meta.get("api_export_ok"):
            flash("Документ сохранён. Данные отправлены в API.", "success")
        elif meta.get("api_export_message"):
            flash(
                f"Документ сохранён, но отправка в API не выполнена: {meta.get('api_export_message')}",
                "warning",
            )
        else:
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

        missing_fields = opop_data.get("_missing_fields")
        if not isinstance(missing_fields, list):
            missing_fields = []

        return render_template(
            "preview.html",
            job_id=job_id,
            opop_data=opop_data,
            params=meta["params"],
            missing_fields=missing_fields,
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

