import { BranchesOutlined, FileTextOutlined, SearchOutlined } from '@ant-design/icons'
import { Input, Select, Skeleton } from 'antd'
import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import { api } from '../api'
import { DEPT_BY_NAME, fromNow, useRequest } from '../lib'
import { DeptTile, Empty, PageHeader, Panel, Pill, Token } from '../ui'

export default function Skills() {
  const skills = useRequest(api.skills)
  const [dept, setDept] = useState('全部部门')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<string>()

  const depts = useMemo(() => ['全部部门', ...new Set(skills.data?.map((s) => s.dept_name))], [skills.data])
  const rows = skills.data?.filter((s) => (dept === '全部部门' || s.dept_name === dept) && (!q || s.name.includes(q) || s.description.includes(q))) ?? []

  // 当前选中项不在筛选结果里时，默认显示第一个
  const current = rows.some((r) => r.id === selected) ? selected : rows[0]?.id

  return (
    <>
      <PageHeader
        title="技能库"
        sub="写 SOP 就是写技能。技能是 Markdown 文件（SKILL.md），业务人员在 Obsidian 里编辑，提交到 git 后由中枢统一下发到每个员工的 agent。"
        extra={<span className="chip"><BranchesOutlined />skills · main</span>}
      />
      <div className="split wide">
        <Panel
          tight
          title={
            <div style={{ display: 'flex', gap: 8, width: '100%' }}>
              <Select value={dept} onChange={setDept} variant="filled" style={{ width: 120 }} options={depts.map((d) => ({ value: d, label: d }))} />
              <Input allowClear prefix={<SearchOutlined className="muted" />} placeholder="搜索技能" variant="filled" onChange={(e) => setQ(e.target.value)} />
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
        {current ? <SkillDetail id={current} /> : <Panel><Empty>选择左侧的技能查看内容</Empty></Panel>}
      </div>
    </>
  )
}

function SkillDetail({ id }: { id: string }) {
  const skill = useRequest(() => api.skill(id), [id])
  const s = skill.data
  if (!s) return <Panel><Skeleton active paragraph={{ rows: 10 }} /></Panel>

  const m = s.content?.match(/^---\n([\s\S]*?)\n---\s*/)
  const front = m?.[1] ?? ''
  const body = m ? s.content!.slice(m[0].length) : s.content ?? ''

  return (
    <Panel
      title={<><FileTextOutlined className="muted" /><span className="mono" style={{ fontWeight: 500 }}>{s.source}</span></>}
      extra={<Pill>{s.status}</Pill>}
    >
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 18 }}>
        {[
          ['版本', `v${s.version}`],
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
    </Panel>
  )
}
