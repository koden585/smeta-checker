<script setup lang="ts">
import type { RunDto, SummaryDto, RowsDto } from '~/generated/types.gen'
import { queueColor, queueLabel, quantityWithUnit, runLabel } from '~/utils/presentation'
const route = useRoute(),
  router = useRouter(),
  backend = useBackend(),
  runId = computed(() => String(route.params.runId)),
  run = ref<RunDto | null>(null),
  summary = ref<SummaryDto | null>(null),
  results = ref<RowsDto | null>(null),
  error = ref(''),
  busy = ref(true),
  cancelling = ref(false),
  focus = ref('fix'),
  query = ref(''),
  offset = ref(0)
const position = computed(() =>
  typeof route.query.position === 'string' && /^\d+$/.test(route.query.position)
    ? Number(route.query.position)
    : null,
)
const queues = [
  { id: 'fix', label: 'Исправить' },
  { id: 'review', label: 'Проверить вручную' },
  { id: 'all', label: 'Все позиции' },
]
const vorDocument = computed(
  () => summary.value?.documents.find((d) => d.id === summary.value?.run.vor_version_id) || null,
)
const vorTitle = computed(() => vorDocument.value?.title || run.value?.vor_filename || '')
function queueCount(id: string) {
  if (!summary.value) return 0
  if (id === 'all')
    return summary.value.run.total ?? Object.values(summary.value.queues).reduce((a, b) => a + b, 0)
  return summary.value.queues[id] ?? 0
}
function rowCell(row: RowsDto['rows'][number]) {
  // Cells map address -> value; show a stable source-row address, never a guess.
  if (typeof row.source_row !== 'number') return 'Позиция ' + row.number
  const hit = Object.keys(row.cells).find((addr) => addr.endsWith(String(row.source_row)))
  return hit || 'Позиция ' + row.number
}
function openPosition(index: number) {
  router.replace({ query: { ...route.query, position: index } })
}
function closePosition() {
  const next = { ...route.query }
  delete next.position
  router.replace({ query: next })
}
let active = true,
  timer: ReturnType<typeof setTimeout> | undefined,
  searchTimer: ReturnType<typeof setTimeout> | undefined,
  epoch = 0
