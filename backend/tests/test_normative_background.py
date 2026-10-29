"""Queue isolation and failure safety against an isolated PostgreSQL database."""
from unittest.mock import Mock
from uuid import UUID

from audit_tasks import DEFAULT_TASK_ROUTES
from test_durable_tasks import pipeline as pipeline


NAME = "audit_tasks.normative_position"


def test_completion_atomically_schedules_only_once(pipeline):
    p = pipeline
    p.repo.update_run_config(p.run.id, {"normative_after_match": True})
    p.repo.create_position_job(p.run.id, 0, queue="llm", payload={})
    p.repo.finish_position_job(p.run.id, 0, "done", result={"status": "ОК"})
    p.repo.finish_position_job(p.run.id, 0, "done", result={"status": "ОК"})
    deliveries = p.repo.reserve_deliveries()
    assert len(deliveries) == 1 and deliveries[0]['name'] == NAME
    assert DEFAULT_TASK_ROUTES[NAME]['queue'] == 'normative'
    assert DEFAULT_TASK_ROUTES['audit_tasks.audit_position']['queue'] == 'llm'
    # The outbox stores the index inside JSON payload, not as an ORM column.
    assert p.repo.normative_validation_context(p.run.id) == {0: {'stage': 'dispatched'}}


def test_large_matching_backlog_does_not_starve_normative_or_consume_its_slots(pipeline):
    p = pipeline
    for i in range(130):
        p.repo.enqueue_task('audit_tasks.audit_position', dict(run_id=str(p.run.id), position_index=i))
    for i in range(5):
        p.repo.enqueue_task(NAME, dict(run_id=str(p.run.id), position_index=i))
    deliveries = p.repo.reserve_deliveries()
    assert sum(t['name'] == NAME for t in deliveries) == 2
    assert sum(t['name'] != NAME for t in deliveries) == 32
    assert p.repo.reserve_deliveries() == []


def test_normative_can_finish_after_matching_and_failure_never_fails_run(pipeline):
    p = pipeline
    p.repo.enqueue_task(NAME, dict(run_id=str(p.run.id), position_index=0))
    p.repo.finish_run(p.run.id, 'done')
    delivery = p.repo.reserve_deliveries()[0]
    task, token = UUID(delivery['id']), UUID(delivery['token'])
    assert p.repo.claim_delivery(task, token, timeout=30)
    assert not p.repo.claim_delivery(task, token, timeout=30)
    p.repo.settle_delivery(task, token, error='synthetic model failure')
    assert p.repo.run_status(p.run.id) == 'done'
    assert p.repo.normative_stage(p.run.id, 0)['status'] == 'failed'
    counts = p.repo.run_progress_records(run_id=p.run.id)[0]['normative_counts']
    assert counts == {'failed': 1}
    assert p.repo.reserve_deliveries() == []  # No automatic paid retry.


def test_stopped_run_does_not_start_normative(pipeline):
    p = pipeline
    p.repo.enqueue_task(NAME, dict(run_id=str(p.run.id), position_index=0))
    p.repo.finish_run(p.run.id, 'cancelled')
    assert p.repo.reserve_deliveries() == []
    assert p.repo.normative_stage(p.run.id, 0)['status'] == 'cancelled'


def test_page_cache_is_shared_across_positions_but_not_pdf_versions(pipeline):
    p = pipeline
    build = Mock(return_value=dict(origin='ocr_unverified', text='synthetic', words_key='words'))
    assert p.repo.cached_normative_page(p.run.id, 'version1:89:v3', build)['text'] == 'synthetic'
    p.repo.cached_normative_page(p.run.id, 'version1:89:v3', build)
    assert build.call_count == 1
    p.repo.cached_normative_page(p.run.id, 'version2:89:v3', build)
    assert build.call_count == 2
