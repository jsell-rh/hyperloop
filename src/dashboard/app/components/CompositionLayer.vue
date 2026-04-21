<script setup lang="ts">
import { marked } from 'marked'

const props = withDefaults(
  defineProps<{
    label: string
    color: string
    source?: string
    content: string
    defaultOpen?: boolean
    defaultViewMode?: 'rendered' | 'raw'
  }>(),
  { defaultOpen: true, defaultViewMode: 'rendered' },
)

const isOpen = ref(props.defaultOpen)
const viewMode = ref<'rendered' | 'raw'>(props.defaultViewMode)

const renderedContent = computed(() => {
  if (!props.content) return ''
  return marked.parse(props.content) as string
})

const badgeStyles: Record<string, { bg: string; text: string }> = {
  gray: {
    bg: 'bg-gray-200 dark:bg-gray-700',
    text: 'text-gray-700 dark:text-gray-300',
  },
  purple: {
    bg: 'bg-purple-100 dark:bg-purple-900/30',
    text: 'text-purple-700 dark:text-purple-400',
  },
  amber: {
    bg: 'bg-amber-100 dark:bg-amber-900/30',
    text: 'text-amber-700 dark:text-amber-400',
  },
  slate: {
    bg: 'bg-slate-200 dark:bg-slate-700',
    text: 'text-slate-700 dark:text-slate-300',
  },
}

const style = computed(() => badgeStyles[props.color] ?? badgeStyles.gray)
</script>

<template>
  <div class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
    <!-- Header -->
    <button
      class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors text-left"
      @click="isOpen = !isOpen"
    >
      <svg
        class="h-3 w-3 text-gray-400 transition-transform duration-150 flex-shrink-0"
        :class="{ 'rotate-90': isOpen }"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="2"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
      </svg>
      <span
        :class="[style.bg, style.text]"
        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
      >
        {{ label }}
      </span>
      <span
        v-if="source"
        class="text-xs text-gray-400 dark:text-gray-500 truncate"
      >
        {{ source }}
      </span>
      <span class="flex-1" />
      <span
        v-if="isOpen"
        class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-150 px-1"
        @click.stop="viewMode = viewMode === 'rendered' ? 'raw' : 'rendered'"
      >
        {{ viewMode === 'rendered' ? 'Raw' : 'Rendered' }}
      </span>
    </button>

    <!-- Body -->
    <Transition name="expand">
      <div
        v-if="isOpen"
        class="border-t border-gray-200 dark:border-gray-800"
      >
        <!-- Rendered markdown view -->
        <div
          v-if="viewMode === 'rendered'"
          class="prose prose-sm dark:prose-invert max-w-none bg-gray-50 dark:bg-gray-950 rounded-b p-4 overflow-x-auto"
          v-html="renderedContent"
        />
        <!-- Raw monospace view -->
        <pre
          v-else
          class="text-sm font-mono whitespace-pre-wrap bg-gray-50 dark:bg-gray-950 rounded-b p-4 text-gray-700 dark:text-gray-300 overflow-x-auto leading-relaxed"
        >{{ content }}</pre>
      </div>
    </Transition>
  </div>
</template>
