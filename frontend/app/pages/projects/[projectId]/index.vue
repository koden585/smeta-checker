<script setup lang="ts">
import type { ProjectDto, RunDto, DocumentDto } from '~/generated/types.gen'
import { runLabel } from '~/utils/presentation'

type Tab = 'vor' | 'pdf' | 'runs'

const backend = useBackend()
const route = useRoute()
const router = useRouter()

const projectId = computed(() => String(route.params.projectId || ''))
const tab = computed<Tab>(() =>
  route.query.tab === 'pdf' || route.query.tab === 'runs' ? route.query.tab : 'vor',
)

const project = ref<ProjectDto | null>(null)
const documents = ref<DocumentDto[]>([])
const runs = ref<RunDto[]>([])
const busy = ref(true)
const runsOffset = ref(0)
const runsBusy = ref(false)
let runsEpoch = 0
const error = ref('')
const search = ref('')
const showArchived = ref(false)

const renamingProject = ref(false)
const projectNameDraft = ref('')
const projectBusy = ref(false)
const renamingDocId = ref<string | null>(null)
const docNameDraft = ref('')
const docBusy = ref(false)
const archivingDocId = ref<string | null>(null)
const archiveBusy = ref(false)
const confirmProjectArchive = ref(false)

const importOpen = ref(false)
const revisionTargetId = ref<string | undefined>(undefined)

let active = true
let epoch = 0

const vorDocs = computed(() => documents.value.filter((d) => d.kind === 'vor'))
const pdfDocs = computed(() => documents.value.filter((d) => d.kind === 'pdf'))

const visibleDocs = computed(() => {
  const q = search.value.trim().toLocaleLowerCase('ru-RU')
  const base = tab.value === 'pdf' ? pdfDocs.value : vorDocs.value
  if (!q) return base
  return base.filter(
    (d) =>
      d.title.toLocaleLowerCase('ru-RU').includes(q) ||
      d.versions.some((v) => v.filename.toLocaleLowerCase('ru-RU').includes(q)),
  )
})

function setTab(next: Tab) {
  router.replace({ query: { ...route.query, tab: next === 'vor' ? undefined : next } })
}

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

function currentVersion(doc: DocumentDto) {
  return doc.versions.find((v) => v.id === doc.current_version_id) || doc.versions[0] || null
}

function openDocument(doc: DocumentDto) {
  router.push(`/projects/${projectId.value}/documents/${doc.id}`)
}

function openImport(targetDocumentId?: string) {
  revisionTargetId.value = targetDocumentId
  importOpen.value = true
}

function closeImport() {
  importOpen.value = false
  revisionTargetId.value = undefined
  if (route.query.import) router.replace({ query: { ...route.query, import: undefined } })
}

async function afterSaved() {
  closeImport()
  await loadCatalog()
}

function startProjectRename() {
  if (!project.value) return
  projectNameDraft.value = project.value.name
  renamingProject.value = true
}

async function saveProjectRename() {
  const name = projectNameDraft.value.trim()
  if (!name || projectBusy.value || !project.value) return
  projectBusy.value = true
  try {
    project.value = await backend.updateProject(projectId.value, { name })
    renamingProject.value = false
  } catch (e) {
    error.value = readableError(e)
  } finally {
    projectBusy.value = false
  }
}

async function setProjectArchived(archived: boolean) {
  projectBusy.value = true
  try {
    project.value = await backend.updateProject(projectId.value, { archived })
    confirmProjectArchive.value = false
  } catch (e) {
    error.value = readableError(e)
  } finally {
    projectBusy.value = false
  }
}

function startDocRename(doc: DocumentDto) {
  renamingDocId.value = doc.id
  docNameDraft.value = doc.title
}

async function saveDocRename(doc: DocumentDto) {
  const title = docNameDraft.value.trim()
  if (!title || docBusy.value) return
  docBusy.value = true
  try {
    const updated = await backend.updateDocument(doc.id, { title })
    doc.title = updated.title
    renamingDocId.value = null
  } catch (e) {
    error.value = readableError(e)
  } finally {
    docBusy.value = false
  }
}

