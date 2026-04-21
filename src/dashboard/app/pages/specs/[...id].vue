<script setup lang="ts">
import { marked } from 'marked'
import type { SpecDetail } from '~/types'

const route = useRoute()
const { fetchSpec } = useApi()
const { markFetched } = useLiveness()

const specRef = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id.join('/') : id
})

const { data: spec, error } = useAsyncData<SpecDetail>(
  `spec-${specRef.value}`,
  async () => {
    const result = await fetchSpec(specRef.value)
    markFetched()
    return result
  },
  { server: false },
)

const renderedContent = computed(() => {
  if (!spec.value?.content) return ''
  return marked.parse(spec.value.content) as string
})

useHead({ title: computed(() => {
  if (!spec.value) return 'Spec - Hyperloop'
  return `${spec.value.spec_ref} - Hyperloop`
}) })

const breadcrumbItems = computed(() => [
  { label: 'Overview', to: '/' },
  { label: spec.value?.spec_ref ?? specRef.value },
])

// Poll every 10 seconds
let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refreshInterval = setInterval(() => {
    refreshNuxtData(`spec-${specRef.value}`)
  }, 10_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 py-8">
    <!-- Breadcrumb -->
    <Breadcrumb :items="breadcrumbItems" />

    <!-- Error banner -->
    <div v-if="error" class="mb-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 flex items-center gap-2">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <template v-if="spec">
      <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-1">
        {{ spec.spec_ref }}
      </h1>

      <div class="mt-6 flex flex-col lg:flex-row gap-6">
        <!-- Main: spec content (wider) -->
        <div class="flex-1 min-w-0">
          <div class="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm">
            <div
              class="prose prose-sm dark:prose-invert max-w-none"
              v-html="renderedContent"
            />
          </div>
        </div>

        <!-- Sidebar: tasks (narrower, sticky) -->
        <div class="w-full lg:w-80 flex-shrink-0">
          <div class="lg:sticky lg:top-20">
            <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-3">
              Tasks
            </h2>

            <div class="space-y-2">
              <NuxtLink
                v-for="task in spec.tasks"
                :key="task.id"
                :to="`/tasks/${task.id}`"
                class="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3 shadow-sm transition-colors duration-150 hover:bg-gray-50 dark:hover:bg-gray-800/50 hover:border-gray-300 dark:hover:border-gray-600"
              >
                <div class="flex items-center justify-between mb-1">
                  <span class="text-xs font-mono text-gray-500 dark:text-gray-400">
                    {{ task.id }}
                  </span>
                  <StatusBadge :status="task.status" />
                </div>
                <p class="text-sm text-gray-900 dark:text-gray-100 truncate">
                  {{ task.title }}
                </p>
                <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  {{ task.phase ?? '--' }}
                </p>
              </NuxtLink>
            </div>

            <div
              v-if="spec.tasks.length === 0"
              class="py-10 flex flex-col items-center gap-3"
            >
              <svg class="h-8 w-8 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <h3 class="text-sm font-semibold text-gray-600 dark:text-gray-400">No tasks yet</h3>
              <p class="text-xs text-gray-400 dark:text-gray-500">No tasks have been created for this spec.</p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Loading spinner -->
    <div v-else-if="!error" class="py-16 flex flex-col items-center gap-3">
      <svg class="animate-spin h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-400 dark:text-gray-500">Loading spec...</span>
    </div>
  </div>
</template>
