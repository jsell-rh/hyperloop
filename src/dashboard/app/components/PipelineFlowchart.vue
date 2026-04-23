<script setup lang="ts">
import type { PipelineTreeStep } from '~/types'

defineProps<{
  steps: PipelineTreeStep[]
}>()

const stepColorClass = (type: string): string => {
  switch (type) {
    case 'agent':
      return 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700'
    case 'gate':
      return 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-700'
    case 'action':
      return 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700'
    case 'check':
      return 'bg-cyan-50 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-700'
    default:
      return 'bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700'
  }
}

const stepLabel = (step: PipelineTreeStep): string => {
  if (step.type === 'loop') return 'loop'
  const prefixMap: Record<string, string> = { gate: 'gate: ', action: 'action: ', check: 'check: ' }
  const prefix = prefixMap[step.type] ?? ''
  return `${prefix}${step.name || ''}`
}
</script>

<template>
  <div class="flex items-center gap-2 flex-wrap">
    <template v-for="(step, i) in steps" :key="i">
      <!-- Arrow between steps -->
      <span
        v-if="i > 0"
        class="text-gray-400 dark:text-gray-500 text-lg select-none shrink-0"
      >
        &rarr;
      </span>

      <!-- Loop container -->
      <div
        v-if="step.type === 'loop' && step.children"
        class="flex items-center gap-2 border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2"
      >
        <span class="text-xs text-gray-400 dark:text-gray-500 font-mono mr-1 self-start">loop</span>
        <template v-for="(child, j) in step.children" :key="'loop-' + j">
          <span
            v-if="j > 0"
            class="text-gray-400 dark:text-gray-500 text-lg select-none"
          >
            &rarr;
          </span>
          <span
            :class="stepColorClass(child.type)"
            class="inline-flex items-center rounded-full px-3 py-1 text-sm font-medium border whitespace-nowrap"
          >
            {{ stepLabel(child) }}
          </span>
        </template>
      </div>

      <!-- Non-loop step -->
      <span
        v-else
        :class="stepColorClass(step.type)"
        class="inline-flex items-center rounded-full px-3 py-1 text-sm font-medium border whitespace-nowrap"
      >
        {{ stepLabel(step) }}
      </span>
    </template>
  </div>
</template>
