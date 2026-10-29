"""Independent bounded normative follow-up; no mutation of matching verdicts."""
from workspace_models import NormativePositionCheckRequest


def review_position(context, run_id, index):
    from normative_position_check import check
    repo = context.repository
    record = repo.load_run(run_id)
    if record["status"] not in {"running", "done"}:
        return {"skipped": "run_stopped"}
    if not record["config"].get("normative_after_match"):
        return {"skipped": "disabled"}
    # A saved manual check takes precedence; delivery recovery never repeats it.
    if any(r["kind"] == "check" for r in repo.normative_reviews(run_id, index)):
        return {"skipped": "already_reviewed"}
    if not any(r["position_index"] == index for r in record["indexed_results"]):
        return {"skipped": "no_matching_result"}
    result = check(context, record, index, NormativePositionCheckRequest(
        question="Следующий слой после сопоставления ПД и ВОР: проверить нормативное основание, состав работ, "
        "измеритель, связанные расчётные строки, коэффициенты и условия. Не считать уточнения размеров, "
        "технологическое разбиение или отсутствие отдельной строки расчётного материала самостоятельной ошибкой."
    ), "automatic-after-matching", automatic=True)
    return {"review_id": result["id"]} if result else {"skipped": "insufficient_sources"}
