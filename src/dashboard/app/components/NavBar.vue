<script setup lang="ts">
const route = useRoute()

const navLinks = [
  { label: 'Overview', to: '/' },
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
  () => fetchHealth(),
  { server: false, default: () => ({ repo_path: '' }) },
)
</script>

<template>
  <nav class="h-12 w-full bg-white dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800 flex items-center px-6">
    <!-- Left: brand -->
    <span class="text-lg font-semibold text-gray-900 dark:text-gray-100 mr-8 shrink-0">
      Hyperloop
    </span>

    <!-- Center/left: route links -->
    <div class="flex items-center gap-1">
      <NuxtLink
        v-for="link in navLinks"
        :key="link.to"
        :to="link.to"
        class="px-3 h-12 flex items-center text-sm font-medium transition-colors"
        :class="[
          isActive(link.to)
            ? 'text-gray-900 dark:text-gray-100 border-b-2 border-gray-900 dark:border-gray-100'
            : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300',
        ]"
      >
        {{ link.label }}
      </NuxtLink>
    </div>

    <!-- Right: repo path -->
    <span class="ml-auto text-sm text-gray-500 dark:text-gray-400 font-mono truncate max-w-xs">
      {{ health?.repo_path || '' }}
    </span>
  </nav>
</template>
