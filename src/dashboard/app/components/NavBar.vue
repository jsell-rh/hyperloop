<script setup lang="ts">
const route = useRoute()
const { markFetched, lastUpdatedText, status, workersActive } = useLiveness()

const navLinks = [
  { label: 'Fleet', to: '/' },
  { label: 'Activity', to: '/activity' },
  { label: 'Process', to: '/process' },
  { label: 'Agents', to: '/agents' },
]

const isActive = (to: string): boolean => {
  if (to === '/') return route.path === '/'
  return route.path.startsWith(to)
}

const { fetchHealth } = useApi()

const { data: health } = useAsyncData(
  'health',
  async () => {
    const result = await fetchHealth()
    markFetched()
    return result
  },
  { server: false, default: () => ({ repo_path: '' }) },
)

const statusDotColor = computed(() => {
  switch (status.value) {
    case 'live': return 'bg-green-400'
    case 'stale': return 'bg-amber-400'
    case 'disconnected': return 'bg-red-400'
  }
})

// Dark mode toggle
const isDark = ref(false)

onMounted(() => {
  const stored = localStorage.getItem('hyperloop-theme')
  if (stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    isDark.value = true
  }
  document.documentElement.classList.toggle('dark', isDark.value)
})

function toggleDark(): void {
  isDark.value = !isDark.value
  document.documentElement.classList.toggle('dark', isDark.value)
  localStorage.setItem('hyperloop-theme', isDark.value ? 'dark' : 'light')
}

// Data refresh visual indicator
const justRefreshed = ref(false)

function flashRefreshBar(): void {
  justRefreshed.value = true
  setTimeout(() => {
    justRefreshed.value = false
  }, 300)
}

watch(lastUpdatedText, (newVal, oldVal) => {
  if (oldVal !== '--' && newVal === 'just now') {
    flashRefreshBar()
  }
})

defineExpose({ flashRefreshBar })
</script>

<template>
  <nav class="relative h-14 w-full bg-white dark:bg-gray-900 border-b border-gray-200/60 dark:border-gray-800 flex items-center px-8">
    <!-- Refresh indicator bar -->
    <div
      class="absolute top-0 left-0 right-0 h-0.5 bg-blue-500 transition-opacity duration-300"
      :class="justRefreshed ? 'opacity-100' : 'opacity-0'"
    />

    <!-- Left: brand -->
    <span class="text-base font-semibold tracking-tight text-gray-800 dark:text-gray-200 mr-8 shrink-0">
      Hyperloop
    </span>

    <!-- Center/left: route links -->
    <div class="flex items-center gap-1">
      <NuxtLink
        v-for="link in navLinks"
        :key="link.to"
        :to="link.to"
        class="px-3 h-14 flex items-center text-sm font-medium transition-colors"
        :class="[
          isActive(link.to)
            ? 'text-gray-900 dark:text-gray-100 border-b-2 border-gray-900 dark:border-gray-100'
            : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300',
        ]"
      >
        {{ link.label }}
      </NuxtLink>
    </div>

    <!-- Right section -->
    <div class="ml-auto flex items-center gap-4">
      <!-- Liveness indicator -->
      <div class="flex items-center gap-2">
        <span
          class="inline-flex rounded-full h-2 w-2"
          :class="[statusDotColor, workersActive ? 'nav-dot-ring' : '']"
        />
        <span class="text-xs text-gray-500 dark:text-gray-400">
          Updated {{ lastUpdatedText }}
        </span>
      </div>

      <!-- Dark mode toggle -->
      <button
        class="p-2 rounded-md text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        title="Toggle dark mode"
        @click="toggleDark"
      >
        <!-- Sun icon (shown in dark mode) -->
        <svg v-if="isDark" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
        <!-- Moon icon (shown in light mode) -->
        <svg v-else class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
      </button>
    </div>
  </nav>
</template>
