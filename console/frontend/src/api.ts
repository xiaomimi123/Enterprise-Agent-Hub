// 后端接口与类型定义。所有请求走 /api，开发时由 Vite 代理到 FastAPI。

export interface Stats {
  members: number
  agents_online: number
  agents_installed: number
  calls_today: number
  tasks_today: number
  tokens_today: number
  cost_today: number
  cost_month: number
  budget_month: number
  denied_today: number
  pending_approvals: number
  role_packs_live: number
  role_packs_total: number
  skills: number
  knowledge_docs: number
}

export interface GpuNode {
  id: string
  name: string
  gpu: string
  workflows: string[]
  status: string
  queue: number
  jobs_today: number
  utilization: number
  online: boolean
}

export interface TraceBrief {
  id: string
  member: string
  member_id?: string
  dept?: string
  dept_name: string
  summary: string
  started_at: string
  outcome?: string
  channel: string
  tokens?: number
  cost?: number
  step_count?: number
}

export interface Overview {
  company: string
  mode: string
  stats: Stats
  trend: { date: string; tokens: number; cost: number }[]
  daily_ops: { date: string; online: number; denied: number }[]
  services: { name: string; component: string; status: string; latency_ms: number }[]
  cost_by_dept: { dept: string; cost: number }[]
  gpu_nodes: GpuNode[]
  pending: { trace_id: string; member: string; dept_name: string; tool: string; detail: string; time: string }[]
  recent_denied: TraceBrief[]
  recent: TraceBrief[]
}

export interface Department {
  id: string
  name: string
  member_count: number
  leader: string
  online: number
  role_pack: string
  role_pack_name: string
}

export interface Member {
  id: string
  name: string
  dept: string
  dept_name: string
  title: string
  role_pack: string
  role_pack_name: string
  agent_status: string
  agent_version: string
  os: string
  dingtalk_bound: boolean
  last_active: string
}

export interface RolePack {
  id: string
  name: string
  dept: string
  dept_name: string
  status: string
  description: string
  skills: string[]
  knowledge_bases: string[]
  tools: string[]
  models: string[]
  monthly_quota: number
  max_action_level: string
  external_access: string
  member_count: number
  members?: Member[]
}

export interface Tool {
  id: string
  name: string
  category: string
  risk: string
  description: string
}

export interface Model {
  id: string
  name: string
  location: string
  rate: number
}

export interface Catalog {
  skills: { id: string; name: string; dept_name: string; status: string }[]
  knowledge_bases: { id: string; name: string; dept_name: string; classification: string }[]
  tools: Tool[]
  models: Model[]
}

export interface Skill {
  id: string
  name: string
  dept: string
  dept_name: string
  status: string
  description: string
  author: string
  version: string
  used_7d: number
  updated_at: string
  source: string
  role_packs: string[]
  content?: string
}

export interface KnowledgeBase {
  id: string
  name: string
  dept: string
  dept_name: string
  classification: string
  source: string
  external_access: boolean
  doc_count: number
  chunk_count: number
  queries_7d: number
  updated_at: string
  role_packs: string[]
}

export interface KbDocument {
  id: string
  title: string
  type: string
  chunks: number
  status: string
  updated_at: string
}

export interface TraceStep {
  time: string
  kind: string
  tool: string
  detail: string
  result: string
  tokens: number
  model: string | null
  cost: number
}

export interface Trace extends TraceBrief {
  steps: TraceStep[]
}

export interface Usage {
  days: number
  total_tokens: number
  total_cost: number
  local_ratio: number
  departments: string[]
  daily: Record<string, number | string>[]
  by_dept: { dept: string; tokens: number; cost: number; quota: number }[]
  by_model: { model: string; location: string; tokens: number; cost: number }[]
  top_members: { member_id: string; member: string; dept_name: string; tokens: number; cost: number; calls: number }[]
}

export interface AuthUser {
  name: string
  display_name: string
  org: string
  title: string
  avatar?: string
  is_admin: boolean
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body.detail ?? `请求失败（${res.status}）`)
  }
  return res.json() as Promise<T>
}

function qs(params: Record<string, string | undefined>) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v && p.set(k, v))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export interface GpuTask {
  id: string
  trace_id: string
  member: string
  member_id: string
  dept: string
  channel: string
  kind: 'image' | 'video'
  workflow: string
  title: string
  prompt: string
  size: string
  count: number
  status: string
  node_id: string | null
  ahead: number | null
  created_at: string
  wait_seconds: number | null
  run_seconds: number | null
  error: string
  files: { type: 'image' | 'video'; url: string }[]
}

export interface GpuTasks {
  summary: { queued: number; running: number; failed: number; done_today: number }
  tasks: GpuTask[]
}

export const api = {
  me: () => request<{ mode: string; user: AuthUser }>('/auth/me'),
  loginUrl: () => request<{ url: string }>('/auth/login'),
  authCallback: (code: string, state: string) =>
    request<{ user: AuthUser }>('/auth/callback', { method: 'POST', body: JSON.stringify({ code, state }) }),
  logout: () => request<{ ok: boolean; casdoor_logout_url: string | null }>('/auth/logout', { method: 'POST' }),
  overview: () => request<Overview>('/overview'),
  departments: () => request<Department[]>('/departments'),
  members: (params: { dept?: string; q?: string } = {}) => request<Member[]>(`/members${qs(params)}`),
  assignRolePack: (memberId: string, rolePackId: string) =>
    request<Member>(`/members/${memberId}/role-pack`, { method: 'PUT', body: JSON.stringify({ role_pack_id: rolePackId }) }),
  rolePacks: () => request<RolePack[]>('/role-packs'),
  rolePack: (id: string) => request<RolePack>(`/role-packs/${id}`),
  updateRolePack: (id: string, patch: Partial<RolePack>) =>
    request<RolePack>(`/role-packs/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  catalog: () => request<Catalog>('/catalog'),
  skills: () => request<Skill[]>('/skills'),
  skill: (id: string) => request<Skill>(`/skills/${id}`),
  knowledgeBases: () => request<KnowledgeBase[]>('/knowledge-bases'),
  kbDocuments: (id: string) => request<KbDocument[]>(`/knowledge-bases/${id}/documents`),
  traces: (params: { member_id?: string; outcome?: string; dept?: string; q?: string } = {}) =>
    request<TraceBrief[]>(`/audit/traces${qs(params)}`),
  trace: (id: string) => request<Trace>(`/audit/traces/${id}`),
  gpuTasks: () => request<GpuTasks>('/gpu/tasks'),
  usage: (days = 30) => request<Usage>(`/usage?days=${days}`),
}
