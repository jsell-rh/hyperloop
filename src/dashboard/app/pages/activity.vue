<script setup lang="ts">
// Legacy route: redirect /activity?repo=X to /repo/X/activity, or to / if no repo
const route = useRoute()
const repo = route.query.repo as string | undefined

if (repo) {
  navigateTo(`/repo/${repo}/activity`, { replace: true })
} else {
  navigateTo('/', { replace: true })
}
</script>

<template>
  <div />
</template>
