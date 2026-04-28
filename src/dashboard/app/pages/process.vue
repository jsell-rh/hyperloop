<script setup lang="ts">
// Legacy route: redirect /process to / (fleet overview).
// Process is now repo-scoped at /repo/{hash}/process.
navigateTo('/', { replace: true })
</script>

<template>
  <div />
</template>
