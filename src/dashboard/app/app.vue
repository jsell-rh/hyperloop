<script setup lang="ts">
useHead({
  title: 'Hyperloop Dashboard',
  htmlAttrs: { lang: 'en' },
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
    { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap' },
  ],
})
</script>

<template>
  <div class="min-h-screen bg-white dark:bg-gray-950">
    <NavBar />
    <NuxtPage v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <component :is="Component" :key="$route.path" />
      </Transition>
    </NuxtPage>
  </div>
</template>
