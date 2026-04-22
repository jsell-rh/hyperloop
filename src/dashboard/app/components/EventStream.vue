<script setup lang="ts">
import type { FlatEvent, WorkerHeartbeat } from '~/types'

const props = defineProps<{
  events: FlatEvent[]
  activeHeartbeats?: WorkerHeartbeat[]
}>()

const showAll = ref(false)
const INITIAL_LIMIT = 30

const visibleEvents = computed(() => {
  if (showAll.value) return props.events
  return props.events.slice(0, INITIAL_LIMIT)
})

const hasMore = computed(() => props.events.length > INITIAL_LIMIT)

// Re-compute relative times every second
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

function relativeTime(ts: string): string {
  if (!ts) return ''
  try {
    const diff = (now.value - new Date(ts).getTime()) / 1000
    if (diff < 0) return 'just now'
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return ''
  }
}

function heartbeatAgoText(hb: WorkerHeartbeat): string {
  const s = Math.round(hb.seconds_since_last)
  if (s < 60) return `${s}s ago`
  return `${Math.floor(s / 60)}m ago`
}

function eventIcon(event: FlatEvent): { symbol: string; colorClass: string } {
  switch (event.event_type) {
    case 'worker_reaped':
      return {
        symbol: '●',  // filled circle
        colorClass: event.verdict === 'pass'
          ? 'text-green-500'
          : 'text-red-500',
      }
    case 'worker_spawned':
      return { symbol: '▶', colorClass: 'text-blue-500' }  // play
    case 'task_advanced':
      return { symbol: '→', colorClass: 'text-purple-500' }  // arrow
    case 'intake_ran':
      return { symbol: '◉', colorClass: 'text-amber-500' }  // target
    case 'process_improver_ran':
      return { symbol: '⚙', colorClass: 'text-gray-500' }  // gear
    default:
      return { symbol: '•', colorClass: 'text-gray-400' }  // bullet
  }
}
</script>

<template>
  <div>
    <div v-if="events.length === 0" class="text-sm text-gray-400 dark:text-gray-500">
      No events recorded yet.
    </div>

    <div v-else class="space-y-0">
      <!-- Active worker heartbeat rows -->
      <div
        v-for="hb in (activeHeartbeats ?? [])"
        :key="`hb-${hb.task_id}`"
        class="flex items-baseline gap-3 py-1.5 border-b border-blue-100 dark:border-blue-900/30 bg-blue-50/50 dark:bg-blue-950/10"
      >
        <span class="w-16 flex-shrink-0 text-right text-[11px] text-blue-400 dark:text-blue-500 font-mono tabular-nums">
          {{ heartbeatAgoText(hb) }}
        </span>
        <span class="w-4 flex-shrink-0 text-center text-sm text-blue-400">
          &#x22EF;
        </span>
        <span class="text-xs text-blue-600 dark:text-blue-300 min-w-0">
          <span class="font-medium">{{ hb.role }}</span> for {{ hb.task_id }}<template v-if="hb.last_tool_name || hb.last_message_type">: <span class="font-mono bg-blue-100 dark:bg-blue-900/30 px-1 rounded text-[10px]">{{ hb.last_tool_name || hb.last_message_type }}</span></template> ({{ hb.message_count_since }} msgs)
        </span>
      </div>

      <div
        v-for="(event, idx) in visibleEvents"
        :key="idx"
        class="flex items-baseline gap-3 py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-b-0"
      >
        <!-- Timestamp -->
        <span class="w-16 flex-shrink-0 text-right text-[11px] text-gray-400 dark:text-gray-500 font-mono tabular-nums">
          {{ relativeTime(event.timestamp) }}
        </span>

        <!-- Icon -->
        <span class="w-4 flex-shrink-0 text-center text-sm" :class="eventIcon(event).colorClass">
          {{ eventIcon(event).symbol }}
        </span>

        <!-- Detail -->
        <span class="text-xs text-gray-700 dark:text-gray-300 min-w-0">
          {{ event.detail }}
        </span>
      </div>
    </div>

    <!-- Show more button -->
    <button
      v-if="hasMore && !showAll"
      class="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:underline"
      @click="showAll = true"
    >
      Show {{ events.length - INITIAL_LIMIT }} more events
    </button>
  </div>
</template>
