<script setup lang="ts">
import type { KpiCard } from '~/types'

const props = defineProps<{
  cards: KpiCard[]
}>()

function trendArrow(card: KpiCard): string {
  if (card.trend === 'up') return card.trend_is_good ? '↑' : '↑'
  if (card.trend === 'down') return card.trend_is_good ? '↓' : '↓'
  return '→'
}

function trendColorClass(card: KpiCard): string {
  if (card.trend === 'flat') return 'text-gray-400'
  return card.trend_is_good
    ? 'text-green-600 dark:text-green-400'
    : 'text-red-600 dark:text-red-400'
}

function sparklinePath(card: KpiCard): string {
  const points = card.sparkline
  if (points.length < 2) return ''
  const values = points.map(p => p.value)
  const maxVal = Math.max(...values, 1)
  const minVal = Math.min(...values, 0)
  const range = maxVal - minVal || 1
  const width = 80
  const height = 24
  const stepX = width / (points.length - 1)

  return points
    .map((p, i) => {
      const x = i * stepX
      const y = height - ((p.value - minVal) / range) * height
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function sparklineColor(card: KpiCard): string {
  if (card.label === 'Drift Remaining') return '#f59e0b'
  return '#3b82f6'
}

function formatValue(card: KpiCard): string {
  if (card.unit === '%') return `${card.value}%`
  if (Number.isInteger(card.value)) return card.value.toString()
  return card.value.toFixed(1)
}
</script>

<template>
  <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
    <div
      v-for="card in cards"
      :key="card.label"
      class="rounded-lg bg-white dark:bg-gray-900 p-4 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
    >
      <!-- Label row -->
      <div class="flex items-center justify-between">
        <p class="text-[11px] text-gray-500 dark:text-gray-400 font-medium uppercase tracking-wider truncate">
          {{ card.label }}
        </p>
        <span
          :class="trendColorClass(card)"
          class="text-sm font-semibold ml-1 shrink-0"
        >
          {{ trendArrow(card) }}
        </span>
      </div>

      <!-- Value + unit -->
      <div class="mt-1 flex items-baseline gap-1.5">
        <span class="text-2xl font-semibold text-gray-900 dark:text-gray-100" style="font-variant-numeric: tabular-nums">
          {{ formatValue(card) }}
        </span>
        <span v-if="card.unit !== '%'" class="text-xs text-gray-400 dark:text-gray-500">
          {{ card.unit }}
        </span>
      </div>

      <!-- Sparkline -->
      <div v-if="card.sparkline.length >= 2" class="mt-2">
        <svg
          viewBox="0 0 80 24"
          class="w-full h-6"
          preserveAspectRatio="none"
        >
          <path
            :d="sparklinePath(card)"
            fill="none"
            :stroke="sparklineColor(card)"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </div>
    </div>
  </div>
</template>
