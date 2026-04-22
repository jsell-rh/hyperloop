<script setup lang="ts">
import type { TaskInFlight, PipelineStepInfo, WorkerHeartbeat } from '~/types'

const props = defineProps<{
  task: TaskInFlight
  pipelineSteps: PipelineStepInfo[]
  heartbeat?: WorkerHeartbeat | null
}>()

// Determine step statuses based on pipeline position and task phase
const stepStatuses = computed(() => {
  const steps = props.pipelineSteps
  if (steps.length === 0) return []

  const currentPhase = props.task.phase
  const history = props.task.worker_history

  // Build a set of completed step names from worker history
  const completedRoles = new Set<string>()
  let lastFailedRole: string | null = null
  for (const entry of history) {
    if (entry.verdict === 'pass') {
      completedRoles.add(entry.role)
    } else if (entry.verdict === 'fail') {
      lastFailedRole = entry.role
      // A fail doesn't clear the completed set — the loop restarts
    }
  }

  let foundCurrent = false
  return steps.map((step) => {
    if (foundCurrent) {
      return { name: step.name, type: step.type, status: 'pending' as const }
    }
    if (step.name === currentPhase) {
      foundCurrent = true
      return { name: step.name, type: step.type, status: 'active' as const }
    }
    // Before the current phase — it's done.
    // Check if the last history entry for this role was a fail
    const lastEntry = [...history].reverse().find((h) => h.role === step.name)
    const verdict = lastEntry?.verdict ?? 'pass'
    return {
      name: step.name,
      type: step.type,
      status: 'done' as const,
      verdict: verdict as 'pass' | 'fail',
    }
  })
})

// Live-ticking timer for the current worker
const elapsedSeconds = ref(0)
let tickInterval: ReturnType<typeof setInterval> | null = null

function updateElapsed(): void {
  if (props.task.current_worker?.started_at) {
    const started = new Date(props.task.current_worker.started_at).getTime()
    elapsedSeconds.value = Math.max(0, Math.round((Date.now() - started) / 1000))
  }
}

onMounted(() => {
  updateElapsed()
  tickInterval = setInterval(updateElapsed, 1000)
})

onUnmounted(() => {
  if (tickInterval) clearInterval(tickInterval)
})

watch(() => props.task.current_worker?.started_at, () => {
  updateElapsed()
})

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}m ${secs.toString().padStart(2, '0')}s`
}

const roundBadgeColor = computed(() => {
  if (props.task.round >= 3) return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
  if (props.task.round >= 2) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
  return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
})

// --- Heartbeat animation class ---
const heartbeatAnimClass = computed(() => {
  if (!props.heartbeat) return ''
  const s = props.heartbeat.seconds_since_last
  if (s < 10) return 'animate-worker-active'
  if (s < 60) return 'animate-worker-thinking'
  return ''
})

// --- Heartbeat amber tint ---
const heartbeatAmberTint = computed(() => {
  if (!props.heartbeat) return false
  return props.heartbeat.seconds_since_last >= 60
})

// --- Pulse dot color ---
const pulseDotColor = computed(() => {
  if (!props.heartbeat) return 'bg-blue-500'
  const s = props.heartbeat.seconds_since_last
  if (s < 10) return 'bg-blue-500'
  if (s < 60) return 'bg-blue-400'
  if (s < 120) return 'bg-amber-500'
  return 'bg-red-500'
})

const pulseDotPingColor = computed(() => {
  if (!props.heartbeat) return 'bg-blue-400'
  const s = props.heartbeat.seconds_since_last
  if (s < 10) return 'bg-blue-400'
  if (s < 60) return 'bg-blue-300'
  if (s < 120) return 'bg-amber-400'
  return 'bg-red-400'
})

const showPulsePing = computed(() => {
  if (!props.heartbeat) return true
  return props.heartbeat.seconds_since_last < 10
})

// --- Heartbeat tool indicator ---
const heartbeatDetail = computed(() => {
  if (!props.heartbeat) return null
  const hb = props.heartbeat
  const toolPart = hb.last_tool_name || hb.last_message_type || 'active'
  const msgCount = hb.message_count_since
  const secAgo = Math.round(hb.seconds_since_last)
  const agoText = secAgo < 60 ? `${secAgo}s ago` : `${Math.floor(secAgo / 60)}m ago`
  return { toolPart, msgCount, agoText }
})

// --- Per-phase duration mapping ---
interface StepDuration {
  durationText: string | null
  verdict: string | null
  isActive: boolean
}

function formatDurationShort(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs.toString().padStart(2, '0')}s`
}

const stepDurations = computed<StepDuration[]>(() => {
  const steps = props.pipelineSteps
  if (steps.length === 0) return []

  const currentPhase = props.task.phase
  const history = props.task.worker_history

  return steps.map((step) => {
    // Find all history entries for this step's role (name)
    const entries = history.filter((h) => h.role === step.name)
    const lastEntry = entries.length > 0 ? entries[entries.length - 1] : null

    const isActive = step.name === currentPhase

    if (isActive) {
      // Show live timer for active step
      return {
        durationText: formatDurationShort(elapsedSeconds.value),
        verdict: null,
        isActive: true,
      }
    }

    if (lastEntry) {
      return {
        durationText: formatDurationShort(lastEntry.duration_s),
        verdict: lastEntry.verdict === 'fail' ? 'fail' : null,
        isActive: false,
      }
    }

    // Check if this step is pending (after current phase) or not yet reached
    return {
      durationText: null,
      verdict: null,
      isActive: false,
    }
  })
})
</script>

