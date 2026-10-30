from copy import deepcopy
from types import SimpleNamespace
from normative_layer_conditions import layer_condition_proof


def fixture():
    p=SimpleNamespace(work_name='Нижний слой основания',formula='',position_type='Работа',
        comment='При толщине однослойного основания более 15 см его нормировать в два слоя')
    group=dict(height='26',first='13',second='13')
    result=dict(parameter_cards=[dict(id='thickness',state='confirmed',found_value='26',found_unit='см',source_ids=['p'])],
        items=[dict(state='confirmed',claim_ids=['normative:applicability'],project_source_ids=['p'],normative_source_ids=['n'])],
        sources=[dict(id='n',kind='normative',text='При толщине основания более 15 см его нормировать в два слоя.')])
    return p,result,group


def test_condition_uses_cited_threshold_not_a_hardcoded_collection_or_value():
    p,result,group=fixture()
    proof=layer_condition_proof(p,result,group)
    assert proof and proof['claim_ids']==['basis:comment:consumption:2']
    assert '15 см' in proof['explanation'] and '13 + 13 = 26' in proof['explanation']
    assert proof['project_source_ids']==['p'] and proof['normative_source_ids']==['n']


def test_missing_project_or_normative_confirmation_cannot_close_the_rule():
    p,result,group=fixture()
    unknown=deepcopy(result); unknown['parameter_cards'][0]['state']='needs_facts'
    assert layer_condition_proof(p,unknown,group) is None
    unknown=deepcopy(result); unknown['items'][0]['state']='needs_facts'
    assert layer_condition_proof(p,unknown,group) is None
    result['items'][0]['project_source_ids']=[]
    assert layer_condition_proof(p,result,group) is None


def test_wrong_layer_unmet_threshold_or_wrong_sum_cannot_close_the_rule():
    p,result,group=fixture()
    result['sources'][0]['text']='При толщине верхнего слоя основания более 15 см его нормировать в два слоя.'
    assert layer_condition_proof(p,result,group) is None
    result['sources'][0]['text']='При толщине основания более 30 см его нормировать в два слоя.'
    assert layer_condition_proof(p,result,group) is None
    result['sources'][0]['text']='При толщине основания более 15 см его нормировать в два слоя.'
    result['parameter_cards'][0]['found_value']='20'
    assert layer_condition_proof(p,result,group) is None
