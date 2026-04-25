<script setup lang="ts">
import type { DepDetail } from '~/types'

defineProps<{
  deps: DepDetail[]
}>()
</script>

<template>
  <div class="space-y-0">
    <div
      v-for="(dep, index) in deps"
      :key="dep.id"
      class="relative pl-6 pb-3 last:pb-0"
    >
      <!-- Connector line -->
      <div
        v-if="index < deps.length - 1"
        class="absolute left-[7px] top-3 bottom-0 w-px bg-gray-200 dark:bg-gray-700"
      />

      <!-- Branch connector -->
      <div class="absolute left-0 top-2 w-4 h-px bg-gray-200 dark:bg-gray-700" />
      <div class="absolute left-0 top-0 w-px h-2 bg-gray-200 dark:bg-gray-700" />

      <!-- Node dot -->
      <div
        class="absolute left-0 top-1 h-[14px] w-[14px] rounded-full border-2 flex items-center justify-center"
        :class="{
          'border-green-500 bg-green-500 dark:border-green-400 dark:bg-green-400': dep.status === 'completed',
          'border-blue-500 bg-blue-500 dark:border-blue-400 dark:bg-blue-400': dep.status === 'in-progress',
          'border-red-500 bg-red-500 dark:border-red-400 dark:bg-red-400': dep.status === 'failed',
          'border-gray-300 bg-white dark:border-gray-600 dark:bg-gray-900': dep.status === 'not-started',
        }"
      >
        <!-- Checkmark for complete -->
        <svg
          v-if="dep.status === 'completed'"
          class="h-2 w-2 text-white dark:text-gray-900"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="3"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </div>

      <!-- Content -->
      <div class="flex items-center gap-2 min-h-[20px]">
        <NuxtLink
          :to="`/tasks/${dep.id}`"
          class="text-sm text-blue-600 dark:text-blue-400 hover:underline font-mono"
        >
          {{ dep.id }}
        </NuxtLink>
        <span class="text-sm text-gray-700 dark:text-gray-300 truncate">
          {{ dep.title }}
        </span>
        <StatusBadge :status="dep.status" />
        <span
          v-if="dep.status !== 'completed'"
          class="text-[10px] text-amber-600 dark:text-amber-400 font-medium"
        >
          blocking
        </span>
      </div>
    </div>

    <p
      v-if="deps.length === 0"
      class="text-sm text-gray-400 dark:text-gray-500"
    >
      No dependencies.
    </p>
  </div>
</template>
