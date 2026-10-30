"""Derive the published verdict after normative validation; raw matching is immutable."""
from copy import deepcopy
import re

PENDING = 'Проверяется по нормативам'
FIX = 'Обнаружено расхождение'
REVIEW = 'Требуется ручная проверка'


def source_supported(item):
    claims = item.get('claim_ids') or []
    project_only = bool(claims) and all(c in {'quantity','unit','presence'} or c.startswith('geometry:') for c in claims)
    return bool(claims and item.get('project_source_ids') and (project_only or item.get('normative_source_ids')))


def absence_claim(item):
    """A negative search result is not a positive incompatibility proof."""
    return bool(item.get('state')=='possible_mismatch' and re.search(
        r'не\s+(?:найден|обнаружен|указан|подтвержд)|нет\s+подтвержден|отсутств\w*[^.!?]{0,90}(?:ПД|проект|документ)',
        item.get('explanation',''),re.I))


def readable_review(review):
    """Ephemeral model handles belong in traces, not the engineer's prose."""
    result=deepcopy(review)
    labels={f's{i}':('ПД' if s['kind']=='project' else s.get('label','Норматив'))+
        (f", стр. {s['page']}" if s.get('page') else '') for i,s in enumerate(result.get('sources',[]))}
    def readable(text):
        return re.sub(r'(?<!\w)s\d+(?!\w)',lambda m: labels.get(m[0],m[0]),text)
    result['summary']=readable(result.get('summary',''))
    rejected=False
    for item in result.get('items',[]):
        item['explanation']=readable(item.get('explanation',''))
        if absence_claim(item):
            item['state']='needs_facts'
            rejected=True
    if rejected and result.get('state')=='possible_mismatch' and not any(i.get('state')=='possible_mismatch' for i in result.get('items',[])):
        result['state']='needs_facts'
    return result


def verified_quantity(review, position_key, unit, *, derived=False):
    """Use a scoped, source-backed quantity in the UI without mutating matching."""
    if derived or not review or review.get('position_key') != position_key:
        return None
    def normalize(value):
        return str(value).strip().rstrip('.').replace('²','2').replace('³','3')
    card = next((c for c in review.get('parameter_cards') or [] if c.get('id') == 'quantity'
        and c.get('state') == 'confirmed' and c.get('source_ids') and c.get('found_value') is not None
        and normalize(c.get('found_unit')) == normalize(unit)), None)
    return (card['found_value'], card['found_unit']) if card else None


def required_claims(stored, report_status, derived=False):
    unresolved = {c['claim_id'] for c in stored.get('checks') or []
        if c.get('claim_id') and c.get('required', True)
        and c.get('state') not in {'confirmed', 'not_applicable'}}
    if report_status != 'ОК' and not unresolved:
        unresolved.add('matching:verdict')
    unresolved.add('normative:applicability')
    if derived:
        unresolved.update({'derived:rate', 'derived:parent'})
    return unresolved


