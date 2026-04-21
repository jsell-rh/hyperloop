<script setup lang="ts">
import type { SpecSummary, Summary, GraphData } from '~/types'

const { fetchSpecs, fetchSummary, fetchGraph } = useApi()

const { data: specs } = useAsyncData<SpecSummary[]>(
  'specs',
  () => fetchSpecs(),
  { server: false, default: () => [] },
)

const { data: summary } = useAsyncData<Summary>(
  'summary',
  () => fetchSummary(),
  { server: false, default: () => ({ total: 0, not_started: 0, in_progress: 0, complete: 0, failed: 0, specs_total: 0, specs_complete: 0 }) },
)

const { data: graph } = useAsyncData<GraphData>(
  'graph',
  () => fetchGraph(),
  { server: false, default: () => ({ nodes: [], edges: [], critical_path: [] }) },
)

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

    <p
      v-if="sortedSpecs.length === 0"
      class="text-center text-gray-400 dark:text-gray-500 py-16"
    >
      No specs found. The orchestrator may not have written state yet.
    </p>

    <!-- Dependency Graph -->
    <div
      v-if="graph && graph.nodes.length > 0"
      class="mt-8 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm"
    >
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Dependency Graph
      </h2>
      <DependencyGraph :graph="graph" />
    </div>
  </div>
</template>
