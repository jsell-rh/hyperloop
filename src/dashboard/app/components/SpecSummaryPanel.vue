<script setup lang="ts">
import type { SpecSummaryRecord } from '~/types'

defineProps<{
  summary: SpecSummaryRecord | null
}>()

function formatTime(ts: string | null): string {
  if (!ts) return '--'
  try {
    const d = new Date(ts)
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}
</script>

<template>
  <div
    v-if="summary"
    class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4"
  >
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Summary Record</h3>

    <!-- Baselined spec -->
    <div v-if="summary.baselined" class="text-xs text-gray-400 dark:text-gray-500 py-1">
      <span class="inline-flex items-center gap-1 rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
        Baselined
      </span>
      <p class="mt-1">This spec was baselined -- no hyperloop work history.</p>
    </div>

    <!-- Active summary -->
    <div v-else class="space-y-3">
      <!-- Task counts -->
      <div class="grid grid-cols-3 gap-2 text-center">
        <div>
          <div class="text-lg font-semibold text-gray-900 dark:text-gray-100">{{ summary.total_tasks }}</div>
          <div class="text-[10px] text-gray-400 dark:text-gray-500">Total</div>
        </div>
        <div>
          <div class="text-lg font-semibold text-green-600 dark:text-green-400">{{ summary.completed }}</div>
          <div class="text-[10px] text-gray-400 dark:text-gray-500">Completed</div>
        </div>
        <div>
          <div class="text-lg font-semibold" :class="summary.failed > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-gray-100'">{{ summary.failed }}</div>
          <div class="text-[10px] text-gray-400 dark:text-gray-500">Failed</div>
        </div>
      </div>

      <!-- Failure themes -->
      <div v-if="summary.failure_themes.length > 0" class="border-t border-gray-100 dark:border-gray-800 pt-2">
        <p class="text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Failure themes</p>
        <ul class="space-y-1">
          <li
            v-for="theme in summary.failure_themes"
            :key="theme"
            class="text-xs text-red-600 dark:text-red-400 flex items-start gap-1"
          >
            <span class="text-red-400 mt-0.5 flex-shrink-0">-</span>
            {{ theme }}
          </li>
        </ul>
      </div>

      <!-- Last audit -->
      <div v-if="summary.last_audit_result" class="border-t border-gray-100 dark:border-gray-800 pt-2">
        <div class="flex items-center justify-between">
          <span class="text-xs text-gray-500 dark:text-gray-400">Last audit</span>
          <span
            class="inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium"
            :class="summary.last_audit_result === 'aligned'
              ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
              : 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400'"
          >
            {{ summary.last_audit_result === 'aligned' ? 'Aligned' : 'Misaligned' }}
          </span>
        </div>
        <p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1">
          {{ formatTime(summary.last_audit_at) }}
        </p>
      </div>
    </div>
  </div>
</template>
