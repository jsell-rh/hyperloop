<script setup lang="ts">
import type { TaskSummary } from '~/types'

defineProps<{
  task: TaskSummary
}>()
</script>

<template>
  <NuxtLink
    :to="`/tasks/${task.id}`"
    class="grid grid-cols-[auto_1fr_auto_auto_auto_auto] items-center gap-4 px-4 py-3 border-b border-gray-100 dark:border-gray-800 transition-colors hover:bg-gray-50 dark:hover:bg-gray-900/50"
  >
    <span class="text-xs font-mono text-gray-500 dark:text-gray-400">
      {{ task.id }}
    </span>
    <span class="text-sm text-gray-900 dark:text-gray-100 truncate">
      {{ task.title }}
    </span>
    <StatusBadge :status="task.status" />
    <span class="text-xs text-gray-500 dark:text-gray-400 min-w-[80px]">
      {{ task.phase ?? '--' }}
    </span>
    <span class="text-xs text-gray-500 dark:text-gray-400 min-w-[40px] text-right">
      Round {{ task.round }}
    </span>
    <span class="min-w-[40px] text-right">
      <a
        v-if="task.pr"
        :href="task.pr"
        target="_blank"
        rel="noopener noreferrer"
        class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
        @click.stop
      >
        PR
      </a>
      <span v-else class="text-xs text-gray-300 dark:text-gray-600">--</span>
    </span>
  </NuxtLink>
</template>
