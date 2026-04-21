<script setup lang="ts">
import { marked } from 'marked'
import type { AgentDefinition, CheckScript } from '~/types'

const { fetchAgents, fetchChecks } = useApi()
const { markFetched } = useLiveness()

const agents = ref<AgentDefinition[]>([])
const checks = ref<CheckScript[]>([])
const selectedName = ref<string | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)
const checksOpen = ref(true)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    const [agentData, checkData] = await Promise.all([fetchAgents(), fetchChecks()])
    agents.value = agentData
    checks.value = checkData
    markFetched()
    if (agentData.length > 0 && !selectedName.value) {
      selectedName.value = agentData[0].name
    }
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load agents'
  } finally {
    loading.value = false
  }
}

const selected = computed<AgentDefinition | null>(() =>
  agents.value.find((a) => a.name === selectedName.value) ?? null,
)

const composedPreview = computed(() => {
  if (!selected.value) return ''
  const parts: string[] = []
  if (selected.value.prompt) {
    parts.push(selected.value.prompt)
  }
  if (selected.value.guidelines) {
    parts.push('## Guidelines\n\n' + selected.value.guidelines)
  }
  return parts.join('\n\n---\n\n')
})

const previewRendered = computed(() => {
  if (!composedPreview.value) return ''
  return marked.parse(composedPreview.value) as string
})

const previewMode = ref<'rendered' | 'raw'>('rendered')

onMounted(load)
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Agents</h1>

    <!-- Error banner -->
    <div v-if="loadError" class="mb-4 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-4 py-3 flex items-center gap-2">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="py-16 flex flex-col items-center gap-3">
      <svg class="animate-spin h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-400 dark:text-gray-500">Loading agent definitions...</span>
    </div>

    <!-- Empty state -->
    <div
      v-else-if="agents.length === 0 && !loadError"
      class="py-16 flex flex-col items-center gap-3"
    >
      <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
      <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">No agent templates found</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        Add agent definitions to
        <code class="text-xs bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">.hyperloop/agents/</code>
        to see them here.
      </p>
    </div>

    <!-- Main layout -->
    <div v-else-if="!loading && agents.length > 0" class="flex gap-6">
      <!-- Left sidebar -->
      <div class="w-[200px] flex-shrink-0">
        <nav class="space-y-1">
          <button
            v-for="agent in agents"
            :key="agent.name"
            class="w-full flex items-center justify-between px-3 py-2 rounded-md text-sm text-left transition-colors"
            :class="
              selectedName === agent.name
                ? 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100 font-medium'
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-900 hover:text-gray-900 dark:hover:text-gray-100'
            "
            @click="selectedName = agent.name"
          >
            <span>{{ agent.name }}</span>
            <span
              v-if="agent.has_process_patches"
              class="h-2 w-2 rounded-full bg-amber-400 flex-shrink-0"
              title="Has process overlay patches"
            />
          </button>
        </nav>
      </div>

      <!-- Main area -->
      <div v-if="selected" class="flex-1 min-w-0 space-y-4">
        <h2 class="text-lg font-medium text-gray-900 dark:text-gray-100">
          {{ selected.name }}
        </h2>

        <!-- Panel 1: Prompt (Base) -->
        <CompositionLayer
          label="Base"
          color="gray"
          :source="'.hyperloop/agents/' + selected.name + '.yaml'"
          :content="selected.prompt || '(empty)'"
          :default-open="true"
        />

        <!-- Panel 2: Guidelines -->
        <div v-if="selected.guidelines">
          <CompositionLayer
            :label="selected.has_process_patches ? 'Process Overlay' : 'Project Overlay'"
            :color="selected.has_process_patches ? 'amber' : 'purple'"
            :content="selected.guidelines"
            :default-open="true"
          />
        </div>
        <div
          v-else
          class="rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-3"
        >
          <p class="text-sm text-gray-400 dark:text-gray-500">
            No guidelines configured for this agent.
          </p>
        </div>

        <!-- Panel 3: Process Overlay Detail -->
        <CompositionLayer
          v-if="selected.has_process_patches && selected.process_overlay_guidelines"
          label="Process Overlay"
          color="amber"
          :source="selected.process_overlay_file ?? undefined"
          :content="selected.process_overlay_guidelines"
          :default-open="true"
        />

        <!-- Panel 4: Check Scripts -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
          <button
            class="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-900/50 hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors text-left"
            @click="checksOpen = !checksOpen"
          >
            <svg
              class="h-3 w-3 text-gray-400 transition-transform flex-shrink-0"
              :class="{ 'rotate-90': checksOpen }"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              stroke-width="2"
            >
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            <span class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
              Check Scripts
            </span>
          </button>
          <Transition name="expand">
            <div v-if="checksOpen" class="border-t border-gray-200 dark:border-gray-800">
              <div v-if="checks.length === 0" class="px-4 py-3">
                <p class="text-sm text-gray-400 dark:text-gray-500">No check scripts configured.</p>
              </div>
              <div v-else class="divide-y divide-gray-200 dark:divide-gray-800">
                <div
                  v-for="script in checks"
                  :key="script.name"
                  class="px-4 py-3"
                >
                  <div class="flex items-center gap-2 mb-2">
                    <span class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ script.name }}</span>
                    <span class="text-xs text-gray-400 dark:text-gray-500">{{ script.path }}</span>
                  </div>
                  <pre class="text-sm font-mono whitespace-pre-wrap bg-gray-50 dark:bg-gray-950 rounded p-3 text-gray-700 dark:text-gray-300 overflow-x-auto leading-relaxed">{{ script.content }}</pre>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- Composed Preview -->
        <div class="rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700 p-4">
          <div class="flex items-center justify-between mb-2">
            <h3 class="text-sm font-medium text-gray-600 dark:text-gray-400">
              Composed Preview
            </h3>
            <button
              class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
              @click="previewMode = previewMode === 'rendered' ? 'raw' : 'rendered'"
            >
              {{ previewMode === 'rendered' ? 'Raw' : 'Rendered' }}
            </button>
          </div>
          <div v-if="previewMode === 'rendered' && composedPreview">
            <div class="prose prose-sm dark:prose-invert max-w-none" v-html="previewRendered" />
          </div>
          <pre v-else class="text-sm font-mono whitespace-pre-wrap text-gray-700 dark:text-gray-300 overflow-x-auto leading-relaxed">{{ composedPreview || '(empty)' }}</pre>
          <p class="mt-3 text-xs text-gray-400 dark:text-gray-500">
            Spec content and findings are injected per-task at spawn time.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.expand-enter-active, .expand-leave-active {
  transition: max-height 200ms ease, opacity 200ms ease;
  overflow: hidden;
}
.expand-enter-from, .expand-leave-to { max-height: 0; opacity: 0; }
.expand-enter-to, .expand-leave-from { max-height: 5000px; opacity: 1; }
</style>
