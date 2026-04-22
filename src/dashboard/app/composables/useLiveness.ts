type LivenessStatus = 'live' | 'stale' | 'disconnected'

const lastFetchTime = ref<number>(0)
const lastUpdatedText = ref<string>('--')
const status = ref<LivenessStatus>('disconnected')
const workersActive = ref(false)

let tickTimer: ReturnType<typeof setInterval> | null = null
let activeListeners = 0

function markFetched(): void {
  lastFetchTime.value = Date.now()
}

function setWorkersActive(active: boolean): void {
  workersActive.value = active
}

function tick(): void {
  const now = Date.now()
  const elapsed = lastFetchTime.value === 0 ? Infinity : (now - lastFetchTime.value) / 1000

  if (elapsed === Infinity) {
    lastUpdatedText.value = '--'
    status.value = 'disconnected'
  } else if (elapsed < 2) {
    lastUpdatedText.value = 'just now'
    status.value = 'live'
  } else if (elapsed < 15) {
    lastUpdatedText.value = `${Math.round(elapsed)}s ago`
    status.value = 'live'
  } else if (elapsed < 30) {
    lastUpdatedText.value = `${Math.round(elapsed)}s ago`
    status.value = 'live'
  } else if (elapsed < 60) {
    lastUpdatedText.value = `${Math.round(elapsed)}s ago`
    status.value = 'stale'
  } else {
    const mins = Math.floor(elapsed / 60)
    lastUpdatedText.value = `${mins}m ago`
    status.value = 'disconnected'
  }
}

export function useLiveness(): {
  markFetched: () => void
  setWorkersActive: (active: boolean) => void
  lastUpdatedText: Readonly<Ref<string>>
  status: Readonly<Ref<LivenessStatus>>
  workersActive: Readonly<Ref<boolean>>
} {
  onMounted(() => {
    activeListeners++
    if (activeListeners === 1) {
      tick()
      tickTimer = setInterval(tick, 1000)
    }
  })

  onUnmounted(() => {
    activeListeners--
    if (activeListeners === 0 && tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
  })

  return {
    markFetched,
    setWorkersActive,
    lastUpdatedText: readonly(lastUpdatedText),
    status: readonly(status),
    workersActive: readonly(workersActive),
  }
}
