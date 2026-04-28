<script setup lang="ts">
// Legacy route: redirect /agents to / (fleet overview).
// Agents is now repo-scoped at /repo/{hash}/agents.
navigateTo('/', { replace: true })
</script>

<template>
  <div />
</template>
