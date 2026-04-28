<script setup lang="ts">
const route = useRoute()
const hash = route.params.hash as string

navigateTo(`/repo/${hash}/activity`, { replace: true })
</script>

<template>
  <div />
</template>
