<script setup lang="ts">
import { marked } from 'marked'
import type { SpecDetail } from '~/types'

const route = useRoute()
const { fetchSpec } = useApi()

const specRef = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id.join('/') : id
})

const { data: spec } = useAsyncData<SpecDetail>(
  `spec-${specRef.value}`,
  () => fetchSpec(specRef.value),
  { server: false },
)

const renderedContent = computed(() => {
  if (!spec.value?.content) return ''
  return marked.parse(spec.value.content) as string
})

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
    <NuxtLink
      to="/"
      class="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
      Back to overview
    </NuxtLink>

    <template v-if="spec">
      <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-1">
        {{ spec.spec_ref }}
      </h1>

      <!-- Spec content -->
      <div class="mt-6 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 shadow-sm">
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

        <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-sm overflow-hidden">
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

          <p
            v-if="spec.tasks.length === 0"
            class="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500"
          >
            No tasks for this spec.
          </p>
        </div>
      </div>
    </template>

    <div v-else class="py-16 text-center text-gray-400 dark:text-gray-500">
      Loading spec...
    </div>
  </div>
</template>
