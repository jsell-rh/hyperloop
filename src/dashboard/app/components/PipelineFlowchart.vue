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

const typeIcon: Record<string, string> = {
  agent: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
  gate: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
  action: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z',
  check: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
}
</script>

<template>
  <div class="flex flex-col gap-0">
    <template v-for="(step, i) in steps" :key="i">
      <!-- Vertical connector between top-level steps -->
      <div v-if="i > 0" class="flex items-center pl-5 h-5">
        <div class="w-px h-full bg-gray-300 dark:bg-gray-600" />
      </div>

      <!-- Loop container -->
      <div
        v-if="step.type === 'loop' && step.children"
        class="border-2 border-dashed border-gray-300 dark:border-gray-600 rounded-lg p-3"
      >
        <div class="flex items-center gap-1.5 mb-2">
          <svg class="h-3.5 w-3.5 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M2.985 19.644l3.181-3.182" />
          </svg>
          <span class="text-xs text-gray-400 dark:text-gray-500 font-mono uppercase tracking-wide">loop</span>
        </div>
        <div class="flex flex-col gap-0 pl-2">
          <template v-for="(child, j) in step.children" :key="'loop-' + j">
            <div v-if="j > 0" class="flex items-center pl-3.5 h-4">
              <div class="w-px h-full bg-gray-200 dark:bg-gray-700" />
            </div>
            <div class="flex items-center gap-2">
              <div
                :class="stepColorClass(child.type)"
                class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium border"
              >
                <svg v-if="typeIcon[child.type]" class="h-3.5 w-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" :d="typeIcon[child.type]" />
                </svg>
                {{ stepLabel(child) }}
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Non-loop step -->
      <div v-else class="flex items-center gap-2">
        <div
          :class="stepColorClass(step.type)"
          class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium border"
        >
          <svg v-if="typeIcon[step.type]" class="h-3.5 w-3.5 opacity-70" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" :d="typeIcon[step.type]" />
          </svg>
          {{ stepLabel(step) }}
        </div>
      </div>
    </template>
  </div>
</template>
