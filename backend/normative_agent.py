"""Bounded evidence acquisition over the frozen matching corpus.

Retrieval never scores expected VOR quantities. Tools expose immutable page,
table and cell identities; the model chooses scope, the server owns evidence.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PIPELINE_VERSION = 3
MAX_ROUNDS = 3
MAX_CONTEXT = 58000


def cell_source_id(version, page, table_id, cell_id):
    import hashlib
    namespace = hashlib.sha256(f'{version}:{page}:{table_id}:{cell_id}'.encode()).hexdigest()[:24]
    return f'agent:p{page}:cell:{namespace}'


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool: Literal['search_project', 'search_tables', 'read_page', 'read_source', 'read_table', 'search_norms', 'sum_cells']
    query: str = Field(default='', max_length=300)
    page: int = Field(default=1, ge=1)
    table_id: str = Field(default='', max_length=200)
    offset: int = Field(default=0, ge=0, le=1000000)
    operand_ids: list[str] = Field(default_factory=list, max_length=12)
    unit: str = Field(default='', max_length=30)
    source_id: str = Field(default='', max_length=200)
    row_ids: list[int] = Field(default_factory=list, max_length=12)
    column_ids: list[int] = Field(default_factory=list, max_length=32)


TOOLS = """
Ты работаешь как агент проверки. Если источников недостаточно, верни requests
и пустые items/parameters; не завершай проверку только потому, что первоначальная
выдержка не содержит таблицу. До 4 requests за шаг:
search_project(query): смысл работы/конструкция/участок, без ожидаемого числа ВОР;
search_tables(query): ведомости объёмов, площади, количества и заголовки таблиц;
read_page(page, offset): следующие 3500 символов физической страницы;
read_source(source_id, offset): дочитать конкретный источник; его текст не исчезает;
read_table(page, table_id, row_ids, column_ids): точные строки и столбцы с заголовками
и ID ячеек. Каталог tables содержит columns и total_rows. Для общего количества
читай итоговые строки, а не первые строки заголовка. Различай Итог по участку и Всего.
Одинаковое число в колонке другого материала не является основанием.
search_norms(query): нормативный пункт, термин или код.
sum_cells(operand_ids, unit): сумма 2–12 числовых ячеек с одной единицей
из заголовков. operand_ids — source_id, полученные read_table. Сначала
установи одинаковый участок и конструкцию; разные столбцы итогов не складывай.
Ответ JSON включает summary, items, parameters, requests (по умолчанию []).
Поиск не доказывает отсутствия данных. coverage указывает неполный OCR.
Числа связывай с одной конструкцией и участком, заголовком и единицей.
Для суммы перечисли все слагаемые и источники; не подгоняй сумму под ВОР.
Сумму можно вернуть сразу в parameters: operation="sum", operand_source_ids —
точные ID числовых ячеек, value — полученная сумма, unit — единица заголовка.
Программа сама пересчитает и проверит операнды без дополнительного запроса модели.
В каждом parameters для quantity/thickness передай scope_state="verified" и
scope_quote — точную короткую цитату того же участка/конструкции/слоя, ВКЛЮЧАЯ
число и единицу. Цитата от другого слоя недопустима. Если принадлежность
не установлена, scope_state="unresolved"; такую величину нельзя сравнивать.
Перед итогом needs_facts по количеству обязательно выполни search_tables,
а обрезанное основание дочитай read_source. remaining_steps учитывает запросы модели.
Окончательный ответ допустим только без requests. На последнем шаге дай
обоснованный вывод либо конкретные недостающие факты. Технический сбой не ошибка ВОР.
"""


def compact(inputs, sources, preferred=()):
    """Exclude bulky untrusted fact graphs, retaining claim identity and state."""
    value = deepcopy(inputs)
    value['matching_checks'] = [
        {k: c[k] for k in ('claim_id', 'kind', 'state', 'required', 'reasons') if k in c}
        for c in value.get('matching_checks', [])]
    value['sources'] = []
    # Exact reads first, then search previews. Registry remains intact; adding
    # a table never shrinks a previously selected paragraph to 750 characters.
    preferred = set(preferred)
    ordered = sorted(enumerate(sources), key=lambda item: (item[1]['id'] not in preferred, -item[0]))
    remaining = max(0, min(37000, MAX_CONTEXT-len(json.dumps(value, ensure_ascii=False))-8000))
    for _, source in ordered:
        brief = {k: source[k] for k in ('id', 'kind', 'page', 'label', 'version_id', 'source_id', 'origin',
            'numeric_verified','unit_verified','unit') if k in source}
        text = str(source.get('text', ''))
        allowance = min(len(text), 7000 if source['id'] in preferred else 1500 if source.get('kind') == 'normative' else 500, max(0, remaining-300))
        if allowance == 0:
            continue
        brief.update(text=text[:allowance], excerpt_truncated=len(text) > allowance,
            full_length=len(text), next_offset=allowance if len(text) > allowance else None)
        value['sources'].append(brief)
        remaining -= allowance+300
    value['pipeline_version'] = PIPELINE_VERSION
    if len(json.dumps(value, ensure_ascii=False)) > MAX_CONTEXT:
        # Explicitly fail before spending quota; never silently drop claim IDs.
        raise ValueError('Agent context metadata exceeds budget')
    return value


class EvidenceTools:
    def __init__(self, context, record, index, sources, kb, facts):
        self.sources, self.kb, self.facts = sources, kb, facts
        self.cells = {}
        self.index: Any = None
        self.events = []
        self.preferred = []
        self.table_search_done = False
        self.snapshot_refs = []
        self.coverage: dict[str, Any] = {}
        self.blob_store = context.blob_store
        self.filename = 'Подготовленный ПД'
        self.version = None
        try:
            job = context.repository.load_position_job(record['id'], index)
        except KeyError:
            self.coverage = dict(state='snapshot_unavailable', pending_ocr_pages=[], error_pages=[])
            return
        payload = job.payload
        self.filename = payload.get('pdf_name') or self.filename
        pins = record['config'].get('pdf_versions') or {}
        self.version = pins.get(self.filename)
        # Do not attach a prepared corpus to an arbitrary document version.
        if self.version is None and len(set(pins.values())) == 1:
            self.version = next(iter(pins.values()))
        from audit_snapshot import load_snapshot
        self.index = load_snapshot(context.blob_store, payload['snapshot'])
        jobs = context.repository.list_position_jobs(record['id'], include_results=False)
        self.snapshot_refs = [j.payload['snapshot'] for j in reversed(jobs)
            if j.payload.get('pdf_name') == self.filename and j.payload.get('snapshot')
            and (j.payload.get('pdf_versions') or {}).get(self.filename) == self.version]
        if self.snapshot_refs:
            later = load_snapshot(context.blob_store, self.snapshot_refs[0])
            same_extraction = all(later.metadata.get(k) == self.index.metadata.get(k)
                for k in ('pdf_sha256', 'extraction_key', 'ocr_settings_key'))
            if same_extraction and len(later.pending_ocr) < len(self.index.pending_ocr):
                self.index = later
        refreshed = (record['config'].get('normative_corpora') or {}).get(self.version)
        if refreshed:
            latest = load_snapshot(context.blob_store, refreshed)
            if latest.metadata.get('pdf_sha256') != self.index.metadata.get('pdf_sha256'):
                raise ValueError('Prepared normative corpus belongs to another PDF')
            self.index = latest
            self.snapshot_refs.insert(0, refreshed)
        prepared_tables: Any = self.index.tables
        if record['config'].get('document_preparation_version') and (
            self.index.pending_ocr or not self.index.metadata.get('preparation_complete')
        ):
            raise ValueError('Normative checks require a fully prepared document')
        catalogue = [dict(page=p+1, table_id=t['table_id'], rows=t['row_count'], columns=t['col_count'],
            total_rows=sorted({c['row'] for c in t['cells'] if c['text'].strip().casefold().rstrip(':') in {'всего','итог','итого'}}))
            for p, tables in enumerate(prepared_tables or []) for t in tables]
        self.coverage = dict(state='prepared', pages=len(self.index.texts),
            pending_ocr_pages=[p+1 for p in self.index.pending_ocr],
            error_pages=[int(p)+1 for p in self.index.errors],
            available_tables=catalogue[:80], available_table_count=len(catalogue),
            table_catalog_truncated=len(catalogue)>80)

    def _add(self, source):
        existing = next((s for s in self.sources if s['id'] == source['id']), None)
        if existing is None:
            if len(self.sources) >= 1024:
                return {'error': 'source_budget_exhausted'}
            self.sources.append(source)
        return {'source_id': source['id']}

    def quantity_candidates(self, query, *, unit='', height_cm=None) -> list[dict[str, Any]]:
        """Precompute bounded alternatives; never use the declared VOR amount."""
        if self.index is None or not self.version:
            return []
        from normative_table_candidates import grouped_totals
        ranked = []
        # Coverage is a bounded MODEL preview, not an internal search index.
        # Drawing frames can fill that preview before quantity schedules at
        # the end of a large PDF. Search every prepared table exactly once.
        for page, tables in enumerate(self.index.tables or []):
            for table in tables:
                for candidate in grouped_totals(table, query, unit=unit, height_cm=height_cm):
                    ranked.append(dict(**candidate, page=page+1, table_id=table['table_id']))
        ranked.sort(key=lambda c: -c['score'])
        for candidate in ranked[:4]:
            result = self.execute(EvidenceRequest(tool='read_table', page=candidate['page'],
                table_id=candidate['table_id'], row_ids=[candidate['row']], column_ids=candidate['columns']))
            candidate['operand_source_ids'] = [c['source_id'] for c in result['rows'] if 'source_id' in c]
        return ranked[:4]

    def execute(self, request):
        if request.tool == 'read_source':
            source = next((s for s in self.sources if s['id'] == request.source_id), None)
            if source is None:
                return {'error': 'unknown_source'}
            text = source['text']
            self.preferred.append(source['id'])
            if request.offset:
                source = {**source, 'id':source['id']+f':part:{request.offset}', 'text':text[request.offset:request.offset+3500]}
                self.preferred.append(source['id'])
                return self._add(source)
            return {'source_id': source['id'], 'full_length':len(text)}
        if request.tool == 'sum_cells':
            return self._sum(request)
        if request.tool == 'search_norms':
            from normative_service import candidate
            results = []
            for hit in self.kb.search(request.query, kind='ALL', facts=self.facts, limit=3):
                item = candidate(self.kb, hit, self.facts)
                if not item['citations']:
                    continue
                ref = item['citations'][0]
                source = dict(id='agent:n:'+str(item['id']), kind='normative',
                    source_id=ref['source_id'], page=ref['page'], label=item['designation']+' · '+item['code'],
                    origin=item['extraction_status'], text=item['text'][:2800])
                results.append(self._add(source))
            return {'results': results}
        if self.index is None or not self.version:
            return {'error': 'prepared_corpus_unavailable', 'coverage': self.coverage}
        if request.tool in {'search_project', 'search_tables'}:
            from normative_retrieval import DocumentSearch
            self.table_search_done |= request.tool == 'search_tables'
            ranked = DocumentSearch(self.index.texts).search(request.query, tables=request.tool == 'search_tables')
            pages = []
            for hit in ranked:
                pages.append(dict(**self._page(hit['page'], hit['offset']), preview=hit['preview']))
            return {'pages': pages, 'coverage': self.coverage}
        if request.page > len(self.index.texts):
            return {'error': 'page_out_of_range'}
        if request.tool == 'read_page':
            return self._page(request.page, request.offset, exact=True)
        tables = self._tables(request.page)
        table = next((t for t in tables if t['table_id'] == request.table_id), None)
        if not request.table_id and len(tables) == 1:
            table = tables[0]
        if table is None:
            return {'error': 'unknown_table', 'table_ids': [t['table_id'] for t in tables]}
        cells = table['cells']
        selected = [c for c in cells if (c['row'] in request.row_ids if request.row_ids else request.offset <= c['row'] < request.offset+4)
            and (not request.column_ids or c['column'] in request.column_ids)]
        output = []
        for cell in selected:
            header_text = ' | '.join(str(h['text']) for h in cells if h['cell_id'] in cell.get('header_ids', []))
            from pdf_cell_ocr import column_unit
            resolved_unit = column_unit(table, cell)
            if resolved_unit:
                header_text += '\nЕдиница физического столбца: '+resolved_unit
            text = header_text
            row = sorted((c for c in cells if c['row'] == cell['row'] and c['column'] < 2), key=lambda c: c['column'])
            text += '\n' + ' | '.join(str(c['text']) for c in row) + '\n' + cell['text']
            cell_id = cell_source_id(self.version, request.page, table['table_id'], cell['cell_id'])
            self.cells[cell_id] = dict(cell=cell, headers=text, header_text=header_text, page=request.page,unit=resolved_unit)
            geometry = (getattr(self.index, 'metadata', {}).get('page_geometry') or {}).get(str(request.page-1))
            rects = []
            if geometry and cell.get('bbox'):
                from ocr_engine import _apply_matrix
                box = _apply_matrix(cell['bbox'], geometry['matrix'])
                rects = [[max(0,min(1,box[0]/geometry['width'])),max(0,min(1,box[1]/geometry['height'])),
                    max(0,min(1,box[2]/geometry['width'])),max(0,min(1,box[3]/geometry['height']))]]
            output.append(self._add(dict(id=cell_id, kind='project',
                version_id=self.version, page=request.page, label=self.filename,
                text=text, rects=rects, numeric_verified=bool(cell.get('numeric_verified')),
                unit_verified=bool(resolved_unit),unit=resolved_unit,
                origin=(cell.get('origin', 'native') if cell.get('quality', 'usable') == 'usable' else 'uncertain_table'))))
        from normative_retrieval import terms
        wanted = terms(request.query)
        matching_rows = sorted({c['row'] for c in cells if wanted & terms(c['text'])})[:20]
        return {'cells': output, 'matching_rows': matching_rows, 'columns': table_outline(table)['columns'], 'rows': [dict(**{k: c[k] for k in ('cell_id', 'row', 'column', 'text', 'header_ids', 'bbox', 'quality', 'numeric_verified') if k in c},
            **output[i]) for i,c in enumerate(selected)], 'next_offset': request.offset+4, 'row_count': table['row_count']}

    def _sum(self, request):
        from normative_parameters import number, measure
        ids = request.operand_ids
        if not 2 <= len(ids) <= 12 or len(set(ids)) != len(ids) or not request.unit:
            return {'error': 'distinct_numeric_operands_and_unit_required'}
        cells = [self.cells.get(i) for i in ids]
        if any(c is None for c in cells):
            return {'error': 'unknown_cell'}
        cells = [c for c in cells if c is not None]
        if any((c['cell'].get('origin') == 'ocr' and not c['cell'].get('numeric_verified'))
                or c['cell'].get('quality', 'usable') != 'usable' for c in cells):
            return {'error': 'uncertain_cells_require_image_verification'}
        values = [number(c['cell']['text']) for c in cells]
        if any(v is None for v in values) or any(not c['unit'] or measure('1',request.unit) != measure('1',c['unit']) for c in cells):
            return {'error': 'numeric_cell_or_header_unit_unresolved'}
        values = [v for v in values if v is not None]
        if len({c['page'] for c in cells}) != 1:
            return {'error': 'cross_page_sum_requires_separate_scope_validation'}
        total = sum(values, Decimal(0))
        context = '\n'.join(dict.fromkeys(c.get('header_text', '') for c in cells))
        text = context + '\n' + ' + '.join(str(v) for v in values) + f' = {total} {request.unit}. Ячейки: ' + ', '.join(ids)
        result = self._add(dict(id='agent:sum:'+str(len(self.sources)), kind='project',
            page=cells[0]['page'], version_id=self.version, label=self.filename, origin='calculated_from_cells', text=text,
            numeric_verified=True,unit_verified=True,unit=request.unit,
            rects=[rect for source in self.sources if source['id'] in ids for rect in source.get('rects', [])][:40]))
        return dict(**result, equation=text, value=str(total), operands=ids, scope_verified=False)

    def _page(self, page, offset, *, exact=False):
        assert self.index is not None
        text = self.index.texts[page-1]
        # Retrieve the hit itself, not always the first paragraph of a long page.
        piece = text[offset:offset+3500]
        ref = self._add(dict(id=f'agent:p{page}:{offset}', kind='project', page=page,
            version_id=self.version, label=self.filename, text=piece,
            origin='ocr_unverified' if (self.index.quality.get(page-1) or {}).get('origin') == 'ocr' else 'native'))
        if exact:
            self.preferred.append(ref.get('source_id', ''))
        tables = self._tables(page)
        return dict(**ref, page=page, next_offset=offset+3500 if offset+3500 < len(text) else None,
            tables=[table_outline(t) for t in tables])

    def _tables(self, page):
        """Read shared, SHA-verified prepared pages, never repeat PDF extraction.

        Early positions freeze before later CPU slices finish. Reuse tables
        prepared for sibling positions of the same pinned PDF instead of
        treating the early snapshot's missing table as missing project data.
        """
        tables = self.index.tables[page-1] if self.index.tables else []
        if tables:
            return tables
        from audit_snapshot import load_json, load_snapshot
        for ref in self.snapshot_refs:
            if ref.get('snapshot_storage') == 'pages-v1':
                manifest = load_json(self.blob_store, dict(key=ref['snapshot_key'], sha256=ref['snapshot_sha256']), cache_page=True)
                if manifest.get('format') != 'page-snapshot-v1':
                    raise ValueError('Invalid shared page manifest')
                if page > len(manifest['pages']):
                    continue
                prepared = load_json(self.blob_store, manifest['pages'][page-1], cache_page=True)
                tables = prepared.get('tables', [])
            else:
                other = load_snapshot(self.blob_store, ref)
                tables = other.tables[page-1] if other.tables else []
            if tables:
                return tables
        return []


def table_outline(table):
    """Expose complete column ancestry and total row addresses before a paid read."""
    headers = [c for c in table['cells'] if c.get('role') == 'header' and c['text'].strip()]
    columns = []
    for column in range(table['col_count']):
        path = list(dict.fromkeys(c['text'] for c in headers
            if c['column'] <= column < c['column']+c.get('colspan', 1)
            and c.get('colspan', 1) < table['col_count']))
        columns.append(dict(column=column, headers=path))
    totals = [dict(row=c['row'], label=c['text']) for c in table['cells']
        if c['text'].strip().casefold().rstrip(':') in {'всего','итог','итого'}]
    return dict(table_id=table['table_id'], rows=table['row_count'], column_count=table['col_count'],
        columns=columns, total_rows=sorted({c['row'] for c in totals}), total_labels=totals)


def run(ask, client, credentials, instructions, inputs, schema, trace, stats, tools):
    """At most three model calls; failed acquisition cannot become a verdict."""
    started = time.monotonic()
    history = []
    for step in range(MAX_ROUNDS):
        supplied = compact(inputs, tools.sources, tools.preferred)
        bounded_history = deepcopy(history)
        for event in bounded_history:
            result = event['result']
            if 'rows' in result:
                # Every structured row already carries source_id; avoid a
                # second list of the same IDs and verbose drawing geometry.
                result.pop('cells', None)
                result['rows'] = [{k:v for k,v in row.items() if k not in {'bbox','cell_id'}} for row in result['rows']]
            if len(json.dumps(event, ensure_ascii=False)) > 3500:
                result['rows_in_source_excerpts'] = True
        supplied.update(coverage=tools.coverage, tool_results=bounded_history, remaining_steps=MAX_ROUNDS-step-1)
        stage = 'normative-evidence-plan' if step == 0 else f'normative-evidence-{step}'
        step_instructions = instructions+TOOLS
        if step == 0 and MAX_ROUNDS > 1:
            # Navigation is a separate bounded task, not a full audit of every
            # preliminary claim before the underlying table has been read.
            supplied['sources'] = [{**source, 'text':source['text'][:450],
                'excerpt_truncated':len(source['text'])>450 or source['excerpt_truncated']} for source in supplied['sources']]
            step_instructions = TOOLS + '\nСейчас ТОЛЬКО выбери до четырёх точных чтений. Приоритет: проектная конструкция, итоговые строки ведомости с подходящими заголовками columns, затем норматив. Используй row_ids из total_rows и column_ids подходящего материала/единицы. Начало таблицы без чисел не заменяет чтение итогов. Не проверяй всю позицию на этом шаге. summary до 200 символов, items=[], parameters=[], requests. На следующем шаге выполни проверку по полученным данным.'
            step_instructions += '\nvor_layer_group.height — сумма технологических слоёв одной конструкции ВОР в см; выбирай проектный столбец полной толщины, а не требуй отдельный столбец каждой технологической операции.'
        if step == MAX_ROUNDS-1:
            step_instructions += '\nЭто ОКОНЧАТЕЛЬНЫЙ шаг: requests=[] обязательно. Не ищи снова. Сохрани найденные факты, точные ID ячеек и параметры; непроверенные аспекты — needs_facts с конкретной причиной, не ошибка ВОР. summary до 600 символов, до 5 items с пояснениями до 350 символов.'
        supplied['archived_source_ids'] = []
        while len(json.dumps(supplied, ensure_ascii=False)) > MAX_CONTEXT and len(supplied['sources']) > 1:
            source = supplied['sources'].pop()
            supplied['archived_source_ids'].append(source['id'])
        if len(json.dumps(supplied, ensure_ascii=False)) > MAX_CONTEXT:
            raise ValueError('Agent tool results exceed budget')
        answer = ask(client, credentials, step_instructions, supplied, schema, trace, stage, stats)
        requests = getattr(answer, 'requests', [])
        if not requests:
            unresolved_quantity = any(v.state == 'needs_facts' and set(v.claim_ids) & {'quantity', 'unit'} for v in getattr(answer, 'items', []))
            if unresolved_quantity and not tools.table_search_done:
                if step == MAX_ROUNDS-1:
                    raise TimeoutError('Quantity search incomplete: table discovery not performed')
                requests = [EvidenceRequest(tool='search_tables', query=str(inputs.get('position', {}).get('work', ''))[:300])]
            else:
                return answer
        if step == MAX_ROUNDS-1 and getattr(answer, 'items', []):
            # Preserve useful partial evidence without granting a confirmed
            # verdict while the model still requests additional source reads.
            pending = ', '.join(r.tool for r in requests)
            stats.setdefault('missing_facts', []).append('Не завершён поиск источников: '+pending)
            for item in answer.items:
                if item.state == 'confirmed':
                    item.state = 'needs_facts'
                    item.explanation += ' Поиск связанных источников не завершён.'
            answer.requests = []
            return answer
        if step == MAX_ROUNDS-1 or time.monotonic()-started > 120:
            raise TimeoutError('Evidence acquisition budget exhausted')
        history = []
        for request in requests:
            result = tools.execute(request)
            # Table row text is carried by source IDs; keep the reply bounded.
            history.append(dict(request=request.model_dump(), result=result))
        tools.events.extend(history)
        stats.setdefault('queries', []).extend(f'{r.tool}: {r.query or r.page}' for r in requests)
    raise RuntimeError('Agent did not finish')
