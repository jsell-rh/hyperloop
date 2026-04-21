<script setup lang="ts">
import type { GraphData, PipelineStepInfo } from '~/types'

const props = defineProps<{
  graph: GraphData
  pipelineSteps?: PipelineStepInfo[]
}>()

// Layout constants
const NODE_WIDTH = 200
const NODE_HEIGHT = 72
const LAYER_GAP = 60
const NODE_GAP = 20
const PADDING = 20

// Refs
const containerRef = ref<HTMLDivElement | null>(null)

// Zoom and pan state
const scale = ref(1)
const panX = ref(0)
const panY = ref(0)
const isPanning = ref(false)
let panStart = { x: 0, y: 0 }

// Touch state
let lastTouchDist = 0
let isTouchPanning = false

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

// B2: Cursor-targeted zoom
function onWheel(e: WheelEvent): void {
  e.preventDefault()
  const container = containerRef.value
  if (!container) return
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  const rect = container.getBoundingClientRect()
  const mouseX = e.clientX - rect.left
  const mouseY = e.clientY - rect.top
  const graphX = (mouseX - panX.value) / scale.value
  const graphY = (mouseY - panY.value) / scale.value
  scale.value = clamp(scale.value * delta, 0.3, 3)
  panX.value = mouseX - graphX * scale.value
  panY.value = mouseY - graphY * scale.value
}

function onMouseDown(e: MouseEvent): void {
  if (e.button !== 0) return
  isPanning.value = true
  panStart = { x: e.clientX - panX.value, y: e.clientY - panY.value }
}

function onMouseMove(e: MouseEvent): void {
  if (!isPanning.value) return
  panX.value = e.clientX - panStart.x
  panY.value = e.clientY - panStart.y
}

function onMouseUp(): void {
  isPanning.value = false
}

// B9: Touch support
function onTouchStart(e: TouchEvent): void {
  if (e.touches.length === 1) {
    isTouchPanning = true
    panStart = { x: e.touches[0].clientX - panX.value, y: e.touches[0].clientY - panY.value }
  } else if (e.touches.length === 2) {
    isTouchPanning = false
    const dx = e.touches[0].clientX - e.touches[1].clientX
    const dy = e.touches[0].clientY - e.touches[1].clientY
    lastTouchDist = Math.sqrt(dx * dx + dy * dy)
  }
}

function onTouchMove(e: TouchEvent): void {
  e.preventDefault()
  if (e.touches.length === 1 && isTouchPanning) {
    panX.value = e.touches[0].clientX - panStart.x
    panY.value = e.touches[0].clientY - panStart.y
  } else if (e.touches.length === 2) {
    const dx = e.touches[0].clientX - e.touches[1].clientX
    const dy = e.touches[0].clientY - e.touches[1].clientY
    const dist = Math.sqrt(dx * dx + dy * dy)
    const center = {
      x: (e.touches[0].clientX + e.touches[1].clientX) / 2,
      y: (e.touches[0].clientY + e.touches[1].clientY) / 2,
    }

    if (lastTouchDist > 0) {
      const container = containerRef.value
      if (!container) return
      const rect = container.getBoundingClientRect()
      const pinchScale = dist / lastTouchDist
      const cx = center.x - rect.left
      const cy = center.y - rect.top
      const graphX = (cx - panX.value) / scale.value
      const graphY = (cy - panY.value) / scale.value
      scale.value = clamp(scale.value * pinchScale, 0.3, 3)
      panX.value = cx - graphX * scale.value
      panY.value = cy - graphY * scale.value
    }

    lastTouchDist = dist
  }
}

function onTouchEnd(e: TouchEvent): void {
  if (e.touches.length < 2) {
    lastTouchDist = 0
  }
  if (e.touches.length === 0) {
    isTouchPanning = false
  }
}

// B1: Fit-to-view
function fitToView(): void {
  const container = containerRef.value
  if (!container || layout.value.width === 0) return
  const rect = container.getBoundingClientRect()
  const pad = 20
  const scaleX = (rect.width - pad * 2) / layout.value.width
  const scaleY = (rect.height - pad * 2) / layout.value.height
  const newScale = clamp(Math.min(scaleX, scaleY), 0.3, 3)
  scale.value = newScale
  panX.value = (rect.width - layout.value.width * newScale) / 2
  panY.value = (rect.height - layout.value.height * newScale) / 2
}

