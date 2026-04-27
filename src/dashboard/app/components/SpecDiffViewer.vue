<script setup lang="ts">
const props = defineProps<{
  oldContent: string
  newContent: string
  oldSha: string | null
  newSha: string | null
}>()

interface DiffLine {
  lineNum: number | null
  text: string
  type: 'same' | 'added' | 'removed'
}

const oldLines = computed(() => props.oldContent.split('\n'))
const newLines = computed(() => props.newContent.split('\n'))

/**
 * Simple line-by-line diff: walk both arrays, mark lines as same/added/removed.
 * Uses a longest-common-subsequence approach for reasonable results.
 */
const diff = computed((): { left: DiffLine[]; right: DiffLine[] } => {
  const a = oldLines.value
  const b = newLines.value

  // Build LCS table
  const m = a.length
  const n = b.length
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0) as number[])

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  // Backtrack to build diff
  const left: DiffLine[] = []
  const right: DiffLine[] = []
  let i = m
  let j = n

  const resultPairs: Array<{ leftLine: DiffLine; rightLine: DiffLine }> = []

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      resultPairs.push({
        leftLine: { lineNum: i, text: a[i - 1], type: 'same' },
        rightLine: { lineNum: j, text: b[j - 1], type: 'same' },
      })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      resultPairs.push({
        leftLine: { lineNum: null, text: '', type: 'same' },
        rightLine: { lineNum: j, text: b[j - 1], type: 'added' },
      })
      j--
    } else {
      resultPairs.push({
        leftLine: { lineNum: i, text: a[i - 1], type: 'removed' },
        rightLine: { lineNum: null, text: '', type: 'same' },
      })
      i--
    }
  }

  resultPairs.reverse()

  for (const pair of resultPairs) {
    left.push(pair.leftLine)
    right.push(pair.rightLine)
  }

  return { left, right }
})

const oldShaShort = computed(() => props.oldSha?.slice(0, 7) ?? 'old')
const newShaShort = computed(() => props.newSha?.slice(0, 7) ?? 'new')
</script>

<template>
  <div class="rounded-lg bg-white dark:bg-gray-900 shadow-card dark:ring-1 dark:ring-white/[0.06] dark:shadow-none overflow-hidden">
    <div class="grid grid-cols-2 border-b border-gray-200 dark:border-gray-700">
      <div class="px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 bg-red-50/50 dark:bg-red-900/10">
        Old ({{ oldShaShort }})
      </div>
      <div class="px-4 py-2 text-xs font-medium text-gray-500 dark:text-gray-400 bg-green-50/50 dark:bg-green-900/10 border-l border-gray-200 dark:border-gray-700">
        New ({{ newShaShort }})
      </div>
    </div>

    <div class="grid grid-cols-2 font-mono text-xs leading-5 max-h-[500px] overflow-y-auto">
      <!-- Left (old) -->
      <div class="overflow-x-auto">
        <div
          v-for="(line, idx) in diff.left"
          :key="`l-${idx}`"
          class="flex min-h-[20px]"
          :class="{
            'bg-red-50 dark:bg-red-900/20': line.type === 'removed',
          }"
        >
          <span class="w-10 flex-shrink-0 text-right pr-2 text-gray-400 dark:text-gray-600 select-none border-r border-gray-100 dark:border-gray-800">
            {{ line.lineNum ?? '' }}
          </span>
          <span
            class="px-2 whitespace-pre"
            :class="{
              'text-red-700 dark:text-red-400': line.type === 'removed',
              'text-gray-700 dark:text-gray-300': line.type === 'same',
            }"
          >{{ line.text }}</span>
        </div>
      </div>

      <!-- Right (new) -->
      <div class="overflow-x-auto border-l border-gray-200 dark:border-gray-700">
        <div
          v-for="(line, idx) in diff.right"
          :key="`r-${idx}`"
          class="flex min-h-[20px]"
          :class="{
            'bg-green-50 dark:bg-green-900/20': line.type === 'added',
          }"
        >
          <span class="w-10 flex-shrink-0 text-right pr-2 text-gray-400 dark:text-gray-600 select-none border-r border-gray-100 dark:border-gray-800">
            {{ line.lineNum ?? '' }}
          </span>
          <span
            class="px-2 whitespace-pre"
            :class="{
              'text-green-700 dark:text-green-400': line.type === 'added',
              'text-gray-700 dark:text-gray-300': line.type === 'same',
            }"
          >{{ line.text }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
