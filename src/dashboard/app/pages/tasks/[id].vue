<script setup lang="ts">
import type { TaskDetail, PipelineStepInfo, ReconstructedPrompt } from '~/types'

const route = useRoute()
const router = useRouter()
const { fetchTask, fetchPipeline, fetchTaskPrompt, restartTask, retireTask, forceClearTask } = useApi()
const { markFetched } = useLiveness()

const taskId = computed(() => route.params.id as string)

const { data: task, error } = useAsyncData<TaskDetail>(
  `task-${taskId.value}`,
  async () => {
    const result = await fetchTask(taskId.value)
    markFetched()
    return result
  },
  { server: false },
)

const { data: pipelineSteps } = useAsyncData<PipelineStepInfo[]>(
  'pipeline-steps',
  async () => {
    const result = await fetchPipeline()
    markFetched()
    return result
  },
  { server: false, default: () => [] },
)

// ---------------------------------------------------------------------------
// Deep-linkable tab state
// ---------------------------------------------------------------------------
const validTabs = ['overview', 'reviews', 'prompt'] as const
type TabName = typeof validTabs[number]

function isValidTab(value: unknown): value is TabName {
  return typeof value === 'string' && (validTabs as readonly string[]).includes(value)
}

const activeTab = computed<TabName>({
  get() {
    const queryTab = route.query.tab
    if (isValidTab(queryTab)) return queryTab
    return 'overview'
  },
  set(tab: TabName) {
    const query = tab === 'overview' ? {} : { tab }
    router.replace({ query })
  },
})

// Sorted reviews: most recent round first
const sortedReviews = computed(() => {
  if (!task.value?.reviews) return []
  return [...task.value.reviews].sort((a, b) => b.round - a.round)
})

// Latest review for inline preview on overview tab
const latestReview = computed(() => {
  if (sortedReviews.value.length === 0) return null
  return sortedReviews.value[0]
})

const latestReviewPreview = computed(() => {
  if (!latestReview.value) return ''
  const lines = latestReview.value.detail.split('\n')
  return lines.slice(0, 3).join('\n')
})

const latestReviewTruncated = computed(() => {
  if (!latestReview.value) return false
  return latestReview.value.detail.split('\n').length > 3
})

