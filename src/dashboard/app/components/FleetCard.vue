<script setup lang="ts">
import type { InstanceSummary } from '~/types'

const props = defineProps<{
  instance: InstanceSummary
  now: number
}>()

const emit = defineEmits<{
  navigate: [repoHash: string]
}>()

const statusColor = computed(() => {
  switch (props.instance.status) {
    case 'running': return 'bg-green-500'
    case 'idle': return 'bg-yellow-500'
    case 'stale': return 'bg-gray-500'
    default: return 'bg-gray-400'
  }
})

const statusLabel = computed(() => {
  switch (props.instance.status) {
    case 'running': return 'Running'
    case 'idle': return 'Idle'
    case 'stale': return 'Stale'
    default: return 'Empty'
  }
})

const convergencePercent = computed(() => {
  if (props.instance.specs_total === 0) return 0
  return Math.round((props.instance.specs_converged / props.instance.specs_total) * 100)
})

const relativeTime = computed(() => {
  if (!props.instance.last_event_at) return 'never'
  try {
    const diff = (props.now - new Date(props.instance.last_event_at).getTime()) / 1000
    if (diff < 0) return 'just now'
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return 'unknown'
  }
})
</script>

<template>
  <button
    class="w-full text-left rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 transition-all duration-150 hover:ring-1 hover:ring-blue-500 hover:shadow-md cursor-pointer"
    @click="emit('navigate', instance.repo_hash)"
  >
    <!-- Header: repo name + status -->
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
        {{ instance.repo_name }}
      </h3>
      <div class="flex items-center gap-1.5 shrink-0 ml-2">
        <span class="h-2 w-2 rounded-full" :class="[statusColor, instance.status === 'running' ? 'animate-status-pulse' : '']" />
        <span class="text-xs text-gray-500 dark:text-gray-400">{{ statusLabel }}</span>
      </div>
    </div>

    <!-- Mini KPI row -->
    <div class="flex items-center gap-4 text-xs text-gray-500 dark:text-gray-400 mb-3">
      <div class="flex items-center gap-1">
        <span class="font-medium text-gray-700 dark:text-gray-300" style="font-variant-numeric: tabular-nums">{{ instance.rounds_completed }}</span>
        <span>rounds</span>
      </div>
      <span class="text-gray-300 dark:text-gray-600">|</span>
      <div class="flex items-center gap-1">
        <span class="font-medium text-gray-700 dark:text-gray-300" style="font-variant-numeric: tabular-nums">{{ instance.verify_pass_rate }}%</span>
        <span>pass</span>
      </div>
      <span class="text-gray-300 dark:text-gray-600">|</span>
      <div class="flex items-center gap-1">
        <span class="font-medium text-gray-700 dark:text-gray-300" style="font-variant-numeric: tabular-nums">{{ instance.drift_remaining }}</span>
        <span>drift</span>
      </div>
    </div>

    <!-- Convergence bar -->
    <div v-if="instance.specs_total > 0" class="mb-2">
      <div class="flex items-center justify-between mb-1">
        <span class="text-[10px] text-gray-400 dark:text-gray-500 uppercase tracking-wider">Convergence</span>
        <span class="text-[10px] font-mono text-gray-400 dark:text-gray-500" style="font-variant-numeric: tabular-nums">
          {{ instance.specs_converged }}/{{ instance.specs_total }}
        </span>
      </div>
      <div class="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
        <div
          class="h-full rounded-full bg-green-500 dark:bg-green-400 transition-all duration-300"
          :style="{ width: `${convergencePercent}%` }"
        />
      </div>
    </div>
    <div v-else class="mb-2">
      <span class="text-[10px] text-gray-400 dark:text-gray-500">No specs tracked</span>
    </div>

    <!-- Footer: last active + active workers -->
    <div class="flex items-center justify-between text-[11px] text-gray-400 dark:text-gray-500">
      <span>Last active: {{ relativeTime }}</span>
      <span v-if="instance.active_workers > 0" class="text-blue-500 dark:text-blue-400 font-medium">
        {{ instance.active_workers }} {{ instance.active_workers === 1 ? 'worker' : 'workers' }}
      </span>
    </div>
  </button>
</template>
