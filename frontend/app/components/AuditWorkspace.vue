<script setup lang="ts">
import type { SplitterItem } from '@nuxt/ui'
import type {
  WorkspaceDto,
  VersionDto,
  StructureDto,
  StructureNodeDto,
} from '~/generated/types.gen'
import { queueColor, queueLabel, quantityDelta, quantityWithUnit } from '~/utils/presentation'
const props = defineProps<{
    runId: string
    positionIndex: number
    documents: VersionDto[]
    positionCount?: number
  }>(),
  emit = defineEmits<{ close: []; navigate: [index: number] }>(),
  backend = useBackend(),
  open = ref(true),
  mobileTab = ref<'vor' | 'pdf'>('vor'),
  workspace = ref<WorkspaceDto | null>(null),
  structure = ref<StructureDto | null>(null),
  version = ref(''),
  page = ref(1),
  selectedNode = ref(''),
  sourceIndex = ref(0),
  error = ref(''),
  structureError = ref(''),
  busy = ref(true),
  search = ref(''),
  pdfPanel = ref<{ find: (q: string) => Promise<number[]> }>(),
  searchPages = ref<number[]>([]),
  expandedQuotes = ref<Set<number>>(new Set())
const source = computed(() => workspace.value?.evidence[sourceIndex.value]),
  isBasis = computed(
    () =>
      !!source.value &&
      source.value.version_id === version.value &&
      source.value.page === page.value &&
      !selectedNode.value,
  ),
  isLast = computed(
    () => typeof props.positionCount === 'number' && props.positionIndex >= props.positionCount - 1,
  ),
  headerDescription = computed(() =>
    workspace.value
      ? `${workspace.value.row.number} · ${workspace.value.row.name}`
      : 'Открываем позицию…',
  ),
  region = computed(() => (isBasis.value ? source.value?.region : null)),
  pdfs = computed(() => props.documents.filter((v) => v.kind === 'pdf')),
  printed = computed(
    () => structure.value?.pages.find((p) => p.physical_page === page.value)?.printed_page,
  ),
  sheetName = computed(() => workspace.value?.position.position_source?.sheet || ''),
  quantityCell = computed(() => {
    const cells = workspace.value?.row.cells || {},
      row = workspace.value?.row.source_row
    if (typeof row !== 'number') return ''
    // Cells map address -> value; the quantity column letter is unknown here,
    // so show the first address on the source row (stable, no guessing).
    return Object.keys(cells).find((addr) => addr.endsWith(String(row))) || ''
  }),
  verdictOpen = ref(false),
  verdictLead = computed(() => {
    const text = workspace.value?.row.problem || ''
    const end = text.search(/[.?!]\s/)
    return end > 0 ? text.slice(0, end + 1) : text
  }),
  verdictRest = computed(() => {
    const text = workspace.value?.row.problem || ''
    const end = text.search(/[.?!]\s/)
    return end > 0 ? text.slice(end + 1).trim() : ''
  }),
  dossierItems: SplitterItem[] = [
    { slot: 'pdf', minSize: 30, defaultSize: 62 },
    { slot: 'dossier', minSize: 25, defaultSize: 38 },
  ],
  compareDelta = computed(() =>
    quantityDelta(workspace.value?.row.declared_quantity, workspace.value?.row.found_quantity),
  )
let active = true,
  epoch = 0
