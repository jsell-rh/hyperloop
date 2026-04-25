<script setup lang="ts">
import type { SpecSummary, Summary, GraphData, PipelineStepInfo } from '~/types'

const { fetchSpecs, fetchSummary, fetchGraph, fetchPipeline } = useApi()

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

// Spec-level metrics computed from specs data
const specMetrics = computed(() => {
  const list = specs.value ?? []
  let complete = 0
  let inProgress = 0
  let blocked = 0
  const total = list.length

  for (const s of list) {
    const allDone = s.tasks_total > 0 && s.tasks_complete === s.tasks_total
    const isBlocked = s.tasks_failed > 0 && s.tasks_in_progress === 0
    const hasProgress = s.tasks_in_progress > 0

    if (allDone) {
      complete++
    } else if (isBlocked) {
      blocked++
    } else if (hasProgress) {
      inProgress++
    }
  }

  return { complete, inProgress, blocked, total }
})

const { data: graph, error: graphError } = useAsyncData<GraphData>(
  'graph',
  async () => {
    const result = await fetchGraph()
    markFetched()
    return result
  },
  { server: false, default: () => ({ nodes: [], edges: [], critical_path: [] }) },
)

const { data: pipelineSteps } = useAsyncData<PipelineStepInfo[]>(
  'pipeline-steps',
  () => fetchPipeline(),
  { server: false, default: () => [] },
)

const error = computed(() => specsError.value || summaryError.value || graphError.value)

// Sort specs: blocked first, then in-progress, then not-started, then complete
const sortedSpecs = computed(() => {
  if (!specs.value) return []
  return [...specs.value].sort((a, b) => {
    const priority = (s: SpecSummary): number => {
      const isBlocked = s.tasks_failed > 0 && s.tasks_in_progress === 0
      if (isBlocked) return 0
      if (s.tasks_in_progress > 0) return 1
      if (s.tasks_not_started > 0) return 2
      if (s.tasks_complete > 0 && s.tasks_failed === 0) return 3
      return 4
    }
    return priority(a) - priority(b)
  })
})

