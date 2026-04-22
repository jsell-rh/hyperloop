export interface SpecSummary {
  spec_ref: string
  title: string
  tasks_total: number
  tasks_complete: number
  tasks_in_progress: number
  tasks_failed: number
  tasks_not_started: number
}

export interface SpecDetail {
  spec_ref: string
  content: string
  tasks: TaskSummary[]
}

export interface TaskSummary {
  id: string
  title: string
  status: 'not-started' | 'in-progress' | 'complete' | 'failed'
  phase: string | null
  round: number
  branch: string | null
  pr: string | null
  spec_ref: string
}

export interface DepDetail {
  id: string
  title: string
  status: 'not-started' | 'in-progress' | 'complete' | 'failed'
}

export interface TaskDetail extends TaskSummary {
  deps: string[]
  deps_detail: DepDetail[]
  reviews: Review[]
}

export interface Review {
  round: number
  role: string
  verdict: string
  detail: string
}

export interface PromptEntry {
  round: number
  role: string
  sections: PromptSection[]
}

export interface PromptSection {
  source: string
  label: string
  content: string
}

export interface PipelineStepInfo {
  name: string
  type: string
  in_loop: boolean
}

export interface ReconstructedPrompt {
  role: string
  sections: PromptSection[]
}

export interface Summary {
  total: number
  not_started: number
  in_progress: number
  complete: number
  failed: number
  specs_total: number
  specs_complete: number
}

// ---------------------------------------------------------------------------
// Graph types
// ---------------------------------------------------------------------------

export interface GraphNode {
  id: string
  title: string
  status: 'not-started' | 'in-progress' | 'complete' | 'failed'
  phase: string | null
  spec_ref: string
  round: number
}

export interface GraphEdge {
  from_id: string
  to_id: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
  critical_path: string[]
}

// ---------------------------------------------------------------------------
// Process types
// ---------------------------------------------------------------------------

export interface PipelineTreeStep {
  type: string
  name: string | null
  children: PipelineTreeStep[] | null
}

export interface ProcessLearning {
  patched_agents: string[]
  guidelines: Record<string, string>
}

export interface ProcessData {
  pipeline_steps: PipelineTreeStep[]
  pipeline_raw: string
  gates: Record<string, unknown>
  actions: Record<string, unknown>
  hooks: Record<string, unknown>
  process_learning: ProcessLearning
  source_file: string
  base_ref: string | null
}

// ---------------------------------------------------------------------------
// Health types
// ---------------------------------------------------------------------------

export interface HealthData {
  status: string
  repo_path: string
  state_store: string
  spec_source: string
}

// ---------------------------------------------------------------------------
// Activity types
// ---------------------------------------------------------------------------

export interface ActiveWorker {
  task_id: string
  role: string
  started_at: string
  duration_s: number
}

export interface ReapedWorker {
  task_id: string
  role: string
  verdict: string
  duration_s: number
}

export interface CollectPhase {
  reaped: ReapedWorker[]
}

export interface IntakePhase {
  ran: boolean
  created_tasks: number | null
}

export interface PhaseTransition {
  task_id: string
  from_phase: string | null
  to_phase: string | null
}

export interface AdvancePhase {
  transitions: PhaseTransition[]
}

export interface SpawnedWorker {
  task_id: string
  role: string
}

export interface SpawnPhase {
  spawned: SpawnedWorker[]
}

export interface CyclePhases {
  collect: CollectPhase
  intake: IntakePhase
  advance: AdvancePhase
  spawn: SpawnPhase
}

export interface CycleDetail {
  cycle: number
  timestamp: string
  duration_s: number | null
  phases: CyclePhases
}

export interface WorkerHistoryEntry {
  role: string
  round: number
  started_at: string
  duration_s: number
  verdict: string | null
}

export interface TaskInFlight {
  task_id: string
  title: string
  status: string
  phase: string | null
  round: number
  spec_ref: string
  current_worker: ActiveWorker | null
  worker_history: WorkerHistoryEntry[]
}

export interface FlatEvent {
  timestamp: string
  cycle: number
  event_type: string
  task_id: string | null
  detail: string
  verdict: string | null
  duration_s: number | null
}

export interface ActivityResponse {
  current_cycle: number
  orchestrator_status: string
  active_workers: ActiveWorker[]
  cycles: CycleDetail[]
  enabled: boolean
  tasks_in_flight: TaskInFlight[]
  flattened_events: FlatEvent[]
}

// ---------------------------------------------------------------------------
// Worker heartbeat types
// ---------------------------------------------------------------------------

export interface WorkerHeartbeat {
  task_id: string
  role: string
  last_message_at: string
  last_message_type: string
  last_tool_name: string | null
  message_count_since: number
  seconds_since_last: number
}

export interface HeartbeatResponse {
  heartbeats: WorkerHeartbeat[]
  server_time: string
}

// ---------------------------------------------------------------------------
// Agents types
// ---------------------------------------------------------------------------

export interface AgentDefinition {
  name: string
  prompt: string
  guidelines: string
  has_process_patches: boolean
  process_overlay_guidelines: string | null
  process_overlay_file: string | null
}

export interface CheckScript {
  name: string
  path: string
  content: string
}
