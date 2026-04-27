<script setup lang="ts">
import type { FlatEvent, WorkerHeartbeat } from '~/types'

const props = defineProps<{
  events: FlatEvent[]
  activeHeartbeats?: WorkerHeartbeat[]
}>()

const showAll = ref(false)
const INITIAL_LIMIT = 30

// ---------------------------------------------------------------------------
// Event categorization
// ---------------------------------------------------------------------------

type EventCategory = 'workers' | 'tasks' | 'reconcile' | 'system'

interface EventStyle {
  symbol: string
  colorClass: string
  dotColor: string
  category: EventCategory
  format: (event: FlatEvent) => string
}

const EVENT_STYLES: Record<string, EventStyle | ((event: FlatEvent) => EventStyle)> = {
  // Workers (blue family)
  worker_spawned: {
    symbol: '▶',
    colorClass: 'text-blue-500',
    dotColor: 'bg-blue-500',
    category: 'workers',
    format: (e) => e.detail,
  },
  worker_reaped: (event: FlatEvent): EventStyle => {
    if (event.verdict === 'pass') {
      return {
        symbol: '✓',
        colorClass: 'text-green-500',
        dotColor: 'bg-green-500',
        category: 'workers',
        format: (e) => e.detail,
      }
    }
    return {
      symbol: '✗',
      colorClass: 'text-red-500',
      dotColor: 'bg-red-500',
      category: 'workers',
      format: (e) => e.detail,
    }
  },

  // Tasks (purple family)
  task_advanced: {
    symbol: '→',
    colorClass: 'text-purple-500',
    dotColor: 'bg-purple-500',
    category: 'tasks',
    format: (e) => e.detail,
  },
  task_retried: {
    symbol: '↩',
    colorClass: 'text-amber-500',
    dotColor: 'bg-amber-500',
    category: 'tasks',
    format: (e) => e.detail,
  },
  task_completed: {
    symbol: '✓',
    colorClass: 'text-green-600',
    dotColor: 'bg-green-600',
    category: 'tasks',
    format: (e) => e.detail,
  },
  task_failed: {
    symbol: '✗',
    colorClass: 'text-red-600',
    dotColor: 'bg-red-600',
    category: 'tasks',
    format: (e) => e.detail,
  },

  // Reconcile (purple/amber)
  drift_detected: {
    symbol: '◆',
    colorClass: 'text-amber-500',
    dotColor: 'bg-amber-500',
    category: 'reconcile',
    format: (e) => e.detail,
  },
  audit_ran: {
    symbol: '🛡',
    colorClass: 'text-purple-500',
    dotColor: 'bg-purple-500',
    category: 'reconcile',
    format: (e) => e.detail,
  },
  intake_ran: {
    symbol: '+',
    colorClass: 'text-indigo-500',
    dotColor: 'bg-indigo-500',
    category: 'reconcile',
    format: (e) => e.detail,
  },
  gc_ran: {
    symbol: '∅',
    colorClass: 'text-gray-400',
    dotColor: 'bg-gray-400',
    category: 'reconcile',
    format: (e) => e.detail,
  },
  convergence_marked: {
    symbol: '✓',
    colorClass: 'text-green-500',
    dotColor: 'bg-green-500',
    category: 'reconcile',
    format: (e) => e.detail,
  },
  process_improver_ran: {
    symbol: '⚙',
    colorClass: 'text-gray-500',
    dotColor: 'bg-gray-500',
    category: 'reconcile',
    format: (e) => e.detail,
  },

  // System (gray)
  cycle_started: {
    symbol: '○',
    colorClass: 'text-gray-400',
    dotColor: 'bg-gray-400',
    category: 'system',
    format: (e) => e.detail,
  },
  cycle_completed: {
    symbol: '●',
    colorClass: 'text-gray-500',
    dotColor: 'bg-gray-500',
    category: 'system',
    format: (e) => e.detail,
  },
  orchestrator_started: {
    symbol: '▶',
    colorClass: 'text-green-600',
    dotColor: 'bg-green-600',
    category: 'system',
    format: (e) => e.detail,
  },
  orchestrator_halted: {
    symbol: '⏹',
    colorClass: 'text-red-600',
    dotColor: 'bg-red-600',
    category: 'system',
    format: (e) => e.detail,
  },
}

