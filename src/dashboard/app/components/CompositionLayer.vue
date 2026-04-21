<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    label: string
    color: string
    source?: string
    content: string
    defaultOpen?: boolean
  }>(),
  { defaultOpen: true },
)

const isOpen = ref(props.defaultOpen)

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
        class="h-3 w-3 text-gray-400 transition-transform flex-shrink-0"
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
    </button>

    <!-- Body -->
    <Transition name="expand">
      <div
        v-if="isOpen"
        class="border-t border-gray-200 dark:border-gray-800"
      >
        <pre class="text-sm font-mono whitespace-pre-wrap bg-gray-50 dark:bg-gray-950 rounded-b p-4 text-gray-700 dark:text-gray-300 overflow-x-auto leading-relaxed">{{ content }}</pre>
      </div>
    </Transition>
  </div>
</template>
