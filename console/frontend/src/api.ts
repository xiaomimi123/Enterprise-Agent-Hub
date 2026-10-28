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
  enabled?: boolean
  must_change_password?: boolean
  is_admin?: boolean
  phone?: string
  email?: string
}

export interface ImportResult {
  created: number
  failed: number
  results: { row: number; username: string; ok: boolean; initial_password?: string; error?: string }[]
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
  pending?: number
}

export interface SkillVersion {
  version: number; author: string; author_name: string; note: string; status: 'published' | 'pending' | 'rejected'
  reviewer: string; review_note: string; created_at: string; reviewed_at: string | null; content: string
}
export interface SkillHistory {
  skill: { id: string; name: string; dept: string; dept_name: string; published_version: number }
  mode: 'direct' | 'review' | null // 这个人改这个技能：直接生效 / 提交审核 / 不能改
  can_review: boolean
  versions: SkillVersion[]
}
export interface SkillReview {
  skill_id: string; skill_name: string; version: number; dept: string; dept_name: string; author_name: string
  note: string; created_at: string; published_version: number; content: string
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
  category: string
  owner: string
  owner_name: string
  review_every_days: number
  last_reviewed_at: string | null
  overdue: boolean
  due_in_days: number | null // 距下次复核还有几天；负数 = 已逾期几天；null = 不需要复核
  description: string
}
export interface Proposal {
  id: number; kind: 'skill' | 'doc' | 'new_doc'; kb_id: string; kb_name: string; target: string; target_name: string
  dept: string; dept_name: string; proposer: string; proposer_name: string; summary: string
  status: 'open' | 'accepted' | 'rejected'; has_content: boolean; created_at: string; stale: boolean; review_note: string; reviewer: string
}
export interface ProposalDetail extends Proposal {
  rationale: string; evidence: string; trace_id: string; proposed_content: string; current_content: string
  current_version: number; base_version: number; result_version: number | null
}
export interface KbFields {
  name?: string; dept?: string; classification?: string; external_access?: boolean
  category?: string; owner?: string; review_every_days?: number; description?: string
}

export interface KbDocument {
  id: string
  title: string
  type: string
  chunks: number
  status: string
  updated_at: string
  version?: number
  pending?: number
  author_name?: string
  chars?: number
}
export interface KbDocVersion {
  version: number; author: string; author_name: string; note: string; status: 'published' | 'pending' | 'rejected'; is_delete: boolean
  reviewer: string; review_note: string; created_at: string; reviewed_at: string | null; content: string
}
export interface KbDocDetail {
  kb: { id: string; name: string; dept: string; dept_name: string }
  name: string; deleted: boolean; published_version: number; content: string
  mode: 'direct' | 'review' | null; can_review: boolean; versions: KbDocVersion[]
}
export interface KbReview {
  kb_id: string; kb_name: string; name: string; version: number; is_delete: boolean; author_name: string
  note: string; created_at: string; published_version: number; content: string
}
export interface KbResult { version: number; status: string; published: boolean; synced: boolean | null }

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

export interface WorkCounts { 进行中: number; 待审核: number; 已完成: number; 受阻: number; total: number }
export interface WorkPerson {
  user_name: string; display_name: string; dept: string; role: string; items: WorkCounts; kinds: Record<string, number>
  images: number; videos: number; calls: number; denied: number; active_days: number; active: boolean; last_active: string | null
}
export interface WorkRole {
  role: string; people: number; active_people: number; items: WorkCounts; kinds: Record<string, number>
  images: number; videos: number; calls: number
}
export interface WorkItem {
  id: number; user_name: string; display_name: string; role: string; kind: string; title: string
  status: string; progress: number; link: string; note: string; source: string; updated_at: string
}
// 应用健康（控制台「应用健康」页，只有管理员能看）
export interface HealthRate { total: number; ok: number; rate: number | null }
export interface HealthCode {
  code: string; label: string; fix: string; count: number; people: number; devices: number
  stages: Record<string, number>; os: Record<string, number>; agents: Record<string, number>; versions: Record<string, number>
  last_at: string; sample: string
}
export interface HealthDevice {
  user_name: string; display_name: string; device_id: string; os: string; os_version: string; arch: string
  agent: string; agent_version: string; connector_version: string; app_version: string
  last_at: string; last_ok_at: string | null; last_fail_at: string | null; last_code: string; fails: number; failing: boolean
  // 来自接入器心跳（每人一条）
  last_seen: string | null; online: boolean; presence_agent: string; current_version: string
  outdated: boolean; version_unknown: boolean; no_events: boolean
}
export interface HealthSummary {
  days: number
  totals: {
    events: number; fails: number; people: number; devices: number; fail_people: number; install: HealthRate; login: HealthRate; launch: HealthRate
    online: number; outdated: number; version_unknown: number
  }
  latest_connector: string
  codes: HealthCode[]
  devices: HealthDevice[]
  catalog: Record<string, { label: string; fix: string }>
  apps?: [string, string][]
}
export interface HealthEvent {
  stage: string; stage_label: string; ok: boolean; code: string; label: string; fix: string; message: string
  app_id: string; app_version: string; agent: string; agent_version: string; os: string; at: string
}
export interface WorkReport {
  days: number; since: string; generated_at: string; digest: string
  totals: { people: number; active_people: number; items: WorkCounts; images: number; videos: number; calls: number; denied: number }
  roles: WorkRole[]; people: WorkPerson[]; items: WorkItem[]; inactive: string[]; blocked: WorkItem[]
}

