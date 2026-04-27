<script setup lang="ts">
const props = defineProps<{
  label: string
  count?: number
  color?: 'green' | 'blue' | 'red' | 'amber' | 'default'
}>()

const colorClasses: Record<string, string> = {
  green: 'text-green-600 dark:text-green-400',
  blue: 'text-blue-600 dark:text-blue-400',
  red: 'text-red-600 dark:text-red-400',
  amber: 'text-amber-600 dark:text-amber-400',
  default: 'text-gray-900 dark:text-gray-100',
}

const dotColorClasses: Record<string, string> = {
  green: 'bg-green-500',
  blue: 'bg-blue-500',
  red: 'bg-red-500',
  amber: 'bg-amber-500',
  default: 'bg-gray-400',
}

// Animated display count (only used when count prop is provided)
const displayCount = ref(props.count ?? 0)

watch(() => props.count, (newVal) => {
  if (newVal === undefined) return
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

const resolvedColor = computed(() => props.color ?? 'default')
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
    <div class="flex items-center gap-2">
      <span
        v-if="color && color !== 'default'"
        :class="dotColorClasses[resolvedColor]"
        class="h-2 w-2 rounded-full shrink-0"
        :aria-label="`Status: ${resolvedColor}`"
      />
      <p class="text-sm text-gray-500 dark:text-gray-400">{{ label }}</p>
    </div>
    <!-- Count display (when count prop is provided) -->
    <p v-if="count !== undefined" :class="colorClasses[resolvedColor]" class="mt-1 text-3xl font-semibold" style="font-variant-numeric: tabular-nums">
      {{ displayCount }}
    </p>
    <!-- Slot for custom content -->
    <div v-else class="mt-1">
      <slot />
    </div>
  </div>
</template>
