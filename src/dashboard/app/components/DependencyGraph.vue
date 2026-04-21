<script setup lang="ts">
import type { GraphData } from '~/types'

const props = defineProps<{
  graph: GraphData
}>()

// Layout constants
const NODE_WIDTH = 180
const NODE_HEIGHT = 60
const LAYER_GAP = 60
const NODE_GAP = 20
const PADDING = 20

// Status colors
const statusColors: Record<string, { fill: string; stroke: string; fillDark: string; strokeDark: string }> = {
  'not-started': { fill: '#f3f4f6', stroke: '#9ca3af', fillDark: '#1f2937', strokeDark: '#6b7280' },
  'in-progress': { fill: '#eff6ff', stroke: '#3b82f6', fillDark: '#1e3a5f', strokeDark: '#60a5fa' },
  'complete':    { fill: '#f0fdf4', stroke: '#22c55e', fillDark: '#14532d', strokeDark: '#4ade80' },
  'failed':     { fill: '#fef2f2', stroke: '#ef4444', fillDark: '#450a0a', strokeDark: '#f87171' },
}

const edgeStatusColors: Record<string, { light: string; dark: string }> = {
  'not-started': { light: '#9ca3af', dark: '#6b7280' },
  'in-progress': { light: '#3b82f6', dark: '#60a5fa' },
  'complete':    { light: '#22c55e', dark: '#4ade80' },
  'failed':     { light: '#ef4444', dark: '#f87171' },
}

// Detect dark mode via class on document element
const isDark = ref(false)

onMounted(() => {
  const el = document.documentElement
  isDark.value = el.classList.contains('dark')
  const observer = new MutationObserver(() => {
    isDark.value = el.classList.contains('dark')
  })
  observer.observe(el, { attributes: true, attributeFilter: ['class'] })
  onUnmounted(() => observer.disconnect())
})

interface LayoutNode {
  id: string
  title: string
  fullTitle: string
  status: string
  phase: string | null
  x: number
  y: number
  isCritical: boolean
}

interface LayoutEdge {
  fromX: number
  fromY: number
  toX: number
  toY: number
  fromId: string
  toId: string
  status: string
  isCritical: boolean
}

// Hover state
const hoveredNodeId = ref<string | null>(null)

// Build ancestor/descendant sets for hover highlight
const ancestorMap = computed(() => {
  const { nodes, edges } = props.graph
  const map = new Map<string, Set<string>>()
  for (const n of nodes) map.set(n.id, new Set())

  // Build reverse adjacency (parent -> children)
  const parents = new Map<string, string[]>()
  for (const n of nodes) parents.set(n.id, [])
  for (const e of edges) {
    parents.get(e.to_id)?.push(e.from_id)
  }

  function getAncestors(id: string, visited: Set<string>): Set<string> {
    if (visited.has(id)) return new Set()
    visited.add(id)
    const result = new Set<string>()
    for (const p of (parents.get(id) || [])) {
      result.add(p)
      for (const a of getAncestors(p, visited)) result.add(a)
    }
    return result
  }

  for (const n of nodes) {
    map.set(n.id, getAncestors(n.id, new Set()))
  }
  return map
})

const descendantMap = computed(() => {
  const { nodes, edges } = props.graph
  const map = new Map<string, Set<string>>()
  for (const n of nodes) map.set(n.id, new Set())

  const children = new Map<string, string[]>()
  for (const n of nodes) children.set(n.id, [])
  for (const e of edges) {
    children.get(e.from_id)?.push(e.to_id)
  }

  function getDescendants(id: string, visited: Set<string>): Set<string> {
    if (visited.has(id)) return new Set()
    visited.add(id)
    const result = new Set<string>()
    for (const c of (children.get(id) || [])) {
      result.add(c)
      for (const d of getDescendants(c, visited)) result.add(d)
    }
    return result
  }

  for (const n of nodes) {
    map.set(n.id, getDescendants(n.id, new Set()))
  }
  return map
})

function isRelated(nodeId: string): boolean {
  if (!hoveredNodeId.value) return true
  if (nodeId === hoveredNodeId.value) return true
  const ancestors = ancestorMap.value.get(hoveredNodeId.value)
  const descendants = descendantMap.value.get(hoveredNodeId.value)
  return (ancestors?.has(nodeId) ?? false) || (descendants?.has(nodeId) ?? false)
}

// Tooltip
const tooltipNode = ref<LayoutNode | null>(null)
const tooltipX = ref(0)
const tooltipY = ref(0)

