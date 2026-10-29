from types import SimpleNamespace
from unittest.mock import Mock, patch

import pymupdf

from normative_agent import EvidenceRequest, compact, run
from normative_position_check import AgentAnswer
from normative_retrieval import DocumentSearch
from normative_parameters import build_cards
from ocr_engine import _word_to_pdf, _row_bands
from test_normative_agent import toolkit


def test_rotated_page_coordinates_are_clipped_in_unrotated_pdf_frame():
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.set_rotation(270)
        word = dict(left=20, top=160, width=10, height=10)
        matrix = page.derotation_matrix
        actual, clipped = _word_to_pdf(word, 0, (100,200), None, (100,200), page.rect,
            (matrix.a,matrix.b,matrix.c,matrix.d,matrix.e,matrix.f))
        expected = list(pymupdf.Rect(20,160,30,170)*matrix)
        assert actual == expected
        assert not clipped


def test_rotated_intrinsic_pdf_coordinates_do_not_turn_rows_into_columns():
    words = []
    for row, y in enumerate((10, 30)):
        for col, x in enumerate((0, 20)):
            words.append(dict(text=f'{row}:{col}', bbox=[y,x,y+10,x+10],
                _tbox=[x,y,x+10,y+10], _tx=x, _ty=y))
    rows = _row_bands(words, reading_angle=0)
    assert [[w['text'] for w in r['words']] for r in rows] == [['0:0','0:1'],['1:0','1:1']]


def test_table_discovery_finds_quantity_schedule_without_matching_work_name():
    search = DocumentSearch(['Монтаж опор освещения: технология и машины.',
        'Ведомость количеств по участкам. Всего площадь 12,34 56,78 69,12 м2.'])
    assert search.search('монтаж опор', tables=True)[0]['page'] == 2


def test_read_source_preserves_the_end_of_a_selected_construction_among_many_hits():
    tools = toolkit()
    text = 'Раздел конструкции\n'+'описание '*180+'\nНижний слой h=37 см.'
    tools.sources = [dict(id='target',kind='project',text=text)] + [dict(id=f'n{i}',kind='normative',text='x'*1800) for i in range(55)]
    tools.execute(EvidenceRequest(tool='read_source',source_id='target'))
    result = compact({}, tools.sources, tools.preferred)
    source = next(s for s in result['sources'] if s['id'] == 'target')
    assert source['text'] == text
    assert not source['excerpt_truncated']
    assert len(tools.sources) == 56


def test_cell_identities_cannot_collide_between_pages_with_the_same_table_name():
    tools = toolkit()
    first = tools.execute(EvidenceRequest(tool='read_table',table_id='t1'))
    tools.index.tables[1].append(tools.index.tables[0][0])
    second = tools.execute(EvidenceRequest(tool='read_table',page=2,table_id='t1'))
    assert set(v['source_id'] for v in first['cells']).isdisjoint(v['source_id'] for v in second['cells'])


def test_agent_must_discover_quantity_tables_before_claiming_insufficient_facts():
    tools = toolkit()
    answer = AgentAnswer(summary='Не найдено количество',items=[dict(topic='Количество',state='needs_facts',
        explanation='Нужна таблица',claim_ids=['quantity'],project_source_ids=[],normative_source_ids=[])])
    ask = Mock(return_value=answer)
    run(ask,None,None,'',{'position':{'work':'покрытие'}},AgentAnswer,None,{'queries':[]},tools)
    assert ask.call_count == 2
    assert tools.events[0]['request']['tool'] == 'search_tables'


def test_another_layer_value_cannot_become_a_confirmed_numeric_discrepancy():
    p = SimpleNamespace(index=0,number='1',work_name='Нижний слой основания, h=12 см',
        volume='72',unit='м2',position_source=None,formula='',calculation={})
    text = 'Верхний слой основания h=20 см. Нижний слой основания h=24 см.'
    result = dict(pipeline_version=3,sources=[dict(id='p',kind='project',origin='native',text=text)],
        parameter_proposals=[dict(parameter='thickness',value='20',unit='см',source_id='p',quote='h=20 см',
            scope_state='verified',scope_quote='Верхний слой основания h=20 см')])
    card = next(c for c in build_cards(p,result,{0:p},{}) if c['id']=='thickness')
    assert card['state']=='needs_facts'
    assert 'Принадлежность' in card['reason']


