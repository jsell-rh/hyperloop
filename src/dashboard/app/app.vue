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

// ---------------------------------------------------------------------------
// Global keyboard navigation
// ---------------------------------------------------------------------------
const router = useRouter()
const showKeyboardHelp = ref(false)

useKeyboard({
  goTo: {
    H: () => router.push('/'),
    A: () => router.push('/activity'),
    P: () => router.push('/process'),
  },
  keys: {
    '?': () => { showKeyboardHelp.value = !showKeyboardHelp.value },
  },
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-[#0a0a0f]">
    <NavBar />
    <NuxtPage v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <component :is="Component" :key="$route.path" />
      </Transition>
    </NuxtPage>
    <KeyboardHelpModal :open="showKeyboardHelp" @close="showKeyboardHelp = false" />
  </div>
</template>
