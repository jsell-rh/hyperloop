<script setup lang="ts">
import type { GraphData, PipelineStepInfo, TaskSummary, TaskStatusValue, FleetResponse } from '~/types'

const { fetchGraph, fetchTasks, fetchPipeline, fetchFleet } = useApi()
const { markFetched } = useLiveness()

const route = useRoute()
const repoHash = computed(() => route.params.hash as string)

const repoName = ref<string | null>(null)

async function resolveRepoName(): Promise<void> {
  if (!repoHash.value) return
  try {
    const resp = await fetchFleet()
    const match = resp.instances.find((i: FleetResponse['instances'][number]) => i.repo_hash === repoHash.value)
    if (match) repoName.value = match.repo_name
  } catch {
    // Non-critical
  }
}

const repoParam = computed(() => ({ repo: repoHash.value }))

const { data: graph } = useAsyncData<GraphData>(
  'tasks-graph',
  async () => {
    const result = await fetchGraph(repoParam.value)
    markFetched()
    return result
  },
  { server: false, default: () => ({ nodes: [], edges: [], critical_path: [] }) },
)

const { data: pipelineSteps } = useAsyncData<PipelineStepInfo[]>(
  'tasks-pipeline',
  () => fetchPipeline(repoParam.value),
  { server: false, default: () => [] },
)

const { data: tasks } = useAsyncData<TaskSummary[]>(
  'tasks-list',
  async () => {
    const result = await fetchTasks(repoParam.value)
    markFetched()
    return result
  },
  { server: false, default: () => [] },
)

onMounted(() => {
  resolveRepoName()
})

let graphTimer: ReturnType<typeof setInterval> | null = null
let tasksTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  graphTimer = setInterval(async () => {
    graph.value = await fetchGraph(repoParam.value)
    markFetched()
  }, 10_000)
  tasksTimer = setInterval(async () => {
    tasks.value = await fetchTasks(repoParam.value)
  }, 10_000)
})

onUnmounted(() => {
  if (graphTimer) clearInterval(graphTimer)
  if (tasksTimer) clearInterval(tasksTimer)
})

useHead({
  title: computed(() => {
    const name = repoName.value || repoHash.value
    return `Tasks - ${name} - Hyperloop`
  }),
})

type FilterValue = 'all' | TaskStatusValue

const statusFilter = ref<FilterValue>('all')