const layout = computed(() => {
  const { nodes, edges, critical_path } = props.graph
  if (!nodes || nodes.length === 0) {
    return { nodes: [] as LayoutNode[], edges: [] as LayoutEdge[], width: 0, height: 0 }
  }

  const criticalSet = new Set(critical_path || [])

  // Build adjacency for topological sort
  const nodeMap = new Map(nodes.map(n => [n.id, n]))
  const inDeps = new Map<string, string[]>()
  const outDeps = new Map<string, string[]>()

  for (const node of nodes) {
    inDeps.set(node.id, [])
    outDeps.set(node.id, [])
  }
  for (const edge of edges) {
    if (nodeMap.has(edge.from_id) && nodeMap.has(edge.to_id)) {
      inDeps.get(edge.to_id)!.push(edge.from_id)
      outDeps.get(edge.from_id)!.push(edge.to_id)
    }
  }

  // Assign layers: tasks with no deps are layer 0
  const layers = new Map<string, number>()
  const queue: string[] = []

  for (const node of nodes) {
    const deps = inDeps.get(node.id) || []
    if (deps.length === 0) {
      layers.set(node.id, 0)
      queue.push(node.id)
    }
  }

  // BFS to assign layers
  while (queue.length > 0) {
    const current = queue.shift()!
    const currentLayer = layers.get(current)!
    for (const child of (outDeps.get(current) || [])) {
      const existingLayer = layers.get(child)
      const newLayer = currentLayer + 1
      if (existingLayer === undefined || newLayer > existingLayer) {
        layers.set(child, newLayer)
      }
      // Only add to queue if all deps have been assigned
      const childDeps = inDeps.get(child) || []
      if (childDeps.every(d => layers.has(d))) {
        if (!queue.includes(child)) {
          queue.push(child)
        }
      }
    }
  }

  // Handle any remaining unassigned nodes (cycles or orphans)
  for (const node of nodes) {
    if (!layers.has(node.id)) {
      layers.set(node.id, 0)
    }
  }

  // Group by layer
  const layerGroups = new Map<number, string[]>()
  for (const [id, layer] of layers) {
    if (!layerGroups.has(layer)) layerGroups.set(layer, [])
    layerGroups.get(layer)!.push(id)
  }

  const maxLayer = Math.max(...layerGroups.keys(), 0)

  // Position nodes
  const positioned = new Map<string, { x: number; y: number }>()
  let maxY = 0

  for (let l = 0; l <= maxLayer; l++) {
    const ids = layerGroups.get(l) || []
    const x = PADDING + l * (NODE_WIDTH + LAYER_GAP)
    for (let i = 0; i < ids.length; i++) {
      const y = PADDING + i * (NODE_HEIGHT + NODE_GAP)
      positioned.set(ids[i], { x, y })
      maxY = Math.max(maxY, y + NODE_HEIGHT)
    }
  }

  const layoutNodes: LayoutNode[] = nodes.map(n => {
    const pos = positioned.get(n.id) || { x: PADDING, y: PADDING }
    return {
      id: n.id,
      title: n.title.length > 28 ? n.title.slice(0, 28) + '...' : n.title,
      fullTitle: n.title,
      status: n.status,
      phase: n.phase,
      x: pos.x,
      y: pos.y,
      isCritical: criticalSet.has(n.id),
    }
  })

  // Build critical path edge set
  const criticalEdges = new Set<string>()
  const cpList = critical_path || []
  for (let i = 0; i < cpList.length - 1; i++) {
    criticalEdges.add(`${cpList[i]}->${cpList[i + 1]}`)
  }

  // Build status lookup for edge source nodes
  const nodeStatusMap = new Map(nodes.map(n => [n.id, n.status]))

  const layoutEdges: LayoutEdge[] = edges
    .filter(e => positioned.has(e.from_id) && positioned.has(e.to_id))
    .map(e => {
      const from = positioned.get(e.from_id)!
      const to = positioned.get(e.to_id)!
      return {
        fromX: from.x + NODE_WIDTH,
        fromY: from.y + NODE_HEIGHT / 2,
        toX: to.x,
        toY: to.y + NODE_HEIGHT / 2,
        fromId: e.from_id,
        toId: e.to_id,
        status: nodeStatusMap.get(e.from_id) || 'not-started',
        isCritical: criticalEdges.has(`${e.from_id}->${e.to_id}`),
      }
    })

  const width = PADDING * 2 + (maxLayer + 1) * (NODE_WIDTH + LAYER_GAP) - LAYER_GAP
  const height = maxY + PADDING

  return { nodes: layoutNodes, edges: layoutEdges, width, height }
})

const handleNodeClick = (nodeId: string): void => {
  navigateTo(`/tasks/${nodeId}`)
}

const getNodeFill = (status: string): string => {
  const colors = statusColors[status] || statusColors['not-started']
  return isDark.value ? colors.fillDark : colors.fill
}

const getNodeStroke = (status: string): string => {
  const colors = statusColors[status] || statusColors['not-started']
  return isDark.value ? colors.strokeDark : colors.stroke
}

