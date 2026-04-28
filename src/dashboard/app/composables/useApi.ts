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
  FleetResponse,
} from '~/types'

const API_BASE = '/api'

export function useApi() {
  const fetchSpecs = (params?: { repo?: string }) =>
    $fetch<SpecSummary[]>(`${API_BASE}/specs`, { params })

  const fetchSpec = (specRef: string, params?: { repo?: string }) =>
    $fetch<SpecDetail>(`${API_BASE}/specs/${specRef}`, { params })

  const fetchSpecDrift = (specRef: string, params?: { repo?: string }) =>
    $fetch<SpecDriftDetail>(`${API_BASE}/specs/${specRef}/drift`, { params })

  const fetchSpecSummaryRecord = (specRef: string, params?: { repo?: string }) =>
    $fetch<SpecSummaryRecord>(`${API_BASE}/specs/${specRef}/summary`, { params })

  const fetchTasks = (params?: { status?: string; spec_ref?: string; repo?: string }) =>
    $fetch<TaskSummary[]>(`${API_BASE}/tasks`, { params })

  const fetchTask = (taskId: string, params?: { repo?: string }) =>
    $fetch<TaskDetail>(`${API_BASE}/tasks/${taskId}`, { params })

  const fetchSummary = (params?: { repo?: string }) =>
    $fetch<Summary>(`${API_BASE}/summary`, { params })

  const fetchPipeline = (params?: { repo?: string }) =>
    $fetch<PipelineStepInfo[]>(`${API_BASE}/pipeline`, { params })

  const fetchTaskPrompt = (taskId: string, params?: { repo?: string }) =>
    $fetch<ReconstructedPrompt[]>(`${API_BASE}/tasks/${taskId}/prompt`, { params })

  const fetchGraph = (params?: { repo?: string }) =>
    $fetch<GraphData>(`${API_BASE}/tasks/graph`, { params })

  const fetchProcess = (params?: { repo?: string }) =>
    $fetch<ProcessData>(`${API_BASE}/process`, { params })

  const fetchHealth = (params?: { repo?: string }) =>
    $fetch<HealthData>(`${API_BASE}/health`, { params })

  const fetchAgents = (params?: { repo?: string }) =>
    $fetch<AgentDefinition[]>(`${API_BASE}/agents`, { params })

  const fetchChecks = (params?: { repo?: string }) =>
    $fetch<CheckScript[]>(`${API_BASE}/agents/checks`, { params })

  const fetchActivity = (params?: { since_cycle?: number; limit?: number; repo?: string }) =>
    $fetch<ActivityResponse>(`${API_BASE}/activity`, { params })

  const fetchWorkerHeartbeats = (params?: { since?: string; repo?: string }) =>
    $fetch<HeartbeatResponse>(`${API_BASE}/activity/worker-heartbeats`, { params })

  const restartTask = (taskId: string, body: ControlRequest, params?: { repo?: string }) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/restart`, {
      method: 'POST',
      body,
      params,
    })

  const retireTask = (taskId: string, body: ControlRequest, params?: { repo?: string }) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/retire`, {
      method: 'POST',
      body,
      params,
    })

  const forceClearTask = (taskId: string, body: ControlRequest, params?: { repo?: string }) =>
    $fetch<ControlResponse>(`${API_BASE}/tasks/${taskId}/force-clear`, {
      method: 'POST',
      body,
      params,
    })

  const fetchKpi = (params?: { repo?: string }) =>
    $fetch<KpiResponse>(`${API_BASE}/metrics/kpi`, { params })

  const fetchBurndown = (params?: { repo?: string }) =>
    $fetch<BurndownResponse>(`${API_BASE}/metrics/burndown`, { params })

  const fetchVelocity = (params?: { repo?: string }) =>
    $fetch<VelocityResponse>(`${API_BASE}/metrics/velocity`, { params })

  const fetchRoundEfficiency = (params?: { repo?: string }) =>
    $fetch<RoundEfficiencyResponse>(`${API_BASE}/metrics/round-efficiency`, { params })

  const fetchPhaseFunnel = (params?: { repo?: string }) =>
    $fetch<PhaseFunnelResponse>(`${API_BASE}/metrics/phase-funnel`, { params })

  const fetchFleet = () =>
    $fetch<FleetResponse>(`${API_BASE}/fleet`)

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
    fetchFleet,
  }
}