function resetView(): void {
  fitToView()
}

function zoomIn(): void {
  scale.value = clamp(scale.value * 1.2, 0.3, 3)
}

function zoomOut(): void {
  scale.value = clamp(scale.value * 0.8, 0.3, 3)
}

// Status colors
const statusColors: Record<string, { fill: string; stroke: string; fillDark: string; strokeDark: string }> = {
  'not-started': { fill: '#f3f4f6', stroke: '#9ca3af', fillDark: '#1f2937', strokeDark: '#6b7280' },
  'in-progress': { fill: '#eff6ff', stroke: '#3b82f6', fillDark: '#1e3a5f', strokeDark: '#60a5fa' },
  'complete':    { fill: '#f0fdf4', stroke: '#22c55e', fillDark: '#14532d', strokeDark: '#4ade80' },
  'failed':     { fill: '#fef2f2', stroke: '#ef4444', fillDark: '#450a0a', strokeDark: '#f87171' },
}

// Detect dark mode via class on document element
const isDark = ref(false)

let darkModeObserver: MutationObserver | undefined

onMounted(() => {
  // Dark mode detection
  const el = document.documentElement
  isDark.value = el.classList.contains('dark')
  darkModeObserver = new MutationObserver(() => {
    isDark.value = el.classList.contains('dark')
  })
  darkModeObserver.observe(el, { attributes: true, attributeFilter: ['class'] })

  // Fit to view on mount
  nextTick(() => fitToView())

  // Register touch handlers with passive: false
  const container = containerRef.value
  if (container) {
    container.addEventListener('touchmove', onTouchMove, { passive: false })
  }

  // Legend: first-visit expansion
  const legendStored = localStorage.getItem('hyperloop-graph-legend')
  if (legendStored === null) {
    legendExpanded.value = true
    localStorage.setItem('hyperloop-graph-legend', 'collapsed')
  } else {
    legendExpanded.value = legendStored === 'expanded'
  }
})

onUnmounted(() => {
  darkModeObserver?.disconnect()
  const container = containerRef.value
  if (container) {
    container.removeEventListener('touchmove', onTouchMove)
  }
})

// B6: Word-boundary aware truncation
function truncateTitle(title: string, maxChars: number = 30): string {
  if (title.length <= maxChars) return title
  // Try to break at a word boundary
  const truncated = title.slice(0, maxChars)
  const lastSpace = truncated.lastIndexOf(' ')
  if (lastSpace > maxChars * 0.6) {
    return truncated.slice(0, lastSpace) + '...'
  }
  return truncated + '...'
}

interface LayoutNode {
  id: string
  title: string
  fullTitle: string
  status: string
  phase: string | null
  x: number
  y: number
  isCritical: boolean
  layer: number
}

interface LayoutEdge {
  fromX: number
  fromY: number
  toX: number
  toY: number
  fromId: string
  toId: string
  sourceStatus: string
  isCritical: boolean
}

// Mini pipeline: determine step state for a given node phase
type MiniStepState = 'completed' | 'active' | 'pending'

function getMiniStepState(stepIndex: number, nodePhase: string | null): MiniStepState {
  if (!props.pipelineSteps || props.pipelineSteps.length === 0 || !nodePhase) return 'pending'
  const activeIndex = props.pipelineSteps.findIndex(s => s.name === nodePhase)
  if (activeIndex === -1) return 'pending'
  if (stepIndex < activeIndex) return 'completed'
  if (stepIndex === activeIndex) return 'active'
  return 'pending'
}

function getMiniDotFill(state: MiniStepState): string {
  if (state === 'completed') return isDark.value ? '#4ade80' : '#22c55e'
  if (state === 'active') return isDark.value ? '#60a5fa' : '#3b82f6'
  return 'none'
}

function getMiniDotStroke(state: MiniStepState): string {
  if (state === 'completed') return isDark.value ? '#4ade80' : '#22c55e'
  if (state === 'active') return isDark.value ? '#60a5fa' : '#3b82f6'
  return isDark.value ? '#4b5563' : '#d1d5db'
}

// Hover state
const hoveredNodeId = ref<string | null>(null)
const focusedNodeId = ref<string | null>(null)
const activeNodeId = computed(() => hoveredNodeId.value ?? focusedNodeId.value)

