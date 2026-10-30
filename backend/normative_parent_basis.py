"""Bind a derived material to verified parent geometry, preserving its own rate check."""
from copy import deepcopy


def bind_parent_basis(context,record,result,positions,relation):
    from normative_verdict import publish,source_supported
    from audit_review_policy import review_source
    import normative_service as service
    parent_index=(relation.get('parent') or {}).get('index')
    if not isinstance(parent_index,int) or parent_index not in positions:
        return result
    parent=positions[parent_index]
    row=next((r for r in context.repository.normative_reviews(record['id'],parent_index) if r['kind']=='check'),None)
    if row is None:
        return result
    data=row['payload']
    basis=data.get('position_check') or {}
    if (data.get('position_key')!=service.position_key(parent) or data.get('vor_version_id')!=str(record['vor_version_id'])
            or basis.get('execution_state')!='complete' or basis.get('pipeline_version',0)<3
            or data.get('kb')!=service.corpus(profile=service.profile_for(record)).identity):
        return result
    pinned=set((record['config'].get('pdf_versions') or {}).values())
    if any(s.get('version_id') not in pinned for s in basis['sources'] if s['kind']=='project'):
        return result
    raw=next((r['result'] for r in record['indexed_results'] if r['position_index']==parent_index),None)
    if raw is None:
        return result
    stored=review_source(raw,parent.legacy_task())
    report=publish({'Статус аудита':'ОК' if stored.get('status')=='ОК' else 'Требуется ручная проверка','Что не так':''},
        stored,data['position_key'],{'stage':'done','review':{**basis,'position_key':data['position_key']}},enabled=True)
    if report['Статус аудита']!='ОК':
        return result
    output=deepcopy(result)
    mapping={s['id']:f'parent-{parent_index}:'+s['id'] for s in basis['sources']}
    output['sources']=[s for s in output['sources'] if s['id'] not in mapping.values()]
    output['sources'] += [{**deepcopy(s),'id':mapping[s['id']]} for s in basis['sources']]
    output['parameter_proposals']=[p for p in output.get('parameter_proposals',[]) if p['parameter']=='coefficient']
    for p in basis.get('parameter_proposals',[]):
        if p['parameter'] not in {'quantity','thickness','unit_scale'} or p['source_id'] not in mapping:
            continue
        p=deepcopy(p)
        p['source_id']=mapping[p['source_id']]
        p['operand_source_ids']=[mapping[s] for s in p.get('operand_source_ids',[]) if s in mapping]
        if p.get('operation')=='sum':
            for field in ('quote','scope_quote'):
                p[field]=p.get(field,'').partition(' Ячейки:')[0].rstrip('.')
        output['parameter_proposals'].append(p)
    items=[]
    for item in output.get('items',[]):
        if item.get('topic')=='Проверенное основание родительской работы':
            continue
        item['claim_ids']=[c for c in item.get('claim_ids',[]) if c not in {'derived:parent','quantity'}]
        if item['claim_ids']:
            items.append(item)
    project_ids=list(dict.fromkeys(mapping[sid] for c in basis['parameter_cards'] if c['id'] in {'quantity','thickness'}
        and c['state']=='confirmed' for sid in c.get('source_ids',[])))
    norm_ids=list(dict.fromkeys(mapping[sid] for i in basis['items'] if i['state']=='confirmed'
        and 'normative:applicability' in i['claim_ids'] and source_supported(i) for sid in i['normative_source_ids']))
    items.append(dict(topic='Проверенное основание родительской работы',state='confirmed',required=True,
        claim_ids=['derived:parent','quantity'],project_source_ids=project_ids,normative_source_ids=norm_ids,
        explanation=f'Площадь и проектная толщина взяты из подтверждённого основания работы №{parent.number or parent_index+1}. '
            'Отдельная строка расчётного материала в ПД не требуется. Формула, коэффициенты и характеристики материала проверяются отдельно.'))
    output['items']=items
    output.setdefault('evidence_trace',[]).append(dict(kind='reused_parent_parameters',review_id=row['id'],position_index=parent_index))
    return output
