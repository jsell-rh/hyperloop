<script setup lang="ts">
import type { SpecSummary } from '~/types'

const props = defineProps<{
  spec: SpecSummary
}>()

const emit = defineEmits<{
  hover: [specRef: string | null]
}>()

const DISCRETE_THRESHOLD = 12

const useDiscrete = computed(() => props.spec.tasks_total > 0 && props.spec.tasks_total <= DISCRETE_THRESHOLD)

const segments = computed(() => {
  const s = props.spec
  const items: { status: string }[] = []
  for (let i = 0; i < s.tasks_complete; i++) items.push({ status: 'complete' })
  for (let i = 0; i < s.tasks_failed; i++) items.push({ status: 'failed' })
  for (let i = 0; i < s.tasks_in_progress; i++) items.push({ status: 'in-progress' })
  const notStarted = s.tasks_total - s.tasks_complete - s.tasks_failed - s.tasks_in_progress
  for (let i = 0; i < notStarted; i++) items.push({ status: 'not-started' })
  return items
})

const completePercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_complete / props.spec.tasks_total) * 100
})

const failedPercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_failed / props.spec.tasks_total) * 100
})

const inProgressPercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_in_progress / props.spec.tasks_total) * 100
})

const specPath = computed(() => {
  return `/specs/${props.spec.spec_ref}`
})

const isBlocked = computed(() => {
  return props.spec.tasks_failed > 0 && props.spec.tasks_in_progress === 0
})
</script>

<template>
  <NuxtLink
    :to="specPath"
    class="block rounded-lg bg-white dark:bg-gray-900 p-5 transition-all duration-200 hover:shadow-card-hover hover:-translate-y-px"
    @mouseenter="emit('hover', spec.spec_ref)"
    @mouseleave="emit('hover', null)"
    :class="isBlocked
      ? 'ring-1 ring-red-200 dark:ring-red-800/50 bg-red-50/30 dark:bg-red-950/10 shadow-card dark:shadow-none'
      : 'shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none'"
  >
    <div class="flex items-center gap-2">
      <h3 class="text-base font-medium text-gray-900 dark:text-gray-100 truncate">
        {{ spec.title }}
      </h3>
      <span
        v-if="isBlocked"
        class="inline-flex items-center rounded-md bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs font-medium text-red-700 dark:text-red-400 shrink-0"
      >
        Blocked
      </span>
    </div>
    <p class="mt-1 text-[11px] text-gray-500 dark:text-gray-400 truncate">
      {{ spec.spec_ref }}
    </p>

    <!-- Progress bar -->
    <div class="mt-4">
      <div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
        <span>Progress</span>
        <span>{{ spec.tasks_complete }}/{{ spec.tasks_total }}</span>
      </div>

      <!-- Discrete segments (≤12 tasks) -->
      <div v-if="useDiscrete" class="flex gap-1 h-2">
        <div
          v-for="(seg, i) in segments"
          :key="i"
          class="flex-1 rounded-full transition-all"
          :class="{
            'bg-green-500 dark:bg-green-400': seg.status === 'complete',
            'bg-red-500 dark:bg-red-400': seg.status === 'failed',
            'bg-blue-500 dark:bg-blue-400 progress-bar-shimmer': seg.status === 'in-progress',
            'bg-gray-200 dark:bg-gray-700': seg.status === 'not-started',
          }"
        />
      </div>

      <!-- Continuous bar (>12 tasks) -->
      <div v-else class="h-2 w-full rounded-full bg-gray-100 dark:bg-gray-800 flex overflow-hidden">
        <div
          v-if="completePercent > 0"
          class="h-2 rounded-full bg-green-500 dark:bg-green-400 transition-all"
          :style="{ width: `${completePercent}%` }"
        />
        <div
          v-if="failedPercent > 0"
          class="h-2 rounded-full bg-red-500 dark:bg-red-400 transition-all"
          :style="{ width: `${failedPercent}%` }"
        />
        <div
          v-if="inProgressPercent > 0"
          class="h-2 rounded-full bg-blue-500 dark:bg-blue-400 transition-all"
          :class="{ 'progress-bar-shimmer': spec.tasks_in_progress > 0 }"
          :style="{ width: `${inProgressPercent}%` }"
        />
      </div>
    </div>
  </NuxtLink>
</template>
