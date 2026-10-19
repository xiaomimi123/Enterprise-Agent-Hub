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
  model_mode: '中枢模型' | '自带模型'
  gpu_quota_minutes: number
  apps: string[]
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
  apps: { id: string; name: string; version: string }[]
}

export interface PublishedApp {
  id: string
  name: string
  version: string
  description: string
  sha256: string
  size: number
  requires: Record<string, string>
  allowed_packs: { id: string; name: string }[]
  opens_7d: number
  last_open: string | null
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

export interface HubMemberUsage {
  member_id: string
  member: string
  dept_name: string
  role_pack: string
  model_mode: string
  tool_calls: number
  images: number
  videos: number
  gpu_minutes: number
  gpu_quota_minutes: number
}

export interface HubUsage {
  totals: { tool_calls: number; images: number; videos: number; gpu_minutes: number }
  by_member: HubMemberUsage[]
  by_dept: { dept: string; tool_calls: number; gpu_minutes: number }[]
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
  hub: HubUsage
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
  via: string
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

export interface ConnectInfo {
  hub_url: string
  mcp_url: string
  api_base: string
  script_url: string
}

export interface Upstream {
  id: number
  name: string
  base_url: string
  models: string[]
  status: 'enabled' | 'disabled'
  key_hint: string
}

export interface ImageProvider {
  id: string
  name: string
  kind: string
  base_url: string
  model: string
  params: Record<string, unknown>
  enabled: boolean
  key_hint: string
}

export interface H3Gateway {
  base_url: string
  enabled: boolean
  verify_tls: boolean
  key_hint: string
}

export interface ImageConfig {
  route: 'gpu' | 'api' | 'h3'
  providers: ImageProvider[]
  video_route: 'gpu' | 'h3'
  h3: H3Gateway | null
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
  apps: () => request<PublishedApp[]>('/apps'),
  upstreams: () => request<Upstream[]>('/models/upstreams'),
  probeUpstream: (body: { base_url: string; key: string }) =>
    request<{ models: string[] }>('/models/upstreams/probe', { method: 'POST', body: JSON.stringify(body) }),
  addUpstream: (body: { name: string; base_url: string; key: string; models: string[] }) =>
    request<Upstream>('/models/upstreams', { method: 'POST', body: JSON.stringify(body) }),
  patchUpstream: (id: number, body: Partial<{ name: string; base_url: string; key: string; models: string[]; enabled: boolean }>) =>
    request<Upstream>(`/models/upstreams/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteUpstream: (id: number) => request<{ ok: boolean }>(`/models/upstreams/${id}`, { method: 'DELETE' }),
  imageConfig: () => request<ImageConfig>('/models/image'),
  addImageProvider: (body: { name: string; base_url: string; model: string; key: string; params?: Record<string, unknown> }) =>
    request<ImageProvider>('/models/image/providers', { method: 'POST', body: JSON.stringify(body) }),
  patchImageProvider: (id: string, body: Partial<{ name: string; base_url: string; model: string; key: string; params: Record<string, unknown>; enabled: boolean }>) =>
    request<ImageProvider>(`/models/image/providers/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteImageProvider: (id: string) => request<{ ok: boolean }>(`/models/image/providers/${id}`, { method: 'DELETE' }),
  setImageRoute: (route: 'gpu' | 'api' | 'h3') =>
    request<{ route: string }>('/models/image/route', { method: 'PUT', body: JSON.stringify({ route }) }),
  saveH3: (body: { base_url: string; key?: string; enabled?: boolean; verify_tls?: boolean }) =>
    request<H3Gateway>('/models/h3', { method: 'PUT', body: JSON.stringify(body) }),
  deleteH3: () => request<{ ok: boolean }>('/models/h3', { method: 'DELETE' }),
  testH3: () => request<{ ok: boolean; seconds: number; error: string; preview?: string }>('/models/h3/test', { method: 'POST' }),
  setVideoRoute: (route: 'gpu' | 'h3') =>
    request<{ route: string }>('/models/video/route', { method: 'PUT', body: JSON.stringify({ route }) }),
  testImageProvider: (id: string) =>
    request<{ ok: boolean; seconds: number; error: string; preview?: string }>(`/models/image/providers/${id}/test`, { method: 'POST' }),
  connect: () => request<ConnectInfo>('/connect'),
  gpuTasks: () => request<GpuTasks>('/gpu/tasks'),
  usage: (days = 30) => request<Usage>(`/usage?days=${days}`),
}
