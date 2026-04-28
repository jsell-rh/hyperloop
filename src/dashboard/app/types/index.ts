export type SpecStage =
  | 'written'
  | 'in-progress'
  | 'pending-audit'
  | 'converged'
  | 'freshness-drift'
  | 'alignment-gap'
  | 'failed'
  | 'baselined'

export type SyncStatus = 'synced' | 'syncing' | 'drifted'

export type DriftType = 'coverage' | 'freshness' | 'alignment' | null

export interface SpecSummary {
  spec_ref: string
  title: string
  tasks_total: number
  tasks_complete: number
  tasks_in_progress: number
  tasks_failed: number
  tasks_not_started: number
  drift_type: DriftType
  drift_detail: string
  stage: SpecStage
  last_audit_result: 'aligned' | 'misaligned' | null
  current_sha: string | null
  pinned_sha: string | null
}

export interface SpecDetail {
  spec_ref: string
  content: string
  tasks: TaskSummary[]
}

export type TaskStatusValue = 'not-started' | 'in-progress' | 'completed' | 'failed'

export interface TaskSummary {
  id: string
  title: string
  status: TaskStatusValue
  phase: string | null
  round: number
  branch: string | null
  pr: string | null
  spec_ref: string
  pr_title: string | null
  pr_description: string | null
}

export interface DepDetail {
  id: string
  title: string
  status: TaskStatusValue
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
  status: TaskStatusValue
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
// Process types — flat phase map
// ---------------------------------------------------------------------------

export interface PhaseDefinition {
  run: string
  on_pass: string
  on_fail: string
  on_wait?: string
}

export interface ProcessLearning {
  patched_agents: string[]
  guidelines: Record<string, string>
}

export interface ProcessData {
  phases: Record<string, PhaseDefinition>
  phase_order: string[]
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

export interface AuditDetail {
  spec_ref: string
  result: string
  duration_s: number
}

export interface ReconcileDetail {
  drift_count: number
  audits: AuditDetail[]
  gc_pruned: number
  reconcile_duration_s: number | null
  intake_ran: boolean
  intake_created_tasks: number | null
  intake_duration_s: number | null
  process_improver_ran: boolean
  process_improver_duration_s: number | null
}

export interface AuditEntry {
  spec_ref: string
  result: string
  started_at: string
  duration_s: number
}

export interface AuditTimeline {
  entries: AuditEntry[]
  total_duration_s: number
  max_parallelism: number
}

export interface CyclePhaseTiming {
  collect_s: number | null
  reconcile_s: number | null
  advance_s: number | null
  spawn_s: number | null
}

export interface CycleDetail {
  cycle: number
  timestamp: string
  duration_s: number | null
  phases: CyclePhases
  reconcile: ReconcileDetail | null
  audit_timeline: AuditTimeline | null
  phase_timing: CyclePhaseTiming | null
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

// ---------------------------------------------------------------------------
// Control operation types
// ---------------------------------------------------------------------------

export interface ControlRequest {
  expected_round: number
}

export interface ControlResponse {
  status: string
}

// ---------------------------------------------------------------------------
// Drift detail types (from /api/specs/{ref}/drift)
// ---------------------------------------------------------------------------

export interface SpecDriftDetail {
  drift_type: DriftType
  old_sha: string | null
  new_sha: string | null
  old_content: string | null
  new_content: string | null
  finding: string | null
}

// ---------------------------------------------------------------------------
// Spec summary record types
// ---------------------------------------------------------------------------

export interface SpecSummaryRecord {
  total_tasks: number
  completed: number
  failed: number
  failure_themes: string[]
  last_audit_result: string | null
  last_audit_at: string | null
  baselined: boolean
}

// ---------------------------------------------------------------------------
// KPI / Visualization types
// ---------------------------------------------------------------------------

export interface SparklinePoint {
  cycle: number
  value: number
}

export interface KpiCard {
  label: string
  value: number
  unit: string
  sparkline: SparklinePoint[]
  trend: 'up' | 'down' | 'flat'
  trend_is_good: boolean
}

export interface KpiResponse {
  cards: KpiCard[]
}

export interface BurndownPoint {
  cycle: number
  timestamp: string
  burnup: number
  burndown: number
  scope_change: boolean
}

export interface BurndownResponse {
  points: BurndownPoint[]
}

export interface VelocityPoint {
  cycle: number
  timestamp: string
  tasks_per_hour: number
  completed_count: number
}

export interface VelocityResponse {
  points: VelocityPoint[]
}

export interface RoundEfficiencyPoint {
  window_start: number
  window_end: number
  avg_rounds: number
  sample_count: number
}

export interface RoundDistributionBucket {
  rounds: string
  count: number
}

export interface RoundEfficiencyResponse {
  trend: RoundEfficiencyPoint[]
  distribution: RoundDistributionBucket[]
}

export interface PhaseFunnelEntry {
  phase: string
  avg_duration_s: number
  total_executions: number
  first_pass_success_rate: number
}

export interface PhaseFunnelResponse {
  phases: PhaseFunnelEntry[]
}

// ---------------------------------------------------------------------------
// Fleet types
// ---------------------------------------------------------------------------

export interface InstanceSummary {
  repo_hash: string
  repo_name: string
  repo_path: string
  status: 'running' | 'idle' | 'stale' | 'empty'
  last_event_at: string | null
  current_cycle: number
  active_workers: number
  specs_converged: number
  specs_total: number
  drift_remaining: number
  rounds_completed: number
  verify_pass_rate: number
}

export interface FleetResponse {
  instances: InstanceSummary[]
}