const DEFAULT_STYLE: EventStyle = {
  symbol: '•',
  colorClass: 'text-gray-400',
  dotColor: 'bg-gray-400',
  category: 'system',
  format: (e) => e.detail,
}

function getStyle(event: FlatEvent): EventStyle {
  const entry = EVENT_STYLES[event.event_type]
  if (!entry) return DEFAULT_STYLE
  if (typeof entry === 'function') return entry(event)
  return entry
}

function getCategory(event: FlatEvent): EventCategory {
  return getStyle(event).category
}

// ---------------------------------------------------------------------------
// Error event detection
// ---------------------------------------------------------------------------

function isErrorEvent(event: FlatEvent): boolean {
  if (event.event_type === 'worker_reaped' && event.verdict !== 'pass') return true
  if (event.event_type === 'task_failed') return true
  if (event.event_type === 'audit_ran' && event.detail.includes('misaligned')) return true
  if (event.event_type === 'orchestrator_halted') return true
  return false
}

// ---------------------------------------------------------------------------
// Filter chips
// ---------------------------------------------------------------------------

const activeFilters = ref<Set<string>>(new Set())
const taskIdFilter = ref<string | null>(null)

type FilterChip = {
  key: string
  label: string
  colorActive: string
  colorInactive: string
}

const FILTER_CHIPS: FilterChip[] = [
  { key: 'all', label: 'All', colorActive: 'bg-gray-700 text-white dark:bg-gray-200 dark:text-gray-900', colorInactive: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  { key: 'workers', label: 'Workers', colorActive: 'bg-blue-500 text-white', colorInactive: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  { key: 'tasks', label: 'Tasks', colorActive: 'bg-purple-500 text-white', colorInactive: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  { key: 'reconcile', label: 'Reconcile', colorActive: 'bg-amber-500 text-white', colorInactive: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  { key: 'errors', label: 'Errors Only', colorActive: 'bg-red-500 text-white', colorInactive: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
]

function toggleFilter(key: string): void {
  if (key === 'all') {
    activeFilters.value = new Set()
    return
  }
  const next = new Set(activeFilters.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  activeFilters.value = next
}

function isFilterActive(key: string): boolean {
  if (key === 'all') return activeFilters.value.size === 0
  return activeFilters.value.has(key)
}

function chipClass(chip: FilterChip): string {
  return isFilterActive(chip.key) ? chip.colorActive : chip.colorInactive
}

function clearTaskIdFilter(): void {
  taskIdFilter.value = null
}

function filterByTaskId(taskId: string): void {
  taskIdFilter.value = taskId
}

// ---------------------------------------------------------------------------
// Filtered + visible events
// ---------------------------------------------------------------------------

const filteredEvents = computed(() => {
  let result = props.events

  // Apply task ID filter
  if (taskIdFilter.value) {
    result = result.filter((e) => e.task_id === taskIdFilter.value)
  }

  // Apply category / error filters
  if (activeFilters.value.size > 0) {
    result = result.filter((e) => {
      const cat = getCategory(e)
      if (activeFilters.value.has(cat)) return true
      if (activeFilters.value.has('errors') && isErrorEvent(e)) return true
      return false
    })
  }

  return result
})

const visibleEvents = computed(() => {
  if (showAll.value) return filteredEvents.value
  return filteredEvents.value.slice(0, INITIAL_LIMIT)
})

const hasMore = computed(() => filteredEvents.value.length > INITIAL_LIMIT)

// ---------------------------------------------------------------------------
// Relative time
// ---------------------------------------------------------------------------

const now = ref(Date.now())
let tickTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  tickTimer = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (tickTimer) clearInterval(tickTimer)
})

function relativeTime(ts: string): string {
  if (!ts) return ''
  try {
    const diff = (now.value - new Date(ts).getTime()) / 1000
    if (diff < 0) return 'just now'
    if (diff < 60) return `${Math.round(diff)}s ago`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch {
    return ''
  }
}

function absoluteTime(ts: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

function heartbeatAgoText(hb: WorkerHeartbeat): string {
  const s = Math.round(hb.seconds_since_last)
  if (s < 60) return `${s}s ago`
  return `${Math.floor(s / 60)}m ago`
}

// ---------------------------------------------------------------------------
// "New events" indicator (scroll tracking)
// ---------------------------------------------------------------------------

const scrollContainer = ref<HTMLElement | null>(null)
const isScrolledDown = ref(false)
const newEventCount = ref(0)
const previousEventCount = ref(0)

function onScroll(): void {
  if (!scrollContainer.value) return
  isScrolledDown.value = scrollContainer.value.scrollTop > 40
  if (!isScrolledDown.value) {
    newEventCount.value = 0
  }
}

function scrollToTop(): void {
  if (scrollContainer.value) {
    scrollContainer.value.scrollTo({ top: 0, behavior: 'smooth' })
    newEventCount.value = 0
  }
}

watch(
  () => props.events.length,
  (newLen) => {
    if (previousEventCount.value > 0 && newLen > previousEventCount.value && isScrolledDown.value) {
      newEventCount.value += newLen - previousEventCount.value
    }
    previousEventCount.value = newLen
  },
)

// ---------------------------------------------------------------------------
// Task ID extraction from detail text
// ---------------------------------------------------------------------------

interface DetailSegment {
  type: 'text' | 'task_id'
  value: string
}

function parseDetail(event: FlatEvent): DetailSegment[] {
  const style = getStyle(event)
  const text = style.format(event)
  if (!event.task_id || !text.includes(event.task_id)) {
    return [{ type: 'text', value: text }]
  }
  const parts = text.split(event.task_id)
  const segments: DetailSegment[] = []
  for (let i = 0; i < parts.length; i++) {
    if (parts[i]) segments.push({ type: 'text', value: parts[i] })
    if (i < parts.length - 1) segments.push({ type: 'task_id', value: event.task_id })
  }
  return segments
}
</script>

<template>
  <div>
    <!-- Filter chips -->
    <div class="flex flex-wrap items-center gap-2 mb-3">
      <button
        v-for="chip in FILTER_CHIPS"
        :key="chip.key"
        class="px-2.5 py-1 text-[11px] font-medium rounded-full transition-colors"
        :class="chipClass(chip)"
        @click="toggleFilter(chip.key)"
      >
        {{ chip.label }}
      </button>
    </div>

    <!-- Task ID filter banner -->
    <div
      v-if="taskIdFilter"
      class="mb-3 flex items-center gap-2 rounded-md bg-blue-50 dark:bg-blue-950/30 px-3 py-1.5 text-xs text-blue-700 dark:text-blue-300"
    >
      <span>Showing events for <span class="font-mono font-medium">{{ taskIdFilter }}</span></span>
      <button
        class="ml-auto flex-shrink-0 text-blue-500 hover:text-blue-700 dark:hover:text-blue-200 font-medium"
        @click="clearTaskIdFilter"
      >
        &#x2715; clear
      </button>
    </div>

    <div v-if="events.length === 0" class="text-sm text-gray-400 dark:text-gray-500">
      No events recorded yet.
    </div>

    <div v-else class="relative">
      <!-- New events indicator -->
      <Transition name="fade">
        <button
          v-if="newEventCount > 0"
          class="sticky top-0 z-10 w-full text-center text-xs font-medium py-1.5 bg-blue-500 text-white rounded-t-md hover:bg-blue-600 transition-colors"
          @click="scrollToTop"
        >
          {{ newEventCount }} new event{{ newEventCount === 1 ? '' : 's' }} &#x2191;
        </button>
      </Transition>

      <div
        ref="scrollContainer"
        class="space-y-0 max-h-[400px] overflow-y-auto"
        @scroll="onScroll"
      >
        <!-- Active worker heartbeat rows -->
        <div
          v-for="hb in (activeHeartbeats ?? [])"
          :key="`hb-${hb.task_id}`"
          class="flex items-center gap-2 py-1.5 border-b border-blue-100 dark:border-blue-900/30 bg-blue-50/50 dark:bg-blue-950/10"
        >
          <!-- Category dot -->
          <span class="flex-shrink-0 w-1.5 h-1.5 rounded-full bg-blue-500" />

          <!-- Timestamp -->
          <span class="w-14 flex-shrink-0 text-right text-[11px] text-blue-400 dark:text-blue-500 font-mono tabular-nums">
            {{ heartbeatAgoText(hb) }}
          </span>

          <!-- Icon -->
          <span class="w-4 flex-shrink-0 text-center text-sm text-blue-400">
            &#x22EF;
          </span>

          <!-- Detail -->
          <span class="text-xs text-blue-600 dark:text-blue-300 min-w-0 flex-1">
            <span class="font-medium">{{ hb.role }}</span> for
            <button
              class="font-mono text-blue-700 dark:text-blue-200 hover:underline cursor-pointer bg-transparent border-none p-0"
              @click="filterByTaskId(hb.task_id)"
            >{{ hb.task_id }}</button>
            <template v-if="hb.last_tool_name || hb.last_message_type">
              : <span class="font-mono bg-blue-100 dark:bg-blue-900/30 px-1 rounded text-[10px]">{{ hb.last_tool_name || hb.last_message_type }}</span>
            </template>
            ({{ hb.message_count_since }} msgs)
          </span>
        </div>

        <!-- Event rows -->
        <div
          v-for="(event, idx) in visibleEvents"
          :key="idx"
          class="flex items-center gap-2 py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-b-0"
        >
          <!-- Category dot -->
          <span
            class="flex-shrink-0 w-1.5 h-1.5 rounded-full"
            :class="getStyle(event).dotColor"
          />

          <!-- Timestamp -->
          <span
            class="w-14 flex-shrink-0 text-right text-[11px] text-gray-400 dark:text-gray-500 font-mono tabular-nums"
            :title="absoluteTime(event.timestamp)"
          >
            {{ relativeTime(event.timestamp) }}
          </span>

          <!-- Icon -->
          <span class="w-4 flex-shrink-0 text-center text-sm" :class="getStyle(event).colorClass">
            {{ getStyle(event).symbol }}
          </span>

          <!-- Detail with clickable task IDs -->
          <span class="text-xs text-gray-700 dark:text-gray-300 min-w-0 flex-1">
            <template v-for="(seg, si) in parseDetail(event)" :key="si">
              <button
                v-if="seg.type === 'task_id'"
                class="font-mono text-blue-600 dark:text-blue-400 hover:underline cursor-pointer bg-transparent border-none p-0"
                @click="filterByTaskId(seg.value)"
              >{{ seg.value }}</button>
              <template v-else>{{ seg.value }}</template>
            </template>
          </span>

          <!-- Cycle badge -->
          <span
            v-if="event.cycle"
            class="flex-shrink-0 text-[10px] font-mono text-gray-400 dark:text-gray-600 bg-gray-100 dark:bg-gray-800 rounded px-1.5 py-0.5"
          >
            #{{ event.cycle }}
          </span>
        </div>
      </div>
    </div>

    <!-- Show more button -->
    <button
      v-if="hasMore && !showAll"
      class="mt-3 text-xs text-blue-600 dark:text-blue-400 hover:underline"
      @click="showAll = true"
    >
      Show {{ filteredEvents.length - INITIAL_LIMIT }} more events
    </button>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
