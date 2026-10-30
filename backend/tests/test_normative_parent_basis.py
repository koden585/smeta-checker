from contextlib import ExitStack
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from normative_parameters import enrich
from normative_parent_basis import bind_parent_basis
from test_normative_layer_reuse import fixture


def run_binding(unknown=False):
    parent,peer,donor,record,context=fixture()
    donor['payload']['position_key']='key-0'
    if unknown:
        donor['payload']['position_check']['parameter_cards'][0]['state']='needs_facts'
    child=parent.model_copy(update={'index':1,'number':'2','work_name':'Расчётный материал','volume':'5.355','unit':'м3',
        'comment':'Коэффициент расхода 1,26','formula':'=(42.5*0.10)*1.26'})
    result=dict(pipeline_version=3,items=[dict(topic='Основание',state='needs_facts',required=True,
        claim_ids=['derived:parent','quantity'],project_source_ids=[],normative_source_ids=[],explanation='Нужно основание'),
        dict(topic='Расход',state='needs_facts',required=True,claim_ids=['derived:rate'],project_source_ids=[],normative_source_ids=[],explanation='Нет источника коэффициента')],
        parameter_proposals=[dict(parameter='coefficient',value='1.26',unit='',source_id='m',quote='Купл-1,26',scope_state='unresolved')],
        sources=[dict(id='m',kind='project',origin='native',text='Купл-1,26',version_id='pdf',label='ПД',page=1)],
        related_positions=[dict(row=p.position_source.row,work=p.work_name,quantity=p.volume,unit=p.unit) for p in (parent,peer)])
    original=deepcopy(result)
    positions={0:parent,1:child,2:peer}
    relation=dict(parent={'index':0},children=[])
    with ExitStack() as stack:
        stack.enter_context(patch('normative_service.position_key',side_effect=lambda p:f'key-{p.index}'))
        stack.enter_context(patch('normative_service.profile_for',return_value='test'))
        stack.enter_context(patch('normative_service.corpus',return_value=SimpleNamespace(identity={'sha256':'kb'})))
        stack.enter_context(patch('audit_review_policy.review_source',side_effect=lambda raw,task:raw))
        output=bind_parent_basis(context,record,result,positions,relation)
    assert result==original
    return output,child,positions,relation


def test_parent_geometry_is_reused_but_material_factor_remains_unconfirmed():
    output,child,positions,relation=run_binding()
    assert output['evidence_trace'][0]['kind']=='reused_parent_parameters'
    assert any('derived:parent' in i['claim_ids'] and i['state']=='confirmed' for i in output['items'])
    assert any('derived:rate' in i['claim_ids'] and i['state']=='needs_facts' for i in output['items'])
    cards=enrich(child,output,positions,relation)['parameter_cards']
    assert next(c for c in cards if c['id']=='quantity')['state']=='confirmed'
    assert next(c for c in cards if c['id']=='thickness')['state']=='confirmed'
    assert next(c for c in cards if c['role']=='coefficient')['state']=='needs_facts'


def test_unconfirmed_parent_cannot_supply_verified_geometry():
    output,*_=run_binding(unknown=True)
    assert not output.get('evidence_trace')
    assert not any(i['state']=='confirmed' for i in output['items'])
