<script setup lang="ts">
import type { PhaseDefinition } from '~/types'

const props = defineProps<{
  phases: Record<string, PhaseDefinition>
  phaseOrder: string[]
}>()

const stepColorClass = (run: string): string => {
  // Color by step type prefix or default
  if (run.startsWith('agent:') || !run.includes(':')) {
    return 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-700'
  }
  if (run.startsWith('gate:') || run.startsWith('signal:')) {
    return 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-700'
  }
  if (run.startsWith('action:')) {
    return 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 border-green-200 dark:border-green-700'
  }
  if (run.startsWith('check:')) {
    return 'bg-cyan-50 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-700'
  }
  return 'bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700'
}

// Build transition arrows: on_fail that goes backward in the phase order
interface FailBackArrow {
  fromIndex: number
  toIndex: number
  fromPhase: string
  toPhase: string
}

const failBackArrows = computed<FailBackArrow[]>(() => {
  const arrows: FailBackArrow[] = []
  for (let i = 0; i < props.phaseOrder.length; i++) {
    const phaseName = props.phaseOrder[i]
    const def = props.phases[phaseName]
    if (!def) continue
    if (def.on_fail && def.on_fail !== 'done') {
      const targetIndex = props.phaseOrder.indexOf(def.on_fail)
      if (targetIndex >= 0 && targetIndex < i) {
        arrows.push({
          fromIndex: i,
          toIndex: targetIndex,
          fromPhase: phaseName,
          toPhase: def.on_fail,
        })
      }
    }
  }
  return arrows
})

const typeIcon: Record<string, string> = {
  agent: 'M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197m13.5-9a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z',
  gate: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
  signal: 'M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z',
  action: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z',
  check: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
}

function getStepType(run: string): string {
  const colonIdx = run.indexOf(':')
  if (colonIdx > 0) return run.substring(0, colonIdx)
  return 'agent'
}

function getStepLabel(phaseName: string, def: PhaseDefinition): string {
  const type = getStepType(def.run)
  if (type === 'agent') return phaseName
  const prefixMap: Record<string, string> = { gate: 'gate: ', action: 'action: ', check: 'check: ', signal: 'signal: ' }
  const prefix = prefixMap[type] ?? ''
  return `${prefix}${phaseName}`
}
</script>

<template>
  <div class="space-y-2">
    <!-- Phase flow: horizontal layout -->
    <div class="flex flex-wrap items-center gap-0">
      <template v-for="(phaseName, i) in phaseOrder" :key="phaseName">
        <!-- Forward connector arrow -->
        <div v-if="i > 0" class="flex items-center px-1">
          <svg class="h-4 w-6 text-gray-300 dark:text-gray-600" viewBox="0 0 24 16" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2 8h16m0 0l-4-4m4 4l-4 4" />
          </svg>
        </div>

        <!-- Phase node -->
        <div class="flex flex-col items-center gap-1">
          <div
            v-if="phases[phaseName]"
            :class="stepColorClass(phases[phaseName].run)"
            class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium border"
          >
            <svg
              v-if="typeIcon[getStepType(phases[phaseName].run)]"
              class="h-3.5 w-3.5 opacity-70"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" :d="typeIcon[getStepType(phases[phaseName].run)]" />
            </svg>
            {{ getStepLabel(phaseName, phases[phaseName]) }}
          </div>
          <div v-else class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm font-medium border bg-gray-50 dark:bg-gray-800 text-gray-700 dark:text-gray-300 border-gray-200 dark:border-gray-700">
            {{ phaseName }}
          </div>
        </div>
      </template>
    </div>

    <!-- On-fail back arrows -->
    <div v-if="failBackArrows.length > 0" class="mt-2 space-y-1">
      <div
        v-for="arrow in failBackArrows"
        :key="`${arrow.fromPhase}-${arrow.toPhase}`"
        class="flex items-center gap-1.5 text-xs text-red-500 dark:text-red-400"
      >
        <svg class="h-3 w-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M2.985 19.644l3.181-3.182" />
        </svg>
        <span>on_fail: {{ arrow.fromPhase }} &larr; {{ arrow.toPhase }}</span>
      </div>
    </div>
  </div>
</template>
