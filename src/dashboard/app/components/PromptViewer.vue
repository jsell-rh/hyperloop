<script setup lang="ts">
import type { ReconstructedPrompt } from '~/types'

defineProps<{
  prompts: ReconstructedPrompt[]
}>()

const expandedPanels = ref<Record<string, boolean>>({})

function panelKey(roleIndex: number, sectionIndex: number): string {
  return `${roleIndex}-${sectionIndex}`
}

function togglePanel(key: string): void {
  expandedPanels.value[key] = !expandedPanels.value[key]
}

const sourceBadgeStyle: Record<string, { bg: string; text: string }> = {
  base: {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-600 dark:text-gray-400',
  },
  'project-overlay': {
    bg: 'bg-purple-100 dark:bg-purple-900/30',
    text: 'text-purple-700 dark:text-purple-400',
  },
  'process-overlay': {
    bg: 'bg-amber-100 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-400',
  },
  spec: {
    bg: 'bg-blue-100 dark:bg-blue-900/30',
    text: 'text-blue-700 dark:text-blue-400',
  },
  findings: {
    bg: 'bg-orange-100 dark:bg-orange-900/30',
    text: 'text-orange-700 dark:text-orange-400',
  },
  runtime: {
    bg: 'bg-slate-100 dark:bg-slate-800',
    text: 'text-slate-600 dark:text-slate-400',
  },
}

function getSourceStyle(source: string): { bg: string; text: string } {
  return sourceBadgeStyle[source] ?? sourceBadgeStyle.base
}
</script>

<template>
  <div class="space-y-6">
    <div
      v-for="(entry, roleIndex) in prompts"
      :key="entry.role"
    >
      <h4 class="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
        {{ entry.role }}
      </h4>

      <div class="space-y-2">
        <div
          v-for="(section, sectionIndex) in entry.sections"
          :key="sectionIndex"
          class="rounded-lg shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none overflow-hidden"
        >
          <!-- Panel header -->
          <button
            class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors text-left"
            @click="togglePanel(panelKey(roleIndex, sectionIndex))"
          >
            <svg
              class="h-3 w-3 text-gray-400 transition-transform flex-shrink-0"
              :class="{ 'rotate-90': expandedPanels[panelKey(roleIndex, sectionIndex)] }"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            <span
              :class="[getSourceStyle(section.source).bg, getSourceStyle(section.source).text]"
              class="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium"
            >
              {{ section.source }}
            </span>
            <span class="text-xs text-gray-600 dark:text-gray-400">
              {{ section.label }}
            </span>
          </button>

          <!-- Panel content -->
          <Transition name="expand">
            <div
              v-if="expandedPanels[panelKey(roleIndex, sectionIndex)]"
              class="px-3 py-2 border-t border-gray-200 dark:border-gray-800"
            >
              <pre class="text-xs text-gray-700 dark:text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto leading-relaxed">{{ section.content }}</pre>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <p
      v-if="prompts.length === 0"
      class="text-sm text-gray-400 dark:text-gray-500"
    >
      No prompt data available for this task.
    </p>
  </div>
</template>
