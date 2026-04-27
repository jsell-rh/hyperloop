<script setup lang="ts">
defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

interface ShortcutGroup {
  title: string
  shortcuts: Array<{ keys: string[]; description: string }>
}

const groups: ShortcutGroup[] = [
  {
    title: 'Navigation',
    shortcuts: [
      { keys: ['G', 'H'], description: 'Go to overview' },
      { keys: ['G', 'A'], description: 'Go to activity' },
      { keys: ['G', 'P'], description: 'Go to process' },
    ],
  },
  {
    title: 'Task Detail',
    shortcuts: [
      { keys: ['1'], description: 'Overview tab' },
      { keys: ['2'], description: 'Reviews tab' },
      { keys: ['3'], description: 'Prompt tab' },
    ],
  },
  {
    title: 'Lists',
    shortcuts: [
      { keys: ['J'], description: 'Next item' },
      { keys: ['K'], description: 'Previous item' },
      { keys: ['Enter'], description: 'Open focused item' },
    ],
  },
  {
    title: 'General',
    shortcuts: [
      { keys: ['?'], description: 'Show this help' },
    ],
  },
]
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center"
        @click.self="emit('close')"
        @keydown.escape="emit('close')"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 dark:bg-black/60" />

        <!-- Modal -->
        <div class="relative bg-white dark:bg-gray-900 rounded-lg shadow-xl dark:ring-1 dark:ring-white/[0.06] max-w-md w-full mx-4 p-6">
          <div class="flex items-center justify-between mb-4">
            <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
              Keyboard Shortcuts
            </h2>
            <button
              class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              aria-label="Close keyboard shortcuts"
              @click="emit('close')"
            >
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <div class="space-y-5">
            <div v-for="group in groups" :key="group.title">
              <h3 class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">
                {{ group.title }}
              </h3>
              <div class="space-y-1.5">
                <div
                  v-for="shortcut in group.shortcuts"
                  :key="shortcut.description"
                  class="flex items-center justify-between"
                >
                  <span class="text-sm text-gray-600 dark:text-gray-400">{{ shortcut.description }}</span>
                  <div class="flex items-center gap-1">
                    <template v-for="(key, idx) in shortcut.keys" :key="idx">
                      <span v-if="idx > 0" class="text-[10px] text-gray-400">then</span>
                      <kbd class="inline-flex items-center justify-center min-w-[24px] h-6 px-1.5 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-mono text-gray-700 dark:text-gray-300">
                        {{ key }}
                      </kbd>
                    </template>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active, .modal-leave-active {
  transition: opacity 150ms ease;
}
.modal-enter-from, .modal-leave-to {
  opacity: 0;
}
</style>
