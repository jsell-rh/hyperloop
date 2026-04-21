<script setup lang="ts">
import { marked } from 'marked'
import type { SpecDetail } from '~/types'

const route = useRoute()
const router = useRouter()
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

function goBack(): void {
  router.back()
}

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
    <!-- Back link -->
    <button
      class="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
      @click="goBack"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
      Back
    </button>

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

      <!-- Spec content -->
      <div class="mt-6 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-6 shadow-sm">
        <div
          class="prose prose-sm dark:prose-invert max-w-none"
          v-html="renderedContent"
        />
      </div>

      <!-- Task table -->
      <div class="mt-8">
        <h2 class="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-4">
          Tasks
        </h2>

        <div class="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
          <!-- Table header -->
          <div class="grid grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-4 px-4 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-800 text-xs font-medium text-gray-500 dark:text-gray-400">
            <span>ID</span>
            <span>Title</span>
            <span>Status</span>
            <span>Phase</span>
            <span class="text-right">Round</span>
            <span class="text-right">PR</span>
          </div>

          <TaskRow
            v-for="task in spec.tasks"
            :key="task.id"
            :task="task"
          />

          <div
            v-if="spec.tasks.length === 0"
            class="py-16 flex flex-col items-center gap-3"
          >
            <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">No tasks yet</h3>
            <p class="text-sm text-gray-400 dark:text-gray-500">No tasks have been created for this spec.</p>
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