def publish(report, stored, position_key, validation, *, enabled=False, derived=False):
    """A failed/unsupported second layer is uncertainty, never a proved mismatch."""
    if not enabled and not validation:
        return report
    if report['Статус аудита'] == 'Проверка не выполнена':
        return report
    output = deepcopy(report)
    stage = (validation or {}).get('stage')
    review = (validation or {}).get('review')
    if review and review.get('position_key') != position_key:
        review = None
    if review:
        review=readable_review(review)
    if review and stage in {'pending', 'dispatched', 'running'}:
        from normative_local_checks import LOCAL_RULES_VERSION
        if review.get('local_rules_version', 0) < LOCAL_RULES_VERSION:
            output['Статус аудита'] = PENDING
            output['Что не так'] = 'Автоматически обновляем основание по новым правилам. Готовый результат сохранён; новый запрос к модели не выполняется.'
            return output
    if not review:
        pending = stage in {'pending', 'dispatched', 'running'} or (enabled and stage is None)
        output['Статус аудита'] = PENDING if pending else REVIEW
        output['Что не так'] = ('Сопоставление выполнено. Проверяем основание по нормативам.' if pending else
            'Нормативная валидация не завершена или недостаточно источников. Расхождение не подтверждено.')
        return output
    if review.get('execution_state') == 'technical_failure':
        output['Статус аудита'] = 'Проверка не выполнена'
        output['Что не так'] = review.get('summary') or 'Технический сбой нормативного этапа; вывод о корректности ВОР не получен.'
        return output
    items = review.get('items') or []
    arithmetic_errors = [v.get('message') or 'Ошибка арифметики формулы ВОР.' for v in stored.get('workbook_notes') or []
        if v.get('kind') == 'formula-mismatch']
    if arithmetic_errors:
        output['Статус аудита'] = FIX
        output['Что не так'] = ' '.join(arithmetic_errors)
        return output
    supported = [v for v in items if source_supported(v)]
    contradictions = [v for v in supported if v.get('state') == 'possible_mismatch' and not absence_claim(v)]
    confirmed = {claim for v in supported if v.get('state') == 'confirmed' for claim in v['claim_ids']}
    needed = required_claims(stored, report['Статус аудита'], derived)
    cards = review.get('parameter_cards') or []
    if review.get('pipeline_version', 1) >= 3:
        from normative_parameters import numeric_card_keys
        # Revalidate older saved reviews too. A source ID alone does not prove
        # the model's numerical interpretation or a mismatched thickness.
        contradictions = [v for v in contradictions if not numeric_card_keys(v['claim_ids']) or all(
            any(c.get('id') == key and c['state'] == 'possible_mismatch' for c in cards)
            for key in numeric_card_keys(v['claim_ids']))]
    card_gaps = [c for c in cards if c.get('required', True) and c['state'] != 'confirmed']
    def disputed_scope(card):
        key = card.get('id')
        return any(v.get('state') == 'needs_facts' and any(
            claim == 'quantity' if key == 'quantity' else 'thickness' in claim if key == 'thickness' else False
            for claim in v.get('claim_ids', [])) for v in items)
    card_conflicts = [c for c in card_gaps if c['state'] == 'possible_mismatch' and not disputed_scope(c)]
    if card_conflicts and 'normative:applicability' in confirmed:
        output['Статус аудита'] = FIX
        output['Что не так'] = ' '.join(c['label']+': '+c['reason'] for c in card_conflicts)
        return output
    if contradictions and (review.get('pipeline_version',1) < 3 or 'normative:applicability' in confirmed):
        output['Статус аудита'] = FIX
        output['Что не так'] = ' '.join(v['explanation'] for v in contradictions)
    elif items and needed <= confirmed and not card_gaps and all(
            v.get('state') == 'confirmed' or (v.get('state') == 'needs_facts'
                and v.get('claim_ids') and set(v['claim_ids']) <= confirmed)
            or v.get('required') is False for v in items):
        output['Статус аудита'] = 'ОК'
        output['Что не так'] = 'Основание работы подтверждено по ПД и нормативам. ' + next(
            (v['explanation'] for v in supported if v.get('topic') == 'Основание работы подтверждено'), review.get('summary', ''))
    else:
        output['Статус аудита'] = REVIEW
        uncertain = [v['explanation'] for v in items if v.get('state') == 'needs_facts']
        output['Что не так'] = (' '.join(uncertain) or review.get('summary') or 'Недостаточно нормативных оснований для окончательного вывода.')
        if needed - confirmed:
            output['Что не так'] += ' Не все условия подтверждены; расхождение не доказано.'
        if card_gaps:
            output['Что не так'] = ' '.join(c['label']+': '+c['reason'] for c in card_gaps)
    return output


def apply_parent_verdicts(rows, *, enabled, running):
    """A derived material cannot be confirmed before its parent work basis."""
    if not enabled:
        return rows
    by_index = {r.position_index: r for r in rows}
    for row in rows:
        if not row.related_work or row.queue in {'fix', 'missing'}:
            continue
        parent = by_index.get(row.related_work['index'])
        if (parent is None and running) or (parent is not None and parent.queue == 'pending'):
            row.queue, row.report_status = 'pending', PENDING
            row.problem = f"Расчётный материал работы №{row.related_work['number']}. Ожидаем проверку основания связанной работы."
        elif row.queue == 'ok' and (parent is None or parent.queue != 'ok'):
            row.queue, row.report_status = 'review', REVIEW
            row.problem = f"Расчёт связан с работой №{row.related_work['number']}, но её основание ещё не подтверждено."
    return rows


def finalize_state(result, stored, position_key, *, derived=False):
    """Persist the same validated status that the row publisher computes.

    Previously every new agent result was stored as needs_facts even when all
    required claims and numeric cards passed. This uses the existing guards;
    it cannot promote an unsupported model assertion.
    """
    output = deepcopy(result)
    report = publish({'Статус аудита':'ОК' if stored.get('status')=='ОК' else REVIEW},
        stored,position_key,{'stage':'done','review':dict(result,position_key=position_key)},
        enabled=True,derived=derived)
    output['state'] = 'confirmed' if report['Статус аудита']=='ОК' else 'possible_mismatch' if report['Статус аудита']==FIX else 'needs_facts'
    output['requires_engineer_review'] = output['state']!='confirmed'
    return output
