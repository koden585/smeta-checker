<script setup lang="ts">
import type { ProjectDto, RunDto } from '~/generated/types.gen'
import { runLabel } from '~/utils/presentation'

type Queue = 'fix' | 'review' | 'missing' | 'ok'

interface DashboardProject {
  id: string
  name: string
  archived: boolean
  runs: number
  documents: number
  vorCount: number
  pdfCount: number
  lastRun: RunDto | null
  queues: Record<Queue, number> | null
  summaryBusy: boolean
}

const backend = useBackend()
const router = useRouter()
const route = useRoute()
const query = ref('')
const sort = ref<'recent' | 'name' | 'attention'>('recent')
const showArchived = computed({
  get: () => route.query.archived === 'true',
  set: (archived: boolean) => {
    void router.push({ query: { ...route.query, archived: archived ? 'true' : undefined } })
  },
})
const projects = ref<DashboardProject[]>([])
const error = ref('')
const busy = ref(true)
const renamingId = ref<string | null>(null)
const renamingName = ref('')
const renamingBusy = ref(false)
const confirmArchiveId = ref<string | null>(null)
const archiveBusy = ref(false)
const actionError = ref('')
const restoringId = ref<string | null>(null)

let active = true
let epoch = 0
let timer: ReturnType<typeof setTimeout> | undefined

const attention = (p: DashboardProject) =>
  (p.queues?.fix || 0) * 10 + (p.queues?.review || 0) * 3 + (p.queues?.missing || 0)

const confirmArchiveProject = computed(
  () => projects.value.find((p) => p.id === confirmArchiveId.value) || null,
)

const filtered = computed(() => {
  const q = query.value.trim().toLocaleLowerCase('ru-RU')
  const list = projects.value.filter(
    (p) =>
      !q ||
      p.name.toLocaleLowerCase('ru-RU').includes(q) ||
      p.lastRun?.vor_filename.toLocaleLowerCase('ru-RU').includes(q),
  )
  if (sort.value === 'name') list.sort((a, b) => a.name.localeCompare(b.name, 'ru-RU'))
  else if (sort.value === 'attention') list.sort((a, b) => attention(b) - attention(a))
  else
    list.sort(
      (a, b) =>
        (b.lastRun ? Date.parse(b.lastRun.created_at || '') || 0 : 0) -
        (a.lastRun ? Date.parse(a.lastRun.created_at || '') || 0 : 0),
    )
  return list
})