// Build ancestor/descendant sets for hover highlight
const ancestorMap = computed(() => {
  const { nodes, edges } = props.graph
  const map = new Map<string, Set<string>>()
  for (const n of nodes) map.set(n.id, new Set())

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
  if (!activeNodeId.value) return true
  if (nodeId === activeNodeId.value) return true
  const ancestors = ancestorMap.value.get(activeNodeId.value)
  const descendants = descendantMap.value.get(activeNodeId.value)
  return (ancestors?.has(nodeId) ?? false) || (descendants?.has(nodeId) ?? false)
}

// HTML tooltip (B6)
const tooltipNode = ref<LayoutNode | null>(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })

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

  // B5: Sort nodes within each layer by id alphabetically for stable layout
  for (const [, ids] of layerGroups) {
    ids.sort((a, b) => a.localeCompare(b))
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
      title: truncateTitle(n.title),
      fullTitle: n.title,
      status: n.status,
      phase: n.phase,
      x: pos.x,
      y: pos.y,
      isCritical: criticalSet.has(n.id),
      layer: layers.get(n.id) ?? 0,
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
        sourceStatus: nodeStatusMap.get(e.from_id) || 'not-started',
        isCritical: criticalEdges.has(`${e.from_id}->${e.to_id}`),
      }
    })

  const width = PADDING * 2 + (maxLayer + 1) * (NODE_WIDTH + LAYER_GAP) - LAYER_GAP
  const height = maxY + PADDING

  return { nodes: layoutNodes, edges: layoutEdges, width, height }
})

