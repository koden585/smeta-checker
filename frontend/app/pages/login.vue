<script setup lang="ts">
const backend = useBackend(),
  route = useRoute(),
  password = ref(''),
  loginName = ref(''),
  mode = ref<'local' | 'ldap' | null>(null),
  error = ref(''),
  busy = ref(false),
  checking = ref(true)
const corporate = computed(() => mode.value === 'ldap')
const back = computed(() => safeInternalRedirect(route.query.back))
async function login() {
  if (busy.value || !mode.value) return
  if (!loginName.value.trim() || !password.value) return
  busy.value = true
  error.value = ''
  try {
    await backend.connect(password.value, loginName.value.trim())
    await navigateTo(back.value, { replace: true })
  } catch (e) {
    error.value = readableError(e)
  } finally {
    busy.value = false
    password.value = ''
  }
}
onMounted(async () => {
  try {
    const gate = await backend.gate()
    mode.value = gate.mode
  } catch (e) {
    error.value = readableError(e)
  } finally {
    checking.value = false
  }
})
</script>
<template>
  <div>
    <WorkspaceHeader />
    <main id="main-content" class="shell login-shell" tabindex="-1">
      <section class="login-content">
        <div class="page-heading">
          <div>
            <h1>Вход в рабочее пространство</h1>
            <p class="muted">
              {{
                corporate
                  ? 'Войдите с корпоративным логином и паролем.'
                  : 'Войдите с логином и паролем стенда.'
              }}
            </p>
          </div>
        </div>
        <p v-if="checking" class="empty" role="status">Проверяем доступ…</p>
        <template v-else>
          <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          <form v-if="mode" class="panel login-form" @submit.prevent="login">
            <UFormField :label="corporate ? 'Корпоративный логин' : 'Логин'" name="login" required>
              <UInput
                v-model="loginName"
                name="username"
                :aria-label="corporate ? 'Корпоративный логин' : 'Логин'"
                autocomplete="username"
                autocapitalize="none"
                :spellcheck="false"
                :disabled="busy"
                required
                class="w-full"
              />
            </UFormField>
            <UFormField label="Пароль" name="password" required>
              <UInput
                v-model="password"
                type="password"
                aria-label="Пароль"
                autocomplete="current-password"
                :disabled="busy"
                required
                class="w-full"
              />
            </UFormField>
            <UButton
              type="submit"
              :loading="busy"
              :disabled="!loginName.trim() || !password || busy"
              block
            >
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