function specDirectory(specRef: string): string {
  const stripped = specRef.replace(/^specs\//, '')
  const lastSlash = stripped.lastIndexOf('/')
  if (lastSlash === -1) return ''
  return stripped.substring(0, lastSlash)
}

interface SpecGroup {
  directory: string
  label: string
  specs: SpecSummary[]
  tasksTotal: number
  tasksComplete: number
  tasksFailed: number
  tasksInProgress: number
}

const groupedSpecs = computed<SpecGroup[]>(() => {
  const groups = new Map<string, SpecSummary[]>()
  for (const spec of sortedSpecs.value) {
    const dir = specDirectory(spec.spec_ref)
    if (!groups.has(dir)) groups.set(dir, [])
    groups.get(dir)!.push(spec)
  }
  const result: SpecGroup[] = []
  for (const [dir, dirSpecs] of groups) {
    let total = 0, complete = 0, failed = 0, inProgress = 0
    for (const s of dirSpecs) {
      total += s.tasks_total
      complete += s.tasks_complete
      failed += s.tasks_failed
      inProgress += s.tasks_in_progress
    }
    result.push({
      directory: dir,
      label: dir || 'general',
      specs: dirSpecs,
      tasksTotal: total,
      tasksComplete: complete,
      tasksFailed: failed,
      tasksInProgress: inProgress,
    })
  }
  return result
})

const activeGroup = ref<string | null>(null)

function scrollToGroup(dir: string): void {
  activeGroup.value = dir
  const el = document.getElementById(`spec-group-${dir || 'general'}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// Dynamic page title
useHead({ title: computed(() => {
  const ip = summary.value?.in_progress ?? 0
  const f = summary.value?.failed ?? 0
  if (f > 0) return `Hyperloop - ${f} failed`
  if (ip > 0) return `Hyperloop - ${ip} in progress`
  return 'Hyperloop Dashboard'
}) })

// Spec hover → graph highlight
const hoveredSpecRef = ref<string | null>(null)

// Collapsible dependency graph (A4)
const graphExpanded = ref(false)

watch(graphExpanded, (val) => {
  localStorage.setItem('hyperloop-graph-expanded', val ? 'true' : 'false')
})

// Collapsed graph summary counts
const activeCount = computed(() => {
  const list = specs.value ?? []
  return list.filter((s) => s.tasks_in_progress > 0).length
})

const blockedCount = computed(() => specMetrics.value.blocked)

// Poll every 10 seconds
let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  // Restore graph collapsed state
  const stored = localStorage.getItem('hyperloop-graph-expanded')
  if (stored === 'true') {
    graphExpanded.value = true
  }

  // Start polling
  refreshInterval = setInterval(async () => {
    await Promise.all([
      refreshNuxtData('specs'),
      refreshNuxtData('summary'),
      refreshNuxtData('graph'),
      refreshNuxtData('pipeline-steps'),
    ])
  }, 10_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 md:px-8 lg:px-10 py-8">
    <!-- Error banner -->
    <div v-if="error" class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-2 border-l-red-400">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <!-- Summary bar: spec-level metrics -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      <SummaryCard label="Complete" :count="specMetrics.complete" color="green" />
      <SummaryCard label="In Progress" :count="specMetrics.inProgress" color="blue" />
      <SummaryCard label="Blocked" :count="specMetrics.blocked" :color="specMetrics.blocked > 0 ? 'red' : undefined" />
      <SummaryCard label="Total Specs" :count="specMetrics.total" />
    </div>
    <!-- Task-level secondary line -->
    <p class="text-sm text-gray-400 mb-8">
      {{ summary?.total ?? 0 }} tasks total ({{ summary?.complete ?? 0 }} complete, {{ summary?.in_progress ?? 0 }} in progress, {{ summary?.failed ?? 0 }} failed)
    </p>

    <!-- Sidebar + main content layout -->
    <div v-if="groupedSpecs.length > 0" class="flex gap-8">
      <!-- Sidebar: directory index with progress -->
      <nav class="hidden lg:block w-52 flex-shrink-0 sticky top-20 self-start">
        <h3 class="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-3">Domains</h3>
        <ul class="space-y-1">
          <li v-for="group in groupedSpecs" :key="'nav-' + group.directory">
            <button
              class="w-full text-left px-2.5 py-1.5 rounded-md text-sm transition-colors duration-100"
              :class="activeGroup === group.directory
                ? 'bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 font-medium'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800/50'"
              @click="scrollToGroup(group.directory)"
              @mouseenter="hoveredSpecRef = null"
            >
              <div class="flex items-center justify-between">
                <span class="capitalize">{{ group.label }}</span>
                <span class="text-[10px] font-mono tabular-nums text-gray-400 dark:text-gray-500">
                  {{ group.tasksComplete }}/{{ group.tasksTotal }}
                </span>
              </div>
              <!-- Mini progress bar -->
              <div class="mt-1 h-1 w-full rounded-full bg-gray-100 dark:bg-gray-800 flex overflow-hidden">
                <div
                  v-if="group.tasksComplete > 0"
                  class="h-1 bg-green-500 dark:bg-green-400"
                  :style="{ width: `${(group.tasksComplete / group.tasksTotal) * 100}%` }"
                />
                <div
                  v-if="group.tasksFailed > 0"
                  class="h-1 bg-red-500 dark:bg-red-400"
                  :style="{ width: `${(group.tasksFailed / group.tasksTotal) * 100}%` }"
                />
                <div
                  v-if="group.tasksInProgress > 0"
                  class="h-1 bg-blue-500 dark:bg-blue-400"
                  :style="{ width: `${(group.tasksInProgress / group.tasksTotal) * 100}%` }"
                />
              </div>
            </button>
          </li>
        </ul>
      </nav>

      <!-- Main: spec card groups -->
      <div class="flex-1 min-w-0">
        <div
          v-for="group in groupedSpecs"
          :key="group.directory"
          :id="`spec-group-${group.directory || 'general'}`"
          class="mb-10 scroll-mt-20"
        >
          <div class="flex items-center gap-3 mb-4">
            <h2 class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider capitalize">
              {{ group.label }}
            </h2>
            <span class="text-[10px] font-mono tabular-nums text-gray-400 dark:text-gray-500">
              {{ group.tasksComplete }}/{{ group.tasksTotal }} tasks
            </span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6 md:gap-5">
            <SpecCard
              v-for="spec in group.specs"
              :key="spec.spec_ref"
              :spec="spec"
              @hover="hoveredSpecRef = $event"
            />
          </div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="sortedSpecs.length === 0 && !error"
      class="py-20 flex flex-col items-center gap-4"
    >
      <svg class="h-12 w-12 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
      <h3 class="text-lg font-medium text-gray-500">Waiting for specs</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        When the orchestrator starts processing, your specs and tasks will show up right here.
      </p>
    </div>

    <!-- Dependency Graph (collapsible) -->
    <div
      v-if="graph && graph.nodes.length > 0"
      class="mt-8 rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
    >
      <button
        class="w-full flex items-center justify-between p-5 text-left"
        @click="graphExpanded = !graphExpanded"
      >
        <div class="flex items-center gap-2">
          <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
            Dependency Graph
          </h2>
          <span class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-400">
            {{ graph.nodes.length }}
          </span>
          <span v-if="!graphExpanded" class="text-xs text-gray-400 dark:text-gray-500 ml-2">
            {{ activeCount }} active, {{ blockedCount }} blocked
          </span>
          <!-- Inline legend -->
          <div v-if="graphExpanded" class="flex items-center gap-4 text-[11px] text-gray-400 ml-auto">
            <span class="flex items-center gap-1">
              <span class="h-2 w-2 rounded-full bg-blue-500" /> In progress
            </span>
            <span class="flex items-center gap-1">
              <span class="h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600" /> Complete
            </span>
            <span class="flex items-center gap-1">
              <span class="h-2 w-2 rounded-full border border-dashed border-gray-400" /> Not started
            </span>
            <span class="flex items-center gap-1">
              <span class="h-2 w-2 rounded-full bg-red-100 border border-red-400" /> Failed
            </span>
          </div>
        </div>
        <svg
          class="h-5 w-5 text-gray-400 dark:text-gray-500 transition-transform duration-200"
          :class="{ 'rotate-180': graphExpanded }"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="2"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <Transition name="expand">
        <div v-if="graphExpanded" class="px-5 pb-5">
          <DependencyGraph :graph="graph" :pipeline-steps="pipelineSteps ?? undefined" :highlight-spec-ref="hoveredSpecRef" />
        </div>
      </Transition>
    </div>
  </div>
</template>
