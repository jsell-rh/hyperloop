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
          <!-- Checkmark for completed steps -->
          <svg
            v-if="getStepState(step, index) === 'completed'"
            class="h-2.5 w-2.5 text-white dark:text-gray-900"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            stroke-width="3"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          <!-- Dot for active step -->
          <div
            v-else-if="getStepState(step, index) === 'active'"
            class="h-1.5 w-1.5 rounded-full bg-white dark:bg-gray-900"
          />
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
