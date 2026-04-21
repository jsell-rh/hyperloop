<script setup lang="ts">
import type { ActivityResponse, ReapedWorker } from '~/types'

const { fetchActivity } = useApi()
const { markFetched } = useLiveness()

const data = ref<ActivityResponse | null>(null)
const loadError = ref<string | null>(null)

async function load(): Promise<void> {
  try {
    data.value = await fetchActivity({ limit: 50 })
    loadError.value = null
    markFetched()
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load activity'
  }
}

onMounted(() => {
  load()
})

// Poll every 10s
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  timer = setInterval(load, 10_000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})

const statusColor = computed(() => {
  if (!data.value) return 'text-gray-400'
  switch (data.value.orchestrator_status) {
    case 'running': return 'text-green-600 dark:text-green-400'
    case 'halted': return 'text-red-600 dark:text-red-400'
    case 'stale': return 'text-yellow-600 dark:text-yellow-400'
    default: return 'text-gray-400 dark:text-gray-500'
  }
})

const statusDot = computed(() => {
  if (!data.value) return 'bg-gray-400'
  switch (data.value.orchestrator_status) {
    case 'running': return 'bg-green-500'
    case 'halted': return 'bg-red-500'
    case 'stale': return 'bg-yellow-500'
    default: return 'bg-gray-400'
  }
})

function relativeTime(ts: string): string {
  if (!ts) return 'never'
  try {
    const diff = (Date.now() - new Date(ts).getTime()) / 1000
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return 'unknown'
  }
}

const lastUpdate = computed(() => {
  if (!data.value || data.value.cycles.length === 0) return 'never'
  return relativeTime(data.value.cycles[0]?.timestamp || '')
})

// Collect recent reaped workers from the latest cycles for the timeline
const recentReaped = computed<ReapedWorker[]>(() => {
  if (!data.value) return []
  const reaped: ReapedWorker[] = []
  for (const cycle of data.value.cycles.slice(0, 5)) {
    reaped.push(...cycle.phases.collect.reaped)
  }
  return reaped.slice(0, 10)
})
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Activity</h1>

    <!-- Error banner -->
    <div v-if="loadError" class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-2 border-l-red-400">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <!-- Disabled / no events state -->
    <div v-if="data && !data.enabled"
         class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-8 text-center">
      <p class="text-gray-500 dark:text-gray-400">
        Enable <code class="text-sm bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">dashboard: { enabled: true }</code>
        in .hyperloop.yaml to see cycle activity.
      </p>
    </div>

    <!-- Active state -->
    <template v-if="data && data.enabled">
      <!-- Region 1: Status Strip -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Cycle</div>
          <div class="text-2xl font-bold text-gray-900 dark:text-gray-100">#{{ data.current_cycle }}</div>
        </div>

        <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Active Workers</div>
          <div class="text-2xl font-bold text-gray-900 dark:text-gray-100">{{ data.active_workers.length }}</div>
        </div>

        <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Status</div>
          <div class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full" :class="statusDot"></span>
            <span class="text-lg font-semibold capitalize" :class="statusColor">
              {{ data.orchestrator_status }}
            </span>
          </div>
        </div>

        <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
          <div class="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Last Update</div>
          <div class="text-lg font-semibold text-gray-900 dark:text-gray-100">{{ lastUpdate }}</div>
        </div>
      </div>

      <!-- Region 2: Worker Timeline -->
      <div class="mb-6">
        <WorkerTimeline
          :active-workers="data.active_workers"
          :recent-reaped="recentReaped"
        />
      </div>

      <!-- Region 3: Cycle Log -->
      <div>
        <h2 class="text-base font-medium text-gray-700 dark:text-gray-300 mb-3">Cycle Log</h2>
        <div v-if="data.cycles.length === 0"
             class="text-sm text-gray-400 dark:text-gray-500">
          No cycles recorded yet.
        </div>
        <div class="space-y-3">
          <CycleCard
            v-for="(cycle, idx) in data.cycles"
            :key="cycle.cycle"
            :cycle="cycle"
            :is-latest="idx === 0"
          />
        </div>
      </div>
    </template>

    <!-- Loading spinner -->
    <div v-if="!data && !loadError" class="py-16 flex flex-col items-center gap-3">
      <svg class="animate-spin h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-400 dark:text-gray-500">Loading activity...</span>
    </div>
  </div>
</template>
