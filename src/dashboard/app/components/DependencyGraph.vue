<script setup lang="ts">
import type { GraphData } from '~/types'

interface PipelineStepInfo {
  name: string
  type: string
}

const props = defineProps<{
  graph: GraphData
  pipelineSteps?: PipelineStepInfo[]
}>()

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------
const NODE_WIDTH = 230
const NODE_HEIGHT = 56
const NODE_HEIGHT_WITH_PHASE = 68
const LAYER_GAP = 70
const NODE_GAP = 16
const SPEC_GROUP_GAP = 32
const PADDING = 24
const EDGE_SPREAD_PX = 6

// ---------------------------------------------------------------------------
// Refs
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Dark mode detection
// ---------------------------------------------------------------------------
const isDark = ref(false)
let darkModeObserver: MutationObserver | undefined

// ---------------------------------------------------------------------------
// Zoom / pan handlers
// ---------------------------------------------------------------------------
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

// Touch support
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
  if (e.touches.length < 2) lastTouchDist = 0
  if (e.touches.length === 0) isTouchPanning = false
}

// ---------------------------------------------------------------------------
// Fit-to-view
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Word-boundary aware truncation (28 chars to fit 230px nodes)
// ---------------------------------------------------------------------------
function truncateTitle(title: string, maxChars: number = 28): string {
  if (title.length <= maxChars) return title
  const truncated = title.slice(0, maxChars)
  const lastSpace = truncated.lastIndexOf(' ')
  if (lastSpace > maxChars * 0.6) {
    return truncated.slice(0, lastSpace) + '...'
  }
  return truncated + '...'
}

