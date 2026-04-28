import type {
  SpecSummary,
  SpecDetail,
  SpecDriftDetail,
  SpecSummaryRecord,
  TaskSummary,
  TaskDetail,
  Summary,
  PipelineStepInfo,
  ReconstructedPrompt,
  GraphData,
  ProcessData,
  HealthData,
  AgentDefinition,
  CheckScript,
  ActivityResponse,
  HeartbeatResponse,
  ControlRequest,
  ControlResponse,
  KpiResponse,
  BurndownResponse,
  VelocityResponse,
  RoundEfficiencyResponse,
  PhaseFunnelResponse,
} from '~/types'

const API_BASE = '/api'

export function useApi() {
  const fetchSpecs = () =>
    $fetch<SpecSummary[]>(`${API_BASE}/specs`)

  const fetchSpec = (specRef: string) =>
    $fetch<SpecDetail>(`${API_BASE}/specs/${specRef}`)

  const fetchSpecDrift = (specRef: string) =>
    $fetch<SpecDriftDetail>(`${API_BASE}/specs/${specRef}/drift`)

  const fetchSpecSummaryRecord = (specRef: string) =>
    $fetch<SpecSummaryRecord>(`${API_BASE}/specs/${specRef}/summary`)

  const fetchTasks = (params?: { status?: string; spec_ref?: string }) =>
    $fetch<TaskSummary[]>(`${API_BASE}/tasks`, { params })

  const fetchTask = (taskId: string) =>
    $fetch<TaskDetail>(`${API_BASE}/tasks/${taskId}`)

  const fetchSummary = () =>
    $fetch<Summary>(`${API_BASE}/summary`)

  const fetchPipeline = () =>
    $fetch<PipelineStepInfo[]>(`${API_BASE}/pipeline`)

  const fetchTaskPrompt = (taskId: string) =>
    $fetch<ReconstructedPrompt[]>(`${API_BASE}/tasks/${taskId}/prompt`)

  const fetchGraph = () =>
    $fetch<GraphData>(`${API_BASE}/tasks/graph`)

  const fetchProcess = () =>
    $fetch<ProcessData>(`${API_BASE}/process`)

  const fetchHealth = () =>
    $fetch<HealthData>(`${API_BASE}/health`)

  const fetchAgents = () =>
    $fetch<AgentDefinition[]>(`${API_BASE}/agents`)

  const fetchChecks = () =>
    $fetch<CheckScript[]>(`${API_BASE}/agents/checks`)

  const fetchActivity = (params?: { since_cycle?: number; limit?: number }) =>
    $fetch<ActivityResponse>(`${API_BASE}/activity`, { params })

  const fetchWorkerHeartbeats = (params?: { since?: string }) =>
    $fetch<HeartbeatResponse>(`${API_BASE}/activity/worker-heartbeats`, { params })

  const restartTask = (taskId: string, body: ControlRequest) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/restart`, {
      method: 'POST',
      body,
    })

  const retireTask = (taskId: string, body: ControlRequest) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/retire`, {
      method: 'POST',
      body,
    })

  const forceClearTask = (taskId: string, body: ControlRequest) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/force-clear`, {
      method: 'POST',
      body,
    })

  const fetchKpi = () =>
    $fetch<KpiResponse>(`${API_BASE}/metrics/kpi`)

  const fetchBurndown = () =>
    $fetch<BurndownResponse>(`${API_BASE}/metrics/burndown`)

  const fetchVelocity = () =>
    $fetch<VelocityResponse>(`${API_BASE}/metrics/velocity`)

  const fetchRoundEfficiency = () =>
    $fetch<RoundEfficiencyResponse>(`${API_BASE}/metrics/round-efficiency`)

  const fetchPhaseFunnel = () =>
    $fetch<PhaseFunnelResponse>(`${API_BASE}/metrics/phase-funnel`)

  return {
    fetchSpecs,
    fetchSpec,
    fetchSpecDrift,
    fetchSpecSummaryRecord,
    fetchTasks,
    fetchTask,
    fetchSummary,
    fetchPipeline,
    fetchTaskPrompt,
    fetchGraph,
    fetchProcess,
    fetchHealth,
    fetchAgents,
    fetchChecks,
    fetchActivity,
    fetchWorkerHeartbeats,
    restartTask,
    retireTask,
    forceClearTask,
    fetchKpi,
    fetchBurndown,
    fetchVelocity,
    fetchRoundEfficiency,
    fetchPhaseFunnel,
  }
}
