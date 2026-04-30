<script setup lang="ts">
import type { FlatEvent } from '~/types'

const props = defineProps<{
  events: FlatEvent[]
  specRef: string
}>()

const expanded = ref(false)

const EVENT_DISPLAY: Record<string, { icon: string; color: string; label: string }> = {
  drift_detected: { icon: 'refresh', color: 'blue', label: 'Drift detected' },
  intake_ran: { icon: 'plus', color: 'amber', label: 'Task created' },
  worker_spawned: { icon: 'play', color: 'blue', label: 'Worker spawned' },
  worker_reaped: { icon: 'stop', color: 'gray', label: 'Worker reaped' },
  task_advanced: { icon: 'arrow', color: 'green', label: 'Task advanced' },
  audit_ran: { icon: 'shield', color: 'purple', label: 'Audit ran' },
  convergence_marked: { icon: 'check', color: 'green', label: 'Convergence marked' },
  task_completed: { icon: 'check', color: 'green', label: 'Task completed' },
  task_failed: { icon: 'x', color: 'red', label: 'Task failed' },
}

const specEvents = computed(() => {
  return props.events
    .filter((e) => e.detail?.includes(props.specRef))
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
})

const displayedEvents = computed(() => {
  if (expanded.value) return specEvents.value
  return specEvents.value.slice(-5)
})

function getEventDisplay(eventType: string): { icon: string; color: string; label: string } {
  return EVENT_DISPLAY[eventType] ?? { icon: 'dot', color: 'gray', label: eventType.replace(/_/g, ' ') }
}

function colorClass(color: string): string {
  const map: Record<string, string> = {
    blue: 'bg-blue-500',
    amber: 'bg-amber-500',
    green: 'bg-green-500',
    red: 'bg-red-500',
    gray: 'bg-gray-400 dark:bg-gray-500',
    purple: 'bg-purple-500',
  }
  return map[color] ?? 'bg-gray-400'
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">Event Timeline</h3>
      <button
        v-if="specEvents.length > 5"
        class="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
        @click="expanded = !expanded"
      >
        {{ expanded ? 'Show less' : `Show all (${specEvents.length})` }}
      </button>
    </div>

    <div v-if="specEvents.length === 0" class="text-xs text-gray-400 dark:text-gray-500 py-2">
      No events recorded for this spec.
    </div>

    <div v-else class="relative">
      <!-- Vertical line -->
      <div class="absolute left-[59px] top-2 bottom-2 w-px bg-gray-200 dark:bg-gray-700" />

      <div class="space-y-3">
        <div
          v-for="(event, idx) in displayedEvents"
          :key="`${event.timestamp}-${idx}`"
          class="flex items-start gap-3"
        >
          <!-- Timestamp -->
          <span class="w-[48px] text-[10px] font-mono text-gray-400 dark:text-gray-500 text-right flex-shrink-0 pt-0.5">
            {{ formatTime(event.timestamp) }}
          </span>

          <!-- Dot -->
          <div class="relative z-10 flex-shrink-0 mt-1">
            <div
              class="h-2.5 w-2.5 rounded-full ring-2 ring-white dark:ring-gray-900"
              :class="colorClass(getEventDisplay(event.event_type).color)"
            />
          </div>

          <!-- Description -->
          <div class="min-w-0 flex-1">
            <p class="text-xs text-gray-700 dark:text-gray-300">
              <span class="font-medium">{{ getEventDisplay(event.event_type).label }}</span>
              <span v-if="event.task_id" class="text-gray-500 dark:text-gray-400">
                {{ ' ' }}{{ event.task_id }}
              </span>
            </p>
            <p v-if="event.verdict" class="text-[10px] text-gray-400 dark:text-gray-500 mt-0.5">
              Verdict: {{ event.verdict }}
              <span v-if="event.duration_s !== null"> ({{ event.duration_s < 60 ? event.duration_s.toFixed(1) + 's' : Math.floor(event.duration_s / 60) + 'm' + Math.round(event.duration_s % 60) + 's' }})</span>
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