const kindLabels: Record<string, string> = {
  work: 'Работа',
  volume: 'Объём',
  unit: 'Единица измерения',
  comment: 'Условия',
  reference: 'Ссылка ВОР',
}
const evidenceGroups = computed(() => {
  const groups: { item: WorkspaceDto['evidence'][number]; index: number; kinds: string[] }[] = []
  for (const [index, item] of (workspace.value?.evidence || []).entries()) {
    const group = groups.find(
      (g) =>
        g.item.version_id === item.version_id &&
        g.item.page === item.page &&
        g.item.quote === item.quote,
    )
    if (group) {
      if (!group.kinds.includes(item.kind)) group.kinds.push(item.kind)
    } else groups.push({ item, index, kinds: [item.kind] })
  }
  return groups
})
async function loadStructure() {
  const current = ++epoch
  structure.value = null
  structureError.value = ''
  if (!version.value) return
  try {
    const data = await backend.structure(version.value)
    if (active && current === epoch) structure.value = data
  } catch (e) {
    if (active && current === epoch) structureError.value = readableError(e)
  }
}
function basis(index = sourceIndex.value) {
  sourceIndex.value = index
  const item = workspace.value?.evidence[index]
  if (item) {
    version.value = item.version_id
    page.value = item.page
    selectedNode.value = ''
  }
}
function selectNode(node: StructureNodeDto) {
  page.value = node.physical_start
  selectedNode.value = node.id
}
function changePage(value: number) {
  page.value = value
  selectedNode.value = ''
}
function plainQuote(quote: string) {
  const text = quote
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return text || quote
}
function shortQuote(quote: string) {
  const plain = plainQuote(quote)
  return plain.length > 240 ? `${plain.slice(0, 240)}…` : plain
}
function isNumericCell(value: unknown) {
  if (typeof value !== 'string' && typeof value !== 'number') return false
  const text = String(value).replace(/\s/g, '').replace(',', '.')
  return text !== '' && !Number.isNaN(Number(text))
}
function toggleQuote(index: number) {
  const next = new Set(expandedQuotes.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  expandedQuotes.value = next
}
async function find() {
  if (pdfPanel.value) searchPages.value = await pdfPanel.value.find(search.value)
}
async function downloadSource() {
  if (!workspace.value) return
  try {
    await backend.download(
      backend.contentUrl(workspace.value.vor_version_id) + '?download=true',
      'ВОР.' + (workspace.value.excel ? 'xlsx' : 'csv'),
    )
  } catch (e) {
    error.value = readableError(e)
  }
}
function confirmationText(value: boolean, detail: string) {
  return value ? `Да · ${detail}` : detail
}
const isNarrow = ref(false)
let mediaQuery: MediaQueryList | null = null
function onMediaChange(event: MediaQueryListEvent) {
  isNarrow.value = event.matches
}
watch(version, loadStructure)
watch(
  () => props.positionIndex,
  () => {
    verdictOpen.value = false
    void loadPosition()
  },
)
watch(open, (value) => {
  if (!value) emit('close')
})
async function loadPosition() {
  const current = ++epoch
  busy.value = true
  error.value = ''
  try {
    const data = await backend.workspace(props.runId, props.positionIndex)
    if (!active || current !== epoch) return
    workspace.value = data
    if (workspace.value.evidence.length) basis(0)
    else {
      version.value = pdfs.value[0]?.id || ''
      page.value = 1
    }
  } catch (e) {
    if (active && current === epoch) error.value = readableError(e)
  } finally {
    if (active && current === epoch) busy.value = false
  }
}
onMounted(async () => {
  mediaQuery = window.matchMedia('(max-width: 720px)')
  isNarrow.value = mediaQuery.matches
  mediaQuery.addEventListener('change', onMediaChange)
  await loadPosition()
})
onBeforeUnmount(() => {
  active = false
  epoch++
  mediaQuery?.removeEventListener('change', onMediaChange)
})
</script>
<template>
  <UModal v-model:open="open" fullscreen title="Сверка ВОР с PDF" :description="headerDescription">
    <template #content>
      <div class="aw-dossier">
        <header class="aw-topbar">
          <div class="aw-nav">
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-chevron-left"
              aria-label="Предыдущая позиция"
              :disabled="positionIndex <= 0"
              @click="emit('navigate', positionIndex - 1)"
            />
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-chevron-right"
              aria-label="Следующая позиция"
              :disabled="isLast"
              @click="emit('navigate', positionIndex + 1)"
            />
          </div>
          <div class="aw-heading">
            <p class="aw-position">
              Позиция №{{ workspace?.row.number ?? '…' }} ·
              {{ workspace?.row.name ?? 'Открываем позицию…' }}
            </p>
            <p class="aw-subline">
              {{ sheetName || 'Позиция CSV'
              }}{{ quantityCell ? ` · ячейка ${quantityCell}` : '' }} ·
              {{ source?.filename || pdfs[0]?.filename || 'PDF не выбран' }}
            </p>
          </div>
          <UButton
            color="neutral"
            variant="ghost"
            icon="i-lucide-x"
            aria-label="Закрыть сверку"
            @click="open = false"
          >
            Закрыть
          </UButton>
        </header>

        <div
          v-if="busy && !workspace"
          class="aw-loading"
          role="status"
          aria-label="Открываем позицию"
        >
          <USkeleton class="aw-loading-title" />
          <USkeleton class="aw-loading-line" />
          <div class="aw-loading-panes">
            <USkeleton class="aw-loading-pdf" />
            <USkeleton class="aw-loading-side" />
          </div>
        </div>
        <p v-if="error" class="error-box" role="alert">{{ error }}</p>
        <template v-if="workspace">
          <section class="aw-verdict" aria-live="polite">
            <div class="aw-verdict-main">
              <div class="aw-verdict-meta">
                <UBadge
                  :label="queueLabel(workspace.row.queue)"
                  :color="queueColor(workspace.row.queue)"
                  variant="solid"
                  size="md"
                />
                <span class="aw-verdict-queue">
                  Позиция {{ positionIndex + 1
                  }}{{ typeof positionCount === 'number' ? ` из ${positionCount}` : '' }}
                </span>
              </div>
              <h1 class="aw-verdict-title">
                {{ verdictLead }}
              </h1>
              <button
                v-if="verdictRest"
                type="button"
                class="aw-verdict-more"
                :aria-expanded="verdictOpen"
                @click="verdictOpen = !verdictOpen"
              >
                {{ verdictOpen ? 'Скрыть подробности' : 'Подробнее' }}
              </button>
              <p v-if="verdictOpen && verdictRest" class="aw-verdict-rest">{{ verdictRest }}</p>
              <p v-if="verdictOpen && workspace.row.details" class="aw-verdict-details">
                {{ workspace.row.details }}
              </p>
              <p class="aw-verdict-action">{{ workspace.row.action }}</p>
            </div>
            <div class="aw-compare" role="group" aria-label="Сравнение количества">
              <div class="aw-compare-values">
                <span class="aw-compare-side">
                  <span class="aw-compare-label"
                    >ВОР{{ quantityCell ? ` · ${quantityCell}` : '' }}</span
                  >
                  <span class="aw-compare-number">{{
                    quantityWithUnit(workspace.row.declared_quantity, workspace.row.unit)
                  }}</span>
                </span>
                <span
                  class="aw-compare-sign"
                  :class="{
                    match: compareDelta === '±0',
                    diff: compareDelta !== null && compareDelta !== '±0',
                  }"
                  aria-hidden="true"
                  >{{ compareDelta === null ? '→' : compareDelta === '±0' ? '=' : '≠' }}</span
                >
                <span class="aw-compare-side">
                  <span class="aw-compare-label"
                    >ПД{{ source ? ` · стр. ${source.page}` : '' }}</span
                  >
                  <span class="aw-compare-number">{{
                    quantityWithUnit(workspace.row.found_quantity, workspace.row.found_unit)
                  }}</span>
                </span>
              </div>
              <p v-if="compareDelta && compareDelta !== '±0'" class="aw-compare-delta">
                Разница {{ compareDelta }} {{ workspace.row.unit || '' }}
              </p>
            </div>
          </section>

          <div class="aw-tabs" role="group" aria-label="Выбор панели">
            <UButton
              color="neutral"
              :variant="mobileTab === 'vor' ? 'solid' : 'outline'"
              :aria-pressed="mobileTab === 'vor'"
              @click="mobileTab = 'vor'"
            >
              Данные ВОР
            </UButton>
            <UButton
              color="neutral"
              :variant="mobileTab === 'pdf' ? 'solid' : 'outline'"
              :aria-pressed="mobileTab === 'pdf'"
              @click="mobileTab = 'pdf'"
            >
              PDF
            </UButton>
          </div>

          <main class="aw-main" :data-tab="mobileTab">
            <USplitter
              id="workspace-dossier-splitter"
              auto-save-id="workspace-dossier-splitter"
              :items="dossierItems"
              :orientation="isNarrow ? 'vertical' : 'horizontal'"
              class="aw-splitter"
            >
              <template #pdf>
                <div class="aw-pdf">
                  <UCollapsible>
                    <UButton
                      :label="`Оглавление ПД${structure ? ` · ${structure.pages.length} стр.` : ''} (текущая: стр. ${page})`"
                      color="neutral"
                      variant="soft"
                      trailing-icon="i-lucide-chevron-down"
                      block
                      class="group"
                      :ui="{
                        trailingIcon:
                          'group-data-[state=open]:rotate-180 transition-transform duration-200',
                      }"
                    />
                    <template #content>
                      <div class="aw-outline-panel">
                        <USelect
                          v-model="version"
                          :items="pdfs.map((v) => ({ label: v.filename, value: v.id }))"
                          aria-label="Проектный PDF"
                          class="w-full"
                        />
                        <OutlineTree
                          :data="structure"
                          :page="page"
                          :selected-id="selectedNode"
                          :error="structureError"
                          @select="selectNode"
                        />
                      </div>
                    </template>
                  </UCollapsible>

                  <div class="aw-pdf-toolbar">
                    <div class="aw-pdf-search">
                      <UInput
                        v-model="search"
                        placeholder="Текст в PDF"
                        aria-label="Поиск в PDF, Enter для поиска"
                        size="sm"
                        icon="i-lucide-search"
                        @keyup.enter="find"
                      />
                    </div>
                  </div>
                  <p v-if="searchPages.length" class="muted">
                    Найдено на страницах: {{ searchPages.join(', ') }}
                  </p>
                  <UAlert
                    v-if="source && !isBasis"
                    color="warning"
                    variant="soft"
                    title="Просмотр другой страницы. Заключение по позиции не изменилось."
                    :description="`Открыта стр. ${page}, основание — на стр. ${source.page}. Вердикт «${queueLabel(workspace.row.queue)}» относится к позиции, а не к открытому листу.`"
                  />
                  <p v-if="region && !region.highlights.length" class="muted">
                    Совпадение не подсвечено — листайте страницу вручную
                  </p>

                  <PdfPanel
                    v-if="version"
                    ref="pdfPanel"
                    :key="version"
                    :source-url="backend.contentUrl(version)"
                    :page="page"
                    :region="region"
                    @page="changePage"
                  />
                  <p v-else class="empty">Для этого аудита PDF не выбран.</p>
                  <p class="aw-filename">{{ source?.filename || pdfs[0]?.filename }}</p>
                </div>
              </template>

              <template #dossier>
                <div class="aw-dossier-pane excel-pane">
                  <section aria-label="Основания">
                    <h2 class="aw-section-title">Основания · {{ evidenceGroups.length }}</h2>
                    <p v-if="!evidenceGroups.length" class="muted">
                      Подтверждённый источник не установлен. Документ слева открыт для ручной
                      сверки.
                    </p>
                    <div class="aw-evidence-list">
                      <UCard
                        v-for="group in evidenceGroups"
                        :key="group.index"
                        :ui="{ body: 'p-3 sm:p-3' }"
                        :style="group.item.confirmed ? undefined : 'border-color: var(--ui-error)'"
                      >
                        <div class="aw-evidence-meta">
                          <UBadge
                            v-for="kind in group.kinds"
                            :key="kind"
                            :label="kindLabels[kind] || kind"
                            color="neutral"
                            variant="soft"
                          />
                          <span class="aw-evidence-page">стр. {{ group.item.page }}</span>
                          <UBadge
                            :label="group.item.confirmed ? 'Подтверждено' : 'Не подтверждено'"
                            :color="group.item.confirmed ? 'success' : 'error'"
                            variant="soft"
                          />
                        </div>
                        <blockquote class="aw-quote">
                          «{{
                            expandedQuotes.has(group.index)
                              ? plainQuote(group.item.quote)
                              : shortQuote(group.item.quote)
                          }}»
                        </blockquote>
                        <div class="aw-evidence-actions">
                          <UButton
                            label="К основанию"
                            icon="i-lucide-crosshair"
                            color="primary"
                            variant="soft"
                            size="xs"
                            @click="basis(group.index)"
                          />
                          <UButton
                            v-if="group.item.quote.length > 240"
                            :label="
                              expandedQuotes.has(group.index) ? 'Свернуть' : 'Показать полностью'
                            "
                            color="neutral"
                            variant="ghost"
                            size="xs"
                            @click="toggleQuote(group.index)"
                          />
                          <span class="aw-evidence-file">{{ group.item.filename }}</span>
                        </div>
                      </UCard>
                    </div>
                  </section>

                  <section aria-label="Таблица ВОР">
                    <h2 class="aw-section-title aw-table-head">
                      <span>
                        {{ sheetName || 'Позиция CSV' }} ·
                        {{ quantityCell || workspace.row.number }}
                      </span>
                      <UButton
                        icon="i-lucide-download"
                        color="neutral"
                        variant="ghost"
                        size="xs"
                        aria-label="Скачать исходную ВОР"
                        title="Скачать исходную ВОР"
                        @click="downloadSource"
                      />
                    </h2>
                    <div v-if="workspace.excel" class="sheet-scroll">
                      <table class="sheet">
                        <thead>
                          <tr>
                            <th scope="col">Строка</th>
                            <th v-for="col in workspace.excel.columns" :key="col" scope="col">
                              {{ col }}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr
                            v-for="row in workspace.excel.rows"
                            :key="row.number"
                            :class="{ selected: row.selected }"
                          >
                            <th scope="row">{{ row.number }}</th>
                            <td
                              v-for="cell in row.cells"
                              :key="cell.coordinate"
                              :colspan="cell.column_span"
                              :rowspan="cell.row_span"
                              :class="{
                                question: cell.highlight,
                                numbers: isNumericCell(cell.value),
                              }"
                            >
                              {{ cell.value }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                    <div v-else class="panel aw-fallback">
                      <p>{{ workspace.position.work_name }}</p>
                      <p>{{ workspace.position.reference }}</p>
                      <p>{{ workspace.position.formula }}</p>
                    </div>
                  </section>
                </div>
              </template>
            </USplitter>
          </main>
        </template>
      </div>
    </template>
  </UModal>
</template>
<style scoped>
.aw-dossier {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--ui-bg-muted);
  color: var(--ui-text);
}
.aw-loading {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px 16px;
  flex: 1;
  min-height: 0;
}
.aw-loading-title {
  height: 28px;
  width: min(420px, 70%);
}
.aw-loading-line {
  height: 16px;
  width: min(560px, 85%);
}
.aw-loading-panes {
  display: grid;
  grid-template-columns: 62fr 38fr;
  gap: 12px;
  flex: 1;
  min-height: 280px;
}
.aw-topbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--ui-bg-elevated);
  border-bottom: 1px solid var(--ui-border);
}
.aw-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}
.aw-heading {
  min-width: 0;
  flex: 1;
}
.aw-position {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ui-text-highlighted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.aw-subline {
  margin: 0;
  font-size: 12px;
  color: var(--ui-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.aw-verdict {
  border-bottom: 1px solid var(--ui-border);
  padding: 12px 16px;
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: flex-start;
}
.aw-verdict-main {
  min-width: min(100%, 420px);
  flex: 1;
}
.aw-verdict-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.aw-verdict-queue {
  font-size: 12px;
  color: var(--ui-text-muted);
}
.aw-verdict-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.35;
}
.aw-verdict-action {
  margin: 4px 0 0;
  font-size: 14px;
  color: var(--ui-text);
}
.aw-compare {
  margin: 0;
  padding: 10px 14px;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  background: var(--ui-bg-elevated);
  flex: 0 1 340px;
}
.aw-compare-values {
  display: flex;
  align-items: center;
  gap: 12px;
}
.aw-compare-side {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.aw-compare-label {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--ui-text-muted);
  white-space: nowrap;
}
.aw-compare-number {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.15;
  color: var(--ui-text-highlighted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.aw-compare-sign {
  font-size: 24px;
  font-weight: 700;
  color: var(--ui-text-muted);
  flex-shrink: 0;
}
.aw-compare-sign.match {
  color: var(--ui-success);
}
.aw-compare-sign.diff {
  color: var(--ui-error);
}
.aw-compare-delta {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--ui-text-muted);
  font-variant-numeric: tabular-nums;
}
.aw-verdict-more {
  background: none;
  border: none;
  padding: 0;
  margin-top: 6px;
  color: var(--ui-primary);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}
.aw-verdict-more:hover {
  text-decoration: underline;
}
.aw-verdict-rest {
  margin: 6px 0 0;
  font-size: 15px;
  line-height: 1.5;
  color: var(--ui-text-muted);
}
.aw-verdict-details {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ui-text-muted);
  overflow-wrap: anywhere;
}
.aw-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.aw-tabs {
  display: none;
  gap: 12px;
  padding: 12px 16px 0;
}
.aw-main {
  flex: 1;
  min-height: 0;
  padding: 12px 16px 16px;
}
.aw-splitter {
  height: 100%;
  min-height: 560px;
}
.aw-splitter :deep([role='separator']) {
  width: 1px;
  background: var(--ui-border);
  margin-inline: 6px;
}
.aw-splitter :deep([role='separator']:hover),
.aw-splitter :deep([role='separator']:focus-visible) {
  background: var(--ui-primary);
}
.aw-pdf {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
  padding-right: 0;
}
.aw-outline-panel {
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  background: var(--ui-bg-elevated);
  padding: 8px;
  margin-top: 8px;
  display: grid;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}
.aw-pdf-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  background: var(--ui-bg-elevated);
  font-size: 14px;
}
.aw-page {
  font-size: 13px;
  color: var(--ui-text-muted);
  font-variant-numeric: tabular-nums;
}
.aw-pdf-search {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: min(100%, 280px);
}
.aw-filename {
  margin: 0;
  font-size: 12px;
  color: var(--ui-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.aw-dossier-pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  flex: 1;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding-left: 0;
}
.aw-section-title {
  margin: 0 0 6px;
  font-size: 14px;
  font-weight: 700;
  color: var(--ui-text-highlighted);
}
.aw-evidence-list {
  display: grid;
  gap: 8px;
}
.aw-evidence-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.aw-evidence-page {
  font-size: 12px;
  color: var(--ui-text-muted);
  font-variant-numeric: tabular-nums;
}
.aw-quote {
  margin: 0;
  padding-left: 8px;
  border-left: 2px solid var(--ui-primary);
  font-size: 14px;
  line-height: 1.5;
  color: var(--ui-text);
  overflow-wrap: anywhere;
}
.aw-evidence-actions {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.aw-evidence-file {
  margin-left: auto;
  max-width: 100%;
  font-size: 11px;
  color: var(--ui-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sheet-scroll {
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
}
.sheet {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  background: var(--ui-bg-elevated);
}
.sheet thead {
  position: sticky;
  top: 0;
  background: var(--ui-bg-muted);
}
.sheet th,
.sheet td {
  border: 1px solid var(--ui-border);
  padding: 4px 8px;
  text-align: left;
  vertical-align: top;
  font-variant-numeric: tabular-nums;
}
.sheet td.numbers,
.sheet th.numbers {
  text-align: right;
}
.sheet thead th {
  color: var(--ui-text-muted);
  font-weight: 600;
}
.sheet tbody th {
  color: var(--ui-text-muted);
  font-variant-numeric: tabular-nums;
}
.sheet tbody tr.selected {
  background: var(--app-selected-bg);
}
.sheet .question {
  background: var(--app-warning-bg);
  color: var(--app-warning-text);
}
.aw-fallback {
  padding: 16px;
  font-size: 14px;
}
@media (max-width: 720px) {
  .aw-topbar {
    flex-wrap: wrap;
  }
  .aw-heading {
    order: 3;
    flex-basis: 100%;
  }
  .aw-tabs {
    display: flex;
  }
  .aw-main[data-tab='vor'] .aw-splitter > :has(> .aw-pdf),
  .aw-main[data-tab='pdf'] .aw-splitter > :has(> .aw-dossier-pane),
  .aw-main [role='separator'] {
    display: none;
  }
  .aw-splitter {
    min-height: 0;
  }
  .aw-pdf,
  .aw-dossier-pane {
    padding: 0;
  }
  .aw-verdict {
    padding: 12px;
  }
}
</style>
