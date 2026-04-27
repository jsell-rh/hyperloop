type KeyHandler = () => void

interface KeyboardOptions {
  /** Global go-to chord shortcuts (e.g., G then H → navigate home) */
  goTo?: Record<string, KeyHandler>
  /** Direct key shortcuts (e.g., '1' → switch tab) */
  keys?: Record<string, KeyHandler>
  /** Timeout for chord second-key in ms (default 500) */
  chordTimeout?: number
}

/**
 * Composable for keyboard navigation.
 *
 * Registers keydown listeners, handles G-chord (waits for second key),
 * ignores shortcuts when focus is in input/textarea/contenteditable,
 * and cleans up on unmount.
 */
export function useKeyboard(options: KeyboardOptions): void {
  const chordTimeout = options.chordTimeout ?? 500
  let waitingForChord = false
  let chordTimer: ReturnType<typeof setTimeout> | null = null

  function isInputFocused(): boolean {
    const el = document.activeElement
    if (!el) return false
    const tag = el.tagName.toLowerCase()
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
    if ((el as HTMLElement).isContentEditable) return true
    return false
  }

  function handleKeydown(event: KeyboardEvent): void {
    if (isInputFocused()) return
    // Ignore when modifier keys are held (except shift for uppercase)
    if (event.ctrlKey || event.metaKey || event.altKey) return

    const key = event.key.toUpperCase()

    // If waiting for chord second key
    if (waitingForChord) {
      waitingForChord = false
      if (chordTimer) {
        clearTimeout(chordTimer)
        chordTimer = null
      }
      const handler = options.goTo?.[key]
      if (handler) {
        event.preventDefault()
        handler()
      }
      return
    }

    // Start G-chord
    if (key === 'G' && options.goTo && Object.keys(options.goTo).length > 0) {
      waitingForChord = true
      chordTimer = setTimeout(() => {
        waitingForChord = false
        chordTimer = null
      }, chordTimeout)
      return
    }

    // Direct key shortcuts
    const directHandler = options.keys?.[key]
    if (directHandler) {
      event.preventDefault()
      directHandler()
      return
    }

    // Also check lowercase version of the key
    const directHandlerLower = options.keys?.[event.key]
    if (directHandlerLower) {
      event.preventDefault()
      directHandlerLower()
    }
  }

  onMounted(() => {
    document.addEventListener('keydown', handleKeydown)
  })

  onUnmounted(() => {
    document.removeEventListener('keydown', handleKeydown)
    if (chordTimer) {
      clearTimeout(chordTimer)
      chordTimer = null
    }
    waitingForChord = false
  })
}
