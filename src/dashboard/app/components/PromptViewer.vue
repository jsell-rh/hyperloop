<script setup lang="ts">
import type { ReconstructedPrompt } from '~/types'

const props = defineProps<{
  prompts: ReconstructedPrompt[]
}>()

// --- Role selector ---
const selectedRole = ref<string | null>(null)

const roles = computed(() => props.prompts.map((p) => p.role))

// Auto-select first role when prompts load
watch(
  () => props.prompts,
  (newPrompts) => {
    if (newPrompts.length > 0 && !selectedRole.value) {
      selectedRole.value = newPrompts[0].role
    }
  },
  { immediate: true },
)

const selectedPrompt = computed<ReconstructedPrompt | null>(() => {
  if (!selectedRole.value) return null
  return props.prompts.find((p) => p.role === selectedRole.value) ?? null
})

// --- Panel expand/collapse ---
const expandedPanels = ref<Record<string, boolean>>({})

function panelKey(sectionIndex: number): string {
  return `${selectedRole.value}-${sectionIndex}`
}

function togglePanel(key: string): void {
  expandedPanels.value[key] = !expandedPanels.value[key]
}

// --- Source layer labels and badge styles ---
const sourceLabels: Record<string, string> = {
  base: 'Base Prompt',
  'project-overlay': 'Project Overlay',
  'process-overlay': 'Process Guidelines',
  spec: 'Spec Content',
  findings: 'Review Findings',
  runtime: 'Runtime',
  feedback: 'PR Feedback',
}

function getSourceLabel(source: string): string {
  return sourceLabels[source] ?? source
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
  feedback: {
    bg: 'bg-teal-100 dark:bg-teal-900/30',
    text: 'text-teal-700 dark:text-teal-400',
  },
}

function getSourceStyle(source: string): { bg: string; text: string } {
  return sourceBadgeStyle[source] ?? sourceBadgeStyle.base
}
</script>

<template>
  <div class="space-y-4">
    <!-- Empty state -->
    <div
      v-if="prompts.length === 0"
      class="py-16 flex flex-col items-center gap-3"
    >
      <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
      </svg>
      <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">No prompt data available</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        Prompt composition events may not be captured. Enable FileProbe to record prompt data.
      </p>
    </div>

    <!-- Role selector tabs -->
    <div v-if="prompts.length > 0">
      <div class="flex gap-0 border-b border-gray-200 dark:border-gray-800 mb-4">
        <button
          v-for="role in roles"
          :key="role"
          class="px-3 py-1.5 text-xs font-medium border-b-2 transition-colors"
          :class="selectedRole === role
            ? 'border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="selectedRole = role"
        >
          {{ role }}
        </button>
      </div>

      <!-- Sections for the selected role -->
      <div v-if="selectedPrompt" class="space-y-2">
        <div
          v-for="(section, sectionIndex) in selectedPrompt.sections"
          :key="sectionIndex"
          class="rounded-lg shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none overflow-hidden"
        >
          <!-- Panel header -->
          <button
            class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors text-left"
            @click="togglePanel(panelKey(sectionIndex))"
          >
            <svg
              class="h-3 w-3 text-gray-400 transition-transform flex-shrink-0"
              :class="{ 'rotate-90': expandedPanels[panelKey(sectionIndex)] }"
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
              {{ getSourceLabel(section.source) }}
            </span>
            <span class="text-xs text-gray-600 dark:text-gray-400">
              {{ section.label }}
            </span>
            <span class="ml-auto text-[10px] text-gray-400 dark:text-gray-500">
              {{ section.content.length }} chars
            </span>
          </button>

          <!-- Panel content -->
          <Transition name="expand">
            <div
              v-if="expandedPanels[panelKey(sectionIndex)]"
              class="px-3 py-2 border-t border-gray-200 dark:border-gray-800"
            >
              <pre class="text-xs text-gray-700 dark:text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto leading-relaxed">{{ section.content }}</pre>
            </div>
          </Transition>
        </div>
      </div>
    </div>
  </div>
</template>
