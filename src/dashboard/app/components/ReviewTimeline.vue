<script setup lang="ts">
import { marked } from 'marked'
import type { Review } from '~/types'

defineProps<{
  reviews: Review[]
}>()

const expandedMap = ref<Record<number, boolean>>({})

function toggleExpand(index: number) {
  expandedMap.value[index] = !expandedMap.value[index]
}

function isLong(detail: string): boolean {
  return detail.length > 200
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
</script>

<template>
  <div class="space-y-0">
    <div
      v-for="(review, index) in reviews"
      :key="index"
      class="relative pl-6 pb-6 last:pb-0"
    >
      <!-- Timeline line -->
      <div
        v-if="index < reviews.length - 1"
        class="absolute left-[9px] top-4 bottom-0 w-px bg-gray-200 dark:bg-gray-700"
      />

      <!-- Timeline dot -->
      <div class="absolute left-0 top-1 h-[18px] w-[18px] rounded-full border-2 border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 flex items-center justify-center">
        <span class="text-[9px] font-mono text-gray-500 dark:text-gray-400">
          {{ review.round }}
        </span>
      </div>

      <!-- Content -->
      <div class="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-3">
        <div class="flex items-center gap-2 mb-1">
          <span class="text-xs font-medium text-gray-700 dark:text-gray-300">
            Round {{ review.round }}
          </span>
          <span class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
            {{ review.role }}
          </span>
          <span
            :class="[getVerdictStyle(review.verdict).bg, getVerdictStyle(review.verdict).text]"
            class="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium"
          >
            {{ review.verdict }}
          </span>
        </div>

        <div class="mt-2">
          <div
            class="prose prose-sm dark:prose-invert max-w-none text-gray-600 dark:text-gray-400"
            :class="{ 'line-clamp-3': isLong(review.detail) && !expandedMap[index] }"
            v-html="renderDetail(review.detail)"
          />
          <button
            v-if="isLong(review.detail)"
            class="mt-1 text-xs text-blue-600 dark:text-blue-400 hover:underline"
            @click="toggleExpand(index)"
          >
            {{ expandedMap[index] ? 'Show less' : 'Show more' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
