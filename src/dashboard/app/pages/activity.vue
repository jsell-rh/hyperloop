<script setup lang="ts">
import type { ActivityResponse, FlatEvent, TaskInFlight, PipelineStepInfo, CycleDetail, CyclePhaseTiming, WorkerHeartbeat } from '~/types'

const { fetchActivity, fetchPipeline, fetchWorkerHeartbeats } = useApi()
const { markFetched, setWorkersActive } = useLiveness()

const data = ref<ActivityResponse | null>(null)
const loadError = ref<string | null>(null)
const pipelineSteps = ref<PipelineStepInfo[]>([])

async function load(): Promise<void> {
  try {
    data.value = await fetchActivity({ limit: 50 })
    loadError.value = null
    markFetched()
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load activity'
  }
}

async function loadPipeline(): Promise<void> {
  try {
    pipelineSteps.value = await fetchPipeline()
  } catch {
    // Pipeline is optional for this view
  }
}

// --- Heartbeat polling ---
const heartbeats = ref<WorkerHeartbeat[]>([])
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let lastHeartbeatFetch = ''

async function loadHeartbeats(): Promise<void> {
  if (!data.value || data.value.active_workers.length === 0) {
    heartbeats.value = []
    setWorkersActive(false)
    return
  }
  try {
    const resp = await fetchWorkerHeartbeats({ since: lastHeartbeatFetch || undefined })
    heartbeats.value = resp.heartbeats
    lastHeartbeatFetch = resp.server_time
    setWorkersActive(resp.heartbeats.length > 0)
  } catch {
    /* silent */
  }
}

function heartbeatForTask(taskId: string): WorkerHeartbeat | null {
  return heartbeats.value.find((h) => h.task_id === taskId) ?? null
}

onMounted(() => {
  load()
  loadPipeline()
  heartbeatTimer = setInterval(loadHeartbeats, 3000)
})

// Poll every 10s
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  timer = setInterval(load, 10_000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (heartbeatTimer) clearInterval(heartbeatTimer)
})

// Dynamic page title
useHead({ title: 'Activity - Hyperloop' })

// Tick for relative timestamps
const now = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  tickTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})
onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
})

// --- Status Banner ---
const statusDotColor = computed(() => {
  if (!data.value) return 'bg-gray-400'
  switch (data.value.orchestrator_status) {
    case 'running': return 'bg-green-500'
    case 'halted': return 'bg-red-500'
    case 'stale': return 'bg-yellow-500'
    default: return 'bg-gray-400'
  }
})

const statusDotPingColor = computed(() => {
  if (!data.value) return ''
  if (data.value.orchestrator_status === 'running') return 'bg-green-400'
  return ''
})

const statusLabel = computed(() => {
  if (!data.value) return 'Loading'
  switch (data.value.orchestrator_status) {
    case 'running': return 'Running'
    case 'halted': return 'Halted'
    case 'stale': return 'Stale'
    default: return data.value.orchestrator_status
  }
})

function relativeTime(ts: string): string {
  if (!ts) return 'never'
  try {
    const diff = (now.value - new Date(ts).getTime()) / 1000
    if (diff < 0) return 'just now'
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return 'unknown'
  }
}

const lastEventTimestamp = computed(() => {
  if (!data.value) return ''
  const events = data.value.flattened_events
  if (events.length > 0) return events[0].timestamp
  if (data.value.cycles.length > 0) return data.value.cycles[0].timestamp
  return ''
})

const workerCountLabel = computed(() => {
  if (!data.value) return ''
  const count = data.value.active_workers.length
  if (count === 0) return 'No workers active'
  if (count === 1) return '1 worker active'
  return `${count} workers active`
})

// --- Loop Visualizer ---
const latestCycle = computed<CycleDetail | null>(() => {
  if (!data.value || data.value.cycles.length === 0) return null
  return data.value.cycles[0]
})

