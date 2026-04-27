<script setup lang="ts">
const props = defineProps<{
  aligned: number
  total: number
}>()

const percentage = computed(() => {
  if (props.total === 0) return 0
  return Math.round((props.aligned / props.total) * 100)
})

const colorClass = computed(() => {
  const pct = percentage.value
  if (pct >= 67) return 'text-green-600 dark:text-green-400'
  if (pct >= 33) return 'text-amber-600 dark:text-amber-400'
  return 'text-red-600 dark:text-red-400'
})

const barColorClass = computed(() => {
  const pct = percentage.value
  if (pct >= 67) return 'bg-green-500 dark:bg-green-400'
  if (pct >= 33) return 'bg-amber-500 dark:bg-amber-400'
  return 'bg-red-500 dark:bg-red-400'
})
</script>

<template>
  <div>
    <div class="flex items-baseline gap-2">
      <span :class="colorClass" class="text-3xl font-semibold" style="font-variant-numeric: tabular-nums">
        {{ aligned }} / {{ total }}
      </span>
      <span class="text-sm text-gray-500 dark:text-gray-400">specs aligned</span>
    </div>
    <div class="mt-3 h-2 w-full rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
      <div
        :class="barColorClass"
        class="h-2 rounded-full transition-all duration-500"
        :style="{ width: `${percentage}%` }"
      />
    </div>
    <p :class="colorClass" class="mt-1.5 text-sm font-medium" style="font-variant-numeric: tabular-nums">
      {{ percentage }}%
    </p>
  </div>
</template>