const fixButton = ref<HTMLButtonElement | null>(null)
async function loadRows() {
  const current = ++epoch
  busy.value = true
  try {
    const data = await backend.rows(runId.value, {
      focus: focus.value,
      q: query.value,
      offset: offset.value,
    })
    if (active && current === epoch) results.value = data
  } catch (e) {
    if (active && current === epoch) error.value = readableError(e)
  } finally {
    if (active && current === epoch) busy.value = false
  }
}
function changePage(delta: number) {
  offset.value = Math.max(0, offset.value + delta)
  loadRows()
}
async function poll() {
  clearTimeout(timer)
  error.value = ''
  try {
    const value = await backend.run(runId.value)
    if (!active) return
    run.value = value
    if (value.status === 'running') {
      timer = setTimeout(poll, 1500)
      return
    }
    if (value.status === 'cancelled') {
      busy.value = false
      return
    }
    summary.value = await backend.summary(runId.value)
    await loadRows()
    fixButton.value?.focus({ preventScroll: true })
  } catch (e) {
    if (active) {
      error.value = readableError(e) + '. Повторяем подключение…'
      timer = setTimeout(poll, 3000)
    }
  } finally {
    busy.value = false
  }
}
async function download() {
  try {
    await backend.download(
      `${backend.audit(runId.value)}/reports/word`,
      `audit-${runId.value}.docx`,
    )
  } catch (e) {
    error.value = readableError(e)
  }
}
async function cancel() {
  if (cancelling.value || !run.value || run.value.status !== 'running') return
  cancelling.value = true
  try {
    const value = await backend.cancelAudit(runId.value)
    run.value = value
    clearTimeout(timer)
  } catch (e) {
    error.value = readableError(e)
  } finally {
    cancelling.value = false
    busy.value = false
  }
}
watch(focus, () => {
  offset.value = 0
  loadRows()
})
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    offset.value = 0
    loadRows()
  }, 250)
})
onMounted(async () => {
  try {
    await backend.connect()
    await poll()
  } catch (e) {
    error.value = readableError(e)
  }
})
onBeforeUnmount(() => {
  active = false
  epoch++
  clearTimeout(timer)
  clearTimeout(searchTimer)
})
</script>
<template>
  <div>
    <WorkspaceHeader active="projects" />
    <main id="main-content" tabindex="-1" class="shell">
      <nav v-if="summary" class="toolbar" aria-label="Проект и редакция ведомости">
        <UButton
          :to="`/projects/${summary.project.id}`"
          color="neutral"
          variant="link"
          icon="i-lucide-arrow-left"
          >В проект</UButton
        >
        <UButton
          v-if="summary.documents.find((document) => document.id === summary?.run.vor_version_id)"
          :to="`/projects/${summary.project.id}/documents/${summary.documents.find((document) => document.id === summary?.run.vor_version_id)!.document_id}?version=${summary.run.vor_version_id}`"
          color="neutral"
          variant="link"
          >Редакция ведомости</UButton
        >
      </nav>
      <div class="page-heading">
        <div>
          <h1>{{ vorTitle || summary?.project.name || 'Проверка документов' }}</h1>
          <p class="muted">
            {{ summary?.project.name }} · {{ run?.vor_filename }} ·
            {{ runLabel(run?.status || '') }}
          </p>
        </div>
        <div class="heading-actions">
          <UButton v-if="summary" variant="outline" icon="i-lucide-download" @click="download()">
            Скачать Word
          </UButton>
        </div>
      </div>
      <div v-if="error" class="error-box" role="alert">
        {{ error }} <UButton variant="link" @click="poll">Повторить</UButton>
      </div>
      <section v-if="run?.status === 'running'" class="panel progress" role="status">
        <h2>
          {{
            {
              preparing: 'Подготавливаем документы',
              auditing: 'Проверяем позиции',
              finalizing: 'Собираем отчёты',
              done: 'Завершено',
              failed: 'Технический сбой',
            }[run.stage]
          }}
        </h2>
        <p>
          Готово {{ run.done + run.failed }}{{ run.total === null ? '' : ' из ' + run.total }}
          позиций
        </p>
        <UProgress
          :model-value="
            run.stage === 'preparing'
              ? run.preparation_total
                ? Math.floor(((run.preparation_done ?? 0) / run.preparation_total) * 100)
                : null
              : run.stage === 'finalizing' || !run.total
                ? null
                : Math.floor(((run.done + run.failed) / run.total) * 100)
          "
          :status="run.stage === 'auditing' || !!run.preparation_total"
          aria-label="Прогресс проверки"
          class="progress-bar"
        />
        <p v-if="run.stage === 'preparing'" class="muted">
          Извлекаем текст и таблицы PDF.
          <span v-if="run.preparation_total"
            >Страниц текущего PDF: {{ run.preparation_done }} из {{ run.preparation_total }}.</span
          >
          Счётчик позиций начнёт расти после подготовки документов.
        </p>
        <p v-else-if="run.stage === 'auditing'" class="muted">
          Сейчас проверяется: {{ run.running }}. В очереди: {{ run.queued }}.
        </p>
        <p class="muted">Можно закрыть страницу и вернуться к проверке через историю.</p>
        <div class="toolbar">
          <UButton color="error" variant="outline" :loading="cancelling" @click="cancel">
            Остановить проверку
          </UButton>
        </div>
      </section>
      <p v-if="run?.status === 'failed'" class="error-box">
        Запуск завершился с техническим сбоем. Сохранённые результаты доступны ниже; непроверенные
        позиции не подтверждены.
      </p>
      <p v-if="run?.status === 'cancelled'" class="error-box">
        Проверка остановлена. Частичные результаты могут быть недоступны.
      </p>
      <template v-if="summary">
        <div class="toolbar results-bar">
          <div class="filters" role="group" aria-label="Фильтр позиций по очередям">
            <button
              v-for="item in queues"
              :key="item.id"
              :ref="
                (el) => {
                  if (item.id === 'fix') fixButton = el as HTMLButtonElement | null
                }
              "
              type="button"
              class="filter"
              :aria-pressed="focus === item.id"
              @click="focus = item.id"
            >
              <span class="filter-count">{{ queueCount(item.id) }}</span>
              <span>{{ item.label }}</span>
            </button>
          </div>
          <UInput
            v-model="query"
            class="search"
            placeholder="Работа, номер или ячейка"
            aria-label="Поиск позиций"
          />
        </div>
        <div class="panel table-wrap" :aria-busy="busy">
          <table class="results">
            <thead>
              <tr>
                <th scope="col">Позиция</th>
                <th scope="col">Результат проверки</th>
                <th scope="col">Значения</th>
                <th scope="col"><span class="visually-hidden">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in results?.rows" :key="r.id">
                <td>
                  <strong class="row-name">{{ r.number }} · {{ r.name }}</strong>
                  <p class="muted">{{ r.sheet || 'CSV' }} · {{ rowCell(r) }}</p>
                </td>
                <td>
                  <UBadge :color="queueColor(r.queue)" variant="subtle">{{
                    queueLabel(r.queue)
                  }}</UBadge>
                  <p class="row-problem">{{ r.problem }}</p>
                </td>
                <td class="numbers">
                  <p>
                    <span class="muted">ВОР </span
                    ><strong>{{ quantityWithUnit(r.declared_quantity, r.unit) }}</strong>
                  </p>
                  <p class="muted">ПД {{ quantityWithUnit(r.found_quantity, r.found_unit) }}</p>
                </td>
                <td class="row-action">
                  <UButton variant="ghost" @click="openPosition(r.position_index)">
                    Открыть позицию
                  </UButton>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-if="!results?.rows.length && !busy" class="empty">По этому фильтру позиций нет.</p>
        </div>
        <div v-if="results && (results.total > 100 || offset)" class="toolbar pagination">
          <UButton :disabled="offset === 0" @click="changePage(-100)">Назад</UButton
          ><span class="muted"
            >{{ offset + 1 }}–{{ Math.min(offset + 100, results.total) }} из
            {{ results.total }}</span
          ><UButton :disabled="offset + 100 >= results.total" @click="changePage(100)">
            Далее
          </UButton>
        </div>
        <details class="docs">
          <summary>Исходные версии документов</summary>
          <p v-for="doc in summary.documents" :key="doc.id">
            {{ doc.filename }} · версия {{ doc.number }} · {{ doc.sha256.slice(0, 12) }}
            <UButton
              variant="link"
              @click="
                backend
                  .download(backend.contentUrl(doc.id) + '?download=true', doc.filename)
                  .catch((e) => (error = readableError(e)))
              "
              >Скачать</UButton
            >
          </p>
        </details>
      </template>
      <AuditWorkspace
        v-if="position !== null && summary"
        :key="runId"
        :run-id="runId"
        :position-index="position"
        :position-count="summary.run.total ?? 0"
        :documents="summary.documents"
        @close="closePosition"
        @navigate="openPosition"
      />
    </main>
  </div>
