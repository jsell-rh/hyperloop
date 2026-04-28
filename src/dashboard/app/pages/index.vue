<script setup lang="ts">
import type { FleetResponse, InstanceSummary } from '~/types'

const { fetchFleet } = useApi()
const router = useRouter()

const fleet = ref<FleetResponse | null>(null)
const loadError = ref<string | null>(null)

async function load(): Promise<void> {
  try {
    fleet.value = await fetchFleet()
    loadError.value = null
  } catch (e: unknown) {
    loadError.value = e instanceof Error ? e.message : 'Failed to load fleet'
  }
}

function navigateToInstance(repoHash: string): void {
  router.push({ path: '/activity', query: { repo: repoHash } })
}

// Tick for relative timestamps
const now = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null

// Auto-refresh every 30 seconds
let refreshTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  load()
  refreshTimer = setInterval(load, 30_000)
  tickTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (tickTimer) clearInterval(tickTimer)
})

// Page title
useHead({ title: 'Fleet - Hyperloop' })

// Fleet-level summary stats
const totalInstances = computed(() => fleet.value?.instances.length ?? 0)
const runningCount = computed(() => fleet.value?.instances.filter(i => i.status === 'running').length ?? 0)
const idleCount = computed(() => fleet.value?.instances.filter(i => i.status === 'idle').length ?? 0)
const staleCount = computed(() => fleet.value?.instances.filter(i => i.status === 'stale' || i.status === 'empty').length ?? 0)
</script>

<template>
  <div class="max-w-7xl mx-auto px-6 md:px-8 lg:px-10 py-8">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-100">Fleet</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">
          All hyperloop instances across your repositories
        </p>
      </div>
      <div v-if="totalInstances > 0" class="flex items-center gap-4 text-sm text-gray-500 dark:text-gray-400">
        <div class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-green-500" />
          <span>{{ runningCount }} running</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-yellow-500" />
          <span>{{ idleCount }} idle</span>
        </div>
        <div v-if="staleCount > 0" class="flex items-center gap-1.5">
          <span class="h-2 w-2 rounded-full bg-gray-500" />
          <span>{{ staleCount }} stale</span>
        </div>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="loadError" class="mb-4 rounded-lg bg-white dark:bg-gray-900 shadow-card p-4 flex items-center gap-3 border-l-4 border-l-red-400">
      <svg class="h-4 w-4 text-red-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clip-rule="evenodd" />
      </svg>
      <span class="text-sm text-red-700 dark:text-red-400">{{ loadError }}</span>
    </div>

    <!-- Fleet grid -->
    <div
      v-if="fleet && fleet.instances.length > 0"
      class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
    >
      <FleetCard
        v-for="instance in fleet.instances"
        :key="instance.repo_hash"
        :instance="instance"
        :now="now"
        @navigate="navigateToInstance"
      />
    </div>

    <!-- Empty state -->
    <div
      v-if="fleet && fleet.instances.length === 0"
      class="py-20 flex flex-col items-center gap-4"
    >
      <svg class="h-12 w-12 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
      </svg>
      <h3 class="text-lg font-medium text-gray-500">No instances found</h3>
      <p class="text-sm text-gray-400 dark:text-gray-500 text-center max-w-sm">
        No hyperloop instances detected. Start the orchestrator on a repository to see it here.
      </p>
    </div>

    <!-- Skeleton loading state -->
    <div v-if="!fleet && !loadError" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="n in 3" :key="n" class="skeleton h-40 w-full rounded-lg" />
    </div>
  </div>
</template>
