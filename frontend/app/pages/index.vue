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
  lastRun: RunDto | null
  queues: Record<Queue, number>
}

const backend = useBackend()
const router = useRouter()
const query = ref('')
const sort = ref<'recent' | 'name' | 'attention'>('recent')
const showArchived = ref(false)
const projects = ref<DashboardProject[]>([])
const error = ref('')
const busy = ref(true)
const renamingId = ref<string | null>(null)
const renamingName = ref('')
const renamingBusy = ref(false)
const confirmArchiveId = ref<string | null>(null)
const archiveBusy = ref(false)

let active = true
let epoch = 0
let timer: ReturnType<typeof setTimeout> | undefined

const attention = (p: DashboardProject) =>
  p.queues.fix * 10 + p.queues.review * 3 + p.queues.missing

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
      (a, b) => Date.parse(b.lastRun?.created_at || '') - Date.parse(a.lastRun?.created_at || ''),
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
    : '—'
}

function statusColor(status: RunDto['status']): 'success' | 'error' | 'warning' | 'neutral' {
  return status === 'done' ? 'success' : status === 'failed' ? 'error' : 'warning'
}

function queueBadge(queue: Queue, count: number) {
  if (!count) return null
  const meta = {
    fix: { label: 'Исправить', color: 'error' },
    review: { label: 'Вручную', color: 'warning' },
    missing: { label: 'Не выполнено', color: 'neutral' },
    ok: { label: 'ОК', color: 'success' },
  } as const
  return { ...meta[queue], count }
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
  renamingId.value = p.id
  renamingName.value = p.name
}

function cancelRename() {
  renamingId.value = null
  renamingName.value = ''
}

async function saveRename(p: DashboardProject) {
  const name = renamingName.value.trim()
  if (!name || renamingBusy.value) return
  renamingBusy.value = true
  try {
    const renamed = await backend.updateProject(p.id, { name })
    p.name = renamed.name
    cancelRename()
  } catch (e) {
    error.value = readableError(e)
  } finally {
    renamingBusy.value = false
  }
}

function askArchive(p: DashboardProject) {
  confirmArchiveId.value = p.id
}

async function restore(p: DashboardProject) {
  try {
    await backend.updateProject(p.id, { archived: false })
    await load()
  } catch (e) {
    error.value = readableError(e)
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
    error.value = readableError(e)
  } finally {
    archiveBusy.value = false
  }
}

