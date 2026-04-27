<script setup lang="ts">
import { marked } from 'marked'
import type { Review } from '~/types'

const props = defineProps<{
  reviews: Review[]
  /** Current task round, used to detect "in progress" for the most recent entry */
  currentRound?: number
  /** Current task phase name */
  currentPhase?: string | null
}>()

const expandedMap = ref<Record<number, boolean>>({})

function toggleExpand(index: number) {
  expandedMap.value[index] = !expandedMap.value[index]
}

function renderDetail(detail: string): string {
  return marked.parse(detail) as string
}

const verdictStyle: Record<string, { bg: string; text: string }> = {
  pass: {
    bg: 'bg-green-100 dark:bg-green-900/30',
    text: 'text-green-700 dark:text-green-400',
  },
  fail: {
    bg: 'bg-red-100 dark:bg-red-900/30',
    text: 'text-red-700 dark:text-red-400',
  },
}

function getVerdictStyle(verdict: string) {
  return verdictStyle[verdict] ?? {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-600 dark:text-gray-400',
  }
}

// --- Phase Journey ---
// Build a round-by-round journey with retry bounce-back annotations.

interface JourneyEntry {
  round: number
  role: string
  verdict: string
  detail: string
  isCurrent: boolean
  isFailed: boolean
  retryTarget: string | null
}

function inferRetryTarget(role: string): string {
  const retryMap: Record<string, string> = {
    verifier: 'implement',
    'spec-reviewer': 'implement',
    verify: 'implement',
    'spec-review': 'implement',
  }
  return retryMap[role] ?? 'previous phase'
}

const journeyEntries = computed<JourneyEntry[]>(() => {
  const sorted = [...props.reviews].sort((a, b) => {
    if (a.round !== b.round) return a.round - b.round
    return 0
  })

  return sorted.map((review) => {
    const isCurrent = props.currentRound !== undefined && review.round === props.currentRound
    const isFailed = review.verdict === 'fail'
    const retryTarget = isFailed ? inferRetryTarget(review.role) : null

    return {
      round: review.round,
      role: review.role,
      verdict: review.verdict,
      detail: review.detail,
      isCurrent,
      isFailed,
      retryTarget,
    }
  })
})

function getBorderClass(entry: JourneyEntry): string {
  if (entry.isCurrent) return 'border-l-blue-500 dark:border-l-blue-400'
  if (entry.isFailed) return 'border-l-red-400 dark:border-l-red-500'
  return 'border-l-green-400 dark:border-l-green-500'
}
</script>

<template>
  <div class="space-y-0">
    <div
      v-for="(entry, index) in journeyEntries"
      :key="`journey-${index}`"
      class="relative pl-6 pb-4 last:pb-0"
    >
      <!-- Timeline line -->
      <div
        v-if="index < journeyEntries.length - 1"
        class="absolute left-[9px] top-4 bottom-0 w-px bg-gray-200 dark:bg-gray-700"
      />

      <!-- Timeline dot -->
      <div
        class="absolute left-0 top-1 h-[18px] w-[18px] rounded-full border-2 flex items-center justify-center"
        :class="{
          'border-blue-500 dark:border-blue-400 bg-blue-500 dark:bg-blue-400': entry.isCurrent,
          'border-red-400 dark:border-red-500 bg-white dark:bg-gray-900': entry.isFailed && !entry.isCurrent,
          'border-green-400 dark:border-green-500 bg-green-400 dark:bg-green-500': !entry.isFailed && !entry.isCurrent,
        }"
      >
        <!-- Current: pulsing inner dot -->
        <div
          v-if="entry.isCurrent"
          class="h-1.5 w-1.5 rounded-full bg-white dark:bg-gray-900 animate-badge-pulse"
        />
        <!-- Pass: checkmark -->
        <svg
          v-else-if="!entry.isFailed"
          class="h-2 w-2 text-white dark:text-gray-900"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
        <!-- Fail: X mark -->
        <svg
          v-else
          class="h-2 w-2 text-red-500 dark:text-red-400"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </div>

      <!-- Content card -->
      <div
        class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none overflow-hidden border-l-2"
        :class="getBorderClass(entry)"
      >
        <!-- Header -->
        <button
          class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors"
          @click="toggleExpand(index)"
        >
          <span class="text-xs font-medium text-gray-700 dark:text-gray-300">
            Round {{ entry.round }}
          </span>
          <span class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
            {{ entry.role }}
          </span>
          <!-- Verdict badge -->
          <span
            v-if="!entry.isCurrent"
            :class="[getVerdictStyle(entry.verdict).bg, getVerdictStyle(entry.verdict).text]"
            class="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium"
          >
            {{ entry.verdict }}
          </span>
          <span
            v-else
            class="inline-flex items-center rounded-md bg-blue-100 dark:bg-blue-900/30 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:text-blue-400 animate-badge-pulse"
          >
            in progress
          </span>

          <!-- Expand chevron -->
          <svg
            class="h-3 w-3 text-gray-400 transition-transform ml-auto flex-shrink-0"
            :class="{ 'rotate-90': expandedMap[index] }"
            fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>

        <!-- Retry bounce-back annotation -->
        <div
          v-if="entry.retryTarget"
          class="px-3 py-1 bg-red-50 dark:bg-red-950/20 border-t border-red-100 dark:border-red-900/30"
        >
          <span class="text-[10px] text-red-600 dark:text-red-400 font-medium">
            &#8594; back to {{ entry.retryTarget }}
          </span>
        </div>

        <!-- Detail content (expandable) -->
        <Transition name="expand">
          <div
            v-if="expandedMap[index]"
            class="px-3 py-2 border-t border-gray-200 dark:border-gray-800"
          >
            <div
              class="prose prose-sm dark:prose-invert max-w-none text-gray-600 dark:text-gray-400"
              v-html="renderDetail(entry.detail)"
            />
          </div>
        </Transition>
      </div>
    </div>
  </div>
</template>
