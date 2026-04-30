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

// --- Progressive disclosure ---

const hasWarnings = computed(() => {
  const drift = reconcile.value?.drift_count ?? 0
  const failedAudits = reconcile.value?.audits.filter(
    (a) => a.result !== 'aligned' && a.result !== 'pass',
  ).length ?? 0
  return drift > 0 || failedAudits > 0
})

const expandedState = ref<'collapsed' | 'expanded' | string>(
  props.isLatest && hasWarnings.value ? 'expanded' : 'collapsed',
)

// Whether to show the Gantt (via "View Audit Timeline" link)
const ganttForced = ref(false)

const isFullyExpanded = computed(() => expandedState.value === 'expanded')
const activePhase = computed(() => {
  if (expandedState.value.startsWith('phase:')) {
    return expandedState.value.slice('phase:'.length)
  }
  return null
})
const showDetail = computed(() => expandedState.value !== 'collapsed')

const showGantt = computed(() =>
  isFullyExpanded.value || ganttForced.value,
)

function toggleChevron(): void {
  if (expandedState.value === 'collapsed') {
    expandedState.value = 'expanded'
  } else {
    expandedState.value = 'collapsed'
    ganttForced.value = false
  }
}

function togglePhase(phase: string): void {
  const target = `phase:${phase}`
  if (expandedState.value === target) {
    expandedState.value = 'collapsed'
  } else {
    expandedState.value = target
  }
}

function isPhaseActive(phase: string): boolean {
  return activePhase.value === phase || isFullyExpanded.value
}

function showGanttFromLink(): void {
  ganttForced.value = true
}

// --- Phase pill tooltip text ---
const collectTooltip = computed(() => {
  const count = collectCount.value
  const timing = props.cycle.phase_timing?.collect_s
  const parts: string[] = [`Collect: ${count} reaped`]
  if (timing != null) parts.push(`Duration: ${formatDuration(timing)}`)
  if (count > 0) {
    const reaped = props.cycle.phases.collect.reaped
    const passed = reaped.filter(r => r.verdict === 'pass').length
    const failed = reaped.filter(r => r.verdict !== 'pass').length
    parts.push(`${passed} pass, ${failed} fail`)
  }
  return parts.join(' | ')
})

const reconcileTooltip = computed(() => {
  const rec = reconcile.value
  if (!rec) return 'Reconcile: no data'
  const parts: string[] = []
  if (rec.reconcile_duration_s != null) {
    parts.push(`Duration: ${formatDuration(rec.reconcile_duration_s)}`)
  }
  if (rec.audits.length > 0) {
    const aligned = rec.audits.filter(a => a.result === 'aligned' || a.result === 'pass').length
    const misaligned = rec.audits.length - aligned
    parts.push(`${rec.audits.length} audits (${aligned} aligned, ${misaligned} misaligned)`)
  }
  if (rec.drift_count > 0) {
    parts.push(`${rec.drift_count} drift detected`)
  }
  return parts.length > 0 ? parts.join(' | ') : 'Reconcile'
})

const advanceTooltip = computed(() => {
  const count = advanceCount.value
  const timing = props.cycle.phase_timing?.advance_s
  const parts: string[] = [`Advance: ${count} transition${count !== 1 ? 's' : ''}`]
  if (timing != null) parts.push(`Duration: ${formatDuration(timing)}`)
  return parts.join(' | ')
})

