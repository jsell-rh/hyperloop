<script setup lang="ts">
import type { AgentDefinition, CheckScript } from '~/types'

const { fetchAgents, fetchChecks } = useApi()

const agents = ref<AgentDefinition[]>([])
const checks = ref<CheckScript[]>([])
const selectedName = ref<string | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const checksOpen = ref(true)

async function load() {
  loading.value = true
  error.value = null
  try {
    const [agentData, checkData] = await Promise.all([fetchAgents(), fetchChecks()])
    agents.value = agentData
    checks.value = checkData
    if (agentData.length > 0 && !selectedName.value) {
      selectedName.value = agentData[0].name
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load agents'
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

onMounted(load)
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-6">Agents</h1>

    <!-- Loading state -->
    <div v-if="loading" class="text-gray-500 dark:text-gray-400">
      Loading agent definitions...
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="text-red-600 dark:text-red-400">
      {{ error }}
    </div>

    <!-- Empty state -->
    <div
      v-else-if="agents.length === 0"
      class="text-gray-500 dark:text-gray-400"
    >
      No agent templates found. Add agent definitions to
      <code class="text-xs bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">.hyperloop/agents/</code>.
    </div>

    <!-- Main layout -->
    <div v-else class="flex gap-6">
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
          class="rounded-lg border border-gray-200 dark:border-gray-800 px-4 py-3"
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
        <div class="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
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
                <pre class="text-sm font-mono whitespace-pre-wrap bg-gray-50 dark:bg-gray-950 rounded p-3 text-gray-700 dark:text-gray-300 overflow-x-auto">{{ script.content }}</pre>
              </div>
            </div>
          </div>
        </div>

        <!-- Composed Preview -->
        <div class="rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-700 p-4">
          <h3 class="text-sm font-medium text-gray-600 dark:text-gray-400 mb-2">
            Composed Preview
          </h3>
          <pre class="text-sm font-mono whitespace-pre-wrap text-gray-700 dark:text-gray-300 overflow-x-auto">{{ composedPreview || '(empty)' }}</pre>
          <p class="mt-3 text-xs text-gray-400 dark:text-gray-500">
            Spec content and findings are injected per-task at spawn time.
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
