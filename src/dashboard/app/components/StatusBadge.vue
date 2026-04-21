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
    :class="[style.bg, style.text]"
    class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium"
  >
    {{ style.label }}
  </span>
</template>