async function loadProject(p: ProjectDto): Promise<DashboardProject> {
  const [runs, documents] = await Promise.all([backend.runs(p.id, 0), backend.catalog(p.id)])
  const lastRun = runs[0] || null
  const queues: Record<Queue, number> = { fix: 0, review: 0, missing: 0, ok: 0 }
  if (lastRun && lastRun.status === 'done') {
    try {
      const summary = await backend.summary(lastRun.run_id)
      for (const key of Object.keys(queues) as Queue[]) queues[key] = summary.queues[key] || 0
    } catch {
      // Очереди — дополнение; строка проекта показывается и без них.
    }
  }
  return {
    id: p.id,
    name: p.name,
    archived: Boolean(p.archived),
    runs: runs.length,
    documents: documents.length,
    lastRun,
    queues,
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

watch(showArchived, () => load())

onMounted(() => load())
onBeforeUnmount(() => {
  active = false
  epoch++
  clearTimeout(timer)
})
</script>

<template>
  <div>
    <WorkspaceHeader active="projects" />
    <main id="main-content" tabindex="-1" class="shell dashboard">
      <div class="page-heading">
        <div>
          <h1 class="page-title">Проекты</h1>
          <p class="muted">Все комплекты компании и их последние проверки</p>
        </div>
        <UButton to="/upload" icon="i-lucide-plus" color="primary">Новый проект</UButton>
      </div>

      <template v-if="busy && !projects.length && !error">
        <div class="dashboard-toolbar" aria-hidden="true">
          <USkeleton class="dashboard-skeleton-bar" />
          <USkeleton class="dashboard-skeleton-sort" />
        </div>
        <div class="panel dashboard-skeleton-panel" aria-hidden="true">
          <USkeleton v-for="n in 5" :key="n" class="dashboard-skeleton-row" />
        </div>
        <p class="empty" role="status">Загружаем проекты…</p>
      </template>

      <UAlert
        v-else-if="error && !projects.length"
        color="error"
        variant="soft"
        title="Не удалось загрузить проекты"
        description="Проверьте соединение с сервером и попробуйте ещё раз."
      >
        <template #actions>
          <UButton color="error" variant="soft" size="sm" @click="load()">Повторить</UButton>
        </template>
      </UAlert>

      <div v-else-if="!projects.length" class="panel dashboard-empty">
        <UIcon name="i-lucide-folder-open" class="dashboard-empty-icon" aria-hidden="true" />
        <h2>Пока нет проектов</h2>
        <p class="muted">Создайте проект и загрузите первую ведомость и проектные PDF.</p>
      </div>

      <template v-else>
        <div class="dashboard-toolbar">
          <UInput
            v-model="query"
            icon="i-lucide-search"
            placeholder="Найти проект или ведомость…"
            aria-label="Поиск проектов"
            class="dashboard-search"
          />
          <USelect
            v-model="sort"
            :items="[
              { label: 'Сначала недавние', value: 'recent' },
              { label: 'Требуют внимания', value: 'attention' },
              { label: 'По алфавиту', value: 'name' },
            ]"
            aria-label="Сортировка проектов"
            class="dashboard-sort"
          />
          <UButton
            color="neutral"
            :variant="showArchived ? 'soft' : 'outline'"
            icon="i-lucide-archive"
            :aria-pressed="showArchived"
            @click="showArchived = !showArchived"
            >{{ showArchived ? 'Архив: показаны' : 'Архив' }}</UButton
          >
        </div>

        <p v-if="!filtered.length" class="empty" role="status">
          По запросу «{{ query }}» ничего не найдено. Уточните название проекта или ведомости.
        </p>

        <div v-else class="panel dashboard-panel" :aria-busy="busy">
          <table class="results dashboard-table">
            <thead>
              <tr>
                <th scope="col">Проект</th>
                <th scope="col">Последняя проверка</th>
                <th scope="col">Очереди</th>
                <th scope="col"><span class="visually-hidden">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="p in filtered"
                :key="p.id"
                class="dashboard-row"
                tabindex="0"
                role="link"
                :aria-label="`Открыть проект ${p.name}`"
                @click="openProject(p)"
                @keydown.enter="openProject(p)"
              >
                <td>
                  <template v-if="renamingId === p.id">
                    <div class="dashboard-rename" @click.stop @keydown.enter.stop>
                      <UInput
                        v-model="renamingName"
                        aria-label="Новое название проекта"
                        :disabled="renamingBusy"
                        autofocus
                        @keydown.enter="saveRename(p)"
                        @keydown.escape="cancelRename"
                      />
                      <UButton
                        icon="i-lucide-check"
                        aria-label="Сохранить название"
                        color="primary"
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
                  </template>
                  <template v-else>
                    <div class="dashboard-name-row">
                      <strong class="dashboard-name">{{ p.name }}</strong>
                      <UBadge v-if="p.archived" color="neutral" variant="soft" size="sm"
                        >В архиве</UBadge
                      >
                      <UButton
                        icon="i-lucide-pencil"
                        :aria-label="`Переименовать ${p.name}`"
                        color="neutral"
                        variant="ghost"
                        size="xs"
                        @click.stop="startRename(p)"
                      />
                    </div>
                  </template>
                  <p class="muted">
                    {{
                      p.runs
                        ? `Проверок: ${p.runs} · Документов: ${p.documents}`
                        : `Документов: ${p.documents} · проверок пока нет`
                    }}
                  </p>
                </td>
                <td>
                  <template v-if="p.lastRun">
                    <UBadge :color="statusColor(p.lastRun.status)" variant="subtle">
                      {{ runLabel(p.lastRun.status) }}
                    </UBadge>
                    <p class="muted dashboard-file" :title="p.lastRun.vor_filename">
                      {{ p.lastRun.vor_filename }} · {{ formatDate(p.lastRun.created_at) }}
                    </p>
                    <UProgress
                      v-if="p.lastRun.status === 'running' && p.lastRun.total"
                      :model-value="
                        Math.floor(((p.lastRun.done + p.lastRun.failed) / p.lastRun.total) * 100)
                      "
                      size="xs"
                      class="dashboard-progress"
                      aria-label="Прогресс проверки"
                    />
                  </template>
                  <UButton
                    v-else
                    variant="link"
                    color="primary"
                    :to="`/projects/${p.id}?import=1`"
                    @click.stop
                  >
                    Продолжить загрузку
                  </UButton>
                </td>
                <td>
                  <div v-if="p.lastRun" class="dashboard-queues">
                    <template v-for="q in ['fix', 'review', 'missing', 'ok'] as const" :key="q">
                      <UBadge
                        v-if="queueBadge(q, p.queues[q])"
                        :label="`${queueBadge(q, p.queues[q])!.count} ${queueBadge(q, p.queues[q])!.label}`"
                        :color="queueBadge(q, p.queues[q])!.color"
                        variant="soft"
                        size="sm"
                      />
                    </template>
                  </div>
                  <span v-else class="muted">—</span>
                </td>
                <td class="row-action">
                  <div class="dashboard-actions" @click.stop>
                    <UButton variant="ghost" :to="`/projects/${p.id}`"> Открыть проект </UButton>
                    <UButton
                      v-if="p.archived"
                      variant="ghost"
                      color="neutral"
                      icon="i-lucide-archive-restore"
                      :aria-label="`Восстановить ${p.name}`"
                      @click="restore(p)"
                    />
                    <UButton
                      v-else
                      variant="ghost"
                      color="neutral"
                      icon="i-lucide-archive"
                      :aria-label="`Архивировать ${p.name}`"
                      @click="askArchive(p)"
                    />
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>

      <UModal v-model:open="archiveModalOpen" title="Архивировать проект?">
        <template #body>
          <p class="muted modal-text">
            Проект «{{ confirmArchiveProject?.name }}» исчезнет из активного списка. Восстановить
            можно через фильтр «Архив».
          </p>
          <div class="toolbar spread modal-footer">
            <UButton color="neutral" variant="ghost" @click="confirmArchiveId = null"
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
.dashboard-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.dashboard-search {
  flex: 1;
  min-width: min(100%, 240px);
}
.dashboard-sort {
  width: 220px;
}
.dashboard-skeleton-bar {
  flex: 1;
  height: 44px;
}
.dashboard-skeleton-sort {
  width: 220px;
  height: 44px;
}
.dashboard-skeleton-panel {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dashboard-skeleton-row {
  height: 64px;
  width: 100%;
}
.dashboard-panel {
  overflow: auto;
  padding: 8px;
}
.dashboard-row {
  cursor: pointer;
}
.dashboard-file {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 340px;
}
.dashboard-name {
  display: block;
  color: var(--ui-text-highlighted);
  overflow-wrap: anywhere;
}
.dashboard-progress {
  margin-top: 6px;
  max-width: 220px;
}
.dashboard-queues {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dashboard-empty {
  padding: 48px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.dashboard-empty h2 {
  margin: 0;
  font-size: 20px;
}
.dashboard-empty p {
  margin: 0;
}
.dashboard-empty-icon {
  font-size: 40px;
  color: var(--ui-text-muted);
}
.dashboard-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.dashboard-rename {
  display: flex;
  align-items: center;
  gap: 8px;
}
.dashboard-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
}
.row-action {
  text-align: right;
  white-space: nowrap;
}
.modal-text {
  padding: 0 24px 8px;
  overflow-wrap: anywhere;
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
@media (max-width: 700px) {
  .dashboard-toolbar {
    flex-direction: column;
  }
  .dashboard-sort {
    width: 100%;
  }
  .dashboard-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .dashboard-table tbody,
  .dashboard-table tr,
  .dashboard-table td {
    display: block;
  }
  .dashboard-table tr {
    padding: 12px 0;
  }
  .dashboard-table tbody tr + tr {
    border-top: 1px solid var(--ui-border);
  }
  .row-action {
    text-align: left;
  }
  .dashboard-actions {
    justify-content: flex-start;
  }
}
</style>