const filters: { value: FilterValue; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'in-progress', label: 'In Progress' },
  { value: 'not-started', label: 'Not Started' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

const filteredTasks = computed(() => {
  const list = tasks.value ?? []
  if (statusFilter.value === 'all') return list
  return list.filter(t => t.status === statusFilter.value)
})

const taskCounts = computed(() => {
  const list = tasks.value ?? []
  return {
    all: list.length,
    'in-progress': list.filter(t => t.status === 'in-progress').length,
    'not-started': list.filter(t => t.status === 'not-started').length,
    completed: list.filter(t => t.status === 'completed').length,
    failed: list.filter(t => t.status === 'failed').length,
  }
})

function statusBadgeClass(status: TaskStatusValue): string {
  switch (status) {
    case 'completed': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
    case 'in-progress': return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
    case 'failed': return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
    case 'not-started': return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
  }
}

function statusLabel(status: TaskStatusValue): string {
  switch (status) {
    case 'completed': return 'Completed'
    case 'in-progress': return 'In Progress'
    case 'failed': return 'Failed'
    case 'not-started': return 'Not Started'
  }
}

function specShortName(specRef: string): string {
  return specRef.replace(/^specs\//, '').replace(/\.spec\.md$/, '')
}
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 md:px-8 py-8">
    <!-- Breadcrumb -->
    <div class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-2">
      <NuxtLink to="/" class="hover:text-gray-700 dark:hover:text-gray-300 transition-colors flex items-center gap-1">
        <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Fleet
      </NuxtLink>
      <span class="text-gray-300 dark:text-gray-600">/</span>
      <span class="text-gray-700 dark:text-gray-300 font-medium">{{ repoName || repoHash }}</span>
      <span class="text-gray-300 dark:text-gray-600">/</span>
      <span class="text-gray-700 dark:text-gray-300 font-medium">Tasks</span>
    </div>

    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Tasks</h1>

    <!-- Dependency Graph -->
    <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none mb-6">
      <div class="px-5 pt-4 pb-2">
        <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider">Dependency Graph</h2>
      </div>
      <div class="px-5 pb-5">
        <DependencyGraph
          v-if="graph.nodes.length > 0"
          :graph="graph"
          :pipeline-steps="pipelineSteps ?? undefined"
          :repo-hash="repoHash"
        />
        <div v-else class="py-8 text-center text-sm text-gray-400 dark:text-gray-500">
          No tasks found.
        </div>
      </div>
    </div>

    <!-- Task Table -->
    <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
      <div class="px-5 pt-4 pb-3 flex items-center justify-between flex-wrap gap-3">
        <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider">
          All Tasks
          <span class="ml-1 text-gray-300 dark:text-gray-600">({{ taskCounts.all }})</span>
        </h2>

        <!-- Status filter chips -->
        <div class="flex items-center gap-1.5">
          <button
            v-for="f in filters"
            :key="f.value"
            class="px-2.5 py-1 text-xs rounded-full border transition-colors"
            :class="statusFilter === f.value
              ? 'bg-gray-900 text-white border-gray-900 dark:bg-gray-100 dark:text-gray-900 dark:border-gray-100'
              : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700 dark:hover:border-gray-600'"
            @click="statusFilter = f.value"
          >
            {{ f.label }}
            <span
              v-if="f.value !== 'all'"
              class="ml-1 opacity-60"
            >{{ taskCounts[f.value] }}</span>
          </button>
        </div>
      </div>

      <!-- Table -->
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-t border-gray-100 dark:border-gray-800">
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">ID</th>
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Title</th>
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Status</th>
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Phase</th>
              <th class="px-5 py-2.5 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Round</th>
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Spec</th>
              <th class="px-5 py-2.5 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">PR</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in filteredTasks"
              :key="task.id"
              class="border-t border-gray-50 dark:border-gray-800/50 hover:bg-gray-50 dark:hover:bg-gray-800/40 cursor-pointer transition-colors"
              @click="navigateTo(`/repo/${repoHash}/tasks/${task.id}`)"
            >
              <td class="px-5 py-3 font-mono text-xs text-gray-500 dark:text-gray-400 whitespace-nowrap">{{ task.id }}</td>
              <td class="px-5 py-3 text-gray-900 dark:text-gray-100 max-w-xs truncate">{{ task.title }}</td>
              <td class="px-5 py-3 whitespace-nowrap">
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="statusBadgeClass(task.status)"
                >
                  {{ statusLabel(task.status) }}
                </span>
              </td>
              <td class="px-5 py-3 text-gray-500 dark:text-gray-400 text-xs font-mono whitespace-nowrap">
                {{ task.phase ?? '—' }}
              </td>
              <td class="px-5 py-3 text-right text-gray-500 dark:text-gray-400 tabular-nums">
                {{ task.round }}
              </td>
              <td class="px-5 py-3 text-xs text-gray-500 dark:text-gray-400 max-w-[180px] truncate" :title="task.spec_ref">
                {{ specShortName(task.spec_ref) }}
              </td>
              <td class="px-5 py-3 whitespace-nowrap">
                <a
                  v-if="task.pr"
                  :href="task.pr"
                  target="_blank"
                  rel="noopener"
                  class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
                  @click.stop
                >
                  PR
                </a>
                <span v-else class="text-xs text-gray-300 dark:text-gray-600">—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <div
          v-if="filteredTasks.length === 0"
          class="px-5 py-8 text-center text-sm text-gray-400 dark:text-gray-500"
        >
          {{ statusFilter === 'all' ? 'No tasks found.' : `No ${statusFilter} tasks.` }}
        </div>
      </div>
    </div>
  </div>
</template>
