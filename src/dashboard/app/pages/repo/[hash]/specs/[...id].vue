<script setup lang="ts">
import { marked } from 'marked'
import type { SpecDetail, SpecDriftDetail, SpecSummaryRecord, ActivityResponse, FlatEvent } from '~/types'

const route = useRoute()
const repoHash = computed(() => route.params.hash as string)
const { fetchSpec, fetchSpecDrift, fetchSpecSummaryRecord, fetchActivity } = useApi()
const { markFetched } = useLiveness()

const specRef = computed(() => {
  const id = route.params.id
  return Array.isArray(id) ? id.join('/') : id
})

// ---------------------------------------------------------------------------
// Core spec data
// ---------------------------------------------------------------------------

const { data: spec, error } = useAsyncData<SpecDetail>(
  `spec-${specRef.value}`,
  async () => {
    const result = await fetchSpec(specRef.value, { repo: repoHash.value })
    markFetched()
    return result
  },
  { server: false },
)

// ---------------------------------------------------------------------------
// Drift data (may 404 -- gracefully handled)
// ---------------------------------------------------------------------------

const drift = ref<SpecDriftDetail | null>(null)
const driftLoaded = ref(false)

async function loadDrift(): Promise<void> {
  try {
    drift.value = await fetchSpecDrift(specRef.value, { repo: repoHash.value })
  } catch {
    drift.value = null
  } finally {
    driftLoaded.value = true
  }
}

// ---------------------------------------------------------------------------
// Summary record (may 404 -- gracefully handled)
// ---------------------------------------------------------------------------

const summaryRecord = ref<SpecSummaryRecord | null>(null)

async function loadSummaryRecord(): Promise<void> {
  try {
    summaryRecord.value = await fetchSpecSummaryRecord(specRef.value, { repo: repoHash.value })
  } catch {
    summaryRecord.value = null
  }
}

// ---------------------------------------------------------------------------
// Activity events for audit history + event timeline
// ---------------------------------------------------------------------------

const activityEvents = ref<FlatEvent[]>([])

async function loadActivity(): Promise<void> {
  try {
    const activity: ActivityResponse = await fetchActivity({ repo: repoHash.value })
    activityEvents.value = activity.flattened_events ?? []
  } catch {
    activityEvents.value = []
  }
}

// ---------------------------------------------------------------------------
// Diff viewer toggle
// ---------------------------------------------------------------------------

const showDiff = ref(false)

function handleShowDiff(): void {
  showDiff.value = !showDiff.value
}

const hasFreshnessDrift = computed(() => drift.value?.drift_type === 'freshness')
const hasDiffContent = computed(
  () => hasFreshnessDrift.value && drift.value?.old_content && drift.value?.new_content,
)

// ---------------------------------------------------------------------------
// Rendered markdown content
// ---------------------------------------------------------------------------

const renderedContent = computed(() => {
  if (!spec.value?.content) return ''
  return marked.parse(spec.value.content) as string
})

// ---------------------------------------------------------------------------
// Page head + breadcrumb
// ---------------------------------------------------------------------------

useHead({
  title: computed(() => {
    if (!spec.value) return 'Spec - Hyperloop'
    return `${spec.value.spec_ref} - Hyperloop`
  }),
})

const breadcrumbItems = computed(() => [
  { label: 'Fleet', to: '/' },
  { label: 'Activity', to: `/repo/${repoHash.value}/activity` },
  { label: spec.value?.spec_ref ?? specRef.value },
])

// ---------------------------------------------------------------------------
// Poll every 10 seconds + initial loads
// ---------------------------------------------------------------------------

