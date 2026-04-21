<script setup lang="ts">
defineProps<{
  items: Array<{ label: string; to?: string }>
}>()
</script>

<template>
  <nav class="flex items-center gap-1 text-sm mb-6" aria-label="Breadcrumb">
    <template v-for="(item, index) in items" :key="index">
      <NuxtLink
        v-if="item.to"
        :to="item.to"
        class="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
      >
        {{ item.label }}
      </NuxtLink>
      <span
        v-else
        class="text-gray-900 dark:text-gray-100 font-medium"
      >
        {{ item.label }}
      </span>
      <svg
        v-if="index < items.length - 1"
        class="h-3.5 w-3.5 text-gray-400 dark:text-gray-500 flex-shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        stroke-width="2"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
      </svg>
    </template>
  </nav>
</template>