</template>
<style scoped>
.heading-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}
.progress {
  padding: 24px;
  margin: 24px 0;
}
.progress-bar {
  margin: 16px 0;
}
.results-bar {
  margin: 20px 0;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.filter {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 8px 14px;
  border: 1px solid var(--ui-border);
  border-radius: 999px;
  background: var(--ui-bg-elevated);
  color: var(--ui-text);
  font-size: 14px;
  line-height: 1.4;
}
.filter-count {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.filter[aria-pressed='true'] {
  background: var(--app-selected-bg);
  color: var(--app-selected-text);
  border-color: var(--app-selected-text);
  font-weight: 600;
}
.search {
  flex: 1 1 240px;
  min-width: min(100%, 240px);
}
.table-wrap {
  overflow: auto;
}
.row-name {
  display: block;
  color: var(--ui-text-highlighted);
}
.row-problem {
  margin-top: 6px;
  color: var(--ui-text-highlighted);
  font-weight: 600;
}
.numbers {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.row-action {
  text-align: right;
  white-space: nowrap;
}
.pagination {
  margin: 20px 0;
}
.docs {
  margin-top: 8px;
  font-size: 14px;
}
.docs summary {
  font-weight: 600;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
}
.docs p {
  margin: 8px 0;
  color: var(--ui-text-muted);
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
@media (max-width: 700px) {
  .results thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .results tbody {
    display: block;
  }
  .results tr {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 16px 12px;
    padding: 20px 16px;
  }
  .results td {
    display: block;
    padding: 0;
    border: 0;
  }
  .results td:nth-child(1),
  .results td:nth-child(2) {
    grid-column: 1 / -1;
  }
  .results tbody tr + tr {
    border-top: 1px solid var(--ui-border);
  }
  .row-action {
    align-self: end;
    text-align: end;
  }
}
</style>
