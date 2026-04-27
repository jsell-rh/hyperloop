<script setup lang="ts">
import type { TaskInFlight, PipelineStepInfo, WorkerHeartbeat } from '~/types'

const props = defineProps<{
  task: TaskInFlight
  pipelineSteps: PipelineStepInfo[]
  heartbeat?: WorkerHeartbeat | null
}>()

// --- Phase flow strip props ---
const phaseNames = computed<string[]>(() => {
  return props.pipelineSteps.map((s) => s.name)
})

const completedPhases = computed<string[]>(() => {
  const steps = props.pipelineSteps
  const currentPhase = props.task.phase
  const history = props.task.worker_history

  const completed: string[] = []
  for (const step of steps) {
    if (step.name === currentPhase) break
    const entries = history.filter((h) => h.role === step.name)
    const lastEntry = entries.length > 0 ? entries[entries.length - 1] : null
    if (lastEntry && lastEntry.verdict !== 'fail') {
      completed.push(step.name)
    }
  }
  return completed
})

const failedPhases = computed<string[]>(() => {
  const history = props.task.worker_history
  const failed: string[] = []
  for (const step of props.pipelineSteps) {
    if (step.name === props.task.phase) continue
    const entries = history.filter((h) => h.role === step.name)
    const lastEntry = entries.length > 0 ? entries[entries.length - 1] : null
    if (lastEntry && lastEntry.verdict === 'fail') {
      failed.push(step.name)
    }
  }
  return failed
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

const stepDurations = computed<StepDuration[]>(() => {
  const steps = props.pipelineSteps
  if (steps.length === 0) return []

  const currentPhase = props.task.phase
  const history = props.task.worker_history

  return steps.map((step) => {
    const entries = history.filter((h) => h.role === step.name)
    const lastEntry = entries.length > 0 ? entries[entries.length - 1] : null

    const isActive = step.name === currentPhase

    if (isActive) {
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

    return {
      durationText: null,
      verdict: null,
      isActive: false,
    }
  })
})

const roundBadgeColor = computed(() => {
  if (props.task.round >= 3) return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
  if (props.task.round >= 2) return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
  return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
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

// --- Health indicator border ---
type HealthLevel = 'green' | 'amber' | 'red'

const healthLevel = computed<HealthLevel>(() => {
  const staleSeconds = props.heartbeat?.seconds_since_last ?? 0
  if (staleSeconds > 120 || props.task.round >= 3) return 'red'
  if (staleSeconds > 60 || props.task.round >= 2) return 'amber'
  return 'green'
})

const healthBorderClass = computed(() => {
  switch (healthLevel.value) {
    case 'green': return 'border-l-4 border-l-green-500'
    case 'amber': return 'border-l-4 border-l-amber-500'
    case 'red': return 'border-l-4 border-l-red-500'
  }
})

// --- Pulse dot tooltip ---
const pulseDotTooltip = computed(() => {
  if (!props.heartbeat) return 'Worker active'
  const hb = props.heartbeat
  const tool = hb.last_tool_name || hb.last_message_type || 'active'
  const secAgo = Math.round(hb.seconds_since_last)
  const agoText = secAgo < 60 ? `${secAgo}s ago` : `${Math.floor(secAgo / 60)}m ago`
  return `${tool} tool, ${hb.message_count_since} messages, ${agoText}`
})
</script>

<template>
  <NuxtLink
    :to="`/tasks/${task.task_id}`"
    class="block rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 hover:ring-2 hover:ring-blue-400/50 transition-all cursor-pointer"
    :class="healthBorderClass"
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

    <!-- Phase flow strip -->
    <div v-if="phaseNames.length > 0" class="mb-2">
      <PhaseFlowStrip
        :phases="phaseNames"
        :current-phase="task.phase"
        :failed-phases="failedPhases"
        :completed-phases="completedPhases"
      />
    </div>

    <!-- Per-phase durations -->
    <div v-if="stepDurations.length > 0" class="flex items-center gap-0.5 mb-3">
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
      </div>
    </div>

    <!-- Current worker with heartbeat -->
    <div v-if="task.current_worker" class="space-y-1">
      <div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
        <!-- Pulse dot -->
        <span class="relative flex h-2 w-2 flex-shrink-0 cursor-default" :title="pulseDotTooltip">
          <span
            v-if="showPulsePing"
            class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
            :class="pulseDotPingColor"
          />
          <span
            class="relative inline-flex rounded-full h-2 w-2"
            :class="pulseDotColor"
          />
        </span>
        <span class="font-medium text-blue-600 dark:text-blue-400">{{ task.current_worker.role }}</span>
        <span class="font-mono text-blue-700 dark:text-blue-300">{{ formatDuration(elapsedSeconds) }}</span>
        <!-- Tool call indicator -->
        <template v-if="heartbeatDetail">
          <span>&middot;</span>
          <span class="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-[10px] text-gray-600 dark:text-gray-300">{{ heartbeatDetail.toolPart }}</span>
          <span class="text-[10px] text-gray-400 dark:text-gray-500">{{ heartbeatDetail.agoText }}</span>
        </template>
      </div>
    </div>
  </NuxtLink>
</template>