def test_same_layer_exact_scope_can_confirm_value_without_matching_expected_number_in_retrieval():
    p = SimpleNamespace(index=0,number='1',work_name='Нижний слой основания, h=17 см',
        volume='72',unit='м2',position_source=None,formula='',calculation={})
    text = 'Верхний слой основания h=11 см. Нижний слой основания h=17 см.'
    result = dict(pipeline_version=3,sources=[dict(id='p',kind='project',origin='native',text=text)],
        parameter_proposals=[dict(parameter='thickness',value='17',unit='см',source_id='p',quote='h=17 см',
            scope_state='verified',scope_quote='Нижний слой основания h=17 см')])
    card = next(c for c in build_cards(p,result,{0:p},{}) if c['id']=='thickness')
    assert card['state']=='confirmed'


def test_ocr_number_requires_independent_agreement_in_the_same_physical_cell():
    from pdf_tables import verify_numeric_cells
    cell = dict(text='37,125',bbox=[10,10,90,30],quality='usable',header_ids=['header'],
        words=[dict(text='37,125',confidence=.99)])
    tables = [dict(cells=[cell])]
    word = dict(text='37,125',conf=97,bbox=[20,15,60,25])
    verify_numeric_cells(tables,[word])
    assert cell['numeric_verified']
    verify_numeric_cells(tables,[{**word,'text':'37,725'}])
    assert not cell['numeric_verified']
    verify_numeric_cells(tables,[{**word,'bbox':[100,15,150,25]}])
    assert not cell['numeric_verified']


def test_docker_warmup_materializes_lazy_cyrillic_recognition_weights():
    from pdf_tables import warm_raster_engine
    ocr = SimpleNamespace(_load_rec_model=Mock())
    with patch('pdf_tables.raster_engine',return_value=(ocr,object())):
        warm_raster_engine()
    ocr._load_rec_model.assert_called_once_with()


def test_physical_grid_is_found_inside_the_enclosing_drawing_frame():
    import cv2
    import numpy as np
    from pdf_tables import physical_table_regions
    grid=np.zeros((450,450),dtype=np.uint8)
    cv2.rectangle(grid,(5,5),(444,444),255,2)
    for x in (40,130,220,310,400):
        cv2.line(grid,(x,80),(x,350),255,2)
    for y in (80,170,260,350):
        cv2.line(grid,(40,y),(400,y),255,2)
    regions=physical_table_regions(grid,450,450)
    assert regions and all(box[0]>20 and box[1]>50 for box in regions)


def test_multiline_unit_and_thickness_headers_are_not_mistaken_for_numeric_data():
    from pdf_tables import physical_header_rows
    cells=[dict(row=0,text='Основание'),dict(row=1,text='h=0,24 м'),
        dict(row=2,text='Площадь'),dict(row=2,text='м2'),
        dict(row=3,text='12,75'),dict(row=3,text='6,25')]
    assert physical_header_rows(cells)==3


def test_sum_keeps_separate_pdf_highlights_for_each_operand():
    from test_normative_agent import sid
    tools=toolkit()
    tools.index.metadata={'page_geometry':{'0':dict(width=100,height=100,matrix=[1,0,0,1,0,0])}}
    for i,cell in enumerate(tools.index.tables[0][0]['cells']):
        cell['bbox']=[10,i*10,20,i*10+5]
    tools.execute(EvidenceRequest(tool='read_table',table_id='t1'))
    summed=tools.execute(EvidenceRequest(tool='sum_cells',operand_ids=[sid('c1'),sid('c2')],unit='м2'))
    source=next(s for s in tools.sources if s['id']==summed['source_id'])
    assert source['rects']==[[.1,.1,.2,.15],[.1,.2,.2,.25]]


def test_unit_recovery_requires_literal_unit_inside_its_physical_header():
    from pdf_tables import recover_unit_headers
    cell=dict(role='header',text='${}$',bbox=[10,10,40,30])
    words=[dict(text='м²',conf=95,bbox=[15,15,25,25])]
    recover_unit_headers([dict(cells=[cell])],words)
    assert 'м2' in cell['text']
    other=dict(role='header',text='${}$',bbox=[50,10,80,30])
    recover_unit_headers([dict(cells=[other])],words)
    assert other['text']=='${}$'
