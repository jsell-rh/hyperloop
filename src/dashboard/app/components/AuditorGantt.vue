<script setup lang="ts">
import type { AuditTimeline, AuditEntry } from '~/types'

const props = defineProps<{
  timeline: AuditTimeline
  cycleTimestamp: string
}>()

// Compute the time range for the chart
const timeRange = computed(() => {
  const entries = props.timeline.entries
  if (entries.length === 0) return { minMs: 0, maxMs: 1000, spanMs: 1000 }

  const cycleStart = new Date(props.cycleTimestamp).getTime()

  let minMs = Infinity
  let maxMs = 0

  for (const entry of entries) {
    const startMs = new Date(entry.started_at).getTime() - cycleStart
    const endMs = startMs + entry.duration_s * 1000
    if (startMs < minMs) minMs = startMs
    if (endMs > maxMs) maxMs = endMs
  }

  // Clamp minMs to 0 (don't show negative offsets)
  if (minMs < 0) minMs = 0
  // Add 5% padding on the right
  const padding = (maxMs - minMs) * 0.05
  maxMs += padding

  const spanMs = maxMs - minMs || 1000
  return { minMs, maxMs, spanMs }
})

// Sorted entries by start time
const sortedEntries = computed(() => {
  return [...props.timeline.entries].sort((a, b) => {
    return new Date(a.started_at).getTime() - new Date(b.started_at).getTime()
  })
})

// Compute bar positions as percentages
function barStyle(entry: AuditEntry): Record<string, string> {
  const cycleStart = new Date(props.cycleTimestamp).getTime()
  const startMs = Math.max(0, new Date(entry.started_at).getTime() - cycleStart - timeRange.value.minMs)
  const widthMs = entry.duration_s * 1000

  const leftPct = (startMs / timeRange.value.spanMs) * 100
  const widthPct = Math.max(0.5, (widthMs / timeRange.value.spanMs) * 100)

  return {
    left: `${leftPct}%`,
    width: `${Math.min(widthPct, 100 - leftPct)}%`,
  }
}

function barColorClass(entry: AuditEntry): string {
  if (entry.result === 'aligned' || entry.result === 'pass') {
    return 'bg-emerald-400/70 dark:bg-emerald-500/50'
  }
  if (entry.result === 'misaligned' || entry.result === 'fail' || entry.result === 'drift') {
    return 'bg-amber-400/70 dark:bg-amber-500/50'
  }
  return 'bg-gray-300/70 dark:bg-gray-600/50'
}

function barHoverClass(entry: AuditEntry): string {
  if (entry.result === 'aligned' || entry.result === 'pass') {
    return 'hover:bg-emerald-500/80 dark:hover:bg-emerald-400/60'
  }
  if (entry.result === 'misaligned' || entry.result === 'fail' || entry.result === 'drift') {
    return 'hover:bg-amber-500/80 dark:hover:bg-amber-400/60'
  }
  return 'hover:bg-gray-400/80 dark:hover:bg-gray-500/60'
}

function shortSpecRef(specRef: string): string {
  // Show just the filename without path prefix
  const parts = specRef.split('/')
  const name = parts[parts.length - 1] ?? specRef
  // Remove .md extension and @version
  return name.replace(/\.spec\.md$/, '').replace(/\.md$/, '').split('@')[0] ?? name
}

