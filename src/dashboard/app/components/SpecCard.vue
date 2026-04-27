<script setup lang="ts">
import type { SpecSummary, SyncStatus, SpecStage } from '~/types'

const props = defineProps<{
  spec: SpecSummary
}>()

const emit = defineEmits<{
  hover: [specRef: string | null]
}>()

const DISCRETE_THRESHOLD = 12

const useDiscrete = computed(() => props.spec.tasks_total > 0 && props.spec.tasks_total <= DISCRETE_THRESHOLD)

const segments = computed(() => {
  const s = props.spec
  const items: { status: string }[] = []
  for (let i = 0; i < s.tasks_complete; i++) items.push({ status: 'completed' })
  for (let i = 0; i < s.tasks_failed; i++) items.push({ status: 'failed' })
  for (let i = 0; i < s.tasks_in_progress; i++) items.push({ status: 'in-progress' })
  const notStarted = s.tasks_total - s.tasks_complete - s.tasks_failed - s.tasks_in_progress
  for (let i = 0; i < notStarted; i++) items.push({ status: 'not-started' })
  return items
})

const completePercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_complete / props.spec.tasks_total) * 100
})

const failedPercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_failed / props.spec.tasks_total) * 100
})

const inProgressPercent = computed(() => {
  if (props.spec.tasks_total === 0) return 0
  return (props.spec.tasks_in_progress / props.spec.tasks_total) * 100
})

const specPath = computed(() => {
  return `/specs/${props.spec.spec_ref}`
})

const isBlocked = computed(() => {
  return props.spec.tasks_failed > 0 && props.spec.tasks_in_progress === 0
})

// Derive sync status from spec fields (graceful degradation for old API)
const syncStatus = computed<SyncStatus>(() => {
  const stage = props.spec.stage ?? null
  const drift = props.spec.drift_type ?? null

  if (stage === 'converged' || stage === 'baselined') return 'synced'
  if (drift !== null) return 'drifted'
  if (stage === 'in-progress' || stage === 'pending-audit') return 'syncing'

  // Fallback: derive from task counts
  if (props.spec.tasks_in_progress > 0) return 'syncing'
  if (props.spec.tasks_total > 0 && props.spec.tasks_complete === props.spec.tasks_total) return 'synced'
  return 'drifted'
})

// Stage badge configuration
const stageBadge = computed<{ label: string; classes: string } | null>(() => {
  const stage: SpecStage | null = props.spec.stage ?? null
  if (stage === null) return null

  const map: Record<SpecStage, { label: string; classes: string }> = {
    'written': { label: 'Written', classes: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400' },
    'in-progress': { label: 'In Progress', classes: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400' },
    'pending-audit': { label: 'Pending Audit', classes: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400' },
    'converged': { label: 'Converged', classes: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400' },
    'freshness-drift': { label: 'Freshness Drift', classes: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400' },
    'alignment-gap': { label: 'Alignment Gap', classes: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400' },
    'failed': { label: 'Failed', classes: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400' },
    'baselined': { label: 'Baselined', classes: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400' },
  }
  return map[stage]
})

// Drift label
const driftLabel = computed<string | null>(() => {
  const drift = props.spec.drift_type ?? null
  if (drift === null) return null
  const labels: Record<string, string> = {
    coverage: 'coverage gap',
    freshness: 'freshness drift',
    alignment: 'alignment gap',
  }
  return labels[drift] ?? null
})
</script>

<template>
  <NuxtLink
    :to="specPath"
    class="block rounded-lg bg-white dark:bg-gray-900 p-5 transition-all duration-200 hover:shadow-card-hover hover:-translate-y-px relative"
    @mouseenter="emit('hover', spec.spec_ref)"
    @mouseleave="emit('hover', null)"
    :class="isBlocked
      ? 'ring-1 ring-red-200 dark:ring-red-800/50 bg-red-50/30 dark:bg-red-950/10 shadow-card dark:shadow-none'
      : 'shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none'"
  >
    <!-- Sync status icon (top-right) -->
    <div class="absolute top-4 right-4" :title="`Sync: ${syncStatus}`">
      <!-- Synced: green checkmark -->
      <svg v-if="syncStatus === 'synced'" class="h-5 w-5 text-green-500 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5" aria-label="Synced">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <!-- Syncing: blue gear -->
      <svg v-else-if="syncStatus === 'syncing'" class="h-5 w-5 text-blue-500 dark:text-blue-400 animate-spin-slow" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5" aria-label="Syncing">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.204-.107-.397.165-.71.505-.78.929l-.15.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.506-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.108-1.204l-.526-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
      <!-- Drifted: amber/blue refresh -->
      <svg v-else class="h-5 w-5 text-amber-500 dark:text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-label="Drifted">
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M21.015 4.356v4.992" />
      </svg>
    </div>

    <div class="flex items-center gap-2 pr-8">
      <h3 class="text-base font-medium text-gray-900 dark:text-gray-100 truncate">
        {{ spec.title }}
      </h3>
      <span
        v-if="isBlocked"
        class="inline-flex items-center rounded-md bg-red-100 dark:bg-red-900/30 px-1.5 py-0.5 text-xs font-medium text-red-700 dark:text-red-400 shrink-0"
      >
        Blocked
      </span>
    </div>

    <p class="mt-1 text-[11px] text-gray-500 dark:text-gray-400 truncate">
      {{ spec.spec_ref }}
    </p>

    <!-- Lifecycle stage badge -->
    <div v-if="stageBadge" class="mt-2">
      <span :class="stageBadge.classes" class="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium">
        {{ stageBadge.label }}
      </span>
    </div>

    <!-- Drift indicator -->
    <p v-if="driftLabel" class="mt-1.5 text-[10px] text-amber-600 dark:text-amber-400 font-medium uppercase tracking-wide">
      {{ driftLabel }}
    </p>

    <!-- Progress bar -->
    <div class="mt-4">
      <div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400 mb-1">
        <span>Progress</span>
        <span>{{ spec.tasks_complete }}/{{ spec.tasks_total }}</span>
      </div>

      <!-- Discrete segments (<=12 tasks) -->
      <div v-if="useDiscrete" class="flex gap-1 h-2">
        <div
          v-for="(seg, i) in segments"
          :key="i"
          class="flex-1 rounded-full transition-all"
          :class="{
            'bg-green-500 dark:bg-green-400': seg.status === 'completed',
            'bg-red-500 dark:bg-red-400': seg.status === 'failed',
            'bg-blue-500 dark:bg-blue-400 progress-bar-shimmer': seg.status === 'in-progress',
            'bg-gray-200 dark:bg-gray-700': seg.status === 'not-started',
          }"
        />
      </div>

      <!-- Continuous bar (>12 tasks) -->
      <div v-else class="h-2 w-full rounded-full bg-gray-100 dark:bg-gray-800 flex overflow-hidden">
        <div
          v-if="completePercent > 0"
          class="h-2 rounded-full bg-green-500 dark:bg-green-400 transition-all"
          :style="{ width: `${completePercent}%` }"
        />
        <div
          v-if="failedPercent > 0"
          class="h-2 rounded-full bg-red-500 dark:bg-red-400 transition-all"
          :style="{ width: `${failedPercent}%` }"
        />
        <div
          v-if="inProgressPercent > 0"
          class="h-2 rounded-full bg-blue-500 dark:bg-blue-400 transition-all"
          :class="{ 'progress-bar-shimmer': spec.tasks_in_progress > 0 }"
          :style="{ width: `${inProgressPercent}%` }"
        />
      </div>
    </div>
  </NuxtLink>
</template>
