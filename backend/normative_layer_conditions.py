"""Evaluate a cited layer-thickness condition against verified project facts.

Thresholds and clause IDs are read from the supplied normative text, not coded
for a project. The model must first confirm the source's applicability.
"""
import re

from normative_parameters import measure

TOPIC = 'Условие нормирования по подтверждённой толщине'


def layer_condition_proof(position, result, group):
    if not group:
        return None
    from audit_predicates import technical_specs
    claims = [s.claim_id for s in technical_specs(position.work_name,getattr(position,'comment',''),
        getattr(position,'position_type',''),[],getattr(position,'formula',''))
        if s.property_label == 'consumption' and re.match(r'в\s+два\s+слоя\b',s.expected_text,re.I)]
    if not claims:
        return None
    card = next((c for c in result['parameter_cards'] if c['id']=='thickness' and c['state']=='confirmed'),None)
    if not card:
        return None
    actual = measure(card['found_value'],card['found_unit'])
    if actual != measure(str(group['height']),'см'):
        return None
    selected = {sid for item in result.get('items',[]) if item['state']=='confirmed'
        and item.get('project_source_ids') and 'normative:applicability' in item.get('claim_ids',[])
        for sid in item.get('normative_source_ids',[])}
    for source in result['sources']:
        if source['kind']!='normative' or source['id'] not in selected:
            continue
        for match in re.finditer(r'при\s+толщин\w*[^.!?]{0,220}?(более|свыше|не\s+менее|не\s+более)\s*'
                r'(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b[^.!?]{0,180}?нормир\w*\s+в\s+два\s+слоя',source['text'],re.I):
            limit=measure(match[2],match[3])
            roles=set(re.findall(r'нижн|средн|верхн',match[0].casefold()))
            own_roles=set(re.findall(r'нижн|средн|верхн',position.work_name.casefold()))
            if roles and roles!=own_roles:
                continue
            if not actual or not limit or actual[0]!=limit[0]:
                continue
            operator=re.sub(r'\s+',' ',match[1].casefold())
            satisfied={'более':actual[1]>limit[1],'свыше':actual[1]>limit[1],
                'не менее':actual[1]>=limit[1],'не более':actual[1]<=limit[1]}[operator]
            if not satisfied:
                continue
            return dict(topic=TOPIC,state='confirmed',required=True,claim_ids=claims,
                project_source_ids=card['source_ids'],normative_source_ids=[source['id']],
                explanation=f"ПД: {card['found_value']} {card['found_unit']}. Условие источника: «{match[0]}». "
                    f"Условие выполнено; два технологических слоя ВОР {group['first']} + {group['second']} = {group['height']} см соответствуют проектной толщине.")
    return None