async function setDocArchived(doc: DocumentDto, archived: boolean) {
  if (archiveBusy.value) return
  archiveBusy.value = true
  try {
    await backend.updateDocument(doc.id, { archived })
    archivingDocId.value = null
    await loadCatalog()
  } catch (e) {
    error.value = readableError(e)
  } finally {
    archiveBusy.value = false
  }
}

function reset() {
  project.value = null
  documents.value = []
  runs.value = []
  error.value = ''
  renamingProject.value = false
  renamingDocId.value = null
  archivingDocId.value = null
  confirmProjectArchive.value = false
  closeImportSilent()
}

function closeImportSilent() {
  importOpen.value = false
  revisionTargetId.value = undefined
}

async function loadCatalog() {
  const id = projectId.value
  const archived = showArchived.value
  try {
    const catalog = await backend.catalog(id, archived)
    if (active && projectId.value === id && showArchived.value === archived)
      documents.value = catalog
  } catch (e) {
    if (active && projectId.value === id) error.value = readableError(e)
  }
}

async function loadRuns(offset: number) {
  const current = ++runsEpoch
  const id = projectId.value
  runsBusy.value = true
  try {
    const loaded = await backend.runs(id, offset)
    if (!active || current !== runsEpoch || projectId.value !== id) return
    runs.value = loaded
    runsOffset.value = offset
  } catch (e) {
    if (active && current === runsEpoch) error.value = readableError(e)
  } finally {
    if (active && current === runsEpoch) runsBusy.value = false
  }
}

async function load() {
  const current = ++epoch
  reset()
  runsEpoch++
  runsOffset.value = 0
  runsBusy.value = false
  busy.value = true
  try {
    await backend.connect()
    if (!active || current !== epoch) return
    const id = projectId.value
    const [loaded, catalog, history] = await Promise.all([
      backend.project(id),
      backend.catalog(id, showArchived.value),
      backend.runs(id, 0),
    ])
    if (!active || current !== epoch || projectId.value !== id) return
    project.value = loaded
    documents.value = catalog
    runs.value = history
  } catch (e) {
    if (active && current === epoch) error.value = readableError(e)
  } finally {
    if (active && current === epoch) busy.value = false
  }
}

watch(projectId, () => load())
watch(showArchived, () => loadCatalog())

onMounted(() => {
  load()
  if (route.query.import === '1') importOpen.value = true
})
onBeforeUnmount(() => {
  active = false
  epoch++
})
</script>

