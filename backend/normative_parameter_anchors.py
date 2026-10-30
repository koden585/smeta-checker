"""Typed literal anchors from supplied sources; never engineer applicability."""
import re

from normative_parameters import measure, quoted, construction_conflict


def parameter_candidates(sources):
    result = []
    for source in sources:
        text = source['text']
        if source['kind'] == 'project' and source.get('origin') == 'native':
            roles = list(re.finditer(r'(?:нижн\w*|средн\w*|верхн\w*)\s+сло[йя]\s+основан\w*',text,re.I))
            for match in re.finditer(r'\bh\s*=\s*(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b',text,re.I):
                prior = [r for r in roles if 0 < match.start()-r.start() < 800]
                if not prior:
                    continue
                role = prior[-1]
                scope = text[role.start():match.end()]
                if len(scope) <= 900:
                    result.append(dict(parameter='thickness',value=match[1].replace(',','.'),unit=match[2].lower(),
                        source_id=source['id'],quote=match[0],scope_quote=scope,scope_state='verified'))
        if source['kind'] == 'normative':
            for match in re.finditer(r'Измеритель\s*:?\s*(\d+(?:[.,]\d+)?)\s*(м[23²³]|шт\.?|т|кг)\b',text,re.I):
                result.append(dict(parameter='unit_scale',value=match[1].replace(',','.'),unit=match[2],
                    source_id=source['id'],quote=match[0],scope_quote=match[0],scope_state='verified'))
    return result[:32]


def resolve_anchors(proposals, sources, items, *, work_scope='', height_cm=None, owner_unit=''):
    """Repair a citation only through a unique literal anchor in the SAME source.

    A missing or conflicting engineering scope is never upgraded by this step.
    """
    from workspace_models import NormativeParameterProposal
    candidates = parameter_candidates(sources)
    lookup = {s['id']:s for s in sources}
    for proposal in proposals:
        if proposal.operation != 'direct' or proposal.parameter not in {'thickness','unit_scale'}:
            continue
        source = lookup.get(proposal.source_id)
        if source is None:
            continue
        if quoted(proposal.value,proposal.quote,source['text']) and proposal.scope_quote and proposal.scope_quote in source['text']:
            continue
        matches = [c for c in candidates if c['parameter'] == proposal.parameter and c['source_id'] == proposal.source_id
            and measure(c['value'],c['unit']) == measure(proposal.value,proposal.unit)
            and not construction_conflict(c['scope_quote'],work_scope,height_cm)]
        if len(matches) == 1:
            candidate = matches[0]
            proposal.value,proposal.unit = candidate['value'],candidate['unit']
            proposal.quote,proposal.scope_quote = candidate['quote'],candidate['scope_quote']
    if not any(p.parameter == 'unit_scale' for p in proposals):
        selected = {sid for i in items if 'normative:applicability' in i.claim_ids for sid in i.normative_source_ids}
        matching_units = [c for c in candidates if c['parameter'] == 'unit_scale' and c['source_id'] in selected
            and (value := measure(c['value'],c['unit'])) and (owner := measure('1',owner_unit)) and value[0] == owner[0]]
        values = {measure(c['value'],c['unit']) for c in matching_units}
        if matching_units and len(values) == 1:
            proposals.append(NormativeParameterProposal(**matching_units[0]))
    return proposals
