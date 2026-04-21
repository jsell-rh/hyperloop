<script setup lang="ts">
const props = defineProps<{
  label: string
  count: number
  color?: 'green' | 'blue' | 'red' | 'default'
}>()

const colorClasses: Record<string, string> = {
  green: 'text-green-600 dark:text-green-400',
  blue: 'text-blue-600 dark:text-blue-400',
  red: 'text-red-600 dark:text-red-400',
  default: 'text-gray-900 dark:text-gray-100',
}

// Animated display count
const displayCount = ref(props.count)

watch(() => props.count, (newVal) => {
  const from = displayCount.value
  const duration = 400
  const start = performance.now()
  function step(now: number): void {
    const t = Math.min((now - start) / duration, 1)
    const eased = 1 - Math.pow(1 - t, 3)
    displayCount.value = Math.round(from + (newVal - from) * eased)
    if (t < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
})
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
    <p class="text-sm text-gray-500 dark:text-gray-400">{{ label }}</p>
    <p :class="colorClasses[color ?? 'default']" class="mt-1 text-3xl font-semibold" style="font-variant-numeric: tabular-nums">
      {{ displayCount }}
    </p>
  </div>
</template>
