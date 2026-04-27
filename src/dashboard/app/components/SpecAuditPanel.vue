<script setup lang="ts">
import type { FlatEvent } from '~/types'

const props = defineProps<{
  events: FlatEvent[]
  specRef: string
}>()

interface AuditRow {
  cycle: number
  result: string
  duration_s: number | null
  timestamp: string
}

const auditEvents = computed((): AuditRow[] => {
  return props.events
    .filter(
      (e) =>
        e.event_type === 'audit_ran' &&
        e.detail?.includes(props.specRef),
    )
    .map((e) => ({
      cycle: e.cycle,
      result: e.verdict ?? 'unknown',
      duration_s: e.duration_s,
      timestamp: e.timestamp,
    }))
    .sort((a, b) => a.timestamp.localeCompare(b.timestamp))
})

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '--'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4">
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Audit History</h3>

    <div v-if="auditEvents.length === 0" class="text-xs text-gray-400 dark:text-gray-500 py-2">
      No audits yet for this spec.
    </div>

    <div v-else class="space-y-2">
      <div
        v-for="audit in auditEvents"
        :key="`${audit.cycle}-${audit.timestamp}`"
        class="flex items-center justify-between py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-0"
      >
        <div class="flex items-center gap-2">
          <span class="text-xs font-mono text-gray-500 dark:text-gray-400">
            #{{ audit.cycle }}
          </span>
          <span
            class="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium"
            :class="audit.result === 'aligned'
              ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
              : 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400'"
          >
            <svg v-if="audit.result === 'aligned'" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            <svg v-else class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
            </svg>
            {{ audit.result === 'aligned' ? 'Aligned' : 'Misaligned' }}
          </span>
        </div>
        <div class="flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
          <span>{{ formatDuration(audit.duration_s) }}</span>
          <span>{{ formatTime(audit.timestamp) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