const latestPhaseTiming = computed<CyclePhaseTiming | null>(() => {
  return latestCycle.value?.phase_timing ?? null
})

const currentPhase = computed<string | null>(() => {
  if (!data.value || data.value.orchestrator_status !== 'running') return null
  const cycle = latestCycle.value
  if (!cycle) return null
  // If the cycle is fully complete, no current phase
  if (cycle.duration_s != null) return null
  const timing = cycle.phase_timing
  if (!timing) return 'collect'
  // Walk phase order: if phase has no completed event, it's current
  if (timing.collect_s == null) return 'collect'
  if (timing.reconcile_s == null) return 'reconcile'
  if (timing.advance_s == null) return 'advance'
  if (timing.spawn_s == null) return 'spawn'
  return null
})

// --- Warnings ---
interface Warning {
  key: string
  title: string
  detail: string
  level: 'amber' | 'red'
}

const warnings = computed<Warning[]>(() => {
  if (!data.value) return []
  const result: Warning[] = []

  // Check for failure loops: 3+ consecutive fail verdicts for same task
  const taskFailStreaks: Record<string, { phase: string; count: number }> = {}
  const chronologicalEvents = [...data.value.flattened_events].reverse()
  for (const ev of chronologicalEvents) {
    if (ev.event_type === 'worker_reaped' && ev.task_id) {
      const key = ev.task_id
      if (ev.verdict === 'fail') {
        if (!taskFailStreaks[key]) {
          taskFailStreaks[key] = { phase: '', count: 0 }
        }
        taskFailStreaks[key].count++
      } else {
        delete taskFailStreaks[key]
      }
    }
  }
  for (const [taskId, streak] of Object.entries(taskFailStreaks)) {
    if (streak.count >= 3) {
      result.push({
        key: `fail-loop-${taskId}`,
        title: `Failure loop: ${taskId}`,
        detail: `${streak.count} consecutive failures. The task may be stuck in a loop.`,
        level: 'red',
      })
    }
  }

  // Check for long-running workers (3x average)
  const reapedDurations: number[] = []
  for (const ev of data.value.flattened_events) {
    if (ev.event_type === 'worker_reaped' && ev.duration_s != null) {
      reapedDurations.push(ev.duration_s)
    }
  }
  const avgDuration = reapedDurations.length > 0
    ? reapedDurations.reduce((a, b) => a + b, 0) / reapedDurations.length
    : 0
  if (avgDuration > 0) {
    for (const worker of data.value.active_workers) {
      if (worker.duration_s > avgDuration * 3) {
        const mins = Math.floor(worker.duration_s / 60)
        const avgMins = Math.round(avgDuration / 60)
        result.push({
          key: `long-worker-${worker.task_id}`,
          title: `Worker may be stuck: ${worker.task_id}/${worker.role} running ${mins}m (avg: ${avgMins}m)`,
          detail: `Running ${mins}m while average worker duration is ${avgMins}m. May be stuck.`,
          level: 'amber',
        })
      }
    }
  }

  // Check for prolonged idle (10+ minutes with no events despite in-progress tasks)
  if (data.value.tasks_in_flight.length > 0 && lastEventTimestamp.value) {
    const lastEvtAge = (now.value - new Date(lastEventTimestamp.value).getTime()) / 1000
    if (lastEvtAge > 600) {
      result.push({
        key: 'idle',
        title: 'Prolonged idle',
        detail: `No events in ${Math.floor(lastEvtAge / 60)}m despite ${data.value.tasks_in_flight.length} in-progress tasks.`,
        level: 'amber',
      })
    }
  }

  return result
})

// --- In-Flight Tasks ---
const tasksInFlight = computed<TaskInFlight[]>(() => {
  return data.value?.tasks_in_flight ?? []
})

// --- Flattened Events ---
const flattenedEvents = computed<FlatEvent[]>(() => {
  return data.value?.flattened_events ?? []
})

