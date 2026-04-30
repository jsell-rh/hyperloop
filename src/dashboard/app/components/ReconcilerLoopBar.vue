<script setup lang="ts">
import type { CyclePhaseTiming } from '~/types'

const props = defineProps<{
  phaseTiming: CyclePhaseTiming | null
  currentPhase: string | null
}>()

interface PhaseSegment {
  key: string
  label: string
  duration: number | null
  color: string
  activeColor: string
}

const phases: PhaseSegment[] = [
  { key: 'collect', label: 'Collect', duration: null, color: 'bg-green-500', activeColor: 'bg-blue-500' },
  { key: 'reconcile', label: 'Reconcile', duration: null, color: 'bg-purple-500', activeColor: 'bg-blue-500' },
  { key: 'advance', label: 'Advance', duration: null, color: 'bg-blue-500', activeColor: 'bg-blue-500' },
  { key: 'spawn', label: 'Spawn', duration: null, color: 'bg-amber-500', activeColor: 'bg-blue-500' },
]

const phaseOrder = ['collect', 'reconcile', 'advance', 'spawn'] as const

const segments = computed(() => {
  const timing = props.phaseTiming
  if (!timing) return phases

  const durations: Record<string, number | null> = {
    collect: timing.collect_s,
    reconcile: timing.reconcile_s,
    advance: timing.advance_s,
    spawn: timing.spawn_s,
  }

  return phases.map(p => ({
    ...p,
    duration: durations[p.key] ?? null,
  }))
})

const totalDuration = computed(() => {
  return segments.value.reduce((sum, s) => sum + (s.duration ?? 0), 0)
})

function segmentWidthPercent(seg: PhaseSegment & { duration: number | null }): number {
  if (!totalDuration.value || seg.duration == null) return 25 // equal width when no data
  return Math.max((seg.duration / totalDuration.value) * 100, 5) // min 5% so label fits
}

function phaseState(key: string): 'completed' | 'active' | 'future' {
  if (!props.currentPhase) {
    // If no current phase but we have timing, all phases are completed
    if (props.phaseTiming) return 'completed'
    return 'future'
  }
  const currentIdx = phaseOrder.indexOf(props.currentPhase as typeof phaseOrder[number])
  const thisIdx = phaseOrder.indexOf(key as typeof phaseOrder[number])
  if (currentIdx < 0 || thisIdx < 0) return 'future'
  if (thisIdx < currentIdx) return 'completed'
  if (thisIdx === currentIdx) return 'active'
  return 'future'
}

function formatDuration(d: number | null): string {
  if (d == null) return '--'
  if (d < 0.01) return '<0.01s'
  if (d < 1) return `${(d * 1000).toFixed(0)}ms`
  if (d < 60) return `${d.toFixed(1)}s`
  return `${Math.floor(d / 60)}m${Math.round(d % 60)}s`
}

function segmentTooltip(seg: PhaseSegment & { duration: number | null }): string {
  const state = phaseState(seg.key)
  if (state === 'active') return `${seg.label}: In progress`
  if (state === 'future') return `${seg.label}: Pending`
  return seg.duration != null
    ? `${seg.label}: ${formatDuration(seg.duration)}`
    : `${seg.label}: Completed`
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4 mb-4">
    <div class="flex items-center gap-1.5 mb-2">
      <span class="text-xs font-medium text-gray-400 uppercase tracking-wider">Cycle Phases</span>
      <span v-if="totalDuration > 0" class="text-xs text-gray-400 dark:text-gray-500 ml-auto">
        Total: {{ formatDuration(totalDuration) }}
      </span>
    </div>

    <!-- Phase bar -->
    <div class="flex h-6 rounded-md overflow-hidden gap-0.5">
      <div
        v-for="seg in segments"
        :key="seg.key"
        class="relative transition-all duration-300 rounded-sm cursor-default"
        :style="{ width: segmentWidthPercent(seg) + '%' }"
        :class="[
          phaseState(seg.key) === 'active'
            ? seg.activeColor + ' animate-pulse'
            : phaseState(seg.key) === 'completed'
              ? seg.color
              : 'bg-gray-200 dark:bg-gray-700',
        ]"
        :title="segmentTooltip(seg)"
      >
        <span
          class="absolute inset-0 flex items-center justify-center text-[10px] font-medium truncate px-1"
          :class="phaseState(seg.key) === 'future'
            ? 'text-gray-400 dark:text-gray-500'
            : 'text-white'"
        >
          {{ seg.label }}
        </span>
      </div>
    </div>

    <!-- Duration labels -->
    <div class="flex gap-0.5 mt-1">
      <div
        v-for="seg in segments"
        :key="seg.key + '-label'"
        class="text-center text-[10px] text-gray-400 dark:text-gray-500 truncate"
        :style="{ width: segmentWidthPercent(seg) + '%' }"
      >
        {{ formatDuration(seg.duration) }}
      </div>
    </div>
  </div>
</template>
