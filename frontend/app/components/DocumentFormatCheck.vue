<script setup lang="ts">
import type { FormatDto, VersionDto } from '~/generated/types.gen'

const props = defineProps<{ version: VersionDto }>()

const backend = useBackend()
const open = ref(false)
const sheet = ref('')
const checking = ref(false)
const error = ref('')
const result = ref<FormatDto | null>(null)

let epoch = 0

const issues = computed(() => (result.value?.issues ?? []).filter((issue) => issue.status !== 'OK'))

async function check() {
  const current = ++epoch
  checking.value = true
  error.value = ''
  try {
    const value = await backend.formatting(props.version.id, sheet.value.trim())
    if (current !== epoch) return
    result.value = value
  } catch (e) {
    if (current !== epoch) return
    error.value = readableError(e)
  } finally {
    if (current === epoch) checking.value = false
  }
}

watch(
  () => props.version.id,
  () => {
    epoch++
    checking.value = false
    open.value = false
    result.value = null
    error.value = ''
    sheet.value = ''
  },
)

watch(sheet, () => {
  epoch++
  checking.value = false
  result.value = null
  error.value = ''
})

watch(open, (value) => {
  if (value && !result.value && !checking.value && !error.value) void check()
})

onBeforeUnmount(() => {
  epoch++
})
</script>

<template>
  <UButton
    v-if="props.version.filename.toLowerCase().endsWith('.xlsx')"
    icon="i-lucide-spell-check"
    variant="outline"
    aria-label="Проверить оформление ведомости"
    @click="open = true"
  >
    Проверить оформление
  </UButton>

  <UModal
    v-model:open="open"
    :title="`Оформление · ${props.version.filename}`"
    description="Детерминированная проверка шапки, ячеек и формул — без модели"
    :ui="{ content: 'max-w-3xl' }"
  >
    <template #body>
      <div class="toolbar format-bar">
        <UInput
          v-model="sheet"
          placeholder="Лист (по умолчанию — первый)"
          aria-label="Лист ведомости для проверки оформления"
          class="format-sheet"
          @keyup.enter="check()"
        />
        <UButton
          variant="outline"
          :loading="checking"
          :disabled="checking"
          aria-label="Проверить оформление повторно"
          @click="check()"
        >
          Проверить снова
        </UButton>
      </div>

      <p v-if="checking && !result" class="empty" role="status">Проверяем оформление…</p>
      <p v-else-if="error" class="error-box" role="alert">
        {{ error }}
        <UButton variant="link" aria-label="Повторить проверку оформления" @click="check()">
          Повторить
        </UButton>
      </p>
      <p v-else-if="result && !issues.length" class="empty" role="status">
        Замечаний нет. Шапка, ячейки и формулы соответствуют шаблону.
      </p>

      <div v-else-if="result" class="format-table-wrap">
        <table class="results">
          <thead>
            <tr>
              <th scope="col">Ячейка</th>
              <th scope="col">Тип</th>
              <th scope="col">Ошибка</th>
              <th scope="col">Ожидалось</th>
              <th scope="col">Факт</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="issue in issues" :key="issue.coord + issue.type">
              <td class="numbers">{{ issue.coord }}</td>
              <td>{{ issue.type }}</td>
              <td class="format-cell">{{ issue.error }}</td>
              <td class="format-cell">{{ issue.expected || '—' }}</td>
              <td class="format-cell">{{ issue.actual || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p class="muted">Замечаний: {{ issues.length }}</p>
      </div>
    </template>
  </UModal>
</template>

<style scoped>
.format-bar {
  margin-bottom: 12px;
}
.format-sheet {
  min-width: 220px;
  flex: 1;
}
.format-table-wrap {
  overflow-x: auto;
}
.format-cell {
  overflow-wrap: anywhere;
  min-width: 120px;
}
</style>