<template>
  <div>
    <WorkspaceHeader active="projects" />
    <main id="main-content" tabindex="-1" class="shell project">
      <nav aria-label="Навигация">
        <UButton to="/" variant="link" color="neutral" icon="i-lucide-arrow-left"
          >Все проекты</UButton
        >
      </nav>

      <template v-if="busy && !project && !error">
        <USkeleton class="project-title-skeleton" />
        <p class="empty" role="status">Загружаем проект…</p>
      </template>

      <UAlert
        v-else-if="error && !project"
        color="error"
        variant="soft"
        title="Не удалось загрузить проект"
        :description="error"
      >
        <template #actions>
          <UButton color="error" variant="soft" size="sm" @click="load()">Повторить</UButton>
        </template>
      </UAlert>

      <template v-else-if="project">
        <div class="page-heading">
          <div class="project-heading-main">
            <template v-if="renamingProject">
              <div class="project-rename">
                <UInput
                  v-model="projectNameDraft"
                  aria-label="Новое название проекта"
                  :disabled="projectBusy"
                  autofocus
                  @keydown.enter="saveProjectRename"
                  @keydown.escape="renamingProject = false"
                />
                <UButton
                  icon="i-lucide-check"
                  aria-label="Сохранить название проекта"
                  color="primary"
                  :loading="projectBusy"
                  @click="saveProjectRename"
                />
                <UButton
                  icon="i-lucide-x"
                  aria-label="Отменить переименование проекта"
                  color="neutral"
                  variant="ghost"
                  :disabled="projectBusy"
                  @click="renamingProject = false"
                />
              </div>
            </template>
            <template v-else>
              <h1 class="page-title">{{ project.name }}</h1>
              <div class="project-heading-actions">
                <UBadge v-if="project.archived" color="neutral" variant="soft">В архиве</UBadge>
                <UButton
                  icon="i-lucide-pencil"
                  :aria-label="`Переименовать ${project.name}`"
                  color="neutral"
                  variant="ghost"
                  size="xs"
                  @click="startProjectRename"
                />
                <UButton
                  v-if="project.archived"
                  icon="i-lucide-archive-restore"
                  color="neutral"
                  variant="outline"
                  size="sm"
                  :loading="projectBusy"
                  @click="setProjectArchived(false)"
                  >Восстановить</UButton
                >
                <UButton
                  v-else
                  icon="i-lucide-archive"
                  color="neutral"
                  variant="outline"
                  size="sm"
                  @click="confirmProjectArchive = true"
                  >В архив</UButton
                >
              </div>
            </template>
          </div>
          <UButton
            icon="i-lucide-plus"
            color="primary"
            :disabled="project.archived"
            @click="openImport()"
            >Добавить документы</UButton
          >
        </div>

        <UAlert
          v-if="project.archived"
          color="neutral"
          variant="soft"
          title="Проект в архиве"
          description="Восстановите проект, чтобы добавлять документы и запускать проверки."
        />

        <UAlert
          v-if="error"
          color="error"
          variant="soft"
          :title="error"
          role="alert"
          class="project-alert"
        />

        <div class="project-tabs" role="group" aria-label="Разделы проекта">
          <UButton
            :variant="tab === 'vor' ? 'soft' : 'ghost'"
            color="neutral"
            :aria-pressed="tab === 'vor'"
            @click="setTab('vor')"
            >Ведомости ({{ vorDocs.length }})</UButton
          >
          <UButton
            :variant="tab === 'pdf' ? 'soft' : 'ghost'"
            color="neutral"
            :aria-pressed="tab === 'pdf'"
            @click="setTab('pdf')"
            >ПД ({{ pdfDocs.length }})</UButton
          >
          <UButton
            :variant="tab === 'runs' ? 'soft' : 'ghost'"
            color="neutral"
            :aria-pressed="tab === 'runs'"
            @click="setTab('runs')"
            >Проверки</UButton
          >
        </div>

        <template v-if="tab === 'runs'">
          <div v-if="!runs.length" class="panel project-empty">
            <UIcon name="i-lucide-clipboard-list" class="project-empty-icon" aria-hidden="true" />
            <h2>Проверок пока нет</h2>
            <p class="muted">Добавьте ведомость и проектные PDF, затем запустите проверку.</p>
          </div>
          <div v-else class="panel project-panel" :aria-busy="busy">
            <table class="results project-table">
              <caption class="visually-hidden">
                История проверок проекта
              </caption>
              <thead>
                <tr>
                  <th scope="col">Ведомость</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Дата</th>
                  <th scope="col"><span class="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="run in runs" :key="run.run_id">
                  <td class="project-cell-name">{{ run.vor_filename }}</td>
                  <td>
                    <UBadge :color="statusColor(run.status)" variant="subtle">
                      {{ runLabel(run.status) }}
                    </UBadge>
                  </td>
                  <td class="muted">{{ formatDate(run.created_at) }}</td>
                  <td class="row-action">
                    <UButton variant="ghost" :to="`/audits/${run.run_id}`"
                      >Открыть результат</UButton
                    >
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="runsOffset || runs.length === 50" class="toolbar">
            <UButton
              :disabled="runsBusy || runsOffset === 0"
              @click="loadRuns(Math.max(0, runsOffset - 50))"
              >Назад</UButton
            >
            <span class="muted">Запуски {{ runsOffset + 1 }}–{{ runsOffset + runs.length }}</span>
            <UButton :disabled="runsBusy || runs.length < 50" @click="loadRuns(runsOffset + 50)"
              >Далее</UButton
            >
          </div>
        </template>

        <template v-else>
          <div class="project-toolbar">
            <UInput
              v-model="search"
              icon="i-lucide-search"
              placeholder="Найти документ…"
              aria-label="Поиск документов"
              class="project-search"
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

          <p v-if="!visibleDocs.length" class="empty" role="status">
            {{
              search
                ? `По запросу «${search}» ничего не найдено.`
                : tab === 'vor'
                  ? 'Ведомостей пока нет. Добавьте первую ведомость.'
                  : 'Проектных PDF пока нет. Добавьте документы ПД.'
            }}
          </p>

          <div v-else class="panel project-panel" :aria-busy="busy">
            <table class="results project-table">
              <caption class="visually-hidden">
                {{
                  tab === 'vor' ? 'Ведомости проекта' : 'Проектные документы ПД'
                }}
              </caption>
              <thead>
                <tr>
                  <th scope="col">Документ</th>
                  <th scope="col">Текущая ревизия</th>
                  <th scope="col">Статус</th>
                  <th scope="col"><span class="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="doc in visibleDocs" :key="doc.id">
                  <td>
                    <template v-if="renamingDocId === doc.id">
                      <div class="project-rename" @click.stop>
                        <UInput
                          v-model="docNameDraft"
                          :aria-label="`Новое название документа ${doc.title}`"
                          :disabled="docBusy"
                          autofocus
                          @keydown.enter="saveDocRename(doc)"
                          @keydown.escape="renamingDocId = null"
                        />
                        <UButton
                          icon="i-lucide-check"
                          :aria-label="`Сохранить название документа ${doc.title}`"
                          color="primary"
                          :loading="docBusy"
                          @click="saveDocRename(doc)"
                        />
                        <UButton
                          icon="i-lucide-x"
                          :aria-label="`Отменить переименование документа ${doc.title}`"
                          color="neutral"
                          variant="ghost"
                          :disabled="docBusy"
                          @click="renamingDocId = null"
                        />
                      </div>
                    </template>
                    <template v-else>
                      <div class="project-name-row">
                        <NuxtLink
                          :to="`/projects/${projectId}/documents/${doc.id}`"
                          class="project-doc-link"
                          >{{ doc.title }}</NuxtLink
                        >
                        <UButton
                          icon="i-lucide-pencil"
                          :aria-label="`Переименовать документ ${doc.title}`"
                          color="neutral"
                          variant="ghost"
                          size="xs"
                          @click="startDocRename(doc)"
                        />
                      </div>
                    </template>
                    <p class="muted">Ревизий: {{ doc.versions.length }}</p>
                  </td>
                  <td class="muted">
                    <template v-if="currentVersion(doc)">
                      {{ currentVersion(doc)!.filename }} · №{{ currentVersion(doc)!.number }}
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td>
                    <div class="project-badges">
                      <UBadge v-if="doc.archived" color="neutral" variant="soft" size="sm"
                        >В архиве</UBadge
                      >
                      <UBadge v-if="doc.pd_updated" color="warning" variant="soft" size="sm"
                        >ПД обновлена</UBadge
                      >
                      <template v-if="doc.last_run">
                        <UBadge
                          :color="statusColor(doc.last_run.status)"
                          variant="subtle"
                          size="sm"
                        >
                          {{ runLabel(doc.last_run.status) }}
                        </UBadge>
                      </template>
                      <span v-if="!doc.archived && !doc.pd_updated && !doc.last_run" class="muted"
                        >—</span
                      >
                    </div>
                  </td>
                  <td class="row-action">
                    <div class="project-actions">
                      <UButton
                        v-if="doc.last_run"
                        variant="ghost"
                        :to="`/audits/${doc.last_run.run_id}`"
                        >Открыть результат</UButton
                      >
                      <UButton
                        v-if="!doc.archived"
                        variant="ghost"
                        color="neutral"
                        icon="i-lucide-file-plus-2"
                        :aria-label="`Новая ревизия ${doc.title}`"
                        @click="openImport(doc.id)"
                      />
                      <UButton
                        v-if="doc.archived"
                        variant="ghost"
                        color="neutral"
                        icon="i-lucide-archive-restore"
                        :aria-label="`Восстановить документ ${doc.title}`"
                        @click="setDocArchived(doc, false)"
                      />
                      <UButton
                        v-else
                        variant="ghost"
                        color="neutral"
                        icon="i-lucide-archive"
                        :aria-label="`Архивировать документ ${doc.title}`"
                        @click="archivingDocId = doc.id"
                      />
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>

        <UModal
          v-model:open="importOpen"
          :title="
            revisionTargetId
              ? `Новая ревизия · ${documents.find((d) => d.id === revisionTargetId)?.title || ''}`
              : 'Добавить документы'
          "
          description="XLSX/CSV и PDF · до 100 МБ · до 50 файлов"
          :ui="{ content: 'max-w-3xl' }"
          @update:open="(open: boolean) => !open && closeImport()"
        >
          <template #body>
            <DocumentImport
              :project-id="projectId"
              :project-name="project.name"
              :documents="documents"
              @changed="loadCatalog"
              :target-document-id="revisionTargetId"
              @saved="afterSaved"
            />
          </template>
        </UModal>

        <UModal
          :open="archivingDocId !== null"
          title="Архивировать документ?"
          @update:open="(open: boolean) => !open && (archivingDocId = null)"
        >
          <template #body>
            <p class="muted modal-text">
              Документ «{{ documents.find((d) => d.id === archivingDocId)?.title }}» исчезнет из
              активного списка. Восстановить можно через фильтр «Архив».
            </p>
            <div class="toolbar spread modal-footer">
              <UButton color="neutral" variant="ghost" @click="archivingDocId = null"
                >Отмена</UButton
              >
              <UButton
                color="primary"
                :loading="archiveBusy"
                @click="
                  () => {
                    const doc = documents.find((d) => d.id === archivingDocId)
                    if (doc) setDocArchived(doc, true)
                  }
                "
                >Архивировать</UButton
              >
            </div>
          </template>
        </UModal>

        <UModal v-model:open="confirmProjectArchive" title="Архивировать проект?">
          <template #body>
            <p class="muted modal-text">
              Проект «{{ project.name }}» исчезнет из активного списка. Восстановить можно через
              фильтр «Архив» на странице проектов.
            </p>
            <div class="toolbar spread modal-footer">
              <UButton color="neutral" variant="ghost" @click="confirmProjectArchive = false"
                >Отмена</UButton
              >
              <UButton color="primary" :loading="projectBusy" @click="setProjectArchived(true)"
                >Архивировать</UButton
              >
            </div>
          </template>
        </UModal>
      </template>
    </main>
  </div>
