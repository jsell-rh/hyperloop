<script setup lang="ts">
const props = defineProps<{
  steps: string[]
  currentPhase: string | null
}>()

type StepState = 'completed' | 'active' | 'pending'

function getStepState(step: string, index: number): StepState {
  if (!props.currentPhase) return 'pending'
  const activeIndex = props.steps.indexOf(props.currentPhase)
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
    <template v-for="(step, index) in steps" :key="step">
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
          class="h-3 w-3 rounded-full border-2"
          :class="stateClasses[getStepState(step, index)].circle"
        />
        <span
          class="text-[10px] leading-none whitespace-nowrap"
          :class="stateClasses[getStepState(step, index)].label"
        >
          {{ step }}
        </span>
      </div>
    </template>
  </div>
</template>
