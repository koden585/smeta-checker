<script setup lang="ts">
const backend = useBackend(),
  route = useRoute(),
  password = ref(''),
  showPassword = ref(false),
  error = ref(''),
  busy = ref(false),
  locked = ref(true),
  checking = ref(true)
const back = computed(() =>
  typeof route.query.back === 'string' && route.query.back.startsWith('/') ? route.query.back : '/',
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
  <div>
    <main id="main-content" class="shell login-shell" tabindex="-1">
      <section class="login-content">
        <div class="page-heading">
          <div>
            <h1>Вход в рабочее пространство</h1>
            <p class="muted">Проверка ВОР и сохранённые результаты доступны по паролю стенда.</p>
          </div>
        </div>
        <p v-if="checking" class="empty" role="status">Проверяем доступ…</p>
        <template v-else>
          <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          <form v-if="locked" class="panel login-form" @submit.prevent="login">
            <UFormField label="Пароль стенда" name="password" required>
              <UInput
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                aria-label="Пароль стенда"
                autocomplete="current-password"
                :disabled="busy"
                class="w-full"
              >
                <template #trailing>
                  <UButton
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    :icon="showPassword ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                    :aria-label="showPassword ? 'Скрыть пароль' : 'Показать пароль'"
                    type="button"
                    @click="showPassword = !showPassword"
                  />
                </template>
              </UInput>
            </UFormField>
            <UButton type="submit" :loading="busy" :disabled="!password || busy" block>
              Войти
            </UButton>
          </form>
        </template>
      </section>
    </main>
  </div>
</template>

<style scoped>
.login-content {
  max-width: 460px;
  margin: 64px auto;
}
.login-form {
  padding: 28px;
  display: grid;
  gap: 24px;
}
@media (max-width: 640px) {
  .login-content {
    margin-block: 32px;
  }
  .login-form {
    padding: 20px;
  }
}
</style>