</template>

<style scoped>
.project-title-skeleton {
  height: 40px;
  width: min(420px, 80%);
  margin-bottom: 16px;
}
.project-heading-main {
  min-width: 0;
}
.project-heading-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
}
.project-alert {
  margin-bottom: 16px;
}
.project-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.project-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.project-search {
  flex: 1;
  min-width: min(100%, 240px);
}
.project-panel {
  overflow: auto;
  padding: 8px;
}
.modal-footer {
  margin-top: 12px;
}
.project-cell-name {
  overflow-wrap: anywhere;
}
.project-name-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.project-doc-link {
  font-weight: 650;
  color: var(--ui-text-highlighted);
  overflow-wrap: anywhere;
}
.project-rename {
  display: flex;
  align-items: center;
  gap: 8px;
}
.project-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.project-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex-wrap: wrap;
}
.project-empty {
  padding: 48px 24px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.project-empty h2 {
  margin: 0;
  font-size: 20px;
}
.project-empty p {
  margin: 0;
}
.project-empty-icon {
  font-size: 40px;
  color: var(--ui-text-muted);
}
.row-action {
  text-align: right;
  white-space: nowrap;
}
.modal-text {
  padding: 0 24px 8px;
  overflow-wrap: anywhere;
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
  .project-toolbar {
    flex-direction: column;
  }
  .project-table thead {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }
  .project-table tbody,
  .project-table tr,
  .project-table td {
    display: block;
  }
  .project-table tr {
    padding: 12px 0;
  }
  .project-table tbody tr + tr {
    border-top: 1px solid var(--ui-border);
  }
  .row-action {
    text-align: left;
  }
  .project-actions {
    justify-content: flex-start;
  }
}
</style>
