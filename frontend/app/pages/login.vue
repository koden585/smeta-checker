<script setup lang="ts">
const backend = useBackend(),
  route = useRoute(),
  password = ref(''),
  error = ref(''),
  busy = ref(false),
  locked = ref(true),
  checking = ref(true)
const back = computed(() =>
  typeof route.query.back === 'string' && route.query.back.startsWith('/')
    ? route.query.back
    : '/history',
)
async function login() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await backend.connect(password.value)
    await navigateTo(back.value, { replace: true })
  } catch (e) {
    error.value = readableError(e)
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  try {
    locked.value = (await backend.gate()).locked
    if (!locked.value) {
      await backend.connect()
      await navigateTo(back.value, { replace: true })
    }
  } catch (e) {
    error.value = readableError(e)
  } finally {
    checking.value = false
  }
})
</script>
<template>
  <main class="shell" style="max-width: 460px">
    <h1 class="page-title">КДФП · Проверка ВОР</h1>
    <p v-if="checking" class="empty">Проверяем доступ…</p>
    <template v-else>
      <p v-if="error" class="error-box" role="alert">{{ error }}</p>
      <form v-if="locked && !error" class="panel" style="padding: 24px" @submit.prevent="login">
        <h2>Вход</h2>
        <p class="muted">Этот стенд защищён общим паролем.</p>
        <UInput
          v-model="password"
          type="password"
          placeholder="Пароль"
          aria-label="Пароль стенда"
          autocomplete="current-password"
          style="margin: 16px 0"
        />
        <UButton type="submit" :loading="busy" :disabled="!password">Войти</UButton>
      </form>
    </template>
  </main>
</template>
