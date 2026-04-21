<script setup lang="ts">
import type { SpecSummary, Summary, GraphData } from '~/types'

const { fetchSpecs, fetchSummary, fetchGraph } = useApi()
const { markFetched } = useLiveness()

const { data: specs, error: specsError } = useAsyncData<SpecSummary[]>(
  'specs',
  async () => {
    const result = await fetchSpecs()
    markFetched()
    return result
  },
  { server: false, default: () => [] },
)

const { data: summary, error: summaryError } = useAsyncData<Summary>(
  'summary',
  async () => {
    const result = await fetchSummary()
    markFetched()
    return result
  },
  { server: false, default: () => ({ total: 0, not_started: 0, in_progress: 0, complete: 0, failed: 0, specs_total: 0, specs_complete: 0 }) },
)

const { data: graph, error: graphError } = useAsyncData<GraphData>(
  'graph',
  async () => {
    const result = await fetchGraph()
    markFetched()
    return result
  },
  { server: false, default: () => ({ nodes: [], edges: [], critical_path: [] }) },
)

const error = computed(() => specsError.value || summaryError.value || graphError.value)

// Sort specs: in-progress first, then not-started, then complete, then all-failed
const sortedSpecs = computed(() => {
  if (!specs.value) return []
  return [...specs.value].sort((a, b) => {
    const priority = (s: SpecSummary): number => {
      if (s.tasks_in_progress > 0) return 0
      if (s.tasks_not_started > 0) return 1
      if (s.tasks_complete > 0 && s.tasks_failed === 0) return 2
      return 3
    }
    return priority(a) - priority(b)
  })
})

// Dynamic page title
useHead({ title: computed(() => {
  const ip = summary.value?.in_progress ?? 0
  const f = summary.value?.failed ?? 0
  if (f > 0) return `Hyperloop - ${f} failed`
  if (ip > 0) return `Hyperloop - ${ip} in progress`
  return 'Hyperloop Dashboard'
}) })

// Poll every 10 seconds
let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refreshInterval = setInterval(async () => {
    await Promise.all([
      refreshNuxtData('specs'),
      refreshNuxtData('summary'),
      refreshNuxtData('graph'),
    ])
  }, 10_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
      Hyperloop
    </h1>
    <p class="text-gray-500 dark:text-gray-400 mb-8">
      Reconciler Dashboard
    </p>

    <!-- Error banner -->
    <div v-if="error" class="mb-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 flex items-center gap-2">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <!-- Summary bar -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
      <SummaryCard label="Total" :count="summary?.total ?? 0" />
      <SummaryCard label="Complete" :count="summary?.complete ?? 0" color="green" />
      <SummaryCard label="In Progress" :count="summary?.in_progress ?? 0" color="blue" />
      <SummaryCard label="Failed" :count="summary?.failed ?? 0" color="red" />
    </div>

    <!-- Spec cards grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <SpecCard
        v-for="spec in sortedSpecs"
        :key="spec.spec_ref"
        :spec="spec"
      />
    </div>

    <!-- Empty state -->
    <div
      v-if="sortedSpecs.length === 0 && !error"
      class="py-16 flex flex-col items-center gap-3"
    >
      <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
      <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">No specs yet</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        Once the orchestrator runs, specs and tasks will appear here.
      </p>
    </div>

    <!-- Dependency Graph -->
    <div
      v-if="graph && graph.nodes.length > 0"
      class="mt-8 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm"
    >
      <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Dependency Graph
      </h2>
      <DependencyGraph :graph="graph" />
    </div>
  </div>
</template>
