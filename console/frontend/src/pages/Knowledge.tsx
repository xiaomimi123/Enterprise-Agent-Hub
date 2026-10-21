import { Globe, Lock } from 'lucide-react'
import { Button, Select, Table } from 'antd'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useSession } from '../auth'
import { api, type KnowledgeBase } from '../api'
import { fromNow, useRequest } from '../lib'
import { DeptTile, PageHeader, Panel, Pill, Seg, Token } from '../ui'
import { DocsDrawer } from './KbDocs'
import { CATEGORIES, KbSettingsModal, reviewText } from './KbSettings'

export default function Knowledge() {
  const kbs = useRequest(api.knowledgeBases)
  const [open, setOpen] = useState<KnowledgeBase>()
  const [level, setLevel] = useState('全部')
  const [category, setCategory] = useState('全部')
  const [dept, setDept] = useState('全部')
  const [creating, setCreating] = useState(false)
  const role = useSession().user.role
  const data = kbs.data ?? []
  const depts = [...new Map(data.map((k) => [k.dept, k.dept_name])).entries()]
  const rows = data.filter((k) => (level === '全部' || k.classification === level) && (category === '全部' || k.category === category) && (dept === '全部' || k.dept === dept))
  const overdue = data.filter((k) => k.overdue)

  const stats = [
    { label: '知识库', value: data.length, unit: '个' },
    { label: '文档', value: data.reduce((n, k) => n + k.doc_count, 0), unit: '份' },
    { label: '知识片段', value: data.reduce((n, k) => n + k.chunk_count, 0).toLocaleString(), unit: '' },
    { label: '开放给外部智能体', value: data.filter((k) => k.external_access).length, unit: `/ ${data.length}` },
    { label: '逾期未复核', value: overdue.length, unit: '个' },
  ]

  return (
    <>
      <PageHeader
        title="知识库"
        sub="点开一个知识库查看、新建和编辑文档：本部门的知识库保存即生效并同步到检索，全公司的知识库修改要老板或管理员审核；每次保存都是新版本，可以回滚。员工电脑上不放完整知识库，每次查询由中枢按身份过滤。"
        extra={<>
          <Select value={dept} onChange={setDept} style={{ width: 130 }} variant="filled" options={[{ value: '全部', label: '全部部门' }, ...depts.map(([v, l]) => ({ value: v, label: l }))]} />
          <Select value={category} onChange={setCategory} style={{ width: 120 }} variant="filled" options={['全部', ...CATEGORIES].map((v) => ({ value: v, label: v === '全部' ? '全部类型' : v }))} />
          <Seg value={level} onChange={setLevel} options={['全部', '公开', '内部', '机密'].map((v) => ({ value: v, label: v }))} />
          {role !== 'manager' && <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreating(true)}>新建知识库</Button>}
        </>}
      />
      <div className="stack">
        <section className="panel kpi-strip">
          {stats.map((s) => (
            <div className="kpi" key={s.label}>
              <div className="kpi-label">{s.label}</div>
              <div className="kpi-value num">{s.value}{s.unit && <small>{s.unit}</small>}</div>
            </div>
          ))}
        </section>
        <Panel tight>
          <Table<KnowledgeBase>
            rowKey="id" loading={kbs.loading} dataSource={rows} pagination={false} scroll={{ x: 1400 }}
            onRow={(k) => ({ onClick: () => setOpen(k), style: { cursor: 'pointer' } })}
            columns={[
              {
                title: '知识库', dataIndex: 'name', width: 260, render: (v, k) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <DeptTile dept={k.dept} size={30}>{k.classification === '机密' ? <Lock /> : undefined}</DeptTile>
                    <div style={{ lineHeight: 1.35 }}>
                      <div style={{ fontWeight: 600 }}>{v}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{k.dept_name} · {k.source}</div>
                    </div>
                  </div>
                ),
              },
              { title: '内容类型', dataIndex: 'category', width: 100, render: (v) => <Pill tone="gray" dot={false}>{v}</Pill> },
              { title: '密级', dataIndex: 'classification', width: 90, render: (v) => <Pill>{v}</Pill> },
              { title: '负责人', dataIndex: 'owner_name', width: 100, render: (v) => v || <span className="muted">未指定</span> },
              {
                title: '复核', key: 'review', width: 110,
                render: (_, k) => <span style={{ color: k.overdue ? 'var(--red)' : undefined, fontWeight: k.overdue ? 600 : undefined }} className={k.overdue ? '' : 'muted'}>{reviewText(k)}</span>,
              },
              {
                title: '规模', key: 'size', width: 130,
                render: (_, k) => <span className="num">{k.doc_count} 份 · <span className="muted">{k.chunk_count} 片段</span></span>,
              },
              {
                title: '外部智能体', dataIndex: 'external_access', width: 110,
                render: (v) => v
                  ? <span style={{ color: 'var(--violet)', display: 'inline-flex', gap: 6, alignItems: 'center' }}><Globe />只读开放</span>
                  : <span className="muted">不开放</span>,
              },
              { title: '授权岗位包', dataIndex: 'role_packs', render: (v: string[]) => <div className="tagset">{v.map((x) => <Token key={x}>{x}</Token>)}</div> },
              { title: '近 7 天检索', dataIndex: 'queries_7d', width: 110, align: 'right', sorter: (a, b) => a.queries_7d - b.queries_7d, render: (v) => <span className="num">{v}</span> },
              { title: '更新', dataIndex: 'updated_at', width: 100, align: 'right', render: (v) => <span className="muted">{fromNow(v)}</span> },
            ]}
          />
        </Panel>
      </div>
      {open && <DocsDrawer kb={kbs.data?.find((k) => k.id === open.id) ?? open} onClose={() => setOpen(undefined)} onChanged={kbs.reload} />}
      <KbSettingsModal open={creating} onClose={() => setCreating(false)} onSaved={kbs.reload} />
    </>
  )
}
