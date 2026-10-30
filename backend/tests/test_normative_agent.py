"""Agent regression tests: generic tables, bounded prompts and technical failures."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from normative_agent import EvidenceRequest, EvidenceTools, compact, run, cell_source_id
from normative_position_check import AgentAnswer
from normative_verdict import publish


def toolkit():
    tools = EvidenceTools.__new__(EvidenceTools)
    tools.sources, tools.cells = [], {}
    tools.events = []
    tools.preferred = []
    tools.table_search_done = False
    tools.snapshot_refs = []
    tools.version, tools.filename = 'pinned-version', 'copy.pdf'
    tools.coverage = dict(state='prepared', pending_ocr_pages=[3], error_pages=[])
    cells = [dict(cell_id='h', row=0, column=1, text='Площадь, м2', role='header', header_ids=[])]
    cells += [dict(cell_id=f'c{i}', row=i, column=1, text=text, role='cell', header_ids=['h'], origin='native')
        for i, text in enumerate(('12,34', '56,78', '90,12'), 1)]
    tools.index = SimpleNamespace(texts=('Описание бетона и таблица площади 9999', 'Кабельная линия 75', ''),
        quality={},
        tables=([dict(table_id='t1', cells=cells, row_count=4, col_count=2)], [], []))
    return tools


def sid(cell):
    return cell_source_id('pinned-version', 1, 't1', cell)


def test_fact_graph_cannot_overflow_model_prompt():
    inputs = dict(matching_checks=[dict(claim_id='quantity', state='review_required', facts=[{'raw': 'x'*1000000}])])
    result = compact(inputs, [dict(id='p1', kind='project', text='x'*20000)])
    assert len(json.dumps(result)) < 10000
    assert result['matching_checks'] == [dict(claim_id='quantity', state='review_required')]
    assert result['sources'][0]['excerpt_truncated']


def test_search_does_not_prioritize_expected_quantity_and_reports_incomplete_ocr():
    tools = toolkit()
    result = tools.execute(EvidenceRequest(tool='search_project', query='кабельная линия 9999'))
    assert result['pages'][0]['page'] == 2
    assert result['coverage']['pending_ocr_pages'] == [3]


def test_generic_table_cells_preserve_headers_and_numeric_provenance():
    tools = toolkit()
    result = tools.execute(EvidenceRequest(tool='read_table', page=1, table_id='t1'))
    assert result['row_count'] == 4
    assert 'Площадь, м2' in tools.sources[1]['text']
    result = tools.execute(EvidenceRequest(tool='sum_cells', operand_ids=[sid('c1'), sid('c2')], unit='м2'))
    assert '69.12 м2' in result['equation']
    assert result['scope_verified'] is False  # Arithmetic is not semantic applicability.
    assert tools.sources[-1]['version_id'] == 'pinned-version'


@pytest.mark.parametrize('ids,unit', [(['invented', sid('c1')], 'м2'),
    ([sid('c1'), sid('c1')], 'м2'), ([sid('c1'), sid('c2')], 'т')])
def test_sum_rejects_fabricated_duplicate_or_incompatible_cells(ids, unit):
    tools = toolkit()
    tools.execute(EvidenceRequest(tool='read_table', table_id='t1'))
    assert 'error' in tools.execute(EvidenceRequest(tool='sum_cells', operand_ids=ids, unit=unit))


def test_agent_acquires_missing_evidence_before_verdict():
    tools = toolkit()
    answers = [AgentAnswer(summary='Нужна таблица', items=[], requests=[EvidenceRequest(tool='read_table', table_id='t1')]),
        AgentAnswer(summary='Недостаточно данных о применимости', items=[])]
    ask = Mock(side_effect=answers)
    stats = {'queries': []}
    result = run(ask, None, None, '', {}, AgentAnswer, None, stats, tools)
    assert result.summary == answers[1].summary
    supplied = ask.call_args.args[3]
    assert supplied['tool_results'][0]['result']['rows'][1]['text'] == '12,34'
    assert len(tools.sources) == 4
    assert ask.call_count == 2


def test_agent_cannot_turn_exhausted_tool_budget_into_a_verdict():
    ask = Mock(return_value=AgentAnswer(summary='Еще поиск', items=[], requests=[EvidenceRequest(tool='read_page')]))
    with pytest.raises(TimeoutError):
        run(ask, None, None, '', {}, AgentAnswer, None, {'queries': []}, toolkit())
    assert ask.call_count == 3


def test_final_open_search_preserves_partial_evidence_without_confirming_verdict():
    item=dict(topic='Площадь',state='confirmed',explanation='Нужен ещё источник единицы.',
        project_source_ids=[],normative_source_ids=[],claim_ids=['quantity'])
    ask=Mock(return_value=AgentAnswer(summary='Частичный результат',items=[item],
        requests=[EvidenceRequest(tool='read_page')]))
    stats={'queries':[]}
    answer=run(ask,None,None,'',{},AgentAnswer,None,stats,toolkit())
    assert ask.call_count==3
    assert answer.items[0].state=='needs_facts'
    assert answer.requests==[]
    assert 'read_page' in stats['missing_facts'][0]


def test_one_remaining_call_uses_prepared_evidence_instead_of_planning_more_reads():
    ask=Mock(return_value=AgentAnswer(summary='Недостаточно подтверждённых данных',items=[]))
    with patch('normative_agent.MAX_ROUNDS',1):
        run(ask,None,None,'Проверить факты.',{},AgentAnswer,None,{'queries':[]},toolkit())
    assert 'Проверить факты.' in ask.call_args.args[2]
    assert 'requests=[] обязательно' in ask.call_args.args[2]


def test_generic_composite_quantity_can_clear_verdict_without_road_repair_rules():
    from normative_parameters import enrich
    from normative_position_check import validate_items
    tools = toolkit()
    tools.sources.append(dict(id='n1', kind='normative', label='Норма', page=1, text='Измеритель м2', origin='native'))
    def answer(*args):
        supplied = args[3]
        step = 2-supplied['remaining_steps']
        if step == 0:
            return AgentAnswer(summary='Читаю исходные площади', items=[], requests=[EvidenceRequest(tool='read_table', table_id='t1')])
        if step == 1:
            return AgentAnswer(summary='Проверяю сумму', items=[], requests=[EvidenceRequest(tool='sum_cells',
                operand_ids=[sid('c1'), sid('c2')], unit='м2')])
        source = next(s for s in supplied['sources'] if s['origin'] == 'calculated_from_cells')
        return AgentAnswer(summary='Площадь рассчитана из двух участков', items=[dict(topic='Площадь', state='confirmed',
            explanation='Сумма двух площадей по таблице.', claim_ids=['quantity', 'normative:applicability'],
            project_source_ids=[source['id']], normative_source_ids=['n1'])], parameters=[dict(parameter='quantity',
                value='69.12', unit='м2', source_id=source['id'], quote='12.34 + 56.78 = 69.12 м2',
                scope_state='verified', scope_quote='12.34 + 56.78 = 69.12 м2')])
    result = run(answer, None, None, '', {}, AgentAnswer, None, {'queries': []}, tools)
    p = SimpleNamespace(index=0, number='1', work_name='Покрытие', volume='69.12', unit='м2', formula='', calculation={}, position_source=None)
    review = enrich(p, dict(pipeline_version=3, position_key='k', sources=tools.sources, summary=result.summary,
        items=validate_items(result.items, tools.sources, {'quantity', 'normative:applicability'}),
        parameter_proposals=[v.model_dump() for v in result.parameters]), {0:p}, {})
    report = publish({'Статус аудита':'Требуется ручная проверка'},
        {'checks':[dict(claim_id='quantity', state='review_required')]}, 'k', {'review':review}, enabled=True)
    assert report['Статус аудита'] == 'ОК'


def test_technical_failure_is_not_engineering_discrepancy_or_manual_ambiguity():
    report = {'Статус аудита': 'Обнаружено расхождение', 'Что не так': 'old'}
    review = dict(position_key='key', execution_state='technical_failure', summary='Истекло время запроса')
    result = publish(report, {}, 'key', dict(review=review, stage='done'), enabled=True)
    assert result['Статус аудита'] == 'Проверка не выполнена'
    assert result['Что не так'] == 'Истекло время запроса'


def test_early_position_can_read_table_prepared_for_a_sibling_without_reextracting_pdf():
    tools = toolkit()
    tools.blob_store = object()
    tools.snapshot_refs = [dict(snapshot_storage='pages-v1', snapshot_key='manifest', snapshot_sha256='sha')]
    table = dict(table_id='later-table', row_count=1, col_count=1, cells=[])
    manifest = dict(format='page-snapshot-v1', pages=[{'key':'p1'}, {'key':'p2'}])
    with patch('audit_snapshot.load_json', side_effect=[manifest, {'tables':[table]}]) as read:
        result = tools.execute(EvidenceRequest(tool='read_table', page=2, table_id='later-table'))
    assert result['row_count'] == 1
    assert read.call_count == 2
    assert read.call_args.args[1] == {'key':'p2'}