function formatDuration(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs}s`
}

// Tick marks for the x-axis
const tickMarks = computed(() => {
  const { spanMs } = timeRange.value
  const spanS = spanMs / 1000

  // Choose a nice interval
  let interval: number
  if (spanS <= 5) interval = 1
  else if (spanS <= 15) interval = 2
  else if (spanS <= 30) interval = 5
  else if (spanS <= 60) interval = 10
  else if (spanS <= 180) interval = 30
  else interval = 60

  const ticks: { label: string; pct: number }[] = []
  for (let t = 0; t <= spanS; t += interval) {
    const pct = (t / spanS) * 100
    if (pct <= 100) {
      ticks.push({ label: `${t}s`, pct })
    }
  }
  return ticks
})

// Summary text
const summaryText = computed(() => {
  const n = props.timeline.entries.length
  const total = props.timeline.total_duration_s
  const par = props.timeline.max_parallelism
  const specWord = n === 1 ? 'spec' : 'specs'
  return `${n} ${specWord} audited in ${formatDuration(total)} (max parallelism: ${par})`
})

// Tooltip state
const hoveredEntry = ref<AuditEntry | null>(null)
const tooltipPos = ref({ x: 0, y: 0 })

function showTooltip(entry: AuditEntry, event: MouseEvent): void {
  hoveredEntry.value = entry
  tooltipPos.value = { x: event.clientX, y: event.clientY }
}

function hideTooltip(): void {
  hoveredEntry.value = null
}
</script>

<template>
  <div class="mt-4">
    <!-- Section header -->
    <div class="flex items-center justify-between mb-3">
      <h4 class="text-[10px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">
        Auditor Timeline
      </h4>
      <span class="text-[10px] text-gray-400 dark:text-gray-500">
        {{ summaryText }}
      </span>
    </div>

    <!-- Gantt chart -->
    <div class="relative">
      <!-- Rows -->
      <div
        class="space-y-1"
        :class="{ 'max-h-[240px] overflow-y-auto': sortedEntries.length > 8 }"
      >
        <div
          v-for="(entry, idx) in sortedEntries"
          :key="`audit-${idx}`"
          class="flex items-center gap-2 h-7"
        >
          <!-- Spec label -->
          <span
            class="w-24 flex-shrink-0 text-right text-[11px] text-gray-500 dark:text-gray-400 truncate font-mono"
            :title="entry.spec_ref"
          >
            {{ shortSpecRef(entry.spec_ref) }}
          </span>

          <!-- Bar track -->
          <div class="flex-1 relative h-5 rounded bg-gray-100/50 dark:bg-gray-800/30">
            <!-- Bar -->
            <div
              class="absolute top-0.5 bottom-0.5 rounded transition-all duration-150 cursor-default"
              :class="[barColorClass(entry), barHoverClass(entry)]"
              :style="barStyle(entry)"
              @mouseenter="showTooltip(entry, $event)"
              @mousemove="showTooltip(entry, $event)"
              @mouseleave="hideTooltip"
            >
              <!-- Duration label inside bar (only if bar is wide enough) -->
              <span
                class="absolute inset-0 flex items-center justify-center text-[9px] font-medium text-white/90 dark:text-white/80 select-none pointer-events-none"
              >
                {{ formatDuration(entry.duration_s) }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- X-axis tick marks -->
      <div class="flex items-center gap-2 mt-1">
        <span class="w-24 flex-shrink-0" />
        <div class="flex-1 relative h-4">
          <div
            v-for="tick in tickMarks"
            :key="tick.label"
            class="absolute bottom-0 text-[9px] text-gray-400 dark:text-gray-500 font-mono -translate-x-1/2"
            :style="{ left: `${tick.pct}%` }"
          >
            <span class="block h-1.5 w-px bg-gray-300 dark:bg-gray-600 mx-auto mb-0.5" />
            {{ tick.label }}
          </div>
        </div>
      </div>
    </div>

    <!-- Floating tooltip -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="hoveredEntry"
          class="fixed z-50 pointer-events-none px-3 py-2 rounded-lg shadow-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-[11px] leading-relaxed"
          :style="{
            left: `${tooltipPos.x + 12}px`,
            top: `${tooltipPos.y - 8}px`,
          }"
        >
          <div class="font-medium">{{ hoveredEntry.spec_ref }}</div>
          <div class="flex items-center gap-2 mt-0.5">
            <span
              class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
              :class="
                hoveredEntry.result === 'aligned' || hoveredEntry.result === 'pass'
                  ? 'bg-emerald-700 text-emerald-100 dark:bg-emerald-200 dark:text-emerald-800'
                  : 'bg-amber-700 text-amber-100 dark:bg-amber-200 dark:text-amber-800'
              "
            >
              {{ hoveredEntry.result }}
            </span>
            <span class="opacity-70">{{ formatDuration(hoveredEntry.duration_s) }}</span>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 120ms ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
