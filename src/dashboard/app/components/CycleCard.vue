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

// Phase breakdown summary counts
const collectCount = computed(() => props.cycle.phases.collect.reaped.length)
const advanceCount = computed(() => props.cycle.phases.advance.transitions.length)
const spawnCount = computed(() => props.cycle.phases.spawn.spawned.length)

// Reconcile detail
const reconcile = computed(() => props.cycle.reconcile)

// Cycle timeline bar: show reconcile proportion within total cycle duration
const reconcilePct = computed(() => {
  const total = props.cycle.duration_s
  const rec = reconcile.value?.reconcile_duration_s
  if (total == null || total <= 0 || rec == null) return 0
  return Math.min(100, Math.round((rec / total) * 100))
})
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

    <!-- Cycle duration bar -->
    <div v-if="cycle.duration_s != null && cycle.duration_s > 0" class="mb-3">
      <div class="h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden flex">
        <!-- Non-reconcile portion (collect + advance + spawn) -->
        <div
          class="bg-blue-200 dark:bg-blue-800/50 transition-all"
          :style="{ width: `${100 - reconcilePct}%` }"
        />
        <!-- Reconcile portion -->
        <div
          v-if="reconcilePct > 0"
          class="bg-purple-300 dark:bg-purple-700/50 transition-all"
          :style="{ width: `${reconcilePct}%` }"
          :title="`Reconcile: ${reconcile?.reconcile_duration_s?.toFixed(1)}s (${reconcilePct}% of cycle)`"
        />
      </div>
      <div v-if="reconcilePct > 10" class="flex justify-between mt-0.5">
        <span class="text-[9px] text-blue-400 dark:text-blue-500">collect+advance+spawn</span>
        <span class="text-[9px] text-purple-400 dark:text-purple-500">reconcile {{ reconcilePct }}%</span>
      </div>
    </div>

    <!-- Phase breakdown pills — always visible to show cycle structure -->
    <div class="flex flex-wrap items-center gap-1.5 mb-3">
      <span
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
        :class="collectCount > 0
          ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400'
          : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500'"
      >
        Collect{{ collectCount > 0 ? `: ${collectCount}` : '' }}
      </span>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <span
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
        :class="reconcile
          ? 'bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
          : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500'"
      >
        Reconcile<template v-if="reconcile?.reconcile_duration_s != null">: {{ formatDuration(reconcile.reconcile_duration_s) }}</template>
      </span>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <span
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
        :class="advanceCount > 0
          ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
          : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500'"
      >
        Advance{{ advanceCount > 0 ? `: ${advanceCount}` : '' }}
      </span>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <span
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
        :class="spawnCount > 0
          ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
          : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500'"
      >
        Spawn{{ spawnCount > 0 ? `: ${spawnCount}` : '' }}
      </span>
      <span
        v-if="cycle.phases.intake.ran"
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ml-1"
      >
        Intake{{ cycle.phases.intake.created_tasks != null ? `: ${cycle.phases.intake.created_tasks}` : '' }}
      </span>
    </div>

    <!-- Phases detail grid -->
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

    <!-- Reconcile detail section -->
    <div
      v-if="reconcile"
      class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800"
    >
      <div class="font-medium text-gray-500 dark:text-gray-400 mb-2 uppercase tracking-wide text-[10px]">
        Reconcile Detail
      </div>
      <div class="grid grid-cols-3 gap-3 text-xs">
        <div>
          <span class="text-gray-400 dark:text-gray-500">Drift:</span>
          <span class="ml-1 text-gray-700 dark:text-gray-300 font-medium">{{ reconcile.drift_count }}</span>
        </div>
        <div>
          <span class="text-gray-400 dark:text-gray-500">Audits:</span>
          <span class="ml-1 text-gray-700 dark:text-gray-300 font-medium">{{ reconcile.audits.length }}</span>
        </div>
        <div>
          <span class="text-gray-400 dark:text-gray-500">GC pruned:</span>
          <span class="ml-1 text-gray-700 dark:text-gray-300 font-medium">{{ reconcile.gc_pruned }}</span>
        </div>
      </div>
      <!-- Per-audit results -->
      <ul v-if="reconcile.audits.length > 0" class="mt-2 space-y-0.5">
        <li
          v-for="(audit, aidx) in reconcile.audits"
          :key="`audit-${aidx}`"
          class="flex items-center gap-2 text-xs"
        >
          <span class="font-mono text-gray-500 dark:text-gray-400 truncate max-w-[160px]" :title="audit.spec_ref">
            {{ audit.spec_ref.split('/').pop()?.replace(/\.md$/, '') }}
          </span>
          <span
            class="text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded"
            :class="audit.result === 'aligned' || audit.result === 'pass'
              ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
              : 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'"
          >
            {{ audit.result }}
          </span>
          <span class="text-gray-400 dark:text-gray-500">{{ formatDuration(audit.duration_s) }}</span>
        </li>
      </ul>
    </div>

    <!-- Auditor Timeline (Gantt chart) -->
    <AuditorGantt
      v-if="cycle.audit_timeline && cycle.audit_timeline.entries.length > 0"
      :timeline="cycle.audit_timeline"
      :cycle-timestamp="cycle.timestamp"
    />
  </div>
</template>
