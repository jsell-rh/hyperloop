<script setup lang="ts">
import type { WorkerHeartbeat } from '~/types'

const props = defineProps<{
  taskId: string
  taskStatus: string
}>()

const { fetchWorkerHeartbeats } = useApi()

const heartbeat = ref<WorkerHeartbeat | null>(null)
const elapsedSeconds = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null

async function poll(): Promise<void> {
  if (props.taskStatus !== 'in-progress') {
    heartbeat.value = null
    return
  }
  try {
    const resp = await fetchWorkerHeartbeats()
    const found = resp.heartbeats.find((h) => h.task_id === props.taskId)
    heartbeat.value = found ?? null
  } catch {
    // silent
  }
}

function tick(): void {
  if (heartbeat.value) {
    elapsedSeconds.value++
  }
}

watch(() => heartbeat.value?.seconds_since_last, () => {
  if (heartbeat.value) {
    elapsedSeconds.value = heartbeat.value.seconds_since_last
  }
})

onMounted(() => {
  poll()
  pollTimer = setInterval(poll, 3000)
  tickTimer = setInterval(tick, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (tickTimer) clearInterval(tickTimer)
})

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}m ${secs.toString().padStart(2, '0')}s`
}

const pulseDotColor = computed(() => {
  if (!heartbeat.value) return 'bg-blue-500'
  const s = heartbeat.value.seconds_since_last
  if (s < 10) return 'bg-blue-500'
  if (s < 60) return 'bg-blue-400'
  if (s < 120) return 'bg-amber-500'
  return 'bg-red-500'
})

const pulseDotPingColor = computed(() => {
  if (!heartbeat.value) return 'bg-blue-400'
  const s = heartbeat.value.seconds_since_last
  if (s < 10) return 'bg-blue-400'
  if (s < 60) return 'bg-blue-300'
  if (s < 120) return 'bg-amber-400'
  return 'bg-red-400'
})

const showPing = computed(() => {
  if (!heartbeat.value) return false
  return heartbeat.value.seconds_since_last < 10
})

const toolDetail = computed(() => {
  if (!heartbeat.value) return null
  const hb = heartbeat.value
  const toolName = hb.last_tool_name || hb.last_message_type || 'active'
  const secAgo = Math.round(hb.seconds_since_last)
  const agoText = secAgo < 60 ? `${secAgo}s ago` : `${Math.floor(secAgo / 60)}m ago`
  return { toolName, messageCount: hb.message_count_since, agoText }
})
</script>

<template>
  <div
    v-if="heartbeat"
    class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
  >
    <div class="flex items-center gap-2 mb-3">
      <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
        Active Worker
      </h2>
      <span class="relative flex h-2.5 w-2.5">
        <span
          v-if="showPing"
          class="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
          :class="pulseDotPingColor"
        />
        <span class="relative inline-flex rounded-full h-2.5 w-2.5" :class="pulseDotColor" />
      </span>
    </div>

    <div class="flex items-center gap-3 text-sm">
      <span class="font-medium text-blue-600 dark:text-blue-400">{{ heartbeat.role }}</span>
      <span class="text-gray-400 dark:text-gray-500">running</span>
      <span class="font-mono text-gray-700 dark:text-gray-300">{{ formatElapsed(elapsedSeconds) }}</span>
    </div>

    <div v-if="toolDetail" class="mt-2 flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
      <span class="font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-gray-600 dark:text-gray-300">{{ toolDetail.toolName }}</span>
      <span>{{ toolDetail.messageCount }} messages</span>
      <span>{{ toolDetail.agoText }}</span>
    </div>
  </div>
</template>
