<script setup lang="ts">
import type { CycleDetail } from '~/types'

const props = defineProps<{
  cycle: CycleDetail
  isLatest: boolean
}>()

function relativeTime(ts: string): string {
  if (!ts) return ''
  try {
    const diff = (Date.now() - new Date(ts).getTime()) / 1000
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return ''
  }
}

function formatDuration(d: number): string {
  if (d < 1) return `${Math.round(d * 1000)}ms`
  if (d < 60) return `${d.toFixed(1)}s`
  return `${Math.floor(d / 60)}m ${Math.round(d % 60)}s`
}
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 p-4 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
       :class="isLatest
         ? 'border-l-2 border-l-blue-400'
         : ''">
    <!-- Header -->
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-center gap-2">
        <span class="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Cycle #{{ cycle.cycle }}
        </span>
        <span v-if="cycle.duration_s != null"
              class="text-xs text-gray-400 dark:text-gray-500">
          {{ formatDuration(cycle.duration_s) }}
        </span>
      </div>
      <span class="text-xs text-gray-400 dark:text-gray-500">
        {{ relativeTime(cycle.timestamp) }}
      </span>
    </div>

    <!-- Phases -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
      <!-- COLLECT -->
      <div>
        <div class="font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide text-[10px]">
          Collect
        </div>
        <div v-if="cycle.phases.collect.reaped.length === 0"
             class="text-gray-300 dark:text-gray-600">---</div>
        <ul v-else class="space-y-0.5">
          <li v-for="r in cycle.phases.collect.reaped" :key="r.task_id"
              class="text-gray-700 dark:text-gray-300">
            Reaped {{ r.task_id }} ({{ r.role }},
            <span :class="r.verdict === 'pass' ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'"
                  class="font-medium uppercase">{{ r.verdict }}</span>)
          </li>
        </ul>
      </div>

      <!-- INTAKE -->
      <div>
        <div class="font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide text-[10px]">
          Intake
        </div>
        <div v-if="!cycle.phases.intake.ran"
             class="text-gray-300 dark:text-gray-600">Skipped</div>
        <div v-else class="text-gray-700 dark:text-gray-300">
          Ran PM{{ cycle.phases.intake.created_tasks != null ? `, created ${cycle.phases.intake.created_tasks} tasks` : '' }}
        </div>
      </div>

      <!-- ADVANCE -->
      <div>
        <div class="font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide text-[10px]">
          Advance
        </div>
        <div v-if="cycle.phases.advance.transitions.length === 0"
             class="text-gray-300 dark:text-gray-600">---</div>
        <ul v-else class="space-y-0.5">
          <li v-for="t in cycle.phases.advance.transitions" :key="t.task_id"
              class="text-gray-700 dark:text-gray-300">
            {{ t.task_id }}: {{ t.from_phase || 'start' }} &rarr; {{ t.to_phase || 'end' }}
          </li>
        </ul>
      </div>

      <!-- SPAWN -->
      <div>
        <div class="font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide text-[10px]">
          Spawn
        </div>
        <div v-if="cycle.phases.spawn.spawned.length === 0"
             class="text-gray-300 dark:text-gray-600">---</div>
        <ul v-else class="space-y-0.5">
          <li v-for="s in cycle.phases.spawn.spawned" :key="s.task_id"
              class="text-gray-700 dark:text-gray-300">
            Spawned {{ s.role }} for {{ s.task_id }}
          </li>
        </ul>
      </div>
    </div>

    <!-- Auditor Timeline (Gantt chart) -->
    <AuditorGantt
      v-if="cycle.audit_timeline && cycle.audit_timeline.entries.length > 0"
      :timeline="cycle.audit_timeline"
      :cycle-timestamp="cycle.timestamp"
    />
  </div>
</template>