export interface OrgDept {
  id: string; name: string; member_count: number; managers: string[]
  default_pack: string | null; effective_pack: string; effective_pack_name: string
}
export interface OrgOverview {
  departments: OrgDept[]; bosses: string[]
  members: { id: string; name: string }[]; role_packs: { id: string; name: string }[]
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
  role: 'admin' | 'boss' | 'manager'
  depts: string[] | null // 部门主管负责的部门；管理员和老板为 null（全部）
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 超时要有明确提示，不能让页面一直转圈（比如访问地址不是中枢地址、/api 没转发到中枢）
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(20000),
    ...init,
  }).catch((e: Error) => {
    throw new ApiError(0, e.name === 'TimeoutError'
      ? '连接中枢超时。请确认你是直接用浏览器打开中枢地址（例如 http://192.168.0.41:8088），不是通过别的预览面板或代理访问。'
      : `无法连接中枢（${e.message}）。请确认访问地址就是中枢地址。`)
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
  /** 底座包（Node / uv / Python / 依赖库，tools/build-bundle 构建）；没构建过为 null，员工装机会退回联网下载 */
  bundle: { base: string; built_at: string; components: { name: string; version: string; size: number }[] } | null
  agent_version: string
}

export interface ModelPrice {
  model: string
  configured: boolean
  input_per_m: number
  output_per_m: number
}

export interface PricingInfo {
  models: ModelPrice[]
  default_input_per_m: number
  usd_cny: number
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
  createMember: (body: { username: string; display_name: string; dept: string; title?: string; phone?: string; email?: string; password?: string }) =>
    request<{ id: string; name: string; dept: string; initial_password: string }>('/members', { method: 'POST', body: JSON.stringify(body) }),
  updateMember: (id: string, body: { display_name?: string; dept?: string; title?: string; phone?: string; email?: string }) =>
    request<{ id: string }>(`/members/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  resetMemberPassword: (id: string, password = '') =>
    request<{ id: string; initial_password: string }>(`/members/${id}/password`, { method: 'POST', body: JSON.stringify({ password }) }),
  setMemberEnabled: (id: string, enabled: boolean) =>
    request<{ id: string; enabled: boolean; revoked_keys: number }>(`/members/${id}/enabled`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  deleteMember: (id: string) => request<{ id: string; revoked_keys: number }>(`/members/${id}`, { method: 'DELETE' }),
  importMembers: (csv: string) =>
    request<ImportResult>('/members/import', { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: csv }),
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
  proposals: (status: 'open' | 'closed' = 'open') => request<Proposal[]>(`/proposals?status=${status}`),
  proposal: (id: number) => request<ProposalDetail>(`/proposals/${id}`),
  acceptProposal: (id: number, body: { content?: string; note?: string; confirm_stale?: boolean }) =>
    request<{ version: number; published: boolean; synced: boolean | null }>(`/proposals/${id}/accept`, { method: 'POST', body: JSON.stringify(body) }),
  rejectProposal: (id: number, note: string) => request<{ status: string }>(`/proposals/${id}/reject`, { method: 'POST', body: JSON.stringify({ note }) }),
  createKb: (body: KbFields & { name: string; dept: string; classification: string }) =>
    request<KnowledgeBase>('/knowledge-bases', { method: 'POST', body: JSON.stringify(body) }),
  patchKb: (id: string, body: KbFields) => request<KnowledgeBase>(`/knowledge-bases/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  kbReviewed: (id: string) => request<KnowledgeBase>(`/knowledge-bases/${id}/reviewed`, { method: 'POST' }),
  kbDocument: (kb: string, name: string) => request<KbDocDetail>(`/knowledge-bases/${kb}/documents/${encodeURIComponent(name)}`),
  kbDeleted: (kb: string) => request<{ name: string; updated_at: string }[]>(`/knowledge-bases/${kb}/deleted`),
  createKbDoc: (kb: string, body: { name: string; content: string; note?: string }) =>
    request<KbResult>(`/knowledge-bases/${kb}/documents`, { method: 'POST', body: JSON.stringify(body) }),
  saveKbDoc: (kb: string, name: string, body: { content: string; note: string; base_version: number }) =>
    request<KbResult>(`/knowledge-bases/${kb}/documents/${encodeURIComponent(name)}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteKbDoc: (kb: string, name: string, note = '') =>
    request<KbResult>(`/knowledge-bases/${kb}/documents/${encodeURIComponent(name)}${qs({ note })}`, { method: 'DELETE' }),
  rollbackKbDoc: (kb: string, name: string, version: number) =>
    request<KbResult>(`/knowledge-bases/${kb}/documents/${encodeURIComponent(name)}/rollback`, { method: 'POST', body: JSON.stringify({ version }) }),
  resyncKb: (kb: string) => request<{ synced: number; failed: number }>(`/knowledge-bases/${kb}/sync`, { method: 'POST' }),
  kbReviews: () => request<KbReview[]>('/kb-reviews'),
  reviewKbDoc: (kb: string, name: string, version: number, approve: boolean, note = '') =>
    request<KbResult>(`/kb-reviews/${kb}/${encodeURIComponent(name)}/${version}`, { method: 'POST', body: JSON.stringify({ approve, note }) }),
  kbDocuments: (id: string) => request<KbDocument[]>(`/knowledge-bases/${id}/documents`),
  traces: (params: { member_id?: string; outcome?: string; dept?: string; q?: string } = {}) =>
    request<TraceBrief[]>(`/audit/traces${qs(params)}`),
  trace: (id: string) => request<Trace>(`/audit/traces/${id}`),
  apps: () => request<PublishedApp[]>('/apps'),
  upstreams: () => request<Upstream[]>('/models/upstreams'),
  modelPricing: () => request<PricingInfo>('/models/pricing'),
  setModelPrice: (model: string, body: { input_per_m: number; output_per_m?: number }) =>
    request<ModelPrice>(`/models/pricing/${encodeURIComponent(model)}`, { method: 'PUT', body: JSON.stringify(body) }),
  clearModelPrice: (model: string) => request<{ ok: boolean }>(`/models/pricing/${encodeURIComponent(model)}`, { method: 'DELETE' }),
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
  skillHistory: (id: string) => request<SkillHistory>(`/skills/${id}/history`),
  saveSkill: (id: string, body: { content: string; note: string; base_version: number }) =>
    request<{ version: number; status: string }>(`/skills/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  createSkill: (body: { id: string; dept: string; content: string; note?: string }) =>
    request<{ version: number; status: string }>('/skills', { method: 'POST', body: JSON.stringify(body) }),
  rollbackSkill: (id: string, version: number, note = '') =>
    request<{ version: number; status: string }>(`/skills/${id}/rollback`, { method: 'POST', body: JSON.stringify({ version, note }) }),
  skillReviews: () => request<SkillReview[]>('/skill-reviews'),
  reviewSkill: (id: string, version: number, approve: boolean, note = '') =>
    request<{ version: number; status: string }>(`/skill-reviews/${id}/${version}`, { method: 'POST', body: JSON.stringify({ approve, note }) }),
  org: () => request<OrgOverview>('/org'),
  createDept: (name: string) => request<{ id: string; name: string }>('/org/departments', { method: 'POST', body: JSON.stringify({ name }) }),
  renameDept: (id: string, name: string) => request<{ id: string }>(`/org/departments/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteDept: (id: string) => request<{ ok: boolean }>(`/org/departments/${id}`, { method: 'DELETE' }),
  setDeptManagers: (id: string, users: string[]) =>
    request<{ managers: string[] }>(`/org/departments/${id}/managers`, { method: 'PUT', body: JSON.stringify({ users }) }),
  setDeptPack: (id: string, role_pack_id: string | null) =>
    request<{ default_pack: string | null }>(`/org/departments/${id}/default-pack`, { method: 'PUT', body: JSON.stringify({ role_pack_id }) }),
  setBosses: (users: string[]) => request<{ bosses: string[] }>('/org/bosses', { method: 'PUT', body: JSON.stringify({ users }) }),
  workReport: (days = 7) => request<WorkReport>(`/work/report?days=${days}`),
  usage: (days = 30) => request<Usage>(`/usage?days=${days}`),
  healthSummary: (days = 7, app = '') => {
    const [appId, ver] = app ? app.split('@') : ['', '']
    return request<HealthSummary>(`/health/summary?days=${days}${appId ? `&app_id=${encodeURIComponent(appId)}` : ''}${ver ? `&app_version=${encodeURIComponent(ver)}` : ''}`)
  },
  healthDevice: (user: string, device: string, days = 7) =>
    request<{ events: HealthEvent[] }>(`/health/device?user_name=${encodeURIComponent(user)}&device_id=${encodeURIComponent(device)}&days=${days}`),
}
