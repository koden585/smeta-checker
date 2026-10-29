"""CPU-only refresh of a document corpus; matching snapshots stay immutable."""
from uuid import UUID
from contextlib import closing


def refresh_document(context, run_id, index, *, max_pages=3):
    import pymupdf
    from audit_snapshot import load_snapshot, store_snapshot
    from pdf_text import PDFTextSource
    from normative_retrieval import DocumentSearch
    import normative_service
    record = context.repository.load_run(run_id)
    position = normative_service.locate_position(context, record, index)
    job = context.repository.load_position_job(run_id, index)
    name = job.payload['pdf_name']
    version = (record['config'].get('pdf_versions') or {})[name]
    ref = context.repository.load_version(UUID(version))
    old = load_snapshot(context.blob_store, job.payload['snapshot'])
    # This is a document preparation pass: prioritise quantity schedules,
    # irrespective of the wording of the first VOR item used to open it.
    hits = DocumentSearch(old.texts).search('ведомость площадь объем количество', tables=True, limit=max_pages)
    targets = [h['page']-1 for h in hits]
    with pymupdf.open(stream=context.blob_store.get(ref.blob_key),filetype='pdf') as doc:
        with closing(PDFTextSource(doc)) as source:
            prepared = source.for_position(targets, position.work_name, '', position.reference,
                position.comment, max_ocr_pages=max_pages)
            frozen = store_snapshot(context.blob_store, prepared)
    corpora = dict(record['config'].get('normative_corpora') or {})
    corpora[version] = frozen
    context.repository.update_run_config(run_id, {'normative_corpora':corpora})
    return dict(version_id=version, pages=[p+1 for p in targets], corpus_id=frozen['corpus_id'])
