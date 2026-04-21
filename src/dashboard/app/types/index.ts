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
