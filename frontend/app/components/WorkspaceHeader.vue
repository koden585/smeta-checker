<script setup lang="ts">
const props = defineProps<{ active?: 'projects' | 'create' }>()
const onProjects = computed(() => props.active !== 'create')
</script>

<template>
  <a class="skip-link" href="#main-content">К содержимому</a>
  <header class="app-header">
    <NuxtLink to="/" class="brand" aria-label="КДФП · Проверка ВОР — все проекты">
      <span class="brand-mark">КД<span>ФП</span></span>
      <span class="brand-divider" aria-hidden="true"></span>
      <span class="brand-product">Проверка ВОР</span>
    </NuxtLink>
    <nav class="header-navigation" aria-label="Основная навигация">
      <UButton
        to="/"
        color="neutral"
        :variant="onProjects ? 'soft' : 'ghost'"
        :aria-current="onProjects ? 'page' : undefined"
        icon="i-lucide-layout-dashboard"
        >Проекты</UButton
      >
      <UColorModeButton
        class="theme-button"
        aria-label="Переключить светлую и тёмную тему"
        title="Переключить тему"
      />
    </nav>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding-block: 28px 24px;
  margin: 0 auto 8px;
  width: calc(100% - 64px);
  max-width: 1376px;
  border-bottom: 1px solid var(--ui-border);
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 16px;
  min-height: 44px;
  color: var(--ui-text-highlighted);
  white-space: nowrap;
}
.brand-mark {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.04em;
}
.brand-mark span {
  color: var(--ui-primary);
}
.brand-divider {
  height: 24px;
  width: 1px;
  background: var(--ui-border);
}
.brand-product {
  font-size: 16px;
  font-weight: 650;
}
.header-navigation {
  display: flex;
  align-items: center;
  gap: 8px;
}
.theme-button {
  min-width: 44px;
}
@media (max-width: 640px) {
  .app-header {
    flex-wrap: wrap;
    gap: 12px;
    padding-block: 16px;
    margin-bottom: 8px;
    width: calc(100% - 32px);
  }
  .brand {
    gap: 12px;
  }
  .header-navigation {
    width: 100%;
  }
  .theme-button {
    margin-inline-start: auto;
  }
}
</style>