const verdictStyleMap: Record<string, { bg: string; text: string }> = {
  pass: { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-400' },
  fail: { bg: 'bg-red-100 dark:bg-red-900/30', text: 'text-red-700 dark:text-red-400' },
}

function getVerdictClasses(verdict: string): string {
  const style = verdictStyleMap[verdict] ?? {
    bg: 'bg-gray-100 dark:bg-gray-800',
    text: 'text-gray-600 dark:text-gray-400',
  }
  return `${style.bg} ${style.text}`
}

// Prompt data -- loaded on demand when the prompt tab is activated
const promptData = ref<ReconstructedPrompt[]>([])
const promptLoaded = ref(false)

async function loadPromptData(): Promise<void> {
  if (promptLoaded.value) return
  try {
    promptData.value = await fetchTaskPrompt(taskId.value)
    markFetched()
  } catch {
    promptData.value = []
  }
  promptLoaded.value = true
}

watch(activeTab, async (tab) => {
  if (tab === 'prompt') {
    await loadPromptData()
  }
})

// Also load prompt data if we land directly on the prompt tab
onMounted(async () => {
  if (activeTab.value === 'prompt') {
    await loadPromptData()
  }
})

// ---------------------------------------------------------------------------
// Dynamic page title
// ---------------------------------------------------------------------------
useHead({ title: computed(() => {
  if (!task.value) return 'Task - Hyperloop'
  return `${task.value.id} - Hyperloop`
}) })

const breadcrumbItems = computed(() => {
  const items: Array<{ label: string; to?: string }> = [
    { label: 'Overview', to: '/' },
  ]
  if (task.value) {
    items.push({ label: task.value.spec_ref.split('@')[0], to: `/specs/${task.value.spec_ref.split('@')[0]}` })
    items.push({ label: task.value.id })
  }
  return items
})

// ---------------------------------------------------------------------------
// Control operations
// ---------------------------------------------------------------------------

const controlLoading = ref(false)
const controlError = ref<string | null>(null)
const controlSuccess = ref<string | null>(null)

async function handleRestart(): Promise<void> {
  if (!task.value) return
  controlLoading.value = true
  controlError.value = null
  controlSuccess.value = null
  try {
    await restartTask(task.value.id, { expected_round: task.value.round })
    controlSuccess.value = 'Task restarted successfully'
    await refreshNuxtData(`task-${taskId.value}`)
  } catch (e: unknown) {
    if (e && typeof e === 'object' && 'statusCode' in e && (e as { statusCode: number }).statusCode === 409) {
      controlError.value = 'Task was modified by the orchestrator. Please refresh and try again.'
    } else {
      controlError.value = e instanceof Error ? e.message : 'Failed to restart task'
    }
  } finally {
    controlLoading.value = false
  }
}

async function handleRetire(): Promise<void> {
  if (!task.value) return
  controlLoading.value = true
  controlError.value = null
  controlSuccess.value = null
  try {
    await retireTask(task.value.id, { expected_round: task.value.round })
    controlSuccess.value = 'Task retired successfully'
    await refreshNuxtData(`task-${taskId.value}`)
  } catch (e: unknown) {
    if (e && typeof e === 'object' && 'statusCode' in e && (e as { statusCode: number }).statusCode === 409) {
      controlError.value = 'Task was modified by the orchestrator. Please refresh and try again.'
    } else {
      controlError.value = e instanceof Error ? e.message : 'Failed to retire task'
    }
  } finally {
    controlLoading.value = false
  }
}

async function handleForceClear(): Promise<void> {
  if (!task.value) return
  controlLoading.value = true
  controlError.value = null
  controlSuccess.value = null
  try {
    await forceClearTask(task.value.id, { expected_round: task.value.round })
    controlSuccess.value = 'Task force-cleared successfully'
    await refreshNuxtData(`task-${taskId.value}`)
  } catch (e: unknown) {
    if (e && typeof e === 'object' && 'statusCode' in e && (e as { statusCode: number }).statusCode === 409) {
      controlError.value = 'Task was modified by the orchestrator. Please refresh and try again.'
    } else {
      controlError.value = e instanceof Error ? e.message : 'Failed to force-clear task'
    }
  } finally {
    controlLoading.value = false
  }
}

function dismissControlMessage(): void {
  controlError.value = null
  controlSuccess.value = null
}

// Show force-clear only when task has a phase (is at a step)
const showForceClear = computed(() => {
  return task.value?.status === 'in-progress' && task.value?.phase != null
})

// ---------------------------------------------------------------------------
// Keyboard navigation: tab switching (1, 2, 3)
// ---------------------------------------------------------------------------
useKeyboard({
  keys: {
    '1': () => { activeTab.value = 'overview' },
    '2': () => { activeTab.value = 'reviews' },
    '3': () => { activeTab.value = 'prompt' },
  },
})

// Task not found detection
const taskNotFound = computed(() => {
  return error.value != null && !task.value
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
    <!-- Breadcrumb -->
    <Breadcrumb :items="breadcrumbItems" />

    <!-- Task not found -->
    <div
      v-if="taskNotFound"
      class="py-16 flex flex-col items-center gap-3"
    >
      <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
      </svg>
      <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">Task not found</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        This task may have been retired or garbage collected.
      </p>
      <NuxtLink to="/" class="mt-2 text-sm text-blue-600 dark:text-blue-400 hover:underline">
        Back to overview
      </NuxtLink>
    </div>

    <!-- Error banner (API unreachable, but not 404) -->
    <div v-if="error && !taskNotFound" class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-2 border-l-red-400">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

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

      <!-- Control operation feedback -->
      <div v-if="controlError" class="mb-4 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3 flex items-center justify-between">
        <span class="text-sm text-red-700 dark:text-red-400">{{ controlError }}</span>
        <button class="text-xs text-red-500 hover:text-red-700 dark:hover:text-red-300" @click="dismissControlMessage">Dismiss</button>
      </div>
      <div v-if="controlSuccess" class="mb-4 rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 flex items-center justify-between">
        <span class="text-sm text-green-700 dark:text-green-400">{{ controlSuccess }}</span>
        <button class="text-xs text-green-500 hover:text-green-700 dark:hover:text-green-300" @click="dismissControlMessage">Dismiss</button>
      </div>

      <!-- Control buttons -->
      <div class="flex items-center gap-2 mb-6">
        <button
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border transition-colors"
          :class="controlLoading
            ? 'border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
            : 'border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30'"
          :disabled="controlLoading"
          aria-label="Restart this task"
          @click="handleRestart"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182M2.985 19.644l3.181-3.182" />
          </svg>
          Restart
        </button>
        <button
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border transition-colors"
          :class="controlLoading
            ? 'border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
            : 'border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30'"
          :disabled="controlLoading"
          aria-label="Retire this task"
          @click="handleRetire"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          Retire
        </button>
        <button
          v-if="showForceClear"
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium border transition-colors"
          :class="controlLoading
            ? 'border-gray-200 dark:border-gray-700 text-gray-400 dark:text-gray-500 cursor-not-allowed'
            : 'border-amber-200 dark:border-amber-800 text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30'"
          :disabled="controlLoading"
          aria-label="Force clear the current gate"
          @click="handleForceClear"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z" />
          </svg>
          Force Clear
        </button>
      </div>

      <!-- Tab navigation -->
      <div class="flex gap-0 border-b border-gray-200 dark:border-gray-800 mb-6">
        <button
          v-for="(tab, idx) in validTabs"
          :key="tab"
          class="px-4 py-2 text-sm font-medium border-b-2 transition-colors capitalize"
          :class="activeTab === tab
            ? 'border-gray-900 dark:border-gray-100 text-gray-900 dark:text-gray-100'
            : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = tab"
        >
          {{ tab }}
          <span class="ml-1 text-[10px] text-gray-400 dark:text-gray-500 font-mono">{{ idx + 1 }}</span>
        </button>
      </div>

      <!-- Tab content with transitions and KeepAlive -->
      <KeepAlive>
        <Transition name="tab" mode="out-in">
          <!-- Overview tab -->
          <div v-if="activeTab === 'overview'" key="overview" class="space-y-6">
            <!-- Metadata card -->
            <div class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
              <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-4">
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

            <!-- Live worker activity indicator -->
            <WorkerActivityIndicator
              :task-id="task.id"
              :task-status="task.status"
            />

            <!-- PR description -->
            <div
              v-if="task.pr_description"
              class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
            >
              <h2 class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider mb-2">PR Description</h2>
              <p v-if="task.pr_title" class="text-sm font-medium text-gray-900 dark:text-gray-100 mb-2">{{ task.pr_title }}</p>
              <p class="text-sm text-gray-600 dark:text-gray-300 whitespace-pre-line">{{ task.pr_description }}</p>
            </div>

            <!-- Latest review inline -->
            <div
              v-if="latestReview"
              class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
            >
              <div class="flex items-center gap-2 mb-2">
                <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">
                  Latest Review
                </h2>
                <span
                  :class="getVerdictClasses(latestReview.verdict)"
                  class="inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-medium"
                >
                  {{ latestReview.verdict }}
                </span>
                <span class="inline-flex items-center rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
                  {{ latestReview.role }}
                </span>
              </div>
              <p class="text-sm text-gray-600 dark:text-gray-400 whitespace-pre-line line-clamp-3">{{ latestReviewPreview }}</p>
              <button
                v-if="latestReviewTruncated"
                class="mt-1 text-xs text-blue-600 dark:text-blue-400 hover:underline"
                @click="activeTab = 'reviews'"
              >
                Show full review
              </button>
            </div>

            <!-- Pipeline position -->
            <div
              v-if="pipelineSteps && pipelineSteps.length > 0"
              class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none"
            >
              <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-4">
                Pipeline Position
              </h2>
              <PipelineIndicator
                :steps="pipelineSteps"
                :current-phase="task.phase"
              />
            </div>

            <!-- Dependencies -->
            <div class="rounded-lg bg-white dark:bg-gray-900 p-5 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
              <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100 mb-4">
                Dependencies
              </h2>
              <DependencyTree :deps="task.deps_detail" />
            </div>
          </div>

          <!-- Reviews tab -->
          <div v-else-if="activeTab === 'reviews'" key="reviews">
            <ReviewTimeline
              v-if="sortedReviews.length > 0"
              :reviews="sortedReviews"
              :current-round="task.round"
              :current-phase="task.phase"
            />
            <div
              v-else
              class="py-16 flex flex-col items-center gap-3"
            >
              <svg class="h-10 w-10 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
              </svg>
              <h3 class="text-base font-semibold text-gray-600 dark:text-gray-400">No reviews yet</h3>
              <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
                This task hasn't been verified yet. Reviews will appear here as the task progresses through the pipeline.
              </p>
            </div>
          </div>

          <!-- Prompt tab -->
          <div v-else-if="activeTab === 'prompt'" key="prompt">
            <PromptViewer :prompts="promptData" />
          </div>
        </Transition>
      </KeepAlive>
    </template>

    <!-- Loading spinner -->
    <div v-else-if="!error" class="py-16 flex flex-col items-center gap-3">
      <svg class="animate-spin h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-400 dark:text-gray-500">Loading task...</span>
    </div>
  </div>
</template>

<style scoped>
.tab-enter-active, .tab-leave-active { transition: opacity 120ms ease; }
.tab-enter-from, .tab-leave-to { opacity: 0; }
</style>