const spawnTooltip = computed(() => {
  const count = spawnCount.value
  const timing = props.cycle.phase_timing?.spawn_s
  const parts: string[] = [`Spawn: ${count} worker${count !== 1 ? 's' : ''}`]
  if (timing != null) parts.push(`Duration: ${formatDuration(timing)}`)
  return parts.join(' | ')
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
        <span class="text-xs text-gray-400 dark:text-gray-500">
          {{ relativeTime(cycle.timestamp) }}
        </span>
      </div>
      <button
        class="chevron-btn flex items-center justify-center w-6 h-6 rounded text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        :class="{ 'chevron-open': expandedState !== 'collapsed' }"
        :aria-label="expandedState === 'collapsed' ? 'Expand cycle details' : 'Collapse cycle details'"
        @click="toggleChevron"
      >
        <svg class="w-4 h-4 chevron-icon" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z" clip-rule="evenodd" />
        </svg>
      </button>
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
          :title="`Reconcile: ${reconcile?.reconcile_duration_s != null ? formatDuration(reconcile.reconcile_duration_s) : '--'} (${reconcilePct}% of cycle)`"
        />
      </div>
      <div v-if="reconcilePct > 10" class="flex justify-between mt-0.5">
        <span class="text-[9px] text-blue-400 dark:text-blue-500">collect+advance+spawn</span>
        <span class="text-[9px] text-purple-400 dark:text-purple-500">reconcile {{ reconcilePct }}%</span>
      </div>
    </div>

    <!-- Phase breakdown pills — always visible, clickable for phase-specific expansion -->
    <div class="flex flex-wrap items-center gap-1.5 mb-3">
      <button
        class="phase-pill inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full cursor-pointer hover:ring-2 transition-all"
        :class="[
          collectCount > 0
            ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:ring-green-300 dark:hover:ring-green-600'
            : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500 hover:ring-gray-300 dark:hover:ring-gray-600',
          activePhase === 'collect' ? 'ring-2 ring-green-400 dark:ring-green-500' : '',
        ]"
        :title="collectTooltip"
        @click="togglePhase('collect')"
      >
        Collect{{ collectCount > 0 ? `: ${collectCount}` : '' }}
      </button>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <button
        class="phase-pill inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full cursor-pointer hover:ring-2 transition-all"
        :class="[
          reconcile
            ? 'bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 hover:ring-purple-300 dark:hover:ring-purple-600'
            : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500 hover:ring-gray-300 dark:hover:ring-gray-600',
          activePhase === 'reconcile' ? 'ring-2 ring-purple-400 dark:ring-purple-500' : '',
        ]"
        :title="reconcileTooltip"
        @click="togglePhase('reconcile')"
      >
        Reconcile<template v-if="reconcile?.reconcile_duration_s != null">: {{ formatDuration(reconcile.reconcile_duration_s) }}</template>
      </button>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <button
        class="phase-pill inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full cursor-pointer hover:ring-2 transition-all"
        :class="[
          advanceCount > 0
            ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 hover:ring-blue-300 dark:hover:ring-blue-600'
            : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500 hover:ring-gray-300 dark:hover:ring-gray-600',
          activePhase === 'advance' ? 'ring-2 ring-blue-400 dark:ring-blue-500' : '',
        ]"
        :title="advanceTooltip"
        @click="togglePhase('advance')"
      >
        Advance{{ advanceCount > 0 ? `: ${advanceCount}` : '' }}
      </button>
      <span class="text-gray-300 dark:text-gray-600 text-[10px]">&rarr;</span>
      <button
        class="phase-pill inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full cursor-pointer hover:ring-2 transition-all"
        :class="[
          spawnCount > 0
            ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 hover:ring-amber-300 dark:hover:ring-amber-600'
            : 'bg-gray-50 text-gray-400 dark:bg-gray-800/50 dark:text-gray-500 hover:ring-gray-300 dark:hover:ring-gray-600',
          activePhase === 'spawn' ? 'ring-2 ring-amber-400 dark:ring-amber-500' : '',
        ]"
        :title="spawnTooltip"
        @click="togglePhase('spawn')"
      >
        Spawn{{ spawnCount > 0 ? `: ${spawnCount}` : '' }}
      </button>
      <span
        v-if="cycle.phases.intake.ran"
        class="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400 ml-1 cursor-pointer hover:ring-2 hover:ring-indigo-300 dark:hover:ring-indigo-600 transition-all"
        :class="activePhase === 'intake' ? 'ring-2 ring-indigo-400 dark:ring-indigo-500' : ''"
        role="button"
        tabindex="0"
        @click="togglePhase('intake')"
        @keydown.enter="togglePhase('intake')"
      >
        Intake{{ cycle.phases.intake.created_tasks != null ? `: ${cycle.phases.intake.created_tasks}` : '' }}
      </span>
    </div>

    <!-- Expandable detail content -->
    <Transition name="expand">
      <div v-if="showDetail" class="expand-content">
        <!-- Phases detail grid — full expansion shows all four columns -->
        <div
          v-if="isFullyExpanded"
          class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs"
        >
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

        <!-- Phase-specific detail sections (when a single pill is clicked) -->

        <!-- Collect detail -->
        <div v-if="activePhase === 'collect'" class="text-xs">
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

        <!-- Intake detail -->
        <div v-if="activePhase === 'intake'" class="text-xs">
          <div class="font-medium text-gray-500 dark:text-gray-400 mb-1 uppercase tracking-wide text-[10px]">
            Intake
          </div>
          <div v-if="!cycle.phases.intake.ran"
               class="text-gray-300 dark:text-gray-600">Skipped</div>
          <div v-else class="text-gray-700 dark:text-gray-300">
            Ran PM{{ cycle.phases.intake.created_tasks != null ? `, created ${cycle.phases.intake.created_tasks} tasks` : '' }}
          </div>
        </div>

        <!-- Advance detail -->
        <div v-if="activePhase === 'advance'" class="text-xs">
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

        <!-- Spawn detail -->
        <div v-if="activePhase === 'spawn'" class="text-xs">
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

        <!-- Reconcile detail section — shown on full expand or phase:reconcile -->
        <div
          v-if="reconcile && isPhaseActive('reconcile')"
          class="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800"
        >
          <div class="flex items-center justify-between mb-2">
            <span class="font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide text-[10px]">
              Reconcile Detail
            </span>
            <span v-if="reconcile.reconcile_duration_s != null" class="text-[10px] text-gray-400 dark:text-gray-500">
              {{ formatDuration(reconcile.reconcile_duration_s) }}
            </span>
          </div>

          <!-- Sub-phase tree -->
          <div class="space-y-1.5 text-xs pl-2 border-l-2 border-purple-200 dark:border-purple-800/50">
            <!-- Drift detection -->
            <div class="flex items-center gap-2">
              <span class="text-gray-500 dark:text-gray-400">Drift detection:</span>
              <span v-if="reconcile.drift_count > 0" class="text-amber-600 dark:text-amber-400 font-medium">
                {{ reconcile.drift_count }} gap{{ reconcile.drift_count !== 1 ? 's' : '' }}
              </span>
              <span v-else class="text-green-600 dark:text-green-400">none</span>
            </div>

            <!-- PM intake -->
            <div class="flex items-center gap-2">
              <span class="text-gray-500 dark:text-gray-400">PM intake:</span>
              <template v-if="reconcile.intake_ran">
                <span class="text-gray-700 dark:text-gray-300">
                  ran{{ reconcile.intake_created_tasks != null ? `, created ${reconcile.intake_created_tasks} task${reconcile.intake_created_tasks !== 1 ? 's' : ''}` : '' }}
                </span>
                <span v-if="reconcile.intake_duration_s != null" class="text-gray-400 dark:text-gray-500">
                  ({{ formatDuration(reconcile.intake_duration_s) }})
                </span>
              </template>
              <span v-else class="text-gray-400 dark:text-gray-500">skipped</span>
            </div>

            <!-- Auditors -->
            <div>
              <div class="flex items-center gap-2">
                <span class="text-gray-500 dark:text-gray-400">Auditors:</span>
                <span v-if="reconcile.audits.length > 0" class="text-gray-700 dark:text-gray-300">
                  {{ reconcile.audits.filter(a => a.result === 'aligned' || a.result === 'pass').length }} aligned,
                  {{ reconcile.audits.filter(a => a.result !== 'aligned' && a.result !== 'pass').length }} misaligned
                </span>
                <span v-else class="text-gray-400 dark:text-gray-500">none</span>
              </div>
              <!-- Per-audit results -->
              <ul v-if="reconcile.audits.length > 0" class="mt-1 ml-4 space-y-0.5">
                <li
                  v-for="(audit, aidx) in reconcile.audits"
                  :key="`audit-${aidx}`"
                  class="flex items-center gap-2"
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

            <!-- View Audit Timeline link (only in phase:reconcile mode, not full expand) -->
            <button
              v-if="activePhase === 'reconcile' && !ganttForced && cycle.audit_timeline && cycle.audit_timeline.entries.length > 0"
              class="text-[10px] text-purple-500 dark:text-purple-400 hover:text-purple-700 dark:hover:text-purple-300 underline cursor-pointer mt-1"
              @click="showGanttFromLink"
            >
              View Audit Timeline
            </button>

            <!-- Process-improver -->
            <div class="flex items-center gap-2">
              <span class="text-gray-500 dark:text-gray-400">Process-improver:</span>
              <template v-if="reconcile.process_improver_ran">
                <span class="text-gray-700 dark:text-gray-300">ran</span>
                <span v-if="reconcile.process_improver_duration_s != null" class="text-gray-400 dark:text-gray-500">
                  ({{ formatDuration(reconcile.process_improver_duration_s) }})
                </span>
              </template>
              <span v-else class="text-gray-400 dark:text-gray-500">skipped</span>
            </div>

            <!-- GC -->
            <div class="flex items-center gap-2">
              <span class="text-gray-500 dark:text-gray-400">GC:</span>
              <span v-if="reconcile.gc_pruned > 0" class="text-gray-700 dark:text-gray-300">
                pruned {{ reconcile.gc_pruned }}
              </span>
              <span v-else class="text-gray-400 dark:text-gray-500">none</span>
            </div>
          </div>
        </div>

        <!-- Auditor Timeline (Gantt chart) — lazy loaded -->
        <AuditorGantt
          v-if="showGantt && cycle.audit_timeline && cycle.audit_timeline.entries.length > 0"
          :timeline="cycle.audit_timeline"
          :cycle-timestamp="cycle.timestamp"
        />
      </div>
    </Transition>
  </div>
</template>

<style scoped>
/* Chevron rotation animation */
.chevron-icon {
  transition: transform 150ms ease;
}
.chevron-open .chevron-icon {
  transform: rotate(90deg);
}

/* Expand/collapse transition */
.expand-enter-active,
.expand-leave-active {
  transition: max-height 200ms ease-out, opacity 200ms ease-out;
  overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 2000px;
  opacity: 1;
}

/* Phase pill focus styles */
.phase-pill:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 1px;
}
</style>
