<script setup lang="ts">
import type { SpecSummary } from '~/types'

const props = defineProps<{
  spec: SpecSummary
}>()

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
</script>

<template>
  <NuxtLink
    :to="specPath"
    class="block rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-5 shadow-sm transition-colors hover:border-gray-300 dark:hover:border-gray-600"
  >
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 truncate">
      {{ spec.title }}
    </h3>
    <p class="mt-1 text-xs text-gray-500 dark:text-gray-400 truncate">
      {{ spec.spec_ref }}
    </p>

    <!-- Stacked progress bar -->
    <div class="mt-4">
      <div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
        <span>Progress</span>
        <span>{{ spec.tasks_complete }}/{{ spec.tasks_total }}</span>
      </div>
      <div class="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-800 flex overflow-hidden">
        <div
          v-if="completePercent > 0"
          class="h-1.5 bg-green-500 dark:bg-green-400 transition-all"
          :style="{ width: `${completePercent}%` }"
        />
        <div
          v-if="failedPercent > 0"
          class="h-1.5 bg-red-500 dark:bg-red-400 transition-all"
          :style="{ width: `${failedPercent}%` }"
        />
        <div
          v-if="inProgressPercent > 0"
          class="h-1.5 bg-blue-500 dark:bg-blue-400 transition-all"
          :style="{ width: `${inProgressPercent}%` }"
        />
      </div>
    </div>

    <!-- Status breakdown -->
    <div class="mt-3 flex flex-wrap gap-2">
      <span
        v-if="spec.tasks_in_progress > 0"
        class="inline-flex items-center rounded-md bg-blue-100 dark:bg-blue-900/30 px-1.5 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-400"
      >
        {{ spec.tasks_in_progress }} in progress
      </span>
      <span
        v-if="spec.tasks_not_started > 0"
        class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        {{ spec.tasks_not_started }} not started
      </span>
      <span
        v-if="spec.tasks_complete > 0"
        class="inline-flex items-center rounded-md bg-green-100 dark:bg-green-900/30 px-1.5 py-0.5 text-xs font-medium text-green-700 dark:text-green-400"
      >
        {{ spec.tasks_complete }} complete
      </span>
      <span
        v-if="spec.tasks_failed > 0"
        class="inline-flex items-center rounded-md bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs font-medium text-red-700 dark:text-red-400"
      >
        {{ spec.tasks_failed }} failed
      </span>
    </div>
  </NuxtLink>
</template>
