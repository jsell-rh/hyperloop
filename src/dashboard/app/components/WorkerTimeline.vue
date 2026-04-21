<script setup lang="ts">
import type { ActiveWorker, ReapedWorker } from '~/types'

defineProps<{
  activeWorkers: ActiveWorker[]
  recentReaped: ReapedWorker[]
}>()

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs}s`
}
</script>

<template>
  <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4">
    <h3 class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Worker Timeline</h3>

    <div v-if="activeWorkers.length === 0 && recentReaped.length === 0"
         class="text-sm text-gray-400 dark:text-gray-500">
      No worker activity.
    </div>

    <div class="space-y-2">
      <!-- Active workers -->
      <div v-for="w in activeWorkers" :key="`active-${w.task_id}`"
           class="flex items-center gap-3">
        <div class="flex-1 relative h-8 rounded bg-blue-100 dark:bg-blue-900/40 overflow-hidden">
          <div class="absolute inset-0 flex items-center justify-between px-3">
            <span class="text-xs font-medium text-blue-800 dark:text-blue-200 truncate">
              {{ w.task_id }} &middot; {{ w.role }}
            </span>
            <span class="text-xs text-blue-600 dark:text-blue-300 whitespace-nowrap ml-2">
              {{ formatDuration(w.duration_s) }}
            </span>
          </div>
          <div class="worker-pulse absolute right-0 top-0 bottom-0 w-1 bg-blue-400 dark:bg-blue-500"></div>
        </div>
      </div>

      <!-- Completed workers -->
      <div v-for="(w, i) in recentReaped" :key="`reaped-${i}-${w.task_id}`"
           class="flex items-center gap-3">
        <div class="flex-1 h-8 rounded overflow-hidden flex items-center justify-between px-3"
             :class="w.verdict === 'pass'
               ? 'bg-green-100 dark:bg-green-900/30'
               : 'bg-red-100 dark:bg-red-900/30'">
          <span class="text-xs font-medium truncate"
                :class="w.verdict === 'pass'
                  ? 'text-green-800 dark:text-green-200'
                  : 'text-red-800 dark:text-red-200'">
            {{ w.task_id }} &middot; {{ w.role }}
          </span>
          <div class="flex items-center gap-2 ml-2">
            <span class="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded"
                  :class="w.verdict === 'pass'
                    ? 'bg-green-200 text-green-800 dark:bg-green-800 dark:text-green-200'
                    : 'bg-red-200 text-red-800 dark:bg-red-800 dark:text-red-200'">
              {{ w.verdict }}
            </span>
            <span class="text-xs whitespace-nowrap"
                  :class="w.verdict === 'pass'
                    ? 'text-green-600 dark:text-green-300'
                    : 'text-red-600 dark:text-red-300'">
              {{ formatDuration(w.duration_s) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes pulse-right {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.worker-pulse {
  animation: pulse-right 2s ease-in-out infinite;
}
</style>
