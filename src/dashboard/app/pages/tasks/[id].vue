<script setup lang="ts">
// Legacy route: redirect /tasks/{id} to / (fleet overview).
// Tasks are now repo-scoped at /repo/{hash}/tasks/{id}.
navigateTo('/', { replace: true })
</script>

<template>
  <div />
</template>
