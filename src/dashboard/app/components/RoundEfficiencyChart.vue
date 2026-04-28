<script setup lang="ts">
import type { RoundEfficiencyPoint, RoundDistributionBucket } from '~/types'

const props = defineProps<{
  trend: RoundEfficiencyPoint[]
  distribution: RoundDistributionBucket[]
}>()

// --- Trend line chart ---
const chartWidth = 600
const chartHeight = 160
const padding = { top: 16, right: 16, bottom: 28, left: 40 }
const innerWidth = chartWidth - padding.left - padding.right
const innerHeight = chartHeight - padding.top - padding.bottom

const maxRounds = computed(() => {
  if (props.trend.length === 0) return 5
  return Math.max(...props.trend.map(p => p.avg_rounds), 1)
})

function xScale(i: number): number {
  if (props.trend.length <= 1) return padding.left
  return padding.left + (i / (props.trend.length - 1)) * innerWidth
}

function yScale(val: number): number {
  return padding.top + innerHeight - (val / maxRounds.value) * innerHeight
}

const trendPath = computed(() => {
  if (props.trend.length < 2) return ''
  return props.trend
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(p.avg_rounds).toFixed(1)}`)
    .join(' ')
})

const yTicks = computed(() => {
  const max = maxRounds.value
  const step = Math.max(0.5, Math.ceil(max) / 4)
  const ticks: number[] = []
  for (let v = 0; v <= max + step; v += step) {
    ticks.push(Math.round(v * 10) / 10)
  }
  return ticks.slice(0, 5)
})

// --- Distribution bar chart ---
const maxBucketCount = computed(() => {
  if (props.distribution.length === 0) return 1
  return Math.max(...props.distribution.map(b => b.count), 1)
})

const totalDistribution = computed(() => {
  return props.distribution.reduce((sum, b) => sum + b.count, 0)
})

function barWidth(bucket: RoundDistributionBucket): string {
  if (maxBucketCount.value === 0) return '0%'
  return `${(bucket.count / maxBucketCount.value) * 100}%`
}

function barPercent(bucket: RoundDistributionBucket): string {
  if (totalDistribution.value === 0) return '0%'
  return `${Math.round((bucket.count / totalDistribution.value) * 100)}%`
}

function barColor(rounds: string): string {
  switch (rounds) {
    case '1': return 'bg-green-500'
    case '2': return 'bg-blue-500'
    case '3': return 'bg-amber-500'
    case '4': return 'bg-orange-500'
    default: return 'bg-red-500'
  }
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-5">
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">Round Efficiency</h3>

    <!-- Trend line -->
    <div class="mb-6">
      <p class="text-[11px] text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">Avg Rounds to Completion (per 10-cycle window)</p>

      <div v-if="trend.length < 2" class="text-sm text-gray-400 dark:text-gray-500 text-center py-4">
        Not enough data for trend chart
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
          v-for="(p, i) in trend"
          :key="'xlabel-' + i"
          :x="xScale(i)"
          :y="chartHeight - 4"
          class="text-[10px] fill-gray-400 dark:fill-gray-500"
          text-anchor="middle"
        >
          {{ p.window_start }}-{{ p.window_end }}
        </text>

        <!-- Trend line -->
        <path
          :d="trendPath"
          fill="none"
          stroke="#6366f1"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />

        <!-- Dots with sample count -->
        <circle
          v-for="(p, i) in trend"
          :key="'dot-' + i"
          :cx="xScale(i)"
          :cy="yScale(p.avg_rounds)"
          r="3"
          fill="#6366f1"
        />
        <text
          v-for="(p, i) in trend"
          :key="'val-' + i"
          :x="xScale(i)"
          :y="yScale(p.avg_rounds) - 8"
          class="text-[9px] fill-gray-500 dark:fill-gray-400"
          text-anchor="middle"
        >
          {{ p.avg_rounds.toFixed(1) }}
        </text>
      </svg>
    </div>

    <!-- Distribution histogram -->
    <div>
      <p class="text-[11px] text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">Rounds Distribution</p>

      <div v-if="distribution.length === 0" class="text-sm text-gray-400 dark:text-gray-500 text-center py-2">
        No completion data
      </div>

      <div v-else class="space-y-1.5">
        <div
          v-for="bucket in distribution"
          :key="bucket.rounds"
          class="flex items-center gap-2"
        >
          <span class="text-xs text-gray-500 dark:text-gray-400 w-6 text-right font-mono tabular-nums">
            {{ bucket.rounds }}
          </span>
          <div class="flex-1 h-5 bg-gray-100 dark:bg-gray-800 rounded-sm overflow-hidden">
            <div
              :class="barColor(bucket.rounds)"
              class="h-full rounded-sm transition-all duration-300"
              :style="{ width: barWidth(bucket) }"
            />
          </div>
          <span class="text-xs text-gray-400 dark:text-gray-500 w-12 text-right font-mono tabular-nums">
            {{ bucket.count }} ({{ barPercent(bucket) }})
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
