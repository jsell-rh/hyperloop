<script setup lang="ts">
const props = defineProps<{
  status: 'not-started' | 'in-progress' | 'complete' | 'failed'
}>()

const styleMap: Record<string, { bg: string; text: string; label: string }> = {
  'not-started': {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-600 dark:text-gray-400',
    label: 'Not Started',
  },
  'in-progress': {
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-400',
    label: 'In Progress',
  },
  complete: {
    bg: 'bg-green-100 dark:bg-green-900/30',
    text: 'text-green-700 dark:text-green-400',
    label: 'Complete',
  },
  failed: {
    bg: 'bg-red-100 dark:bg-red-900/30',
    text: 'text-red-700 dark:text-red-400',
    label: 'Failed',
  },
}

const style = computed(() => styleMap[props.status])
</script>

<template>
  <span
    :class="[style.bg, style.text, { 'animate-badge-pulse': status === 'in-progress' }]"
    class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"
  >
    <!-- not-started: circle-dashed -->
    <svg v-if="status === 'not-started'" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9" stroke-dasharray="4 3" />
    </svg>
    <!-- in-progress: clock -->
    <svg v-else-if="status === 'in-progress'" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9" />
      <path stroke-linecap="round" d="M12 7v5l3 3" />
    </svg>
    <!-- complete: checkmark -->
    <svg v-else-if="status === 'complete'" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
    </svg>
    <!-- failed: X mark -->
    <svg v-else-if="status === 'failed'" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
    {{ style.label }}
  </span>
</template>