<template>
  <NuxtLink
    :to="`/tasks/${task.task_id}`"
    class="block rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 hover:ring-2 hover:ring-blue-400/50 transition-all cursor-pointer"
  >
    <!-- Header: task ID, title, round badge -->
    <div class="flex items-start justify-between mb-3">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-gray-900 dark:text-gray-100">{{ task.task_id }}</span>
          <span class="text-sm text-gray-500 dark:text-gray-400 truncate">{{ task.title }}</span>
        </div>
      </div>
      <span
        v-if="task.round > 0"
        class="flex-shrink-0 ml-3 text-[10px] font-bold uppercase px-2 py-0.5 rounded-full"
        :class="roundBadgeColor"
      >
        Round {{ task.round }}
      </span>
    </div>

    <!-- Pipeline progress bar -->
    <div v-if="stepStatuses.length > 0" class="flex items-center gap-1 mb-1">
      <div
        v-for="(step, idx) in stepStatuses"
        :key="idx"
        class="flex-1 h-2 rounded-full relative group"
        :class="[
          {
            'bg-green-400 dark:bg-green-500': step.status === 'done' && (step as any).verdict !== 'fail',
            'bg-red-400 dark:bg-red-500': step.status === 'done' && (step as any).verdict === 'fail',
            'bg-blue-400 dark:bg-blue-500 animate-badge-pulse': step.status === 'active',
            'bg-gray-200 dark:bg-gray-700': step.status === 'pending',
          },
          step.status === 'active' ? heartbeatAnimClass : '',
          step.status === 'active' && heartbeatAmberTint ? 'bg-amber-400 dark:bg-amber-500' : '',
        ]"
      >
        <!-- Tooltip -->
        <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 px-2 py-1 text-[10px] rounded bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-10">
          {{ step.name }} ({{ step.status }})
        </div>
      </div>
    </div>

    <!-- Step labels -->
    <div v-if="stepStatuses.length > 0" class="flex items-center gap-1 mb-0.5">
      <div
        v-for="(step, idx) in stepStatuses"
        :key="`label-${idx}`"
        class="flex-1 text-center"
      >
        <span
          class="text-[9px] uppercase tracking-wide"
          :class="{
            'text-green-600 dark:text-green-400 font-medium': step.status === 'done' && (step as any).verdict !== 'fail',
            'text-red-600 dark:text-red-400 font-medium': step.status === 'done' && (step as any).verdict === 'fail',
            'text-blue-600 dark:text-blue-400 font-semibold': step.status === 'active',
            'text-gray-400 dark:text-gray-500': step.status === 'pending',
          }"
        >
          {{ step.name }}
        </span>
      </div>
    </div>

    <!-- Per-phase durations -->
    <div v-if="stepDurations.length > 0" class="flex items-center gap-1 mb-3">
      <div
        v-for="(sd, idx) in stepDurations"
        :key="`dur-${idx}`"
        class="flex-1 text-center"
      >
        <span
          v-if="sd.durationText"
          class="text-[9px] font-mono tabular-nums"
          :class="{
            'text-blue-600 dark:text-blue-400 font-semibold': sd.isActive,
            'text-gray-400 dark:text-gray-500': !sd.isActive && !sd.verdict,
            'text-red-500 dark:text-red-400': sd.verdict === 'fail',
          }"
        >
          {{ sd.durationText }}
        </span>
        <span
          v-if="sd.verdict === 'fail'"
          class="block text-[8px] text-red-500 dark:text-red-400"
        >
          (fail)
        </span>
      </div>
    </div>

    <!-- Current worker -->
    <div v-if="task.current_worker" class="space-y-1">
      <div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
        <span class="font-medium text-blue-600 dark:text-blue-400">{{ task.current_worker.role }}</span>
        <span>running</span>
        <span class="font-mono text-blue-700 dark:text-blue-300">{{ formatDuration(elapsedSeconds) }}</span>
        <span class="flex-1" />
        <span class="worker-pulse-dot relative flex h-2 w-2">
          <span v-if="showPulsePing" class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" :class="pulseDotPingColor"></span>
          <span class="relative inline-flex rounded-full h-2 w-2" :class="pulseDotColor"></span>
        </span>
      </div>
      <!-- Tool call indicator -->
      <div v-if="heartbeatDetail" class="flex items-center gap-1.5 text-[10px] text-gray-400 dark:text-gray-500">
        <span class="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-gray-600 dark:text-gray-300">{{ heartbeatDetail.toolPart }}</span>
        <span>&middot;</span>
        <span>{{ heartbeatDetail.msgCount }} messages</span>
        <span>&middot;</span>
        <span>last {{ heartbeatDetail.agoText }}</span>
      </div>
    </div>
  </NuxtLink>
</template>
