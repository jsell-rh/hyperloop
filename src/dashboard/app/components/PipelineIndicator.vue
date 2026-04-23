<script setup lang="ts">
import type { PipelineStepInfo } from '~/types'

const props = defineProps<{
  steps: PipelineStepInfo[]
  currentPhase: string | null
}>()

type StepState = 'completed' | 'active' | 'pending'

function getStepState(step: PipelineStepInfo, index: number): StepState {
  if (!props.currentPhase) return 'pending'
  const activeIndex = props.steps.findIndex(s => s.name === props.currentPhase)
  if (activeIndex === -1) return 'pending'
  if (index < activeIndex) return 'completed'
  if (index === activeIndex) return 'active'
  return 'pending'
}

const stateClasses: Record<StepState, { circle: string; label: string }> = {
  completed: {
    circle: 'bg-green-500 dark:bg-green-400 border-green-500 dark:border-green-400',
    label: 'text-green-700 dark:text-green-400',
  },
  active: {
    circle: 'bg-blue-500 dark:bg-blue-400 border-blue-500 dark:border-blue-400',
    label: 'text-blue-700 dark:text-blue-400 font-medium',
  },
  pending: {
    circle: 'bg-white dark:bg-gray-900 border-gray-300 dark:border-gray-600',
    label: 'text-gray-400 dark:text-gray-500',
  },
}

const typeIcons: Record<string, string> = {
  agent: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
  gate: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
  action: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z',
  check: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
}
</script>

<template>
  <div class="flex items-center gap-0 overflow-x-auto">
    <template v-for="(step, index) in steps" :key="step.name">
      <!-- Connector line -->
      <div
        v-if="index > 0"
        class="h-px w-6 flex-shrink-0"
        :class="getStepState(step, index) === 'pending'
          ? 'bg-gray-200 dark:bg-gray-700'
          : 'bg-green-400 dark:bg-green-500'"
      />

      <!-- Step node -->
      <div class="flex flex-col items-center gap-1 flex-shrink-0">
        <div
          class="h-5 w-5 rounded-full border-2 flex items-center justify-center"
          :class="stateClasses[getStepState(step, index)].circle"
        >
          <svg
            v-if="typeIcons[step.type]"
            class="h-2.5 w-2.5"
            :class="getStepState(step, index) === 'pending'
              ? 'text-gray-400 dark:text-gray-500'
              : 'text-white dark:text-gray-900'"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" :d="typeIcons[step.type]" />
          </svg>
        </div>
        <span
          class="text-[10px] leading-none whitespace-nowrap"
          :class="stateClasses[getStepState(step, index)].label"
        >
          {{ step.name }}
        </span>
      </div>
    </template>
  </div>
</template>
