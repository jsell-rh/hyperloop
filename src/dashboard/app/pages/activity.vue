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
type SortOption = 'most-stuck' | 'longest-running' | 'recent' | 'by-phase'

const sortBy = ref<SortOption>('most-stuck')

const sortOptions: { value: SortOption; label: string }[] = [
  { value: 'most-stuck', label: 'Most Stuck' },
  { value: 'longest-running', label: 'Longest Running' },
  { value: 'recent', label: 'Recent' },
  { value: 'by-phase', label: 'By Phase' },
]

function taskHealthLevel(task: TaskInFlight): 'green' | 'amber' | 'red' {
  const hb = heartbeatForTask(task.task_id)
  const staleSeconds = hb?.seconds_since_last ?? 0
  if (staleSeconds > 120 || task.round >= 3) return 'red'
  if (staleSeconds > 60 || task.round >= 2) return 'amber'
  return 'green'
}

const taskHealthCounts = computed(() => {
  const tasks = data.value?.tasks_in_flight ?? []
  let healthy = 0
  let retrying = 0
  let stuck = 0
  for (const t of tasks) {
    const level = taskHealthLevel(t)
    if (level === 'green') healthy++
    else if (level === 'amber') retrying++
    else stuck++
  }
  return { healthy, retrying, stuck }
})