// ---------------------------------------------------------------------------
// Layout types
// ---------------------------------------------------------------------------
interface LayoutNode {
  id: string
  title: string
  fullTitle: string
  status: string
  phase: string | null
  specRef: string
  round: number
  x: number
  y: number
  height: number
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

// ---------------------------------------------------------------------------
// Node style helpers
// ---------------------------------------------------------------------------
function getNodeFill(status: string): string {
  if (status === 'complete') return isDark.value ? '#1a1a24' : '#f3f4f6'
  if (status === 'in-progress') return isDark.value ? '#0f172a' : '#ffffff'
  if (status === 'failed') return isDark.value ? '#1c0a0a' : '#fef2f2'
  // not-started
  return isDark.value ? '#111116' : '#ffffff'
}

function getNodeStroke(status: string): string {
  if (status === 'complete') return isDark.value ? '#2d2d35' : '#d1d5db'
  if (status === 'in-progress') return isDark.value ? '#60a5fa' : '#3b82f6'
  if (status === 'failed') return isDark.value ? '#f87171' : '#ef4444'
  // not-started
  return isDark.value ? '#374151' : '#d1d5db'
}

function getNodeStrokeWidth(status: string): number {
  if (status === 'in-progress' || status === 'failed') return 2.5
  if (status === 'not-started') return 1.5
  return 1 // complete
}

function getNodeStrokeDash(status: string): string | undefined {
  if (status === 'not-started') return '4 3'
  return undefined
}

function getNodeOpacity(status: string): number {
  if (status === 'complete') return isDark.value ? 0.85 : 0.9
  return 1
}

function getNodeFilter(status: string, isHovered: boolean): string | undefined {
  if (isHovered) return 'url(#hover-glow)'
  if (status === 'in-progress') return 'url(#in-progress-glow)'
  if (status === 'failed') return 'url(#failed-glow)'
  return undefined
}

function getTitleFill(status: string): string {
  if (status === 'complete') return isDark.value ? '#6b7280' : '#6b7280'
  if (status === 'in-progress') return isDark.value ? '#f8fafc' : '#0f172a'
  if (status === 'failed') return isDark.value ? '#fca5a5' : '#7f1d1d'
  // not-started
  return isDark.value ? '#9ca3af' : '#374151'
}

function getIdFill(status: string): string {
  if (status === 'complete') return isDark.value ? '#374151' : '#d1d5db'
  if (status === 'in-progress') return isDark.value ? '#60a5fa' : '#3b82f6'
  if (status === 'failed') return isDark.value ? '#f87171' : '#ef4444'
  // not-started
  return isDark.value ? '#6b7280' : '#9ca3af'
}

function getMiniBarFill(stepName: string, currentPhase: string | null, stepIndex: number): string {
  if (!currentPhase || !props.pipelineSteps) return isDark.value ? '#2d2d35' : '#e5e7eb'
  const activeIndex = props.pipelineSteps.findIndex(s => s.name === currentPhase)
  if (activeIndex === -1) return isDark.value ? '#2d2d35' : '#e5e7eb'
  if (stepIndex < activeIndex) return isDark.value ? '#166534' : '#86efac' // completed: green
  if (stepIndex === activeIndex) return isDark.value ? '#60a5fa' : '#3b82f6' // active: blue
  return isDark.value ? '#2d2d35' : '#e5e7eb' // pending: gray
}

// ---------------------------------------------------------------------------
// Edge style helpers
// ---------------------------------------------------------------------------
function getEdgeColor(sourceStatus: string): string {
  if (sourceStatus === 'complete') return isDark.value ? '#374151' : '#d1d5db'
  if (sourceStatus === 'in-progress') return isDark.value ? '#60a5fa' : '#3b82f6'
  if (sourceStatus === 'failed') return isDark.value ? '#f87171' : '#ef4444'
  return isDark.value ? '#4b5563' : '#9ca3af'
}

function getEdgeOpacity(sourceStatus: string): number {
  if (sourceStatus === 'complete') return 0.5
  if (sourceStatus === 'in-progress') return 0.8
  if (sourceStatus === 'failed') return 0.7
  return 0.5
}

function getEdgeDashArray(sourceStatus: string, isCritical: boolean): string | undefined {
  if (isCritical) return '6 3'
  if (sourceStatus === 'failed') return '6 3'
  return undefined
}

function getEdgeStrokeWidth(isCritical: boolean): number {
  return isCritical ? 2 : 1.5
}

// ---------------------------------------------------------------------------
// Hover state
// ---------------------------------------------------------------------------
const hoveredNodeId = ref<string | null>(null)
const focusedNodeId = ref<string | null>(null)
const activeNodeId = computed(() => hoveredNodeId.value ?? focusedNodeId.value)

// Ancestor/descendant maps for hover highlighting
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

function getNodeDimOpacity(nodeId: string, status: string): number {
  if (!activeNodeId.value) return getNodeOpacity(status)
  if (isRelated(nodeId)) return getNodeOpacity(status)
  if (status === 'complete') return 0.08
  return 0.15
}

function isEdgeRelated(edge: LayoutEdge): boolean {
  if (!activeNodeId.value) return true
  return isRelated(edge.fromId) && isRelated(edge.toId)
}

function getEdgeDimOpacity(edge: LayoutEdge): number {
  if (!activeNodeId.value) return getEdgeOpacity(edge.sourceStatus)
  if (isEdgeRelated(edge)) return getEdgeOpacity(edge.sourceStatus)
  return 0.05
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------
const tooltipNode = ref<LayoutNode | null>(null)
const tooltipStyle = ref({ top: '0px', left: '0px' })

// Bar segment tooltip (separate from main node tooltip)
const barTooltip = ref<{ text: string; x: number; y: number } | null>(null)
const barTooltipStyle = computed(() => {
  if (!barTooltip.value || !containerRef.value) return { left: '0px', top: '0px' }
  const rect = containerRef.value.getBoundingClientRect()
  return {
    left: `${barTooltip.value.x - rect.left - 30}px`,
    top: `${barTooltip.value.y - rect.top - 28}px`,
  }
})

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
  const container = containerRef.value
  if (container) {
    const rect = container.getBoundingClientRect()
    const tooltipWidth = 250
    let left = panX.value + (node.x + NODE_WIDTH / 2) * scale.value
    let top = panY.value + node.y * scale.value - 60

    if (left + tooltipWidth / 2 > rect.width) {
      left = rect.width - tooltipWidth / 2 - 8
    }
    if (left - tooltipWidth / 2 < 0) {
      left = tooltipWidth / 2 + 8
    }
    if (top < 8) {
      top = panY.value + (node.y + node.height) * scale.value + 20
    }

    tooltipStyle.value = {
      left: `${left}px`,
      top: `${top}px`,
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
  const tooltipWidth = 240
  let left = event.clientX - rect.left - tooltipWidth / 2
  let top = event.clientY - rect.top - 70

  // Clamp: don't let tooltip go off right edge
  if (left + tooltipWidth > rect.width - 8) {
    left = rect.width - tooltipWidth - 8
  }
  // Clamp: don't let it go off left edge
  if (left < 8) {
    left = 8
  }
  // Flip below cursor if too close to top
  if (top < 8) {
    top = event.clientY - rect.top + 20
  }

  tooltipStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
  }
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
const handleNodeClick = (nodeId: string): void => {
  navigateTo(`/tasks/${nodeId}`)
}

function handleNodeKeydown(e: KeyboardEvent, nodeId: string): void {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    handleNodeClick(nodeId)
  }
}

// ---------------------------------------------------------------------------
// Accessibility
// ---------------------------------------------------------------------------
function getNodeAriaLabel(node: LayoutNode): string {
  const phase = node.phase ? `, phase: ${node.phase}` : ''
  const round = node.round > 0 ? `, round ${node.round}` : ''
  return `${node.fullTitle} (${node.id}), status: ${node.status}${phase}${round}`
}

// ---------------------------------------------------------------------------
// Animation
// ---------------------------------------------------------------------------
function getNodeAnimDelay(node: LayoutNode): string {
  return `${node.layer * 30}ms`
}

// ---------------------------------------------------------------------------
// Adaptive Bezier curve path
// ---------------------------------------------------------------------------
function getEdgePath(edge: LayoutEdge): string {
  const { fromX, fromY, toX, toY } = edge
  const dx = toX - fromX
  const dy = Math.abs(toY - fromY)
  const verticalRatio = dx > 0 ? Math.min(dy / dx, 1) : 0
  const cpOffset = 0.4 + 0.15 * verticalRatio
  const cx1 = fromX + dx * cpOffset
  const cx2 = toX - dx * cpOffset
  return `M ${fromX} ${fromY} C ${cx1} ${fromY}, ${cx2} ${toY}, ${toX} ${toY}`
}

// ---------------------------------------------------------------------------
// Layout computation
// ---------------------------------------------------------------------------
const layout = computed(() => {
  const { nodes, edges, critical_path } = props.graph
  if (!nodes || nodes.length === 0) {
    return {
      nodes: [] as LayoutNode[],
      edges: [] as LayoutEdge[],
      width: 0,
      height: 0,
    }
  }

  const criticalSet = new Set(critical_path || [])

  // Build adjacency
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

  // ------- Layer assignment (BFS) -------
  const layers = new Map<string, number>()
  const queue: string[] = []

  for (const node of nodes) {
    const deps = inDeps.get(node.id) || []
    if (deps.length === 0) {
      layers.set(node.id, 0)
      queue.push(node.id)
    }
  }

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

  // Handle unassigned nodes (cycles/orphans)
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

  // ------- Barycenter ordering with spec group constraints -------
  // Initial: group by spec_ref, sort groups alphabetically within each layer
  for (const [, ids] of layerGroups) {
    // Group by spec_ref
    const specGroups = new Map<string, string[]>()
    for (const id of ids) {
      const spec = nodeMap.get(id)?.spec_ref || ''
      if (!specGroups.has(spec)) specGroups.set(spec, [])
      specGroups.get(spec)!.push(id)
    }
    // Sort within each group alphabetically
    for (const [, group] of specGroups) {
      group.sort((a, b) => a.localeCompare(b))
    }
    // Sort groups alphabetically initially
    const sortedGroups = [...specGroups.entries()].sort((a, b) => a[0].localeCompare(b[0]))
    ids.length = 0
    for (const [, group] of sortedGroups) {
      ids.push(...group)
    }
  }

  // Assign temporary positions for barycenter calc
  const tempPos = new Map<string, number>()
  function assignTempPositions(): void {
    for (const [, ids] of layerGroups) {
      for (let i = 0; i < ids.length; i++) {
        tempPos.set(ids[i], i)
      }
    }
  }
  assignTempPositions()

  // Barycenter sweep (4 iterations forward+backward)
  for (let iter = 0; iter < 4; iter++) {
    // Forward sweep: layers 1..max
    for (let l = 1; l <= maxLayer; l++) {
      const ids = layerGroups.get(l)
      if (!ids) continue
      reorderLayerByBarycenter(ids, l, -1)
      assignTempPositions()
    }
    // Backward sweep: layers max-1..0
    for (let l = maxLayer - 1; l >= 0; l--) {
      const ids = layerGroups.get(l)
      if (!ids) continue
      reorderLayerByBarycenter(ids, l, 1)
      assignTempPositions()
    }
  }

  function reorderLayerByBarycenter(ids: string[], _layer: number, direction: number): void {
    // direction: -1 = use previous layer neighbors, +1 = use next layer neighbors
    const neighborLayer = _layer + direction

    // Group by spec_ref
    const specGroups = new Map<string, string[]>()
    for (const id of ids) {
      const spec = nodeMap.get(id)?.spec_ref || ''
      if (!specGroups.has(spec)) specGroups.set(spec, [])
      specGroups.get(spec)!.push(id)
    }

    // Compute barycenter for each spec group
    const groupBarycenter = new Map<string, number>()
    for (const [spec, group] of specGroups) {
      let sum = 0
      let count = 0
      for (const id of group) {
        const neighbors = direction === -1
          ? (inDeps.get(id) || [])
          : (outDeps.get(id) || [])
        for (const n of neighbors) {
          if (layers.get(n) === neighborLayer) {
            sum += tempPos.get(n) ?? 0
            count++
          }
        }
      }
      groupBarycenter.set(spec, count > 0 ? sum / count : Infinity)
    }

    // Sort groups by barycenter
    const sortedGroups = [...specGroups.entries()].sort((a, b) => {
      const ba = groupBarycenter.get(a[0]) ?? Infinity
      const bb = groupBarycenter.get(b[0]) ?? Infinity
      if (ba !== bb) return ba - bb
      return a[0].localeCompare(b[0])
    })

    // Also reorder nodes within each group by individual barycenter
    for (const [, group] of sortedGroups) {
      group.sort((a, b) => {
        const neighborsA = direction === -1 ? (inDeps.get(a) || []) : (outDeps.get(a) || [])
        const neighborsB = direction === -1 ? (inDeps.get(b) || []) : (outDeps.get(b) || [])
        const bcA = avgPos(neighborsA, neighborLayer)
        const bcB = avgPos(neighborsB, neighborLayer)
        if (bcA !== bcB) return bcA - bcB
        return a.localeCompare(b)
      })
    }

    // Flatten back
    ids.length = 0
    for (const [, group] of sortedGroups) {
      ids.push(...group)
    }
  }

  function avgPos(neighbors: string[], targetLayer: number): number {
    let sum = 0
    let count = 0
    for (const n of neighbors) {
      if (layers.get(n) === targetLayer) {
        sum += tempPos.get(n) ?? 0
        count++
      }
    }
    return count > 0 ? sum / count : Infinity
  }

  // ------- Position nodes with spec group gaps -------
  const positioned = new Map<string, { x: number; y: number; h: number }>()
  let maxY = 0

  for (let l = 0; l <= maxLayer; l++) {
    const ids = layerGroups.get(l) || []
    const x = PADDING + l * (NODE_WIDTH + LAYER_GAP)
    let y = PADDING
    let prevSpec: string | null = null

    for (const id of ids) {
      const node = nodeMap.get(id)
      const spec = node?.spec_ref || ''
      const hasPhase = node?.status === 'in-progress' && node?.phase
      const h = hasPhase ? NODE_HEIGHT_WITH_PHASE : NODE_HEIGHT

      // Add spec group gap + label space
      if (prevSpec !== null && spec !== prevSpec) {
        y += SPEC_GROUP_GAP
      }

      positioned.set(id, { x, y, h })
      y += h + NODE_GAP
      maxY = Math.max(maxY, y)
      prevSpec = spec
    }
  }

  // ------- Build layout nodes -------
  const layoutNodes: LayoutNode[] = nodes.map(n => {
    const pos = positioned.get(n.id) || { x: PADDING, y: PADDING, h: NODE_HEIGHT }
    return {
      id: n.id,
      title: truncateTitle(n.title),
      fullTitle: n.title,
      status: n.status,
      phase: n.phase,
      specRef: n.spec_ref,
      round: n.round,
      x: pos.x,
      y: pos.y,
      height: pos.h,
      isCritical: criticalSet.has(n.id),
      layer: layers.get(n.id) ?? 0,
    }
  })

  // ------- Build critical path edge set -------
  const criticalEdges = new Set<string>()
  const cpList = critical_path || []
  for (let i = 0; i < cpList.length - 1; i++) {
    criticalEdges.add(`${cpList[i]}->${cpList[i + 1]}`)
  }

  // ------- Edge convergence spreading -------
  const nodeStatusMap = new Map(nodes.map(n => [n.id, n.status]))

  // Count incoming and outgoing edges per node
  const incomingEdges = new Map<string, { fromId: string; fromX: number; fromY: number }[]>()
  const outgoingEdges = new Map<string, { toId: string; toX: number; toY: number }[]>()

  for (const e of edges) {
    if (!positioned.has(e.from_id) || !positioned.has(e.to_id)) continue
    const from = positioned.get(e.from_id)!
    const to = positioned.get(e.to_id)!

    if (!incomingEdges.has(e.to_id)) incomingEdges.set(e.to_id, [])
    incomingEdges.get(e.to_id)!.push({
      fromId: e.from_id,
      fromX: from.x + NODE_WIDTH,
      fromY: from.y + from.h / 2,
    })

    if (!outgoingEdges.has(e.from_id)) outgoingEdges.set(e.from_id, [])
    outgoingEdges.get(e.from_id)!.push({
      toId: e.to_id,
      toX: to.x,
      toY: to.y + to.h / 2,
    })
  }

  // Sort incoming edges by source y for consistent spread ordering
  for (const [, inc] of incomingEdges) {
    inc.sort((a, b) => a.fromY - b.fromY)
  }
  for (const [, out] of outgoingEdges) {
    out.sort((a, b) => a.toY - b.toY)
  }

  const layoutEdges: LayoutEdge[] = edges
    .filter(e => positioned.has(e.from_id) && positioned.has(e.to_id))
    .map(e => {
      const from = positioned.get(e.from_id)!
      const to = positioned.get(e.to_id)!

      let fromY = from.y + from.h / 2
      let toY = to.y + to.h / 2

      // Spread outgoing edges from source
      const outList = outgoingEdges.get(e.from_id) || []
      if (outList.length > 1) {
        const idx = outList.findIndex(o => o.toId === e.to_id)
        const offset = (idx - (outList.length - 1) / 2) * EDGE_SPREAD_PX
        fromY += offset
      }

      // Spread incoming edges at target
      const inList = incomingEdges.get(e.to_id) || []
      if (inList.length > 1) {
        const idx = inList.findIndex(o => o.fromId === e.from_id)
        const offset = (idx - (inList.length - 1) / 2) * EDGE_SPREAD_PX
        toY += offset
      }

      return {
        fromX: from.x + NODE_WIDTH,
        fromY,
        toX: to.x,
        toY,
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

// viewBox
const viewBox = computed(() => {
  return `0 0 ${layout.value.width} ${layout.value.height}`
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(() => {
  const el = document.documentElement
  isDark.value = el.classList.contains('dark')
  darkModeObserver = new MutationObserver(() => {
    isDark.value = el.classList.contains('dark')
  })
  darkModeObserver.observe(el, { attributes: true, attributeFilter: ['class'] })

  nextTick(() => fitToView())

  const container = containerRef.value
  if (container) {
    container.addEventListener('touchmove', onTouchMove, { passive: false })
  }
})

onUnmounted(() => {
  darkModeObserver?.disconnect()
  const container = containerRef.value
  if (container) {
    container.removeEventListener('touchmove', onTouchMove)
  }
})
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
    <svg
      :viewBox="viewBox"
      :width="layout.width"
      :height="layout.height"
      class="select-none"
      role="img"
      :aria-label="`Dependency graph showing ${layout.nodes.length} tasks and their relationships`"
    >
      <title>Task Dependency Graph</title>
      <desc>A directed graph showing task dependencies. Nodes represent tasks styled by status. Edges show dependency relationships.</desc>

      <defs>
        <!-- Arrowheads: 6x5px, color-matched -->
        <marker
          id="arrowhead-gray"
          markerWidth="6"
          markerHeight="5"
          refX="6"
          refY="2.5"
          orient="auto"
        >
          <polygon points="0 0, 6 2.5, 0 5" :fill="isDark ? '#374151' : '#d1d5db'" />
        </marker>
        <marker
          id="arrowhead-blue"
          markerWidth="6"
          markerHeight="5"
          refX="6"
          refY="2.5"
          orient="auto"
        >
          <polygon points="0 0, 6 2.5, 0 5" :fill="isDark ? '#60a5fa' : '#3b82f6'" />
        </marker>
        <marker
          id="arrowhead-red"
          markerWidth="6"
          markerHeight="5"
          refX="6"
          refY="2.5"
          orient="auto"
        >
          <polygon points="0 0, 6 2.5, 0 5" :fill="isDark ? '#f87171' : '#ef4444'" />
        </marker>
        <marker
          id="arrowhead-muted"
          markerWidth="6"
          markerHeight="5"
          refX="6"
          refY="2.5"
          orient="auto"
        >
          <polygon points="0 0, 6 2.5, 0 5" :fill="isDark ? '#4b5563' : '#9ca3af'" />
        </marker>

        <!-- Filters -->
        <filter id="hover-glow">
          <feDropShadow dx="0" dy="0" stdDeviation="4" :flood-color="isDark ? '#60a5fa' : '#3b82f6'" flood-opacity="0.3" />
        </filter>
        <filter id="in-progress-glow">
          <feDropShadow
            dx="0" dy="0" stdDeviation="4"
            :flood-color="isDark ? 'rgba(96,165,250,0.2)' : 'rgba(59,130,246,0.15)'"
            :flood-opacity="isDark ? 0.2 : 0.15"
          />
        </filter>
        <filter id="failed-glow">
          <feDropShadow dx="0" dy="0" stdDeviation="3" flood-color="rgba(239,68,68,0.12)" flood-opacity="0.12" />
        </filter>
      </defs>

      <g :transform="`translate(${panX}, ${panY}) scale(${scale})`" class="graph-pan-group">
        <!-- Edges -->
        <path
          v-for="(edge, i) in layout.edges"
          :key="'edge-' + i"
          :d="getEdgePath(edge)"
          fill="none"
          :stroke="getEdgeColor(edge.sourceStatus)"
          :stroke-width="getEdgeStrokeWidth(edge.isCritical)"
          :stroke-dasharray="getEdgeDashArray(edge.sourceStatus, edge.isCritical)"
          :marker-end="
            edge.sourceStatus === 'complete' ? 'url(#arrowhead-gray)' :
            edge.sourceStatus === 'in-progress' ? 'url(#arrowhead-blue)' :
            edge.sourceStatus === 'failed' ? 'url(#arrowhead-red)' :
            'url(#arrowhead-muted)'
          "
          :opacity="getEdgeDimOpacity(edge)"
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
          :style="{
            animationDelay: getNodeAnimDelay(node),
            transform: activeNodeId === node.id
              ? `translate(${node.x + NODE_WIDTH/2}px, ${node.y + node.height/2}px) scale(1.03) translate(${-(node.x + NODE_WIDTH/2)}px, ${-(node.y + node.height/2)}px)`
              : `translate(0,0) scale(1)`,
            transformOrigin: '0 0',
          }"
          :opacity="getNodeDimOpacity(node.id, node.status)"
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
            :height="node.height"
            :rx="8"
            :ry="8"
            :fill="getNodeFill(node.status)"
            :stroke="getNodeStroke(node.status)"
            :stroke-width="activeNodeId === node.id ? 3 : getNodeStrokeWidth(node.status)"
            :stroke-dasharray="getNodeStrokeDash(node.status)"
            :filter="getNodeFilter(node.status, activeNodeId === node.id)"
            class="graph-node-rect"
            :class="{
              'animate-badge-pulse-urgent': node.status === 'in-progress' && node.round >= 2,
              'animate-badge-pulse': node.status === 'in-progress' && node.round < 2,
            }"
          />

          <!-- Title: 13px, font-weight 600, centered, clipped to node bounds -->
          <text
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 20"
            font-size="13"
            font-weight="600"
            text-anchor="middle"
            :fill="getTitleFill(node.status)"
            :textLength="node.title.length > 24 ? NODE_WIDTH - 16 : undefined"
            :lengthAdjust="node.title.length > 24 ? 'spacing' : undefined"
          >
            {{ node.title }}
          </text>

          <!-- ID: 10px, monospace, muted, centered -->
          <text
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 38"
            font-size="10"
            font-family="ui-monospace, monospace"
            text-anchor="middle"
            :fill="getIdFill(node.status)"
          >
            {{ node.id }}
          </text>

          <!-- Round indicator badge (top-right corner, only when round > 0) -->
          <g v-if="node.round > 0">
            <rect
              :x="node.x + NODE_WIDTH - 52"
              :y="node.y + 4"
              width="48"
              height="14"
              rx="7"
              :fill="isDark ? 'rgba(251,191,36,0.15)' : 'rgba(245,158,11,0.1)'"
              :stroke="isDark ? '#fbbf24' : '#f59e0b'"
              stroke-width="0.5"
            />
            <text
              :x="node.x + NODE_WIDTH - 28"
              :y="node.y + 14"
              font-size="8"
              font-weight="600"
              text-anchor="middle"
              :fill="isDark ? '#fbbf24' : '#d97706'"
            >
              Round {{ node.round }}
            </text>
          </g>

          <!-- Mini pipeline bar (in-progress nodes with pipeline steps) -->
          <template v-if="node.status === 'in-progress' && pipelineSteps && pipelineSteps.length > 0">
            <g :transform="`translate(${node.x + 12}, ${node.y + 46})`">
              <template v-for="(step, si) in pipelineSteps" :key="'step-' + si">
                <!-- Step segment with hover tooltip and fill transition -->
                <rect
                  :x="si * ((NODE_WIDTH - 24) / pipelineSteps.length)"
                  y="0"
                  :width="(NODE_WIDTH - 24) / pipelineSteps.length - 2"
                  height="4"
                  :rx="2"
                  :fill="getMiniBarFill(step.name, node.phase, si)"
                  class="pipeline-bar-segment"
                  @mouseenter.stop="barTooltip = { text: step.name, x: $event.clientX, y: $event.clientY }"
                  @mouseleave.stop="barTooltip = null"
                />
                <!-- Step label (only for active step) -->
                <text
                  v-if="step.name === node.phase"
                  :x="si * ((NODE_WIDTH - 24) / pipelineSteps.length) + ((NODE_WIDTH - 24) / pipelineSteps.length - 2) / 2"
                  y="14"
                  font-size="8"
                  text-anchor="middle"
                  :fill="isDark ? '#60a5fa' : '#3b82f6'"
                  font-weight="600"
                >
                  {{ step.name }}
                </text>
              </template>
            </g>
          </template>
          <!-- Fallback: simple phase text if no pipeline steps provided -->
          <text
            v-else-if="node.status === 'in-progress' && node.phase"
            :x="node.x + NODE_WIDTH / 2"
            :y="node.y + 55"
            font-size="10"
            font-style="italic"
            text-anchor="middle"
            :fill="isDark ? '#60a5fa' : '#3b82f6'"
          >
            {{ node.phase }}
          </text>
        </g>
      </g>
    </svg>

    <!-- Tooltip -->
    <div
      v-if="tooltipNode"
      class="absolute z-20 pointer-events-none px-3 py-2 rounded-lg text-xs shadow-lg"
      :class="isDark ? 'bg-gray-800 text-gray-100' : 'bg-gray-900 text-white'"
      :style="{ left: tooltipStyle.left, top: tooltipStyle.top, width: '240px' }"
    >
      <p class="font-medium leading-snug">{{ tooltipNode.fullTitle }}</p>
      <p class="text-gray-400 mt-0.5">
        {{ tooltipNode.id }} &middot; {{ tooltipNode.status }}{{ tooltipNode.phase ? ' / ' + tooltipNode.phase : '' }}{{ tooltipNode.round > 0 ? ' (R' + tooltipNode.round + ')' : '' }}
      </p>
    </div>

    <!-- Pipeline bar segment tooltip -->
    <div
      v-if="barTooltip"
      class="absolute z-30 pointer-events-none px-2 py-1 rounded text-[10px] font-medium shadow-md"
      :class="isDark ? 'bg-gray-800 text-gray-200' : 'bg-gray-900 text-white'"
      :style="{ left: barTooltipStyle.left, top: barTooltipStyle.top }"
    >
      {{ barTooltip.text }}
    </div>

    <!-- Zoom controls: glassmorphism icon buttons, stacked vertically -->
    <div class="absolute bottom-3 right-3 flex flex-col gap-1">
      <button
        class="h-8 w-8 flex items-center justify-center rounded-lg bg-white/85 dark:bg-[#111116]/85 backdrop-blur-sm shadow-sm text-gray-600 dark:text-gray-300 hover:bg-white dark:hover:bg-[#111116] transition-colors duration-150"
        aria-label="Zoom in"
        @click="zoomIn"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="7" y1="2" x2="7" y2="12" />
          <line x1="2" y1="7" x2="12" y2="7" />
        </svg>
      </button>
      <button
        class="h-8 w-8 flex items-center justify-center rounded-lg bg-white/85 dark:bg-[#111116]/85 backdrop-blur-sm shadow-sm text-gray-600 dark:text-gray-300 hover:bg-white dark:hover:bg-[#111116] transition-colors duration-150"
        aria-label="Zoom out"
        @click="zoomOut"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
          <line x1="2" y1="7" x2="12" y2="7" />
        </svg>
      </button>
      <button
        class="h-8 w-8 flex items-center justify-center rounded-lg bg-white/85 dark:bg-[#111116]/85 backdrop-blur-sm shadow-sm text-gray-600 dark:text-gray-300 hover:bg-white dark:hover:bg-[#111116] transition-colors duration-150"
        aria-label="Fit graph to view"
        @click="resetView"
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="1,5 1,1 5,1" />
          <polyline points="9,1 13,1 13,5" />
          <polyline points="13,9 13,13 9,13" />
          <polyline points="5,13 1,13 1,9" />
        </svg>
      </button>
    </div>
  </div>

  <!-- Visually-hidden data table for screen readers -->
  <table v-if="layout.nodes.length > 0" class="sr-only" aria-label="Task dependency data">
    <caption>Task dependency graph data with status and relationships</caption>
    <thead>
      <tr>
        <th scope="col">Task ID</th>
        <th scope="col">Title</th>
        <th scope="col">Status</th>
        <th scope="col">Phase</th>
        <th scope="col">Round</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="node in layout.nodes" :key="'table-' + node.id">
        <td>{{ node.id }}</td>
        <td>{{ node.fullTitle }}</td>
        <td>{{ node.status }}</td>
        <td>{{ node.phase ?? '--' }}</td>
        <td>{{ node.round }}</td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.graph-node {
  transition: transform 200ms ease, opacity 150ms ease;
}
.graph-node-rect {
  transition: filter 150ms ease, stroke-width 150ms ease;
}
.graph-pan-group {
  transition: transform 0ms;
}

/* Node entrance animation */
.graph-node {
  animation: node-enter 300ms ease both;
  cursor: pointer;
  outline: none;
}
.graph-node:focus-visible rect {
  stroke-width: 3;
  filter: url(#hover-glow);
}

/* Pipeline bar segment fill transition */
.pipeline-bar-segment {
  transition: fill 500ms ease;
  cursor: default;
}

/* Critical path marching ants */
.critical-edge {
  animation: edge-flow 1s linear infinite;
}

/* Respect prefers-reduced-motion */
@media (prefers-reduced-motion: reduce) {
  .pipeline-bar-segment {
    transition: none;
  }
  .graph-node {
    animation: none;
    transition: none;
  }
  .graph-node-rect {
    transition: none;
  }
  .critical-edge {
    animation: none;
  }
}

/* Screen-reader only utility */
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