const getEdgeColor = (status: string): string => {
  const colors = edgeStatusColors[status] || edgeStatusColors['not-started']
  return isDark.value ? colors.dark : colors.light
}

function handleNodeEnter(node: LayoutNode): void {
  hoveredNodeId.value = node.id
  tooltipNode.value = node
  tooltipX.value = node.x + NODE_WIDTH / 2
  tooltipY.value = node.y - 10
}

function handleNodeLeave(): void {
  hoveredNodeId.value = null
  tooltipNode.value = null
}

function isEdgeRelated(edge: LayoutEdge): boolean {
  if (!hoveredNodeId.value) return true
  return isRelated(edge.fromId) && isRelated(edge.toId)
}
</script>

<template>
  <div v-if="graph.nodes.length === 0" class="text-center text-gray-400 dark:text-gray-500 py-8">
    No tasks to display in the dependency graph.
  </div>

  <div v-else class="overflow-auto max-h-[500px] relative">
    <svg
      :width="layout.width"
      :height="layout.height"
      class="select-none"
    >
      <defs>
        <marker
          id="arrowhead"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill="#9ca3af" />
        </marker>
        <marker
          id="arrowhead-critical"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" fill="#3b82f6" />
        </marker>
        <filter id="shadow">
          <feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.15" />
        </filter>
      </defs>

      <!-- Edges -->
      <line
        v-for="(edge, i) in layout.edges"
        :key="'edge-' + i"
        :x1="edge.fromX"
        :y1="edge.fromY"
        :x2="edge.toX - 8"
        :y2="edge.toY"
        :stroke="getEdgeColor(edge.status)"
        :stroke-width="edge.isCritical ? 2.5 : 1"
        :marker-end="edge.isCritical ? 'url(#arrowhead-critical)' : 'url(#arrowhead)'"
        :opacity="isEdgeRelated(edge) ? 1 : 0.2"
        class="transition-opacity duration-150"
      />

      <!-- Nodes -->
      <g
        v-for="node in layout.nodes"
        :key="node.id"
        class="cursor-pointer"
        :opacity="isRelated(node.id) ? 1 : 0.2"
        style="transition: opacity 150ms ease"
        @click="handleNodeClick(node.id)"
        @mouseenter="handleNodeEnter(node)"
        @mouseleave="handleNodeLeave"
      >
        <rect
          :x="node.x"
          :y="node.y"
          :width="NODE_WIDTH"
          :height="NODE_HEIGHT"
          :rx="8"
          :ry="8"
          :fill="getNodeFill(node.status)"
          :stroke="getNodeStroke(node.status)"
          :stroke-width="hoveredNodeId === node.id ? 3 : (node.isCritical ? 3 : 2)"
          :filter="node.isCritical ? 'url(#shadow)' : undefined"
          class="graph-node-rect"
        />
        <!-- Task ID -->
        <text
          :x="node.x + 10"
          :y="node.y + 18"
          font-size="11"
          font-family="ui-monospace, monospace"
          :fill="isDark ? '#9ca3af' : '#6b7280'"
        >
          {{ node.id }}
        </text>
        <!-- Title -->
        <text
          :x="node.x + 10"
          :y="node.y + 36"
          font-size="13"
          :fill="isDark ? '#e5e7eb' : '#111827'"
        >
          {{ node.title }}
        </text>
        <!-- Phase -->
        <text
          v-if="node.phase"
          :x="node.x + 10"
          :y="node.y + 52"
          font-size="10"
          :fill="isDark ? '#6b7280' : '#9ca3af'"
        >
          {{ node.phase }}
        </text>
      </g>

      <!-- Tooltip -->
      <g v-if="tooltipNode">
        <rect
          :x="tooltipX - 80"
          :y="tooltipY - 38"
          width="160"
          height="32"
          rx="6"
          :fill="isDark ? '#374151' : '#1f2937'"
          opacity="0.95"
        />
        <text
          :x="tooltipX"
          :y="tooltipY - 26"
          font-size="11"
          fill="white"
          text-anchor="middle"
          font-family="ui-sans-serif, system-ui, sans-serif"
        >
          {{ tooltipNode.fullTitle.length > 24 ? tooltipNode.fullTitle.slice(0, 24) + '...' : tooltipNode.fullTitle }}
        </text>
        <text
          :x="tooltipX"
          :y="tooltipY - 13"
          font-size="10"
          fill="#9ca3af"
          text-anchor="middle"
          font-family="ui-sans-serif, system-ui, sans-serif"
        >
          {{ tooltipNode.status }}{{ tooltipNode.phase ? ' / ' + tooltipNode.phase : '' }}
        </text>
      </g>
    </svg>
  </div>
</template>

<style scoped>
.graph-node-rect {
  transition: filter 150ms ease, stroke-width 150ms ease;
}
</style>