const tasksInFlight = computed<TaskInFlight[]>(() => {
  const tasks = [...(data.value?.tasks_in_flight ?? [])]
  switch (sortBy.value) {
    case 'most-stuck':
      return tasks.sort((a, b) => {
        if (b.round !== a.round) return b.round - a.round
        const hbA = heartbeatForTask(a.task_id)
        const hbB = heartbeatForTask(b.task_id)
        return (hbB?.seconds_since_last ?? 0) - (hbA?.seconds_since_last ?? 0)
      })
    case 'longest-running':
      return tasks.sort((a, b) => {
        const durA = a.current_worker?.duration_s ?? 0
        const durB = b.current_worker?.duration_s ?? 0
        return durB - durA
      })
    case 'recent':
      return tasks.sort((a, b) => {
        const startA = a.current_worker?.started_at ?? ''
        const startB = b.current_worker?.started_at ?? ''
        return startB.localeCompare(startA)
      })
    case 'by-phase':
      return tasks.sort((a, b) => {
        const phaseOrder = pipelineSteps.value.map(s => s.name)
        const idxA = phaseOrder.indexOf(a.phase)
        const idxB = phaseOrder.indexOf(b.phase)
        return (idxA === -1 ? 999 : idxA) - (idxB === -1 ? 999 : idxB)
      })
    default:
      return tasks
  }
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

// --- Warning attention pulse ---
const warningAttentionKeys = ref<Set<string>>(new Set())
const seenWarningKeys = ref<Set<string>>(new Set())

watch(warnings, (newWarnings) => {
  for (const w of newWarnings) {
    if (w.level === 'red' && !seenWarningKeys.value.has(w.key)) {
      seenWarningKeys.value.add(w.key)
      warningAttentionKeys.value.add(w.key)
      setTimeout(() => {
        warningAttentionKeys.value.delete(w.key)
      }, 5000)
    }
  }
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
      <!-- 1. Sticky header: stale banner + status banner + loop visualizer -->
      <div class="sticky top-0 z-10 -mx-6 md:-mx-8 px-6 md:px-8 pb-2 pt-1 bg-gray-50 dark:bg-gray-950 border-b border-gray-200/80 dark:border-gray-700/50 shadow-sm">
        <!-- Stale data banner -->
        <div
          v-if="data.orchestrator_status === 'stale'"
          class="mb-2 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/40 px-4 py-2.5 flex items-center gap-2"
        >
          <svg class="h-4 w-4 text-amber-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 6zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
          </svg>
          <span class="text-sm text-amber-700 dark:text-amber-300">Data may be stale — no events in 2+ minutes</span>
        </div>

        <!-- Status Banner -->
        <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 mb-2">
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

        <!-- Loop visualizer (inside sticky header) -->
        <ReconcilerLoopBar
          v-if="latestPhaseTiming || currentPhase"
          :phase-timing="latestPhaseTiming"
          :current-phase="currentPhase"
        />
      </div>

      <!-- Content area (dims when stale) -->
      <div
        class="transition-opacity duration-300 mt-4"
        :class="{ 'opacity-60': data.orchestrator_status === 'stale' }"
      >
        <!-- 2. Warning cards -->
        <div v-if="warnings.length > 0" class="space-y-2 mb-6">
          <div
            v-for="w in warnings"
            :key="w.key"
            class="rounded-lg px-4 py-3 border-l-4"
            :class="[
              w.level === 'red'
                ? 'bg-red-50 dark:bg-red-950/20 border-l-red-500'
                : 'bg-amber-50 dark:bg-amber-950/20 border-l-amber-500',
              warningAttentionKeys.has(w.key) ? 'animate-warning-attention' : '',
            ]"
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

        <!-- 3. Active Work section (full-width tasks) -->
        <div class="mb-8">
          <!-- Section header with counts + sort -->
          <div class="flex items-center justify-between mb-4">
            <div>
              <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider">Active Work</h2>
              <p v-if="tasksInFlight.length > 0" class="text-sm text-gray-500 dark:text-gray-400 mt-1">
                In Flight &mdash; {{ tasksInFlight.length }} {{ tasksInFlight.length === 1 ? 'task' : 'tasks' }}
                <span class="text-gray-400 dark:text-gray-500">
                  ({{ taskHealthCounts.healthy }} healthy, {{ taskHealthCounts.retrying }} retrying, {{ taskHealthCounts.stuck }} stuck)
                </span>
              </p>
            </div>
            <div v-if="tasksInFlight.length > 0">
              <select
                v-model="sortBy"
                class="text-xs bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md px-2 py-1 text-gray-600 dark:text-gray-300 focus:outline-none focus:ring-1 focus:ring-blue-400"
              >
                <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
          </div>

          <!-- Task cards grid -->
          <TransitionGroup
            v-if="tasksInFlight.length > 0"
            tag="div"
            class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
            enter-active-class="animate-card-enter"
            leave-active-class="transition-opacity duration-200"
            leave-to-class="opacity-0"
          >
            <TaskActivityCard
              v-for="t in tasksInFlight"
              :key="t.task_id"
              :task="t"
              :pipeline-steps="pipelineSteps"
              :heartbeat="heartbeatForTask(t.task_id)"
            />
          </TransitionGroup>

          <div v-else class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-6 text-center">
            <p class="text-sm text-gray-400 dark:text-gray-500">No tasks in flight.</p>
          </div>
        </div>

        <!-- 4. Event Timeline section (full-width) -->
        <div class="space-y-6">
          <!-- Recent Events -->
          <div>
            <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">Event Timeline</h2>
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
      </div>
    </template>

    <!-- Skeleton loading state -->
    <div v-if="!data && !loadError" class="space-y-4">
      <!-- Status banner skeleton -->
      <div class="skeleton h-10 w-full" />

      <!-- Loop bar skeleton -->
      <div class="skeleton h-6 w-full" />

      <!-- Task cards skeleton (grid) -->
      <div class="skeleton h-4 w-32 mb-2" />
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <div class="skeleton h-28 w-full" />
        <div class="skeleton h-28 w-full" />
        <div class="skeleton h-28 w-full" />
      </div>

      <!-- Event timeline skeleton -->
      <div class="skeleton h-4 w-32 mb-2 mt-6" />
      <div class="space-y-3">
        <div class="skeleton h-8 w-full" />
        <div class="skeleton h-8 w-full" />
        <div class="skeleton h-8 w-[90%]" />
      </div>
    </div>
  </div>
</template>
