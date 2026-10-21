import { FileText, History, Pencil, Plus, Search } from 'lucide-react'
import { Button, Input, Select, Skeleton } from 'antd'
import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api'
import { useSession } from '../auth'
import { DEPT_BY_NAME, fromNow, useRequest } from '../lib'
import { DeptTile, Empty, PageHeader, Panel, Pill, Token } from '../ui'
import { HistoryDrawer, NewSkillModal, ReviewDrawer, SkillEditor } from './SkillEditor'

export default function Skills() {
  const skills = useRequest(api.skills)
  const [dept, setDept] = useState('全部部门')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<string>()
  const [creating, setCreating] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const session = useSession()
  const canReview = session.user.role !== 'manager'
  const pendingCount = skills.data?.reduce((n, s) => n + (s.pending ?? 0), 0) ?? 0

  const depts = useMemo(() => ['全部部门', ...new Set(skills.data?.map((s) => s.dept_name))], [skills.data])
  const rows = skills.data?.filter((s) => (dept === '全部部门' || s.dept_name === dept) && (!q || s.name.includes(q) || s.description.includes(q))) ?? []

  // 当前选中项不在筛选结果里时，默认显示第一个
  const current = rows.some((r) => r.id === selected) ? selected : rows[0]?.id

  return (
    <>
      <PageHeader
        title="技能库"
        sub="写 SOP 就是写技能。技能是 Markdown（SKILL.md），在这里直接编辑：本部门的技能保存即生效，全公司的技能修改要老板或管理员审核；每次保存都是新版本，可以回滚。"
        extra={<>
          <Button onClick={() => setReviewing(true)}>{canReview ? '待审核' : '我提交的审核'}{pendingCount ? `（${pendingCount}）` : ''}</Button>
          <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreating(true)}>新建技能</Button>
        </>}
      />
      <NewSkillModal open={creating} onClose={() => setCreating(false)} onCreated={skills.reload} />
      <ReviewDrawer open={reviewing} onClose={() => setReviewing(false)} onChanged={skills.reload} canReview={canReview} />
      <div className="split wide">
        <Panel
          tight
          title={
            <div style={{ display: 'flex', gap: 8, width: '100%' }}>
              <Select value={dept} onChange={setDept} variant="filled" style={{ width: 120 }} options={depts.map((d) => ({ value: d, label: d }))} />
              <Input allowClear prefix={<Search className="muted" />} placeholder="搜索技能" variant="filled" onChange={(e) => setQ(e.target.value)} />
            </div>
          }
        >
          {skills.loading ? <div style={{ padding: 18 }}><Skeleton active /></div> : rows.length === 0 ? <Empty>没有匹配的技能</Empty> : (
            <div className="rows" style={{ maxHeight: 'calc(100vh - 230px)', overflow: 'auto' }}>
              {rows.map((s) => (
                <div key={s.id} className="row-item clickable" onClick={() => setSelected(s.id)}
                  style={{ background: s.id === current ? 'var(--accent-soft)' : undefined, alignItems: 'flex-start' }}>
                  <DeptTile dept={s.dept === 'all' ? 'all' : (DEPT_BY_NAME[s.dept_name] ?? 'all')} size={30} />
                  <div className="row-main">
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                      <span className="row-title" style={{ fontWeight: 600 }}>{s.name}</span>
                      <span className="muted num" style={{ fontSize: 12, flexShrink: 0 }}>{s.used_7d} 次/周</span>
                    </div>
                    <div className="row-meta">{s.description}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
        {current ? <SkillDetail key={current} id={current} onChanged={skills.reload} /> : <Panel><Empty>选择左侧的技能查看内容</Empty></Panel>}
      </div>
    </>
  )
}

function SkillDetail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const skill = useRequest(() => api.skill(id), [id])
  const hist = useRequest(() => api.skillHistory(id).catch(() => undefined), [id]) // 还没导入版本库的技能没有历史
  const [editing, setEditing] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const s = skill.data
  const done = () => { setEditing(false); skill.reload(); hist.reload(); onChanged() }
  if (!s) return <Panel><Skeleton active paragraph={{ rows: 10 }} /></Panel>

  const m = s.content?.match(/^---\n([\s\S]*?)\n---\s*/)
  const front = m?.[1] ?? ''
  const body = m ? s.content!.slice(m[0].length) : s.content ?? ''

  return (
    <Panel
      title={<><FileText className="muted" /><span className="mono" style={{ fontWeight: 500 }}>{s.source}</span></>}
      extra={<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {!!s.pending && <Pill tone="amber">有 {s.pending} 份待审核</Pill>}
        <Pill>{s.status}</Pill>
        {hist.data && <Button size="small" icon={<History size={13} />} onClick={() => setShowHistory(true)}>历史版本</Button>}
        {hist.data?.mode && !editing && (
          <Button size="small" type="primary" icon={<Pencil size={13} />} onClick={() => setEditing(true)}>{hist.data.mode === 'direct' ? '编辑' : '编辑（提交审核）'}</Button>
        )}
      </div>}
    >
      <HistoryDrawer id={id} open={showHistory} onClose={() => setShowHistory(false)} onChanged={done} />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        {[
          ['版本', s.version === '—' ? '—' : `第 ${s.version} 版`],
          ['维护人', s.author],
          ['近 7 天调用', `${s.used_7d} 次`],
          ['更新', fromNow(s.updated_at)],
        ].map(([k, v]) => (
          <div key={k} style={{ background: 'var(--surface-2)', border: '1px solid var(--line-2)', borderRadius: 10, padding: '10px 12px' }}>
            <div className="muted" style={{ fontSize: 11.5 }}>{k}</div>
            <div className="num" style={{ fontWeight: 600, marginTop: 4 }}>{v}</div>
          </div>
        ))}
      </div>
      {editing && hist.data?.mode ? (
        <SkillEditor id={id} content={s.content ?? ''} baseVersion={hist.data.skill.published_version} mode={hist.data.mode} onDone={done} onCancel={() => setEditing(false)} />
      ) : <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        <span className="muted">已用于</span>
        {s.role_packs.length ? s.role_packs.map((x) => <Token key={x}>{x}</Token>) : <span className="muted">尚未加入岗位包</span>}
      </div>
      <pre className="frontmatter">
        <span style={{ opacity: 0.5 }}>---</span>{'\n'}
        {front.split('\n').map((line, i) => {
          const [k, ...rest] = line.split(':')
          return <span key={i}><b>{k}</b>:{rest.join(':')}{'\n'}</span>
        })}
        <span style={{ opacity: 0.5 }}>---</span>
      </pre>
      <div className="skill-md"><Markdown>{body}</Markdown></div>
      </>}
    </Panel>
  )
}
