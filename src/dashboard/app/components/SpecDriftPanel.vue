<script setup lang="ts">
import type { SpecDriftDetail } from '~/types'

const props = defineProps<{
  drift: SpecDriftDetail | null
}>()

const emit = defineEmits<{
  'show-diff': []
}>()

const driftType = computed(() => props.drift?.drift_type ?? null)

const oldShaShort = computed(() => props.drift?.old_sha?.slice(0, 7) ?? '-------')
const newShaShort = computed(() => props.drift?.new_sha?.slice(0, 7) ?? '-------')
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4">
    <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">Drift Status</h3>

    <!-- No drift -->
    <div v-if="!drift || driftType === null" class="flex items-center gap-2">
      <svg class="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      <span class="text-sm text-green-700 dark:text-green-400">No drift detected</span>
    </div>

    <!-- Coverage gap -->
    <div v-else-if="driftType === 'coverage'" class="space-y-2">
      <span class="inline-flex items-center gap-1.5 rounded-md bg-amber-100 dark:bg-amber-900/30 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
        <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" />
        </svg>
        Coverage Gap
      </span>
      <p class="text-sm text-gray-600 dark:text-gray-400">
        No tasks have been created for this spec yet.
      </p>
      <p class="text-xs text-gray-400 dark:text-gray-500">
        PM will create tasks next cycle.
      </p>
    </div>

    <!-- Freshness drift -->
    <div v-else-if="driftType === 'freshness'" class="space-y-3">
      <span class="inline-flex items-center gap-1.5 rounded-md bg-blue-100 dark:bg-blue-900/30 px-2 py-0.5 text-xs font-medium text-blue-700 dark:text-blue-400">
        <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Freshness Drift
      </span>
      <p class="text-sm text-gray-600 dark:text-gray-400">
        Spec changed since tasks were pinned.
      </p>
      <div class="flex items-center gap-2 text-xs font-mono">
        <span class="rounded bg-red-50 dark:bg-red-900/20 px-1.5 py-0.5 text-red-600 dark:text-red-400">{{ oldShaShort }}</span>
        <svg class="h-3 w-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
        </svg>
        <span class="rounded bg-green-50 dark:bg-green-900/20 px-1.5 py-0.5 text-green-600 dark:text-green-400">{{ newShaShort }}</span>
      </div>
      <button
        class="text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 transition-colors"
        @click="emit('show-diff')"
      >
        View Spec Diff
      </button>
    </div>

    <!-- Alignment gap -->
    <div v-else-if="driftType === 'alignment'" class="space-y-2">
      <span class="inline-flex items-center gap-1.5 rounded-md bg-orange-100 dark:bg-orange-900/30 px-2 py-0.5 text-xs font-medium text-orange-700 dark:text-orange-400">
        <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        Alignment Gap
      </span>
      <p class="text-sm text-gray-600 dark:text-gray-400">
        All tasks complete, but auditor found issues:
      </p>
      <p v-if="drift.finding" class="text-xs text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-900/20 rounded p-2">
        {{ drift.finding }}
      </p>
    </div>
  </div>
</template>
