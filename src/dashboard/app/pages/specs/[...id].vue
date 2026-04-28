<script setup lang="ts">
// Legacy route: redirect /specs/{id} to / (fleet overview).
// Specs are now repo-scoped at /repo/{hash}/specs/{id}.
navigateTo('/', { replace: true })
</script>

<template>
  <div />
</template>
