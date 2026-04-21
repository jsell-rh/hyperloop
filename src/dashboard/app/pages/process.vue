<script setup lang="ts">
import type { ProcessData } from '~/types'

const { fetchProcess } = useApi()

const { data: process } = useAsyncData<ProcessData>(
  'process',
  () => fetchProcess(),
  {
    server: false,
    default: () => ({
      pipeline_steps: [],
      pipeline_raw: '',
      gates: {},
      actions: {},
      hooks: {},
      process_learning: { patched_agents: [], guidelines: {} },
      source_file: '',
      base_ref: null,
    }),
  },
)

const showRawYaml = ref(false)

const gateEntries = computed(() =>
  Object.entries(process.value?.gates || {})
)

const actionEntries = computed(() =>
  Object.entries(process.value?.actions || {})
)

const hookEntries = computed(() =>
  Object.entries(process.value?.hooks || {})
)

const guidelineEntries = computed(() =>
  Object.entries(process.value?.process_learning?.guidelines || {})
)
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-2">
      Process
    </h1>
    <p class="text-gray-500 dark:text-gray-400 mb-8">
      Pipeline definition, gates, actions, and process learning.
    </p>

    <!-- Section 1: Pipeline Flowchart -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm mb-6">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Pipeline
      </h2>
      <PipelineFlowchart
        v-if="process && process.pipeline_steps.length > 0"
        :steps="process.pipeline_steps"
      />
      <p
        v-else
        class="text-gray-400 dark:text-gray-500 text-sm"
      >
        No pipeline definition found.
      </p>

      <!-- Collapsible raw YAML -->
      <div class="mt-4">
        <button
          class="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 font-medium"
          @click="showRawYaml = !showRawYaml"
        >
          {{ showRawYaml ? 'Hide' : 'Show' }} raw YAML
        </button>
        <pre
          v-if="showRawYaml"
          class="mt-2 p-3 rounded bg-gray-50 dark:bg-gray-800 text-xs font-mono text-gray-700 dark:text-gray-300 overflow-x-auto"
        >{{ process?.pipeline_raw || '' }}</pre>
      </div>
    </div>

    <!-- Section 2: Gates -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm mb-6">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Gates
      </h2>
      <div v-if="gateEntries.length > 0" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 dark:border-gray-700">
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Name</th>
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Configuration</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[name, config] in gateEntries"
              :key="name"
              class="border-b border-gray-100 dark:border-gray-800"
            >
              <td class="py-2 pr-4 font-mono text-gray-900 dark:text-gray-100">{{ name }}</td>
              <td class="py-2 pr-4 text-gray-600 dark:text-gray-400 font-mono text-xs">
                {{ JSON.stringify(config) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="text-gray-400 dark:text-gray-500 text-sm">No gates configured.</p>
    </div>

    <!-- Section 3: Actions -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm mb-6">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Actions
      </h2>
      <div v-if="actionEntries.length > 0" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 dark:border-gray-700">
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Name</th>
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Configuration</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[name, config] in actionEntries"
              :key="name"
              class="border-b border-gray-100 dark:border-gray-800"
            >
              <td class="py-2 pr-4 font-mono text-gray-900 dark:text-gray-100">{{ name }}</td>
              <td class="py-2 pr-4 text-gray-600 dark:text-gray-400 font-mono text-xs">
                {{ JSON.stringify(config) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="text-gray-400 dark:text-gray-500 text-sm">No actions configured.</p>
    </div>

    <!-- Section 4: Hooks -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm mb-6">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Hooks
      </h2>
      <div v-if="hookEntries.length > 0" class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-200 dark:border-gray-700">
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Hook Point</th>
              <th class="text-left py-2 pr-4 font-medium text-gray-500 dark:text-gray-400">Configuration</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[name, config] in hookEntries"
              :key="name"
              class="border-b border-gray-100 dark:border-gray-800"
            >
              <td class="py-2 pr-4 font-mono text-gray-900 dark:text-gray-100">{{ name }}</td>
              <td class="py-2 pr-4 text-gray-600 dark:text-gray-400 font-mono text-xs">
                {{ JSON.stringify(config) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="text-gray-400 dark:text-gray-500 text-sm">No hooks configured.</p>
    </div>

    <!-- Section 5: Process Learning -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm mb-6">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Process Learning
      </h2>
      <div v-if="guidelineEntries.length > 0" class="space-y-4">
        <div
          v-for="[agent, guidelines] in guidelineEntries"
          :key="agent"
          class="rounded border border-gray-100 dark:border-gray-800 p-4"
        >
          <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100 mb-2 font-mono">
            {{ agent }}
          </h3>
          <pre class="text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap font-mono">{{ guidelines }}</pre>
        </div>
      </div>
      <p v-else class="text-gray-400 dark:text-gray-500 text-sm">
        No process-learned guidelines yet.
      </p>
    </div>

    <!-- Section 6: Source -->
    <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm">
      <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
        Source
      </h2>
      <dl class="grid grid-cols-1 gap-2 text-sm">
        <div v-if="process?.source_file" class="flex">
          <dt class="text-gray-500 dark:text-gray-400 w-24 shrink-0">File</dt>
          <dd class="text-gray-900 dark:text-gray-100 font-mono">{{ process.source_file }}</dd>
        </div>
        <div v-if="process?.base_ref" class="flex">
          <dt class="text-gray-500 dark:text-gray-400 w-24 shrink-0">Base ref</dt>
          <dd class="text-gray-900 dark:text-gray-100 font-mono">{{ process.base_ref }}</dd>
        </div>
        <p
          v-if="!process?.source_file && !process?.base_ref"
          class="text-gray-400 dark:text-gray-500"
        >
          No source information available.
        </p>
      </dl>
    </div>
  </div>
</template>
