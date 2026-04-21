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
