<script setup lang="ts">
import type { TaskDetail, PipelineStepInfo, ReconstructedPrompt } from '~/types'

const route = useRoute()
const { fetchTask, fetchPipeline, fetchTaskPrompt } = useApi()

const taskId = computed(() => route.params.id as string)

const { data: task } = useAsyncData<TaskDetail>(
  `task-${taskId.value}`,
  () => fetchTask(taskId.value),
  { server: false },
)

const { data: pipelineSteps } = useAsyncData<PipelineStepInfo[]>(
  'pipeline-steps',
  () => fetchPipeline(),
  { server: false, default: () => [] },
)

const activeTab = ref<'overview' | 'reviews' | 'prompt'>('overview')

// Sorted reviews: most recent round first
const sortedReviews = computed(() => {
  if (!task.value?.reviews) return []
  return [...task.value.reviews].sort((a, b) => b.round - a.round)
})

// Prompt data — loaded on demand when the prompt tab is activated
const promptData = ref<ReconstructedPrompt[]>([])
const promptLoaded = ref(false)

watch(activeTab, async (tab) => {
  if (tab === 'prompt' && !promptLoaded.value) {
    try {
      promptData.value = await fetchTaskPrompt(taskId.value)
    } catch {
      promptData.value = []
    }
    promptLoaded.value = true
  }
})

// Poll every 10 seconds
let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refreshInterval = setInterval(() => {
    refreshNuxtData(`task-${taskId.value}`)
  }, 10_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="max-w-5xl mx-auto px-6 py-8">
    <!-- Back link -->
    <NuxtLink
      to="/"
      class="inline-flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 mb-6"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
      </svg>
      Back to overview
    </NuxtLink>

    <template v-if="task">
      <div class="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100">
            {{ task.title }}
          </h1>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400 font-mono">
            {{ task.id }}
          </p>
        </div>
        <StatusBadge :status="task.status" />
      </div>

      <!-- Tab navigation -->
      <div class="flex gap-0 border-b border-gray-200 dark:border-gray-800 mb-6">
        <button
          v-for="tab in (['overview', 'reviews', 'prompt'] as const)"
          :key="tab"
          class="px-4 py-2 text-sm font-medium border-b-2 transition-colors capitalize"
          :class="activeTab === tab
            ? 'border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = tab"
        >
          {{ tab }}
        </button>
      </div>

      <!-- Overview tab -->
      <div v-if="activeTab === 'overview'" class="space-y-6">
        <!-- Metadata card -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm">
          <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
            Task Metadata
          </h2>
          <dl class="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
            <div>
              <dt class="text-gray-500 dark:text-gray-400">Status</dt>
              <dd class="mt-0.5">
                <StatusBadge :status="task.status" />
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400">Phase</dt>
              <dd class="mt-0.5 text-gray-900 dark:text-gray-100">
                {{ task.phase ?? '--' }}
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400">Round</dt>
              <dd class="mt-0.5 text-gray-900 dark:text-gray-100">
                {{ task.round }}
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400">Spec</dt>
              <dd class="mt-0.5">
                <NuxtLink
                  :to="`/specs/${task.spec_ref.split('@')[0]}`"
                  class="text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {{ task.spec_ref }}
                </NuxtLink>
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400">Branch</dt>
              <dd class="mt-0.5 font-mono text-gray-900 dark:text-gray-100">
                {{ task.branch ?? '--' }}
              </dd>
            </div>
            <div>
              <dt class="text-gray-500 dark:text-gray-400">PR</dt>
              <dd class="mt-0.5">
                <a
                  v-if="task.pr"
                  :href="task.pr"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {{ task.pr }}
                </a>
                <span v-else class="text-gray-400 dark:text-gray-500">--</span>
              </dd>
            </div>
          </dl>
        </div>

        <!-- Pipeline position -->
        <div
          v-if="pipelineSteps && pipelineSteps.length > 0"
          class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm"
        >
          <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
            Pipeline Position
          </h2>
          <PipelineIndicator
            :steps="pipelineSteps"
            :current-phase="task.phase"
          />
        </div>

        <!-- Dependencies -->
        <div class="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 shadow-sm">
          <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-4">
            Dependencies
          </h2>
          <DependencyTree :deps="task.deps_detail" />
        </div>
      </div>

      <!-- Reviews tab -->
      <div v-if="activeTab === 'reviews'">
        <ReviewTimeline
          v-if="sortedReviews.length > 0"
          :reviews="sortedReviews"
        />
        <p
          v-else
          class="text-sm text-gray-400 dark:text-gray-500 py-8 text-center"
        >
          No reviews yet for this task.
        </p>
      </div>

      <!-- Prompt tab -->
      <div v-if="activeTab === 'prompt'">
        <PromptViewer :prompts="promptData" />
      </div>
    </template>

    <div v-else class="py-16 text-center text-gray-400 dark:text-gray-500">
      Loading task...
    </div>
  </div>
</template>
