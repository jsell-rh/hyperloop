<script setup lang="ts">
const props = defineProps<{
  phases: string[]
  currentPhase: string | null
  failedPhases: string[]
  completedPhases: string[]
}>()

type SegmentStatus = 'completed' | 'current' | 'failed' | 'future'

interface Segment {
  name: string
  status: SegmentStatus
}

const segments = computed<Segment[]>(() => {
  return props.phases.map((phase) => {
    if (phase === props.currentPhase) {
      return { name: phase, status: 'current' }
    }
    if (props.failedPhases.includes(phase)) {
      return { name: phase, status: 'failed' }
    }
    if (props.completedPhases.includes(phase)) {
      return { name: phase, status: 'completed' }
    }
    return { name: phase, status: 'future' }
  })
})

// Detect retry arcs: a failed phase that caused a bounce-back to an earlier phase
const retryArcs = computed<Array<{ fromIndex: number; toIndex: number }>>(() => {
  const arcs: Array<{ fromIndex: number; toIndex: number }> = []
  for (let i = 0; i < props.phases.length; i++) {
    if (props.failedPhases.includes(props.phases[i])) {
      // Find the earlier phase that is current or re-completed
      for (let j = 0; j < i; j++) {
        if (props.phases[j] === props.currentPhase ||
            props.completedPhases.includes(props.phases[j])) {
          arcs.push({ fromIndex: i, toIndex: j })
          break
        }
      }
    }
  }
  return arcs
})

function segmentColorClasses(status: SegmentStatus): string {
  switch (status) {
    case 'completed':
      return 'bg-green-400 dark:bg-green-500'
    case 'current':
      return 'bg-blue-400 dark:bg-blue-500 animate-badge-pulse'
    case 'failed':
      return 'bg-red-400 dark:bg-red-500'
    case 'future':
      return 'bg-gray-200 dark:bg-gray-700'
  }
}

function segmentLabelClasses(status: SegmentStatus): string {
  switch (status) {
    case 'completed':
      return 'text-green-600 dark:text-green-400'
    case 'current':
      return 'text-blue-600 dark:text-blue-400 font-semibold'
    case 'failed':
      return 'text-red-600 dark:text-red-400'
    case 'future':
      return 'text-gray-400 dark:text-gray-500'
  }
}
</script>

<template>
  <div class="phase-flow-strip">
    <!-- Bars row -->
    <div class="flex items-center gap-0.5 h-[6px]">
      <div
        v-for="(seg, idx) in segments"
        :key="`bar-${idx}`"
        class="flex-1 rounded-full transition-colors duration-200"
        :class="segmentColorClasses(seg.status)"
        :title="`${seg.name} (${seg.status})`"
      />
    </div>

    <!-- Labels row -->
    <div class="flex items-start gap-0.5 mt-0.5 relative">
      <div
        v-for="(seg, idx) in segments"
        :key="`label-${idx}`"
        class="flex-1 text-center leading-none"
      >
        <span
          class="text-[9px] uppercase tracking-wide"
          :class="segmentLabelClasses(seg.status)"
        >
          {{ seg.name }}
        </span>
        <span
          v-if="seg.status === 'failed'"
          class="block text-[8px] text-red-500 dark:text-red-400 leading-tight"
        >
          (fail)
        </span>
      </div>
    </div>

    <!-- Retry arcs -->
    <div v-if="retryArcs.length > 0" class="relative h-3 mt-0.5">
      <svg
        v-for="(arc, idx) in retryArcs"
        :key="`arc-${idx}`"
        class="absolute inset-0 w-full h-full overflow-visible"
        preserveAspectRatio="none"
      >
        <path
          :d="`M ${((arc.fromIndex + 0.5) / segments.length) * 100}% 0 C ${((arc.fromIndex + 0.5) / segments.length) * 100}% 100%, ${((arc.toIndex + 0.5) / segments.length) * 100}% 100%, ${((arc.toIndex + 0.5) / segments.length) * 100}% 0`"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          class="text-red-400 dark:text-red-500"
          marker-end="url(#retry-arrow)"
        />
        <defs>
          <marker
            id="retry-arrow"
            markerWidth="6"
            markerHeight="6"
            refX="3"
            refY="3"
            orient="auto"
          >
            <path
              d="M0,0 L6,3 L0,6 Z"
              fill="currentColor"
              class="text-red-400 dark:text-red-500"
            />
          </marker>
        </defs>
      </svg>
    </div>
  </div>
</template>