// Refit when data changes
watch(() => props.graph, () => {
  nextTick(() => fitToView())
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

// B4: Edge color = dependency satisfaction (green=complete, red=failed, gray=otherwise)
const getEdgeColor = (sourceStatus: string): string => {
  if (sourceStatus === 'complete') return isDark.value ? '#4ade80' : '#22c55e'
  if (sourceStatus === 'failed') return isDark.value ? '#f87171' : '#ef4444'
  return isDark.value ? '#6b7280' : '#9ca3af'
}

// B4: Edge dash pattern for color-independent status differentiation (B8)
const getEdgeDashArray = (sourceStatus: string, isCritical: boolean): string | undefined => {
  if (isCritical) return undefined // critical edges are solid with animation
  if (sourceStatus === 'failed') return '6 3'
  if (sourceStatus === 'not-started') return '3 3'
  return undefined
}

function handleNodeEnter(node: LayoutNode, event: MouseEvent): void {
  hoveredNodeId.value = node.id
  tooltipNode.value = node
  updateTooltipPosition(event)
}

function handleNodeMove(event: MouseEvent): void {
  updateTooltipPosition(event)
}

function handleNodeLeave(): void {
  hoveredNodeId.value = null
  tooltipNode.value = null
}

function handleNodeFocus(node: LayoutNode): void {
  focusedNodeId.value = node.id
  tooltipNode.value = node
  // Position tooltip at node center for focus
  const container = containerRef.value
  if (container) {
    const rect = container.getBoundingClientRect()
    const x = panX.value + (node.x + NODE_WIDTH / 2) * scale.value
    const y = panY.value + node.y * scale.value
    tooltipStyle.value = {
      left: `${clamp(x, 80, rect.width - 80)}px`,
      top: `${Math.max(0, y - 10)}px`,
    }
  }
}

function handleNodeBlur(): void {
  focusedNodeId.value = null
  if (!hoveredNodeId.value) {
    tooltipNode.value = null
  }
}

function updateTooltipPosition(event: MouseEvent): void {
  const container = containerRef.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  tooltipStyle.value = {
    left: `${event.clientX - rect.left}px`,
    top: `${event.clientY - rect.top - 60}px`,
  }
}

function isEdgeRelated(edge: LayoutEdge): boolean {
  if (!activeNodeId.value) return true
  return isRelated(edge.fromId) && isRelated(edge.toId)
}

// B3: Bezier curve path
function getEdgePath(edge: LayoutEdge): string {
  const { fromX, fromY, toX, toY } = edge
  const cx1 = fromX + (toX - fromX) * 0.4
  const cx2 = toX - (toX - fromX) * 0.4
  return `M ${fromX} ${fromY} C ${cx1} ${fromY}, ${cx2} ${toY}, ${toX} ${toY}`
}

// Mini pipeline dot positions
function getPipelineDotX(stepIndex: number, totalSteps: number, nodeX: number): number {
  const dotSpacing = 8
  const totalWidth = (totalSteps - 1) * dotSpacing
  const startX = nodeX + NODE_WIDTH / 2 - totalWidth / 2
  return startX + stepIndex * dotSpacing
}

// B7: Legend
const legendExpanded = ref(false)

watch(legendExpanded, (val) => {
  localStorage.setItem('hyperloop-graph-legend', val ? 'expanded' : 'collapsed')
})

// B10: Entrance animation stagger delay
function getNodeAnimDelay(node: LayoutNode): string {
  return `${node.layer * 30}ms`
}

// B8: Node aria-label
function getNodeAriaLabel(node: LayoutNode): string {
  const phase = node.phase ? `, phase: ${node.phase}` : ''
  return `${node.fullTitle} (${node.id}), status: ${node.status}${phase}`
}

// B1: viewBox
const viewBox = computed(() => {
  return `0 0 ${layout.value.width} ${layout.value.height}`
})

// B8: Keyboard navigation for nodes
function handleNodeKeydown(e: KeyboardEvent, nodeId: string): void {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    handleNodeClick(nodeId)
  }
}
</script>

<template>
  <div v-if="graph.nodes.length === 0" class="text-center text-gray-400 dark:text-gray-500 py-8">
    No tasks to display in the dependency graph.
  </div>

  <div
    v-else
    ref="containerRef"
    class="relative overflow-hidden rounded-lg max-h-[min(60vh,600px)]"
    :class="isPanning ? 'cursor-grabbing' : 'cursor-grab'"
    @wheel.prevent="onWheel"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
    @mouseleave="onMouseUp"
    @touchstart="onTouchStart"
    @touchend="onTouchEnd"
  >
    <!-- B1: viewBox-based SVG -->
    <svg
      :viewBox="viewBox"
      :width="layout.width"
      :height="layout.height"
      class="select-none"
      role="img"
      :aria-label="`Dependency graph showing ${layout.nodes.length} tasks and their relationships`"
    >
      <title>Task Dependency Graph</title>
      <desc>A directed graph showing task dependencies. Nodes represent tasks colored by status. Edges show dependency relationships with color indicating whether the dependency is satisfied.</desc>

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
          id="arrowhead-green"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" :fill="isDark ? '#4ade80' : '#22c55e'" />
        </marker>
        <marker
          id="arrowhead-red"
          markerWidth="8"
          markerHeight="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <polygon points="0 0, 8 3, 0 6" :fill="isDark ? '#f87171' : '#ef4444'" />
        </marker>
        <filter id="shadow">
          <feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.15" />
        </filter>
        <filter id="hover-glow">
          <feDropShadow dx="0" dy="0" stdDeviation="4" :flood-color="isDark ? '#60a5fa' : '#3b82f6'" flood-opacity="0.3" />
        </filter>
        <!-- Active dot glow -->
        <filter id="active-glow">
          <feGaussianBlur stdDeviation="1.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <g :transform="`translate(${panX}, ${panY}) scale(${scale})`" class="graph-pan-group">
        <!-- B3: Bezier curve edges -->
        <path
          v-for="(edge, i) in layout.edges"
          :key="'edge-' + i"
          :d="getEdgePath(edge)"
          fill="none"
          :stroke="getEdgeColor(edge.sourceStatus)"
          :stroke-width="edge.isCritical ? 2.5 : 1.5"
          :stroke-dasharray="edge.isCritical ? '8 4' : getEdgeDashArray(edge.sourceStatus, edge.isCritical)"
          :marker-end="edge.sourceStatus === 'complete' ? 'url(#arrowhead-green)' : (edge.sourceStatus === 'failed' ? 'url(#arrowhead-red)' : 'url(#arrowhead)')"
          :opacity="isEdgeRelated(edge) ? 1 : 0.2"
          :class="[
            'transition-opacity duration-150',
            edge.isCritical ? 'critical-edge' : ''
          ]"
          :style="{ animationDelay: `${i * 50}ms` }"
        />

        <!-- Nodes -->
        <g
          v-for="node in layout.nodes"
          :key="node.id"
          class="graph-node"
          :style="{ animationDelay: getNodeAnimDelay(node) }"
          :opacity="isRelated(node.id) ? 1 : 0.2"
          tabindex="0"
          role="link"
          :aria-label="getNodeAriaLabel(node)"
          @click="handleNodeClick(node.id)"
          @mouseenter="handleNodeEnter(node, $event)"
          @mousemove="handleNodeMove($event)"
          @mouseleave="handleNodeLeave"
          @focus="handleNodeFocus(node)"
          @blur="handleNodeBlur"
          @keydown="handleNodeKeydown($event, node.id)"
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
            :stroke-width="(activeNodeId === node.id) ? 3 : (node.isCritical ? 3 : 2)"
            :filter="(activeNodeId === node.id) ? 'url(#hover-glow)' : (node.isCritical ? 'url(#shadow)' : undefined)"
            class="graph-node-rect"
            :class="{ 'animate-badge-pulse': node.status === 'in-progress' }"
            :style="(activeNodeId === node.id) ? 'transform: scale(1.03); transform-origin: ' + (node.x + NODE_WIDTH/2) + 'px ' + (node.y + NODE_HEIGHT/2) + 'px' : undefined"
          />

          <!-- B6: Status icon (12x12) in top-left -->
          <g :transform="`translate(${node.x + 8}, ${node.y + 6})`">
            <!-- not-started: dashed circle -->
            <circle
              v-if="node.status === 'not-started'"
              cx="6"
              cy="6"
              r="5"
              fill="none"
              :stroke="isDark ? '#6b7280' : '#9ca3af'"
              stroke-width="1.5"
              stroke-dasharray="3 2"
            />
            <!-- in-progress: circle + clock hand -->
            <template v-else-if="node.status === 'in-progress'">
              <circle cx="6" cy="6" r="5" fill="none" :stroke="isDark ? '#60a5fa' : '#3b82f6'" stroke-width="1.5" />
              <path :d="'M6 3.5v2.5l1.5 1.5'" fill="none" :stroke="isDark ? '#60a5fa' : '#3b82f6'" stroke-width="1.5" stroke-linecap="round" />
            </template>
            <!-- complete: checkmark -->
            <path
              v-else-if="node.status === 'complete'"
              d="M2.5 6.5l2.5 2.5L9.5 3.5"
              fill="none"
              :stroke="isDark ? '#4ade80' : '#22c55e'"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <!-- failed: X -->
            <path
              v-else-if="node.status === 'failed'"
              d="M2.5 2.5l7 7M9.5 2.5l-7 7"
              fill="none"
              :stroke="isDark ? '#f87171' : '#ef4444'"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </g>

          <!-- B6: Title on top (13px, medium weight) -->
          <text
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 22"
            font-size="13"
            font-weight="500"
            text-anchor="middle"
            :fill="isDark ? '#e5e7eb' : '#111827'"
          >
            {{ node.title }}
          </text>
          <!-- B6: ID below (10px, muted monospace) -->
          <text
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 38"
            font-size="10"
            font-family="ui-monospace, monospace"
            text-anchor="middle"
            :fill="isDark ? '#9ca3af' : '#6b7280'"
          >
            {{ node.id }}
          </text>
          <!-- Mini pipeline dots -->
          <template v-if="pipelineSteps && pipelineSteps.length > 0 && node.phase">
            <circle
              v-for="(step, si) in pipelineSteps"
              :key="'pip-' + node.id + '-' + si"
              :cx="getPipelineDotX(si, pipelineSteps.length, node.x)"
              :cy="node.y + 55"
              r="3"
              :fill="getMiniDotFill(getMiniStepState(si, node.phase))"
              :stroke="getMiniDotStroke(getMiniStepState(si, node.phase))"
              stroke-width="1.5"
              :filter="getMiniStepState(si, node.phase) === 'active' ? 'url(#active-glow)' : undefined"
            />
          </template>
          <!-- Phase text fallback -->
          <text
            v-else-if="node.phase"
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 58"
            font-size="10"
            text-anchor="middle"
            :fill="isDark ? '#6b7280' : '#9ca3af'"
          >
            {{ node.phase }}
          </text>
        </g>
      </g>
    </svg>

    <!-- B6: HTML tooltip positioned above SVG -->
    <div
      v-if="tooltipNode"
      class="absolute z-20 pointer-events-none px-3 py-2 rounded-md text-xs shadow-lg max-w-xs"
      :class="isDark ? 'bg-gray-700 text-gray-100' : 'bg-gray-900 text-white'"
      :style="{ left: tooltipStyle.left, top: tooltipStyle.top, transform: 'translateX(-50%)' }"
    >
      <p class="font-medium">{{ tooltipNode.fullTitle }}</p>
      <p class="text-gray-400 mt-0.5">
        {{ tooltipNode.status }}{{ tooltipNode.phase ? ' / ' + tooltipNode.phase : '' }}
      </p>
    </div>

    <!-- B7: Legend -->
    <div class="absolute top-3 left-3 z-10">
      <button
        class="h-7 w-7 flex items-center justify-center rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 text-sm font-bold hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors shadow-sm"
        aria-label="Toggle graph legend"
        @click="legendExpanded = !legendExpanded"
      >
        ?
      </button>
      <Transition name="expand">
        <div
          v-if="legendExpanded"
          class="mt-1 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-2.5 shadow-sm text-[10px] space-y-1.5 min-w-[140px]"
        >
          <p class="font-medium text-gray-700 dark:text-gray-300 text-[11px]">Legend</p>
          <div class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-full bg-gray-300 dark:bg-gray-600 inline-block" />
            <span class="text-gray-600 dark:text-gray-400">Not Started</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-full bg-blue-500 dark:bg-blue-400 inline-block" />
            <span class="text-gray-600 dark:text-gray-400">In Progress</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-full bg-green-500 dark:bg-green-400 inline-block" />
            <span class="text-gray-600 dark:text-gray-400">Complete</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-full bg-red-500 dark:bg-red-400 inline-block" />
            <span class="text-gray-600 dark:text-gray-400">Failed</span>
          </div>
          <hr class="border-gray-200 dark:border-gray-700" />
          <div class="flex items-center gap-1.5">
            <span class="inline-block w-5 h-0 border-t border-gray-400 dark:border-gray-500" />
            <span class="text-gray-600 dark:text-gray-400">Dependency</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="inline-block w-5 h-0 border-t-2 border-blue-500 dark:border-blue-400" />
            <span class="text-gray-600 dark:text-gray-400">Critical path</span>
          </div>
        </div>
      </Transition>
    </div>

    <!-- B8: Zoom controls with aria-label, h-9 w-9 -->
    <div class="absolute bottom-3 right-3 flex gap-1">
      <button
        class="h-9 w-9 flex items-center justify-center rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-150 shadow-sm"
        aria-label="Zoom in"
        @click="zoomIn"
      >
        +
      </button>
      <button
        class="h-9 w-9 flex items-center justify-center rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-150 shadow-sm"
        aria-label="Zoom out"
        @click="zoomOut"
      >
        -
      </button>
      <button
        class="h-9 px-2 flex items-center justify-center rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-500 dark:text-gray-400 text-xs hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors duration-150 shadow-sm"
        aria-label="Fit graph to view"
        @click="resetView"
      >
        Reset
      </button>
    </div>
  </div>

  <!-- B8: Visually-hidden data table for screen readers -->
  <table v-if="layout.nodes.length > 0" class="sr-only" aria-label="Task dependency data">
    <caption>Task dependency graph data with status and relationships</caption>
    <thead>
      <tr>
        <th scope="col">Task ID</th>
        <th scope="col">Title</th>
        <th scope="col">Status</th>
        <th scope="col">Phase</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="node in layout.nodes" :key="'table-' + node.id">
        <td>{{ node.id }}</td>
        <td>{{ node.fullTitle }}</td>
        <td>{{ node.status }}</td>
        <td>{{ node.phase ?? '--' }}</td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.graph-node-rect {
  transition: filter 150ms ease, stroke-width 150ms ease, transform 150ms ease;
}
.graph-pan-group {
  transition: transform 0ms;
}

/* B10: Node entrance animation */
.graph-node {
  animation: node-enter 300ms ease both;
  cursor: pointer;
  outline: none;
}
.graph-node:focus-visible rect {
  stroke-width: 3;
  filter: url(#hover-glow);
}

/* B10: Critical path flow animation */
.critical-edge {
  animation: edge-flow 1s linear infinite;
}

/* B8: Screen-reader only utility (in case not provided by Tailwind) */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border-width: 0;
}
</style>
