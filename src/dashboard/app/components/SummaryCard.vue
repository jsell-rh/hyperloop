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
  const start = displayCount.value
  const diff = newVal - start
  if (diff === 0) return
  const steps = 15
  let step = 0
  const timer = setInterval(() => {
    step++
    displayCount.value = Math.round(start + (diff * step / steps))
    if (step >= steps) clearInterval(timer)
  }, 20)
})
</script>

<template>
  <div class="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-4 shadow-sm">
    <p class="text-sm text-gray-500 dark:text-gray-400">{{ label }}</p>
    <p :class="colorClasses[color ?? 'default']" class="mt-1 text-2xl font-semibold">
      {{ displayCount }}
    </p>
  </div>
</template>
