"""Run-scoped HTTP workspace over the existing repository and audit reports."""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import Response

from workspace_models import (
    DocumentDTO,
    DocumentPatch,
    FormatDTO,
    ProjectCreate,
    ProjectDTO,
    ProjectUpdate,
    RowsDTO,
    RunDTO,
    StructureDTO,
    SummaryDTO,
    VersionDeletedDTO,
    VersionDTO,
    VersionMetadataPatch,
    WorkspaceDTO,
)
from workspace_service import (
    inputs_for_run,
    present_results,
    run_progress,
    sheet_window,
    source_evidence,
)


def workspace_router(get_context) -> APIRouter:
    from api import (
        ApiError,
        _load_run_record,
        _parse_uuid,
        _require_api_token,
        _require_configured,
    )

    def guarded(request: Request, context=Depends(get_context)):
        _require_api_token(context, request)
        _require_configured(context)
        return context

    router = APIRouter()

    def project(context, value):
        try:
            return context.repository.load_project(
                _parse_uuid(value, field="project_id")
            )
        except KeyError as exc:
            raise ApiError(404, "project_not_found", "Проект не найден") from exc

    def version(context, value):
        try:
            return context.repository.load_version(
                _parse_uuid(value, field="version_id")
            )
        except KeyError as exc:
            raise ApiError(
                404, "version_not_found", "Версия документа не найдена"
            ) from exc

    def terminal(context, run_id):
        record = _load_run_record(context, _parse_uuid(run_id, field="run_id"))
        if record["status"] not in {"done", "failed"}:
            raise ApiError(409, "audit_not_finished", "Аудит ещё выполняется")
        return record

    @router.get("/api/v1/projects", response_model=list[ProjectDTO])
    def projects(archived: bool = Query(False), context=Depends(guarded)):
        return context.repository.list_projects(archived=archived)

    @router.post("/api/v1/projects", response_model=ProjectDTO, status_code=201)
    def create_project(payload: ProjectCreate, context=Depends(guarded)):
        name = payload.name.strip()
        if not name:
            raise ApiError(400, "project_required", "Укажите название проекта")
        # Independent UUID per call: duplicate names never merge.
        value = context.repository.create_project(name)
        return {
            "id": str(value.id),
            "name": value.name,
            "archived": value.archived,
            "created_at": value.created_at,
        }

    @router.get("/api/v1/projects/{project_id}", response_model=ProjectDTO)
    def get_project(project_id: str, context=Depends(guarded)):
        return {
            "id": str(project(context, project_id).id),
            "name": project(context, project_id).name,
            "archived": project(context, project_id).archived,
            "created_at": project(context, project_id).created_at,
        }

    @router.patch("/api/v1/projects/{project_id}", response_model=ProjectDTO)
    def update_project(
        project_id: str, payload: ProjectUpdate, context=Depends(guarded)
    ):
        if payload.name is not None and not payload.name.strip():
            raise ApiError(400, "project_required", "Укажите название проекта")
        try:
            _, presented = context.repository.update_project(
                _parse_uuid(project_id, field="project_id"),
                name=(payload.name.strip() if payload.name is not None else None),
                archived=payload.archived,
            )
        except KeyError as exc:
            raise ApiError(404, "project_not_found", "Проект не найден") from exc
        except ValueError as exc:
            raise ApiError(400, "project_invalid", str(exc)) from exc
        return presented

    @router.delete("/api/v1/projects/{project_id}", response_model=ProjectDTO)
    def delete_project(project_id: str, context=Depends(guarded)):
        try:
            row = project(context, project_id)
            context.repository.delete_project(row.id)
        except KeyError as exc:
            raise ApiError(404, "project_not_found", "Проект не найден") from exc
        except LookupError as exc:
            raise ApiError(409, "project_in_use", str(exc)) from exc
        return {
            "id": str(row.id),
            "name": row.name,
            "archived": row.archived,
            "created_at": row.created_at,
        }

    @router.get(
        "/api/v1/projects/{project_id}/documents", response_model=list[VersionDTO]
    )
    def documents(project_id: str, context=Depends(guarded)):
        return context.repository.list_versions(project(context, project_id).id)

    def _enrich_last_run(context, document: dict) -> dict:
        last = dict(document.get("last_run") or {})
        if not last.get("run_id"):
            return document
        try:
            records = context.repository.run_progress_records(
                run_id=_parse_uuid(str(last["run_id"]), field="run_id")
            )
        except Exception:
            return document
        if not records:
            return document
        enriched = dict(document)
        enriched["last_run"] = run_progress(context, records[0])
        return enriched

    @router.get(
        "/api/v1/projects/{project_id}/catalog", response_model=list[DocumentDTO]
    )
    def catalog(
        project_id: str, archived: bool = Query(False), context=Depends(guarded)
    ):
        try:
            documents = context.repository.catalog(
                project(context, project_id).id, archived=archived
            )
        except KeyError as exc:
            raise ApiError(404, "project_not_found", "Проект не найден") from exc
        return [_enrich_last_run(context, document) for document in documents]

    def _document_or_404(context, document_id: str) -> dict:
        try:
            return context.repository.load_document(
                _parse_uuid(document_id, field="document_id")
            )
        except KeyError as exc:
            raise ApiError(404, "document_not_found", "Документ не найден") from exc

    @router.get("/api/v1/documents/{document_id}/detail", response_model=DocumentDTO)
    def document_detail(document_id: str, context=Depends(guarded)):
        return _enrich_last_run(context, _document_or_404(context, document_id))

    @router.patch("/api/v1/documents/{document_id}", response_model=DocumentDTO)
    def update_document(
        document_id: str, payload: DocumentPatch, context=Depends(guarded)
    ):
        if payload.title is not None and not payload.title.strip():
            raise ApiError(400, "document_invalid", "Название не может быть пустым")
        try:
            current_id = (
                _parse_uuid(payload.current_version_id, field="current_version_id")
                if payload.current_version_id
                else ...
            )
            updated = context.repository.update_document(
                _parse_uuid(document_id, field="document_id"),
                title=(payload.title.strip() if payload.title is not None else None),
                archived=payload.archived,
                current_version_id=current_id,
            )
            return _enrich_last_run(context, updated)
        except KeyError as exc:
            raise ApiError(404, "document_not_found", "Документ не найден") from exc
        except ValueError as exc:
            raise ApiError(400, "document_invalid", str(exc)) from exc

    @router.delete("/api/v1/documents/{document_id}/detail", response_model=DocumentDTO)
    def delete_document(document_id: str, context=Depends(guarded)):
        try:
            row = _enrich_last_run(context, _document_or_404(context, document_id))
            from uuid import UUID as _UUID

            context.repository.delete_document(_UUID(str(row["id"])))
        except KeyError as exc:
            raise ApiError(404, "document_not_found", "Документ не найден") from exc
        except LookupError as exc:
            raise ApiError(409, "document_in_use", str(exc)) from exc
        return row

    @router.patch("/api/v1/documents/{version_id}/metadata", response_model=VersionDTO)
    def update_version_metadata(
        version_id: str, payload: VersionMetadataPatch, context=Depends(guarded)
    ):
        try:
            return context.repository.update_version_metadata(
                _parse_uuid(version_id, field="version_id"),
                dict(payload.fields or {}),
            )
        except KeyError as exc:
            raise ApiError(404, "version_not_found", "Версия не найдена") from exc
        except ValueError as exc:
            raise ApiError(400, "metadata_invalid", str(exc)) from exc

    @router.delete(
        "/api/v1/documents/{version_id}/version", response_model=VersionDeletedDTO
    )
    def delete_version(version_id: str, context=Depends(guarded)):
        try:
            context.repository.delete_version(
                _parse_uuid(version_id, field="version_id")
            )
        except KeyError as exc:
            raise ApiError(404, "version_not_found", "Версия не найдена") from exc
        except LookupError as exc:
            raise ApiError(409, "version_in_use", str(exc)) from exc
        return {"deleted": True}

    @router.get("/api/v1/projects/{project_id}/audits", response_model=list[RunDTO])
    def history(
        project_id: str,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        context=Depends(guarded),
    ):
        runs = context.repository.run_progress_records(
            project_id=project(context, project_id).id,
            offset=offset,
            limit=limit,
        )
        return [run_progress(context, record) for record in runs]

    @router.get("/api/v1/audits/{run_id}/progress", response_model=RunDTO)
    def progress(run_id: str, context=Depends(guarded)):
        records = context.repository.run_progress_records(
            run_id=_parse_uuid(run_id, field="run_id")
        )
        if not records:
            raise ApiError(404, "run_not_found", "Запуск аудита не найден")
        return run_progress(context, records[0])

    @router.get("/api/v1/audits/{run_id}/summary", response_model=SummaryDTO)
    def summary(run_id: str, context=Depends(guarded)):
        record = terminal(context, run_id)
        owner = project(context, str(record["project_id"]))
        ids = {
            str(record["vor_version_id"]),
            *record["config"].get("pdf_versions", {}).values(),
        }
        return {
            "run": run_progress(context, record),
            "project": {"id": str(owner.id), "name": owner.name},
            "queues": dict(
                Counter(row.queue for row in present_results(context, record))
            ),
            "documents": [
                v for v in context.repository.list_versions(owner.id) if v["id"] in ids
            ],
        }

    @router.get("/api/v1/audits/{run_id}/rows", response_model=RowsDTO)
    def rows(
        run_id: str,
        focus: str = Query("all", pattern="^(all|fix|review|missing|ok)$"),
        q: str = Query("", max_length=500),
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=200),
        context=Depends(guarded),
    ):
        records = present_results(context, terminal(context, run_id))
        query = q.strip().casefold()
        records = [
            r
            for r in records
            if (focus == "all" or r.queue == focus)
            and (
                not query
                or query
                in " ".join([r.number, r.name, r.sheet, *r.cells.values()]).casefold()
            )
        ]
        return {
            "run_id": run_id,
            "total": len(records),
            "offset": offset,
            "limit": limit,
            "rows": records[offset : offset + limit],
        }

    @router.get(
        "/api/v1/audits/{run_id}/positions/{position_index}/workspace",
        response_model=WorkspaceDTO,
    )
    def workspace(run_id: str, position_index: int, context=Depends(guarded)):
        record = terminal(context, run_id)
        row = next(
            (
                r
                for r in present_results(context, record)
                if r.position_index == position_index
            ),
            None,
        )
        if row is None:
            raise ApiError(404, "position_not_found", "Позиция не найдена")
        position = next(
            p for p in inputs_for_run(context, record) if p.index == position_index
        )
        vor = version(context, str(record["vor_version_id"]))
        return {
            "row": row,
            "position": position,
            "vor_version_id": str(vor.id),
            "excel": sheet_window(context.blob_store.get(vor.blob_key), position)
            if vor.filename.lower().endswith(".xlsx")
            else None,
            "evidence": source_evidence(context, record, position_index, position),
        }

    @router.get("/api/v1/documents/{version_id}/content")
    def content(
        version_id: str,
        request: Request,
        download: bool = False,
        context=Depends(guarded),
    ):
        ref = version(context, version_id)
        try:
            data = context.blob_store.get(ref.blob_key)
        except FileNotFoundError as exc:
            raise ApiError(404, "blob_missing", "Исходный файл недоступен") from exc
        mime = (
            "application/pdf"
            if ref.kind == "pdf"
            else (
                "text/csv; charset=utf-8"
                if ref.filename.lower().endswith(".csv")
                else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        )
        headers = {
            "Accept-Ranges": "bytes",
            "ETag": f'"{ref.sha256}"',
            "Cache-Control": "private, no-cache",
            "Content-Disposition": f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(ref.filename)}",
        }
        if (
            request.headers.get("if-none-match") == headers["ETag"]
            and "range" not in request.headers
        ):
            return Response(status_code=304, headers=headers)
        requested = request.headers.get("range")
        if (
            requested
            and request.headers.get("if-range", headers["ETag"]) == headers["ETag"]
        ):
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return Response(
                    status_code=416,
                    headers={**headers, "Content-Range": f"bytes */{len(data)}"},
                )
            first, last = match.groups()
            start = int(first) if first else max(0, len(data) - int(last))
            end = min(int(last), len(data) - 1) if first and last else len(data) - 1
            if start >= len(data) or start > end:
                return Response(
                    status_code=416,
                    headers={**headers, "Content-Range": f"bytes */{len(data)}"},
                )
            headers["Content-Range"] = f"bytes {start}-{end}/{len(data)}"
            return Response(
                data[start : end + 1], status_code=206, media_type=mime, headers=headers
            )
        return Response(data, media_type=mime, headers=headers)

    @router.get("/api/v1/documents/{version_id}/structure", response_model=StructureDTO)
    def structure(version_id: str, context=Depends(guarded)):
        import fitz

        from document_structure import build_structure, native_records

        ref = version(context, version_id)
        if ref.kind != "pdf":
            raise ApiError(400, "not_pdf_version", "Выберите PDF")
        with fitz.open(
            stream=context.blob_store.get(ref.blob_key), filetype="pdf"
        ) as doc:
            return build_structure(
                native_records(doc), doc.get_toc(), sha256=ref.sha256
            )

    @router.get("/api/v1/documents/{version_id}/format-report")
    def format_report(
        version_id: str,
        request: Request,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        import io
        from vor_rules import (
            get_highlighted_workbook,
            validate_vor_formatting,
            vor_sheet_names,
        )

        ref = version(context, version_id)
        if ref.kind != "vor" or not ref.filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        blob = bytes(context.blob_store.get(ref.blob_key))
        sheets = vor_sheet_names(io.BytesIO(blob))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(io.BytesIO(blob), sheet_name=active or None)
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        painted = get_highlighted_workbook(
            io.BytesIO(blob), rows, sheet_name=active or None
        )
        stem = (
            ref.filename[:-5]
            if ref.filename.lower().endswith(".xlsx")
            else ref.filename
        )
        return Response(
            content=painted or blob,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "ETag": f'"{ref.sha256}:format"',
                "Cache-Control": "private, no-cache",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(stem + ' — оформление.xlsx')}"
                ),
            },
        )

    @router.get("/api/v1/documents/{version_id}/format-word")
    def format_word(
        version_id: str,
        request: Request,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        import io
        from vor_rules import (
            generate_rules_word_report,
            validate_vor_formatting,
            vor_sheet_names,
        )

        ref = version(context, version_id)
        if ref.kind != "vor" or not ref.filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        blob = bytes(context.blob_store.get(ref.blob_key))
        sheets = vor_sheet_names(io.BytesIO(blob))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(io.BytesIO(blob), sheet_name=active or None)
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        report = generate_rules_word_report(ref.filename, rows, sheet=active)
        stem = (
            ref.filename[:-5]
            if ref.filename.lower().endswith(".xlsx")
            else ref.filename
        )
        return Response(
            content=report,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "ETag": f'"{ref.sha256}:format-word"',
                "Cache-Control": "private, no-cache",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(stem + ' — оформление.docx')}"
                ),
            },
        )

    @router.post(
        "/api/v1/documents/{version_id}/format-checks", response_model=FormatDTO
    )
    def formatting(
        version_id: str,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        import io
        from vor_rules import (
            summarize_format_rows,
            validate_vor_formatting,
            vor_sheet_names,
        )

        ref = version(context, version_id)
        if ref.kind != "vor" or not ref.filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        blob = context.blob_store.get(ref.blob_key)
        sheets = vor_sheet_names(io.BytesIO(blob))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(io.BytesIO(blob), sheet_name=active or None)
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        issues, errors = summarize_format_rows(rows)
        from datetime import datetime, timezone

        context.repository.record_format_status(
            _parse_uuid(version_id, field="version_id"),
            {
                "state": "passed" if not issues else "failed",
                "sheet": active,
                "error_count": errors,
                "warning_count": len(issues) - errors,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "version_id": version_id,
            "sheet": active,
            "sheets": sheets,
            "error_count": errors,
            "warning_count": len(issues) - errors,
            "issues": issues,
        }

    @router.post("/api/v1/format-checks", response_model=FormatDTO)
    async def formatting_upload(
        request: Request,
        file: UploadFile,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        from api import (
            _check_upload_limits,
            _check_upload_mime,
            _safe_filename,
        )

        import io
        from vor_rules import (
            summarize_format_rows,
            validate_vor_formatting,
            vor_sheet_names,
        )

        data = await file.read(context.settings.max_upload_bytes + 1)
        filename = _safe_filename(file.filename or "")
        _check_upload_limits(context, bytes(data))
        _check_upload_mime(file, "vor")
        if not filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        if not data:
            raise ApiError(400, "empty_upload", "Загруженный файл пуст.")
        sheets = vor_sheet_names(io.BytesIO(bytes(data)))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(
                io.BytesIO(bytes(data)), sheet_name=active or None
            )
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        except Exception as exc:
            raise ApiError(
                400, "invalid_vor", f"Не удалось прочитать ВОР: {exc}"
            ) from exc
        issues, errors = summarize_format_rows(rows)
        return {
            "version_id": "",
            "sheet": active,
            "sheets": sheets,
            "error_count": errors,
            "warning_count": len(issues) - errors,
            "issues": issues,
        }

    @router.post("/api/v1/format-report")
    async def format_report_upload(
        request: Request,
        file: UploadFile,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        from api import (
            _check_upload_limits,
            _check_upload_mime,
            _safe_filename,
        )

        import io
        from vor_rules import (
            get_highlighted_workbook,
            validate_vor_formatting,
            vor_sheet_names,
        )

        data = await file.read(context.settings.max_upload_bytes + 1)
        filename = _safe_filename(file.filename or "")
        _check_upload_limits(context, bytes(data))
        _check_upload_mime(file, "vor")
        if not filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        if not data:
            raise ApiError(400, "empty_upload", "Загруженный файл пуст.")
        blob = bytes(data)
        sheets = vor_sheet_names(io.BytesIO(blob))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(io.BytesIO(blob), sheet_name=active or None)
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        except Exception as exc:
            raise ApiError(
                400, "invalid_vor", f"Не удалось прочитать ВОР: {exc}"
            ) from exc
        painted = get_highlighted_workbook(
            io.BytesIO(blob), rows, sheet_name=active or None
        )
        stem = filename[:-5] if filename.lower().endswith(".xlsx") else filename
        return Response(
            content=painted or blob,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Cache-Control": "private, no-cache",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(stem + ' — оформление.xlsx')}"
                ),
            },
        )

    @router.post("/api/v1/format-word")
    async def format_word_upload(
        request: Request,
        file: UploadFile,
        sheet: str | None = Query(None, max_length=100),
        context=Depends(guarded),
    ):
        from api import (
            _check_upload_limits,
            _check_upload_mime,
            _safe_filename,
        )

        import io
        from vor_rules import (
            generate_rules_word_report,
            validate_vor_formatting,
            vor_sheet_names,
        )

        data = await file.read(context.settings.max_upload_bytes + 1)
        filename = _safe_filename(file.filename or "")
        _check_upload_limits(context, bytes(data))
        _check_upload_mime(file, "vor")
        if not filename.lower().endswith(".xlsx"):
            raise ApiError(
                400, "xlsx_required", "Оформление проверяется только для XLSX"
            )
        if not data:
            raise ApiError(400, "empty_upload", "Загруженный файл пуст.")
        blob = bytes(data)
        sheets = vor_sheet_names(io.BytesIO(blob))
        wanted = (sheet or "").strip()
        if wanted and wanted not in sheets:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден")
        active = wanted or (sheets[0] if sheets else "")
        try:
            rows = validate_vor_formatting(io.BytesIO(blob), sheet_name=active or None)
        except KeyError as exc:
            raise ApiError(404, "sheet_not_found", "Лист ВОР не найден") from exc
        except Exception as exc:
            raise ApiError(
                400, "invalid_vor", f"Не удалось прочитать ВОР: {exc}"
            ) from exc
        report = generate_rules_word_report(filename, rows, sheet=active)
        stem = filename[:-5] if filename.lower().endswith(".xlsx") else filename
        return Response(
            content=report,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Cache-Control": "private, no-cache",
                "Content-Disposition": (
                    f"attachment; filename*=UTF-8''{quote(stem + ' — оформление.docx')}"
                ),
            },
        )

    return router
