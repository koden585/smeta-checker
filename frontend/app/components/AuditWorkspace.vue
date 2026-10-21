<script setup lang="ts">
import type { SplitterItem } from '@nuxt/ui'
import type {
  WorkspaceDto,
  VersionDto,
  StructureDto,
  StructureNodeDto,
  FormatDto,
} from '~/generated/types.gen'
import { queueColor, queueLabel, quantityWithUnit } from '~/utils/presentation'
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
  formatting = ref<FormatDto | null>(null),
  formatOpen = ref(false),
  formatError = ref(''),
  checking = ref(false),
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
  verdictTone = computed(() => {
    const tones = {
      fix: { bg: 'var(--app-error-bg)', text: 'var(--app-error-text)' },
      review: { bg: 'var(--app-warning-bg)', text: 'var(--app-warning-text)' },
      missing: { bg: 'var(--ui-bg-muted)', text: 'var(--ui-text-muted)' },
      ok: { bg: 'var(--app-success-bg)', text: 'var(--app-success-text)' },
    } as const
    return tones[workspace.value?.row.queue as keyof typeof tones] ?? tones.missing
  }),
  dossierItems: SplitterItem[] = [
    { slot: 'pdf', minSize: 30, defaultSize: 62 },
    { slot: 'dossier', minSize: 25, defaultSize: 38 },
  ]
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
function shortQuote(quote: string) {
  return quote.length > 240 ? `${quote.slice(0, 240)}…` : quote
}
function toggleQuote(index: number) {
  const next = new Set(expandedQuotes.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  expandedQuotes.value = next
}
async function checkFormat() {
  if (!workspace.value) return
  formatOpen.value = true
  checking.value = true
  formatError.value = ''
  try {
    formatting.value = await backend.formatting(workspace.value.vor_version_id, sheetName.value)
  } catch (e) {
    formatError.value = readableError(e)
  } finally {
    checking.value = false
  }
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
watch(open, (value) => {
  if (!value) emit('close')
})
onMounted(async () => {
  mediaQuery = window.matchMedia('(max-width: 720px)')
  isNarrow.value = mediaQuery.matches
  mediaQuery.addEventListener('change', onMediaChange)
  try {
    workspace.value = await backend.workspace(props.runId, props.positionIndex)
    if (!active) return
    if (workspace.value.evidence.length) basis(0)
    else {
      version.value = pdfs.value[0]?.id || ''
      page.value = 1
    }
  } catch (e) {
    if (active) error.value = readableError(e)
  } finally {
    if (active) busy.value = false
  }
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
            v-if="workspace?.excel"
            color="neutral"
            variant="outline"
            icon="i-lucide-clipboard-check"
            aria-label="Проверить оформление ведомости"
            :loading="checking"
            @click="checkFormat"
          >
            Оформление
            <UBadge
              v-if="formatting"
              :label="String(formatting.issues.length)"
              :color="formatting.issues.length ? 'warning' : 'success'"
              variant="solid"
              size="sm"
            />
          </UButton>
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

        <div v-if="busy" class="empty" role="status">Открываем источники…</div>
        <p v-if="error" class="error-box" role="alert">{{ error }}</p>
        <template v-if="workspace">
          <section class="aw-verdict" :style="{ background: verdictTone.bg }" aria-live="polite">
            <div class="aw-verdict-main">
              <div class="aw-verdict-meta">
                <UBadge
                  :label="queueLabel(workspace.row.queue)"
                  :color="queueColor(workspace.row.queue)"
                  variant="solid"
                  size="md"
                />
                <span class="aw-verdict-queue">
                  Очередь · поз. {{ workspace.row.number }} · Позиция {{ positionIndex + 1
                  }}{{ typeof positionCount === 'number' ? ` из ${positionCount}` : '' }}
                </span>
              </div>
              <h1 class="aw-verdict-title" :style="{ color: verdictTone.text }">
                {{ workspace.row.problem }}
              </h1>
              <p class="aw-verdict-action">{{ workspace.row.action }}</p>
            </div>
            <dl class="aw-compare">
              <div>
                <dt>ВОР{{ quantityCell ? ` · ${quantityCell}` : '' }}</dt>
                <dd>{{ quantityWithUnit(workspace.row.declared_quantity, workspace.row.unit) }}</dd>
              </div>
              <div>
                <dt>ПД{{ source ? ` · стр. ${source.page}` : '' }}</dt>
                <dd>
                  {{ quantityWithUnit(workspace.row.found_quantity, workspace.row.found_unit) }}
                </dd>
              </div>
              <div>
                <dt>Единица</dt>
                <dd>{{ workspace.row.unit || '—' }}</dd>
              </div>
            </dl>
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
                    <span class="aw-page">
                      Физическая {{ page }} · печатная {{ printed || 'не установлена' }}
                    </span>
                    <div class="aw-pdf-search">
                      <UInput
                        v-model="search"
                        placeholder="Текст в PDF"
                        aria-label="Поиск в PDF"
                        size="sm"
                        icon="i-lucide-search"
                        @keyup.enter="find"
                      />
                      <UButton variant="outline" size="sm" @click="find">Найти</UButton>
                      <UButton
                        v-if="source"
                        label="К основанию"
                        icon="i-lucide-crosshair"
                        color="primary"
                        variant="soft"
                        size="sm"
                        @click="basis()"
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
                  <p v-if="region?.reason" class="muted">{{ region.reason }}</p>

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
                            size="sm"
                          />
                          <span class="aw-evidence-page">стр. {{ group.item.page }}</span>
                          <UBadge
                            :label="group.item.confirmed ? 'Подтверждено' : 'Не подтверждено'"
                            :color="group.item.confirmed ? 'success' : 'error'"
                            variant="soft"
                            size="sm"
                          />
                        </div>
                        <blockquote class="aw-quote">
                          «{{
                            expandedQuotes.has(group.index)
                              ? group.item.quote
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
                    <h2 class="aw-section-title">
                      {{ sheetName || 'Позиция CSV' }} ·
                      {{ quantityCell || workspace.row.number }}
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
                              :class="{ question: cell.highlight }"
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

                  <section aria-label="Детали проверки">
                    <h2 class="aw-section-title">Детали проверки</h2>
                    <UCard :ui="{ body: 'p-3 sm:p-3' }">
                      <dl class="aw-details">
                        <div>
                          <dt>Работа найдена</dt>
                          <dd>
                            {{
                              confirmationText(
                                workspace.row.work_found,
                                workspace.row.work_found
                                  ? `${source?.filename || ''}${source ? `, стр. ${source.page}` : ''}`
                                  : 'Не найдена в проекте',
                              )
                            }}
                          </dd>
                        </div>
                        <div>
                          <dt>Объём подтверждён</dt>
                          <dd
                            :style="{
                              color: workspace.row.volume_confirmed
                                ? 'var(--ui-success)'
                                : 'var(--ui-error)',
                            }"
                          >
                            {{
                              confirmationText(
                                workspace.row.volume_confirmed,
                                workspace.row.volume_confirmed
                                  ? quantityWithUnit(
                                      workspace.row.found_quantity,
                                      workspace.row.found_unit,
                                    )
                                  : `${quantityWithUnit(workspace.row.declared_quantity, workspace.row.unit)} ≠ ${quantityWithUnit(workspace.row.found_quantity, workspace.row.found_unit)}`,
                              )
                            }}
                          </dd>
                        </div>
                        <div>
                          <dt>Единица подтверждена</dt>
                          <dd>
                            {{
                              confirmationText(
                                workspace.row.unit_confirmed,
                                workspace.row.unit || '—',
                              )
                            }}
                          </dd>
                        </div>
                        <div>
                          <dt>Формула ВОР</dt>
                          <dd class="aw-formula">
                            {{ workspace.position.formula || 'не указано' }}
                          </dd>
                        </div>
                      </dl>
                      <p class="aw-details-text">{{ workspace.row.details }}</p>
                      <p class="aw-details-text">
                        Ссылка на страницы: {{ workspace.position.page_ref }}
                      </p>
                      <div class="aw-details-actions">
                        <UButton
                          label="Скачать исходную ВОР"
                          icon="i-lucide-download"
                          color="neutral"
                          variant="soft"
                          size="xs"
                          @click="downloadSource"
                        />
                      </div>
                    </UCard>
                  </section>
                </div>
              </template>
            </USplitter>
          </main>
        </template>
      </div>
    </template>
  </UModal>
  <UModal
    v-model:open="formatOpen"
    :title="`Оформление · ${sheetName || 'ведомости'}`"
    description="Детерминированная проверка шапки, ячеек и формул — без модели"
    :ui="{ content: 'max-w-3xl' }"
  >
    <template #body>
      <p v-if="checking" class="empty" role="status">Проверяем оформление…</p>
      <p v-else-if="formatError" class="error-box" role="alert">
        {{ formatError }}
        <UButton variant="link" @click="checkFormat">Повторить</UButton>
      </p>
      <FormatCheckResult
        v-else-if="formatting"
        :result="formatting"
        :version-id="workspace?.vor_version_id"
        filename="Ведомость"
      />
    </template>
    <template #footer>
      <div class="aw-format-footer">
        <span v-if="formatting" class="muted">Замечаний: {{ formatting.issues.length }}</span>
        <UButton color="neutral" variant="outline" :loading="checking" @click="checkFormat">
          Проверить снова
        </UButton>
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
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  padding: 8px;
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  background: var(--ui-bg-elevated);
  flex: 0 1 320px;
}
.aw-compare dt {
  font-size: 11px;
  text-transform: uppercase;
  color: var(--ui-text-muted);
}
.aw-compare dd {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ui-text-highlighted);
  font-variant-numeric: tabular-nums;
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
.aw-pdf {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  height: 100%;
  min-height: 0;
  padding-right: 8px;
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
  height: 100%;
  min-height: 0;
  overflow: auto;
  padding-left: 8px;
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
  gap: 8px;
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
.aw-details {
  margin: 0;
  display: grid;
  gap: 6px;
  font-size: 14px;
}
.aw-details > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.aw-details dt {
  color: var(--ui-text-muted);
}
.aw-details dd {
  margin: 0;
  font-weight: 600;
  color: var(--ui-text);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.aw-formula {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.aw-details-text {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ui-text-muted);
  overflow-wrap: anywhere;
}
.aw-format-table {
  overflow: auto;
  max-height: 60vh;
}
.aw-format-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}
.aw-details-actions {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--ui-border);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
@media (max-width: 720px) {
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