function formatDate(value: string | null) {
  return value
    ? new Date(value).toLocaleString('ru-RU', {
        day: 'numeric',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '-'
}

function countLabel(count: number, forms: [string, string, string]) {
  const last = count % 10
  const teen = count % 100 >= 11 && count % 100 <= 14
  return `${count} ${forms[teen ? 2 : last === 1 ? 0 : last >= 2 && last <= 4 ? 1 : 2]}`
}

function positionCount(count: number) {
  return countLabel(count, ['позиция', 'позиции', 'позиций'])
}

function confirmedLabel(count: number) {
  const singular = count % 10 === 1 && count % 100 !== 11
  return `${singular ? 'Подтверждена' : 'Подтверждено'} ${positionCount(count)}`
}

const queueLabels = {
  fix: 'Исправить',
  review: 'Проверить вручную',
  missing: 'Не выполнено',
} as const

const progressLabel = () => 'Прогресс проверки'

async function readQueues(runId: string): Promise<Record<Queue, number>> {
  const summary = await backend.summary(runId)
  return {
    fix: summary.queues.fix || 0,
    review: summary.queues.review || 0,
    missing: summary.queues.missing || 0,
    ok: summary.queues.ok || 0,
  }
}

async function retrySummary(p: DashboardProject) {
  if (!p.lastRun || p.summaryBusy) return
  p.summaryBusy = true
  try {
    p.queues = await readQueues(p.lastRun.run_id)
  } catch {
    p.queues = null
  } finally {
    p.summaryBusy = false
  }
}

const archiveModalOpen = computed({
  get: () => confirmArchiveId.value !== null,
  set: (open: boolean) => {
    if (!open) confirmArchiveId.value = null
  },
})

function openProject(p: DashboardProject) {
  router.push(`/projects/${p.id}`)
}

function startRename(p: DashboardProject) {
  actionError.value = ''
  renamingId.value = p.id
  renamingName.value = p.name
}

function cancelRename() {
  renamingId.value = null
  renamingName.value = ''
}

async function saveRename(p: DashboardProject) {
  actionError.value = ''
  const name = renamingName.value.trim()
  if (!name || renamingBusy.value) return
  renamingBusy.value = true
  try {
    const renamed = await backend.updateProject(p.id, { name })
    p.name = renamed.name
    cancelRename()
  } catch (e) {
    actionError.value = readableError(e)
  } finally {
    renamingBusy.value = false
  }
}

function askArchive(p: DashboardProject) {
  actionError.value = ''
  confirmArchiveId.value = p.id
}

async function restore(p: DashboardProject) {
  if (restoringId.value) return
  actionError.value = ''
  restoringId.value = p.id
  try {
    await backend.updateProject(p.id, { archived: false })
    await load()
  } catch (e) {
    actionError.value = readableError(e)
  } finally {
    restoringId.value = null
  }
}

async function confirmArchive() {
  if (!confirmArchiveId.value || archiveBusy.value) return
  archiveBusy.value = true
  try {
    await backend.updateProject(confirmArchiveId.value, { archived: true })
    confirmArchiveId.value = null
    await load()
  } catch (e) {
    actionError.value = readableError(e)
  } finally {
    archiveBusy.value = false
  }
}

async function loadProject(p: ProjectDto): Promise<DashboardProject> {
  const [runs, documents] = await Promise.all([backend.runs(p.id, 0), backend.catalog(p.id)])
  const lastRun = runs[0] || null
  let queues: Record<Queue, number> | null = null
  if (lastRun?.status === 'done') {
    try {
      queues = await readQueues(lastRun.run_id)
    } catch {
      // Unavailable results stay distinct from a successful summary with zero findings.
    }
  }
  return {
    id: p.id,
    name: p.name,
    archived: Boolean(p.archived),
    runs: runs.length,
    documents: documents.length,
    vorCount: documents.filter((document) => document.kind === 'vor').length,
    pdfCount: documents.filter((document) => document.kind === 'pdf').length,
    lastRun,
    queues,
    summaryBusy: false,
  }
}

async function load(background = false) {
  clearTimeout(timer)
  const current = ++epoch
  if (!background) busy.value = true
  error.value = ''
  try {
    await backend.connect()
    const list = await backend.projects(showArchived.value)
    if (!active || current !== epoch) return
    const rows = await Promise.all(list.map(loadProject))
    if (!active || current !== epoch) return
    projects.value = rows
    if (rows.some((p) => p.lastRun?.status === 'running'))
      timer = setTimeout(() => load(true), 5000)
  } catch (e) {
    if (active && current === epoch) {
      error.value = readableError(e)
      if (background) timer = setTimeout(() => load(true), 5000)
    }
  } finally {
    if (current === epoch) busy.value = false
  }
}

watch(showArchived, () => {
  projects.value = []
  query.value = ''
  cancelRename()
  actionError.value = ''
  load()
})

onMounted(() => load())
onBeforeUnmount(() => {
  active = false
  epoch++
  clearTimeout(timer)
})
</script>

<template>
  <div class="dashboard-page">
    <WorkspaceHeader active="projects" />
    <main id="main-content" tabindex="-1" class="shell dashboard">
      <div class="dashboard-heading">
        <div class="dashboard-title">
          <h1>Проекты</h1>
          <span v-if="!busy && !error" class="dashboard-count" role="status">
            {{ countLabel(filtered.length, ['проект', 'проекта', 'проектов']) }}
          </span>
        </div>
        <UButton to="/upload" icon="i-lucide-plus" color="primary">Новый проект</UButton>
      </div>

      <div class="dashboard-toolbar">
        <div class="dashboard-scope" role="group" aria-label="Раздел проектов">
          <UButton
            color="neutral"
            variant="ghost"
            :aria-pressed="!showArchived"
            :class="{ selected: !showArchived }"
            @click="showArchived = false"
            >Активные</UButton
          >
          <UButton
            color="neutral"
            variant="ghost"
            :aria-pressed="showArchived"
            :class="{ selected: showArchived }"
            @click="showArchived = true"
            >Архив</UButton
          >
        </div>
        <UInput
          v-model="query"
          icon="i-lucide-search"
          placeholder="Найти проект или ведомость"
          aria-label="Поиск проектов"
          class="dashboard-search"
        />
        <div class="dashboard-sort">
          <USelect
            v-model="sort"
            :items="[
              { label: 'Недавние', value: 'recent' },
              { label: 'По вниманию', value: 'attention' },
              { label: 'По алфавиту', value: 'name' },
            ]"
            aria-label="Сортировка проектов"
          />
        </div>
      </div>

      <div v-if="error && projects.length" class="dashboard-notice" role="alert">
        <UIcon name="i-lucide-circle-alert" aria-hidden="true" />
        <span>Не удалось обновить список. Показаны последние загруженные данные.</span>
        <UButton color="neutral" variant="link" @click="load()">Повторить</UButton>
      </div>
      <p v-if="actionError && !archiveModalOpen" class="dashboard-action-error" role="alert">
        {{ actionError }}
      </p>

      <section class="dashboard-panel" aria-label="Список проектов" :aria-busy="busy">
        <table class="dashboard-table">
          <caption class="visually-hidden">
            {{
              showArchived ? 'Архив проектов' : 'Активные проекты'
            }}
          </caption>
          <colgroup>
            <col class="project-column" />
            <col class="last-check-column" />
            <col />
            <col class="actions-column" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">Проект</th>
              <th scope="col">Последняя проверка</th>
              <th scope="col">Результат</th>
              <th scope="col"><span class="visually-hidden">Действия</span></th>
            </tr>
          </thead>
          <tbody v-if="busy && !projects.length && !error">
            <tr v-for="n in 3" :key="n" class="dashboard-loading-row" aria-hidden="true">
              <td>
                <USkeleton class="dashboard-skeleton skeleton-name" />
                <USkeleton class="dashboard-skeleton skeleton-meta" />
              </td>
              <td>
                <USkeleton class="dashboard-skeleton skeleton-date" />
                <USkeleton class="dashboard-skeleton skeleton-meta" />
              </td>
              <td><USkeleton class="dashboard-skeleton skeleton-result" /></td>
              <td></td>
            </tr>
          </tbody>
          <tbody v-else-if="error && !projects.length">
            <tr>
              <td colspan="4" class="dashboard-empty">
                <h2>Не удалось загрузить проекты</h2>
                <p>Проверьте соединение с сервером и попробуйте ещё раз.</p>
                <UButton color="neutral" variant="outline" @click="load()">Повторить</UButton>
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="!projects.length">
            <tr>
              <td colspan="4" class="dashboard-empty">
                <h2>{{ showArchived ? 'Архив проектов пуст' : 'Пока нет проектов' }}</h2>
                <p>
                  {{
                    showArchived
                      ? 'Архивированные проекты появятся здесь. Вернуться можно вкладкой «Активные».'
                      : 'Создайте проект кнопкой «Новый проект», затем добавьте ведомость и проектные PDF.'
                  }}
                </p>
              </td>
            </tr>
          </tbody>
          <tbody v-else-if="!filtered.length">
            <tr>
              <td colspan="4" class="dashboard-empty">
                <h2>Ничего не найдено</h2>
                <p>По запросу «{{ query }}» нет проектов или ведомостей.</p>
                <UButton color="neutral" variant="outline" @click="query = ''"
                  >Сбросить поиск</UButton
                >
              </td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr v-for="p in filtered" :key="p.id" class="dashboard-row" @click="openProject(p)">
              <td class="dashboard-identity">
                <div
                  v-if="renamingId === p.id"
                  class="dashboard-rename"
                  @click.stop
                  @keydown.enter.stop
                >
                  <UInput
                    v-model="renamingName"
                    aria-label="Новое название проекта"
                    :disabled="renamingBusy"
                    autofocus
                    class="rename-input"
                    @keydown.enter="saveRename(p)"
                    @keydown.escape="cancelRename"
                  />
                  <UButton
                    icon="i-lucide-check"
                    aria-label="Сохранить название"
                    color="neutral"
                    variant="outline"
                    :disabled="!renamingName.trim()"
                    :loading="renamingBusy"
                    @click="saveRename(p)"
                  />
                  <UButton
                    icon="i-lucide-x"
                    aria-label="Отменить переименование"
                    color="neutral"
                    variant="ghost"
                    :disabled="renamingBusy"
                    @click="cancelRename"
                  />
                </div>
                <NuxtLink
                  v-else
                  :to="`/projects/${p.id}`"
                  class="dashboard-name"
                  :aria-label="`Открыть проект ${p.name}`"
                  @click.stop
                  >{{ p.name }}</NuxtLink
                >
                <p
                  class="dashboard-meta"
                  role="group"
                  :aria-label="`Документов: ${p.documents}, проверок: ${p.runs}`"
                >
                  <span>ВОР {{ p.vorCount }}</span>
                  <span>ПД {{ p.pdfCount }}</span>
                  <span>Проверок: {{ p.runs }}</span>
                </p>
              </td>
              <td class="dashboard-last-check" :class="{ 'no-check': !p.lastRun }">
                <template v-if="p.lastRun">
                  <p class="dashboard-date">{{ formatDate(p.lastRun.created_at) }}</p>
                  <p class="dashboard-file" :title="p.lastRun.vor_filename">
                    {{ p.lastRun.vor_filename }}
                  </p>
                </template>
                <span v-else class="dashboard-muted" aria-label="Проверок ещё не было">-</span>
              </td>
              <td class="dashboard-result">
                <template v-if="!p.lastRun">
                  <p class="dashboard-muted">Проверок пока нет</p>
                  <p class="dashboard-detail">Откройте проект для подготовки проверки</p>
                </template>
                <template v-else-if="p.lastRun.status === 'done'">
                  <div v-if="p.queues" class="dashboard-queues">
                    <template v-for="q in ['fix', 'review', 'missing'] as const" :key="q">
                      <p v-if="p.queues[q]" :class="`result-${q}`">
                        {{ queueLabels[q] }}: {{ positionCount(p.queues[q]) }}
                      </p>
                    </template>
                    <p v-if="p.queues.ok" class="result-ok">{{ confirmedLabel(p.queues.ok) }}</p>
                    <p v-if="!Object.values(p.queues).some(Boolean)" class="dashboard-muted">
                      Проверка без позиций
                    </p>
                  </div>
                  <div v-else class="dashboard-summary-error" @click.stop>
                    <p>Результат недоступен</p>
                    <UButton
                      color="neutral"
                      variant="link"
                      :loading="p.summaryBusy"
                      :aria-label="`Повторить загрузку результата ${p.name}`"
                      @click="retrySummary(p)"
                      >Повторить</UButton
                    >
                  </div>
                </template>
                <template v-else>
                  <p :class="{ 'result-fix': p.lastRun.status === 'failed' }">
                    {{ runLabel(p.lastRun.status) }}
                  </p>
                  <template v-if="p.lastRun.status === 'running'">
                    <p class="dashboard-detail">
                      {{
                        p.lastRun.total
                          ? `Обработано ${p.lastRun.done + p.lastRun.failed} из ${p.lastRun.total}`
                          : 'Подготовка проверки'
                      }}
                    </p>
                    <UProgress
                      v-if="p.lastRun.total"
                      :model-value="
                        Math.floor(((p.lastRun.done + p.lastRun.failed) / p.lastRun.total) * 100)
                      "
                      color="neutral"
                      size="xs"
                      class="dashboard-progress"
                      :get-value-label="progressLabel"
                    />
                  </template>
                </template>
              </td>
              <td class="dashboard-actions" @click.stop>
                <UDropdownMenu
                  :items="[
                    {
                      label: 'Переименовать',
                      icon: 'i-lucide-pencil',
                      disabled: renamingBusy,
                      onSelect: () => startRename(p),
                    },
                    {
                      label: p.archived ? 'Восстановить' : 'Архивировать',
                      icon: p.archived ? 'i-lucide-archive-restore' : 'i-lucide-archive',
                      disabled: archiveBusy || restoringId !== null,
                      onSelect: () => (p.archived ? restore(p) : askArchive(p)),
                    },
                  ]"
                  :content="{ align: 'end' }"
                >
                  <UButton
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-ellipsis"
                    :loading="restoringId === p.id"
                    :aria-label="`Действия проекта ${p.name}`"
                  />
                </UDropdownMenu>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="busy && !projects.length && !error" class="visually-hidden" role="status">
          Загружаем проекты…
        </p>
      </section>

      <UModal v-model:open="archiveModalOpen" title="Архивировать проект?">
        <template #body>
          <p class="modal-text">
            Проект «{{ confirmArchiveProject?.name }}» исчезнет из активного списка. Восстановить
            можно во вкладке «Архив».
          </p>
          <p v-if="actionError" class="dashboard-action-error" role="alert">{{ actionError }}</p>
          <div class="toolbar spread modal-footer">
            <UButton
              color="neutral"
              variant="ghost"
              :disabled="archiveBusy"
              @click="confirmArchiveId = null"
              >Отмена</UButton
            >
            <UButton color="primary" :loading="archiveBusy" @click="confirmArchive"
              >Архивировать</UButton
            >
          </div>
        </template>
      </UModal>
    </main>
  </div>