let refreshInterval: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  loadDrift()
  loadSummaryRecord()
  loadActivity()

  refreshInterval = setInterval(() => {
    refreshNuxtData(`spec-${specRef.value}`)
    loadDrift()
    loadActivity()
  }, 10_000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 py-8">
    <!-- Breadcrumb -->
    <Breadcrumb :items="breadcrumbItems" />

    <!-- Error banner -->
    <div
      v-if="error"
      class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-2 border-l-red-400"
    >
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path
          fill-rule="evenodd"
          d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
          clip-rule="evenodd"
        />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">Unable to reach the Hyperloop API. Retrying...</span>
    </div>

    <template v-if="spec">
      <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100 mb-1">
        {{ spec.spec_ref }}
      </h1>

      <div class="mt-6 flex flex-col lg:flex-row gap-6">
        <!-- Left column: spec content (2/3) -->
        <div class="flex-1 min-w-0 lg:w-2/3">
          <div class="rounded-lg bg-white dark:bg-gray-900 p-6 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none">
            <div
              class="prose prose-sm dark:prose-invert max-w-none"
              v-html="renderedContent"
            />
          </div>
        </div>

        <!-- Right column: intelligence panel (1/3, sticky) -->
        <div class="w-full lg:w-1/3 flex-shrink-0">
          <div class="lg:sticky lg:top-20 space-y-4">
            <!-- 1. Drift panel -->
            <SpecDriftPanel
              v-if="driftLoaded"
              :drift="drift"
              @show-diff="handleShowDiff"
            />

            <!-- 2. Audit history -->
            <SpecAuditPanel
              :events="activityEvents"
              :spec-ref="specRef"
            />

            <!-- 3. Summary record -->
            <SpecSummaryPanel :summary="summaryRecord" />

            <!-- 4. Task list -->
            <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none p-4">
              <h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100 mb-3">
                Tasks
              </h3>

              <div class="space-y-2">
                <NuxtLink
                  v-for="task in spec.tasks"
                  :key="task.id"
                  :to="`/repo/${repoHash}/tasks/${task.id}`"
                  class="block rounded-lg bg-gray-50 dark:bg-gray-800/50 p-3 transition-all duration-200 hover:bg-gray-100 dark:hover:bg-gray-800"
                >
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-xs font-mono text-gray-500 dark:text-gray-400">
                      {{ task.id }}
                    </span>
                    <StatusBadge :status="task.status" />
                  </div>
                  <p class="text-sm text-gray-900 dark:text-gray-100 truncate">
                    {{ task.title }}
                  </p>
                  <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">
                    {{ task.phase ?? '--' }}
                  </p>
                </NuxtLink>
              </div>

              <div
                v-if="spec.tasks.length === 0"
                class="py-6 flex flex-col items-center gap-2"
              >
                <svg
                  class="h-6 w-6 text-gray-300 dark:text-gray-600"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  stroke-width="1.5"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                  />
                </svg>
                <h4 class="text-xs font-semibold text-gray-600 dark:text-gray-400">No tasks yet</h4>
                <p class="text-xs text-gray-400 dark:text-gray-500 text-center">
                  No tasks have been created for this spec.
                </p>
              </div>
            </div>

            <!-- 5. Event timeline (collapsible) -->
            <SpecEventTimeline
              :events="activityEvents"
              :spec-ref="specRef"
            />
          </div>
        </div>
      </div>

      <!-- Below main content: Spec diff view (full width, collapsible) -->
      <Transition name="expand">
        <div v-if="showDiff && hasDiffContent" class="mt-6">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-base font-semibold text-gray-900 dark:text-gray-100">Spec Diff</h2>
            <button
              class="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
              @click="showDiff = false"
            >
              Hide diff
            </button>
          </div>
          <SpecDiffViewer
            :old-content="drift!.old_content!"
            :new-content="drift!.new_content!"
            :old-sha="drift!.old_sha"
            :new-sha="drift!.new_sha"
          />
        </div>
      </Transition>
    </template>

    <!-- Loading spinner -->
    <div v-else-if="!error" class="py-16 flex flex-col items-center gap-3">
      <svg class="animate-spin h-6 w-6 text-gray-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-400 dark:text-gray-500">Loading spec...</span>
    </div>
  </div>
</template>
