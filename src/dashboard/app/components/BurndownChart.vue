<script setup lang="ts">
import type { BurndownPoint } from '~/types'

const props = defineProps<{
  points: BurndownPoint[]
}>()

const chartWidth = 600
const chartHeight = 200
const padding = { top: 16, right: 16, bottom: 28, left: 40 }
const innerWidth = chartWidth - padding.left - padding.right
const innerHeight = chartHeight - padding.top - padding.bottom

const maxY = computed(() => {
  if (props.points.length === 0) return 1
  const allValues = props.points.flatMap(p => [p.burnup, p.burndown])
  return Math.max(...allValues, 1)
})

function xScale(i: number): number {
  if (props.points.length <= 1) return padding.left
  return padding.left + (i / (props.points.length - 1)) * innerWidth
}

function yScale(val: number): number {
  return padding.top + innerHeight - (val / maxY.value) * innerHeight
}

const burnupPath = computed(() => {
  if (props.points.length < 2) return ''
  return props.points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(p.burnup).toFixed(1)}`)
    .join(' ')
})

const burndownPath = computed(() => {
  if (props.points.length < 2) return ''
  return props.points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(p.burndown).toFixed(1)}`)
    .join(' ')
})

const scopeChanges = computed(() => {
  return props.points
    .map((p, i) => ({ ...p, x: xScale(i) }))
    .filter(p => p.scope_change)
})

// Y-axis ticks
const yTicks = computed(() => {
  const max = maxY.value
  const step = Math.max(1, Math.ceil(max / 4))
  const ticks: number[] = []
  for (let v = 0; v <= max; v += step) {
    ticks.push(v)
  }
  return ticks
})

// X-axis labels (show ~5 labels)
const xLabels = computed(() => {
  const pts = props.points
  if (pts.length === 0) return []
  const step = Math.max(1, Math.floor(pts.length / 5))
  const labels: { x: number; label: string }[] = []
  for (let i = 0; i < pts.length; i += step) {
    labels.push({
      x: xScale(i),
      label: `#${pts[i].cycle}`,
    })
  }
  return labels
})
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">Burndown / Burnup</h3>
      <div class="flex items-center gap-4 text-[11px] text-gray-400">
        <span class="flex items-center gap-1">
          <span class="h-2 w-6 rounded-sm bg-green-500" /> Cumulative Completed
        </span>
        <span class="flex items-center gap-1">
          <span class="h-2 w-6 rounded-sm bg-orange-500" /> Drift Remaining
        </span>
      </div>
    </div>

    <div v-if="points.length < 2" class="text-sm text-gray-400 dark:text-gray-500 text-center py-8">
      Not enough data for chart (need 2+ cycles)
    </div>

    <svg
      v-else
      :viewBox="`0 0 ${chartWidth} ${chartHeight}`"
      class="w-full"
      preserveAspectRatio="xMidYMid meet"
    >
      <!-- Grid lines -->
      <line
        v-for="tick in yTicks"
        :key="'grid-' + tick"
        :x1="padding.left"
        :y1="yScale(tick)"
        :x2="chartWidth - padding.right"
        :y2="yScale(tick)"
        stroke="currentColor"
        class="text-gray-100 dark:text-gray-800"
        stroke-width="1"
      />

      <!-- Y-axis labels -->
      <text
        v-for="tick in yTicks"
        :key="'ylabel-' + tick"
        :x="padding.left - 6"
        :y="yScale(tick) + 3"
        class="text-[10px] fill-gray-400 dark:fill-gray-500"
        text-anchor="end"
      >
        {{ tick }}
      </text>

      <!-- X-axis labels -->
      <text
        v-for="lbl in xLabels"
        :key="'xlabel-' + lbl.label"
        :x="lbl.x"
        :y="chartHeight - 4"
        class="text-[10px] fill-gray-400 dark:fill-gray-500"
        text-anchor="middle"
      >
        {{ lbl.label }}
      </text>

      <!-- Scope change markers -->
      <line
        v-for="sc in scopeChanges"
        :key="'scope-' + sc.cycle"
        :x1="sc.x"
        :y1="padding.top"
        :x2="sc.x"
        :y2="padding.top + innerHeight"
        stroke="#a855f7"
        stroke-width="1"
        stroke-dasharray="3,3"
        opacity="0.6"
      />

      <!-- Burnup line (green) -->
      <path
        :d="burnupPath"
        fill="none"
        stroke="#22c55e"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <!-- Burndown line (orange) -->
      <path
        :d="burndownPath"
        fill="none"
        stroke="#f97316"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />

      <!-- Burnup dots -->
      <circle
        v-for="(p, i) in points"
        :key="'bu-' + i"
        :cx="xScale(i)"
        :cy="yScale(p.burnup)"
        r="2.5"
        fill="#22c55e"
      />

      <!-- Burndown dots -->
      <circle
        v-for="(p, i) in points"
        :key="'bd-' + i"
        :cx="xScale(i)"
        :cy="yScale(p.burndown)"
        r="2.5"
        fill="#f97316"
      />
    </svg>
  </div>
</template>