</template>

<style scoped>
/* Kept brand, editorial column: 12 × 77px + 11 × 16px = 1100px of working content. */
.dashboard {
  max-width: 1164px;
  padding-top: 32px;
}
.dashboard-page :deep(.app-header) {
  max-width: 1100px;
  min-height: 72px;
  padding-block: 14px;
  margin-bottom: 0;
  border-color: var(--ui-border-muted);
}
.dashboard-heading,
.dashboard-title {
  display: flex;
  align-items: center;
  gap: 16px;
}
.dashboard-heading {
  justify-content: space-between;
  margin-bottom: 24px;
}
.dashboard-title h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 650;
  letter-spacing: -0.025em;
  line-height: 1.3;
}
.dashboard-count {
  color: var(--ui-text-muted);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.dashboard-toolbar {
  display: grid;
  grid-template-columns: 1fr minmax(220px, 300px) 184px;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.dashboard-scope {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dashboard-scope :deep(button) {
  color: var(--ui-text-muted);
  border-radius: 0;
  border-bottom: 2px solid transparent;
}
.dashboard-scope :deep(button.selected) {
  color: var(--ui-text-highlighted);
  border-bottom-color: currentColor;
}
.dashboard-search,
.dashboard-sort {
  width: 100%;
  min-width: 0;
}
.dashboard-sort :deep(button) {
  width: 100%;
  min-width: 0;
}
.dashboard-panel {
  background: var(--ui-bg);
  border: 1px solid var(--ui-border-muted);
  border-radius: 8px;
  padding-inline: 20px;
  min-width: 0;
}
.dashboard-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: 15px;
  line-height: 1.5;
}
.project-column {
  width: 40%;
}
.last-check-column {
  width: 25%;
}
.actions-column {
  width: 44px;
}
.dashboard-table th {
  height: 44px;
  text-align: left;
  color: var(--ui-text-muted);
  font-size: 14px;
  font-weight: 400;
}
.dashboard-table td {
  padding-block: 20px;
  vertical-align: middle;
  border-top: 1px solid var(--ui-border-muted);
}
.dashboard-table th:not(:last-child),
.dashboard-table td:not(:last-child) {
  padding-right: 16px;
}
.dashboard-row {
  cursor: pointer;
}
.dashboard-row:hover {
  outline: 1px solid var(--ui-border);
  outline-offset: -1px;
}
.dashboard-name {
  display: block;
  width: fit-content;
  max-width: 100%;
  color: var(--ui-text-highlighted);
  font-size: 17px;
  font-weight: 600;
  overflow-wrap: break-word;
}
.dashboard-name:hover {
  text-decoration: underline;
}
.dashboard-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  margin-top: 4px;
  color: var(--ui-text-muted);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.dashboard-meta span {
  white-space: nowrap;
}
.dashboard-file,
.dashboard-detail {
  color: var(--ui-text-muted);
  font-size: 14px;
  margin-top: 4px;
}
.dashboard-file {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dashboard-date {
  font-variant-numeric: tabular-nums;
}
.dashboard-muted,
.dashboard-summary-error {
  color: var(--ui-text-muted);
}
.dashboard-queues {
  display: grid;
  gap: 4px;
}
.result-ok {
  color: var(--app-success-text);
}
.result-fix {
  color: var(--app-error-text);
}
.result-review {
  color: var(--app-warning-text);
}
.result-missing {
  color: var(--ui-text-muted);
}
.dashboard-progress {
  margin-top: 8px;
  max-width: 200px;
}
.dashboard-actions {
  text-align: right;
}
.dashboard-rename {
  display: flex;
  align-items: center;
  gap: 4px;
}
.rename-input {
  min-width: 0;
  flex: 1;
}
.dashboard-skeleton {
  background: var(--ui-bg-accented);
  animation: none;
  height: 20px;
  max-width: 100%;
  border-radius: 4px;
}
.skeleton-name {
  width: 180px;
}
.skeleton-meta {
  width: 140px;
  height: 14px;
  margin-top: 8px;
}
.skeleton-date {
  width: 120px;
}
.skeleton-result {
  width: 180px;
}
.dashboard-table td.dashboard-empty {
  padding-block: 32px;
}
.dashboard-empty h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 8px;
}
.dashboard-empty p {
  color: var(--ui-text-muted);
  font-size: 15px;
  margin: 0 0 16px;
  max-width: 65ch;
}
.dashboard-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  color: var(--ui-text-muted);
  font-size: 15px;
}
.dashboard-notice > svg {
  flex-shrink: 0;
}
.dashboard-action-error {
  color: var(--app-error-text);
  margin-bottom: 16px;
}
.modal-text {
  padding: 0 24px 8px;
  overflow-wrap: break-word;
}
.modal-footer {
  margin: 4px 24px 8px;
}
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
@media (max-width: 900px) {
  .dashboard-toolbar {
    grid-template-columns: 1fr 184px;
    gap: 12px 16px;
  }
  .dashboard-scope {
    grid-column: 1;
  }
  .dashboard-sort {
    grid-column: 2;
    grid-row: 1;
  }
  .dashboard-search {
    grid-column: 1 / -1;
  }
  .project-column {
    width: 39%;
  }
  .last-check-column {
    width: 25%;
  }
}
@media (max-width: 640px) {
  .dashboard {
    padding: 20px 16px 40px;
  }
  .dashboard-page :deep(.app-header) {
    min-height: 64px;
    padding-block: 10px;
    width: calc(100% - 32px);
    flex-wrap: nowrap;
    gap: 8px;
  }
  .dashboard-page :deep(.brand) {
    gap: 8px;
  }
  .dashboard-page :deep(.brand-mark) {
    font-size: 20px;
  }
  .dashboard-page :deep(.brand-product) {
    font-size: 13px;
  }
  .dashboard-page :deep(.brand-divider) {
    height: 20px;
  }
  .dashboard-page :deep(.header-navigation) {
    width: auto;
    gap: 4px;
  }
  .dashboard-page :deep(.header-project-label) {
    display: none;
  }
  .dashboard-heading {
    margin-bottom: 16px;
    gap: 12px;
  }
  .dashboard-title {
    display: block;
  }
  .dashboard-title h1 {
    font-size: 24px;
  }
  .dashboard-count {
    font-size: 13px;
  }
  .dashboard-toolbar {
    grid-template-columns: 1fr 168px;
    gap: 12px 8px;
  }
  .dashboard-panel {
    padding-inline: 16px;
  }
  .dashboard-table colgroup,
  .dashboard-table thead {
    display: none;
  }
  .dashboard-table,
  .dashboard-table tbody {
    display: block;
  }
  .dashboard-table tr.dashboard-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 44px;
    gap: 8px 12px;
    padding-block: 16px;
    border-top: 1px solid var(--ui-border-muted);
  }
  .dashboard-table tr:first-child {
    border-top: 0;
  }
  .dashboard-table td,
  .dashboard-table td:not(:last-child) {
    display: block;
    border: 0;
    padding: 0;
  }
  .dashboard-identity {
    grid-column: 1;
    grid-row: 1;
  }
  .dashboard-actions {
    grid-column: 2;
    grid-row: 1;
  }
  .dashboard-result {
    grid-column: 1 / -1;
    grid-row: 2;
  }
  .dashboard-last-check {
    grid-column: 1 / -1;
    grid-row: 3;
    display: flex !important;
    flex-wrap: wrap;
    gap: 4px 12px;
    color: var(--ui-text-muted);
    font-size: 14px;
  }
  .dashboard-last-check.no-check {
    display: none !important;
  }
  .dashboard-last-check .dashboard-file {
    margin: 0;
    max-width: 100%;
  }
  .dashboard-meta {
    gap: 4px 10px;
  }
  .dashboard-loading-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    padding-block: 20px;
    border-top: 1px solid var(--ui-border-muted);
  }
  .dashboard-loading-row td:first-child {
    grid-column: 1 / -1;
  }
  .dashboard-loading-row td:last-child {
    display: none;
  }
  .dashboard-notice {
    flex-wrap: wrap;
  }
}
</style>
