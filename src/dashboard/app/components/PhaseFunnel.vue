<script setup lang="ts">
import type { PhaseFunnelEntry } from '~/types'

const props = defineProps<{
  phases: PhaseFunnelEntry[]
}>()

const maxDuration = computed(() => {
  if (props.phases.length === 0) return 1
  return Math.max(...props.phases.map(p => p.avg_duration_s), 1)
})

const maxExecutions = computed(() => {
  if (props.phases.length === 0) return 1
  return Math.max(...props.phases.map(p => p.total_executions), 1)
})

function durationBarWidth(phase: PhaseFunnelEntry): string {
  return `${(phase.avg_duration_s / maxDuration.value) * 100}%`
}

function executionBarWidth(phase: PhaseFunnelEntry): string {
  return `${(phase.total_executions / maxExecutions.value) * 100}%`
}

function successColor(rate: number): string {
  if (rate >= 80) return 'text-green-600 dark:text-green-400'
  if (rate >= 50) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
}

function successBg(rate: number): string {
  if (rate >= 80) return 'bg-green-500'
  if (rate >= 50) return 'bg-amber-500'
  return 'bg-red-500'
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">Phase Funnel</h3>

    <div v-if="phases.length === 0" class="text-sm text-gray-400 dark:text-gray-500 text-center py-8">
      No phase data available
    </div>

    <div v-else class="space-y-4">
      <div
        v-for="phase in phases"
        :key="phase.phase"
        class="border-b border-gray-100 dark:border-gray-800 pb-3 last:border-b-0 last:pb-0"
      >
        <!-- Phase header -->
        <div class="flex items-center justify-between mb-2">
          <span class="text-sm font-medium text-gray-700 dark:text-gray-300 capitalize">
            {{ phase.phase }}
          </span>
          <div class="flex items-center gap-3 text-xs">
            <span class="text-gray-400 dark:text-gray-500">
              {{ phase.total_executions }} runs
            </span>
            <span :class="successColor(phase.first_pass_success_rate)" class="font-semibold tabular-nums">
              {{ phase.first_pass_success_rate.toFixed(0) }}% pass
            </span>
          </div>
        </div>

        <!-- Duration bar -->
        <div class="flex items-center gap-2 mb-1">
          <span class="text-[10px] text-gray-400 dark:text-gray-500 w-12 shrink-0">Duration</span>
          <div class="flex-1 h-4 bg-gray-100 dark:bg-gray-800 rounded-sm overflow-hidden">
            <div
              class="h-full bg-blue-500 dark:bg-blue-400 rounded-sm transition-all duration-300"
              :style="{ width: durationBarWidth(phase) }"
            />
          </div>
          <span class="text-[10px] text-gray-500 dark:text-gray-400 w-14 text-right font-mono tabular-nums">
            {{ formatDuration(phase.avg_duration_s) }}
          </span>
        </div>

        <!-- Success rate bar -->
        <div class="flex items-center gap-2">
          <span class="text-[10px] text-gray-400 dark:text-gray-500 w-12 shrink-0">Success</span>
          <div class="flex-1 h-4 bg-gray-100 dark:bg-gray-800 rounded-sm overflow-hidden">
            <div
              :class="successBg(phase.first_pass_success_rate)"
              class="h-full rounded-sm transition-all duration-300"
              :style="{ width: `${phase.first_pass_success_rate}%` }"
            />
          </div>
          <span class="text-[10px] text-gray-500 dark:text-gray-400 w-14 text-right font-mono tabular-nums">
            {{ phase.first_pass_success_rate.toFixed(0) }}%
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