// --- Raw Cycle Log ---
const rawLogOpen = ref(false)

interface CompressedCycleGroup {
  type: 'single' | 'compressed'
  cycle?: CycleDetail
  fromCycle?: number
  toCycle?: number
  count?: number
  duration?: string
}

function isCycleEmpty(cycle: CycleDetail): boolean {
  const p = cycle.phases
  return (
    p.collect.reaped.length === 0 &&
    !p.intake.ran &&
    p.advance.transitions.length === 0 &&
    p.spawn.spawned.length === 0
  )
}

const compressedCycles = computed<CompressedCycleGroup[]>(() => {
  if (!data.value) return []
  const cycles = data.value.cycles
  const result: CompressedCycleGroup[] = []

  let i = 0
  while (i < cycles.length) {
    const cycle = cycles[i]
    if (!isCycleEmpty(cycle)) {
      result.push({ type: 'single', cycle })
      i++
      continue
    }

    // Start of an empty run
    const start = i
    let totalDuration = 0
    while (i < cycles.length && isCycleEmpty(cycles[i])) {
      totalDuration += cycles[i].duration_s ?? 0
      i++
    }
    const count = i - start

    if (count === 1) {
      result.push({ type: 'single', cycle: cycles[start] })
    } else {
      const fromCycle = cycles[start].cycle
      const toCycle = cycles[i - 1].cycle
      const mins = Math.floor(totalDuration / 60)
      const secs = Math.round(totalDuration % 60)
      const duration = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`
      result.push({
        type: 'compressed',
        fromCycle: toCycle,
        toCycle: fromCycle,
        count,
        duration,
      })
    }
  }

  return result
})

function formatCycleDuration(d: number): string {
  if (d < 1) return `${Math.round(d * 1000)}ms`
  if (d < 60) return `${d.toFixed(1)}s`
  return `${Math.floor(d / 60)}m ${Math.round(d % 60)}s`
}
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 md:px-8 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Activity</h1>

    <!-- Error banner -->
    <div v-if="loadError" class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-4 border-l-red-400">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <!-- Disabled state: FileProbe not configured -->
    <div v-if="data && !data.enabled"
         class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-8 text-center">
      <div class="text-gray-500 dark:text-gray-400 space-y-2">
        <p class="text-lg font-medium text-gray-700 dark:text-gray-300">Activity tracking not enabled</p>
        <p>
          Activity tracking requires
          <code class="text-sm bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded font-mono">dashboard: { enabled: true }</code>
          in <code class="text-sm bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded font-mono">.hyperloop.yaml</code>
        </p>
      </div>
    </div>

    <!-- Active state -->
    <template v-if="data && data.enabled">
      <!-- 1. Status Banner -->
      <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 mb-4">
        <div class="flex items-center gap-4 flex-wrap">
          <!-- Status dot + label -->
          <div class="flex items-center gap-2">
            <span class="relative flex h-2.5 w-2.5">
              <span
                v-if="statusDotPingColor"
                class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
                :class="statusDotPingColor"
              />
              <span class="relative inline-flex rounded-full h-2.5 w-2.5" :class="statusDotColor" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-gray-100">
              {{ statusLabel }}
            </span>
          </div>

          <span class="text-gray-300 dark:text-gray-600">|</span>

          <!-- Cycle number -->
          <span class="text-sm text-gray-600 dark:text-gray-400">
            Cycle #{{ data.current_cycle }}
          </span>

          <span class="text-gray-300 dark:text-gray-600">|</span>

          <!-- Worker count -->
          <span class="text-sm text-gray-600 dark:text-gray-400">
            {{ workerCountLabel }}
          </span>

          <span class="text-gray-300 dark:text-gray-600">|</span>

          <!-- Last event -->
          <span class="text-sm text-gray-500 dark:text-gray-500">
            Updated {{ lastEventTimestamp ? relativeTime(lastEventTimestamp) : 'never' }}
          </span>
        </div>
      </div>

      <!-- 2. Loop visualizer -->
      <ReconcilerLoopBar
        v-if="latestPhaseTiming || currentPhase"
        :phase-timing="latestPhaseTiming"
        :current-phase="currentPhase"
      />

      <!-- 3. Warning cards -->
      <div v-if="warnings.length > 0" class="space-y-2 mb-6">
        <div
          v-for="w in warnings"
          :key="w.key"
          class="rounded-lg px-4 py-3 border-l-4"
          :class="w.level === 'red'
            ? 'bg-red-50 dark:bg-red-950/20 border-l-red-500'
            : 'bg-amber-50 dark:bg-amber-950/20 border-l-amber-500'"
        >
          <p
            class="text-sm font-medium"
            :class="w.level === 'red'
              ? 'text-red-800 dark:text-red-200'
              : 'text-amber-800 dark:text-amber-200'"
          >
            {{ w.title }}
          </p>
          <p
            class="text-xs mt-1"
            :class="w.level === 'red'
              ? 'text-red-600 dark:text-red-400'
              : 'text-amber-600 dark:text-amber-400'"
          >
            {{ w.detail }}
          </p>
        </div>
      </div>

      <!-- 4. Split layout: lg+ side-by-side, mobile stacked -->
      <div class="flex flex-col-reverse lg:flex-row gap-6">
        <!-- Left panel: Cycle timeline (70%) -->
        <div class="lg:w-[70%] min-w-0 space-y-6">
          <!-- Recent Events -->
          <div>
            <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Recent Events</h2>
            <EventStream :events="flattenedEvents" :active-heartbeats="heartbeats" />
          </div>

          <!-- Raw Cycle Log (collapsed) -->
          <div>
            <button
              class="flex items-center gap-2 text-xs font-medium text-gray-400 uppercase tracking-wider hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              @click="rawLogOpen = !rawLogOpen"
            >
              <svg
                class="h-3 w-3 transition-transform"
                :class="{ 'rotate-90': rawLogOpen }"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
              </svg>
              Raw Cycle Log ({{ data.cycles.length }} cycles)
            </button>

            <Transition name="expand">
              <div v-if="rawLogOpen" class="mt-3 space-y-3">
                <template v-for="(group, idx) in compressedCycles" :key="idx">
                  <!-- Single non-empty cycle -->
                  <CycleCard
                    v-if="group.type === 'single' && group.cycle"
                    :cycle="group.cycle"
                    :is-latest="idx === 0"
                  />

                  <!-- Compressed empty cycles -->
                  <div
                    v-else-if="group.type === 'compressed'"
                    class="rounded-lg bg-gray-50 dark:bg-gray-900/50 px-4 py-2 text-xs text-gray-400 dark:text-gray-500 dark:ring-1 dark:ring-white/[0.04]"
                  >
                    Cycles #{{ group.fromCycle }}&#8211;#{{ group.toCycle }}: idle ({{ group.duration }})
                  </div>
                </template>

                <div v-if="data.cycles.length === 0" class="text-sm text-gray-400 dark:text-gray-500">
                  No cycles recorded yet.
                </div>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Right panel: In-flight tasks (30%, sticky on lg) -->
        <div class="lg:w-[30%] flex-shrink-0">
          <div class="lg:sticky lg:top-6">
            <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">In Flight</h2>

            <div v-if="tasksInFlight.length > 0" class="space-y-3">
              <TaskActivityCard
                v-for="t in tasksInFlight"
                :key="t.task_id"
                :task="t"
                :pipeline-steps="pipelineSteps"
                :heartbeat="heartbeatForTask(t.task_id)"
              />
            </div>

            <div v-else class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-6 text-center">
              <p class="text-sm text-gray-400 dark:text-gray-500">No tasks in flight.</p>
            </div>
          </div>
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
