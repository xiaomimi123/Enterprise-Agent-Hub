import { Globe, Lock } from 'lucide-react'
import { Table } from 'antd'
import { useState } from 'react'
import { api, type KnowledgeBase } from '../api'
import { fromNow, useRequest } from '../lib'
import { DeptTile, PageHeader, Panel, Pill, Seg, Token } from '../ui'
import { DocsDrawer } from './KbDocs'

export default function Knowledge() {
  const kbs = useRequest(api.knowledgeBases)
  const [open, setOpen] = useState<KnowledgeBase>()
  const [level, setLevel] = useState('全部')
  const data = kbs.data ?? []
  const rows = data.filter((k) => level === '全部' || k.classification === level)

  const stats = [
    { label: '知识库', value: data.length, unit: '个' },
    { label: '文档', value: data.reduce((n, k) => n + k.doc_count, 0), unit: '份' },
    { label: '知识片段', value: data.reduce((n, k) => n + k.chunk_count, 0).toLocaleString(), unit: '' },
    { label: '开放给外部智能体', value: data.filter((k) => k.external_access).length, unit: `/ ${data.length}` },
  ]

  return (
    <>
      <PageHeader
        title="知识库"
        sub="点开一个知识库查看、新建和编辑文档：本部门的知识库保存即生效并同步到检索，全公司的知识库修改要老板或管理员审核；每次保存都是新版本，可以回滚。员工电脑上不放完整知识库，每次查询由中枢按身份过滤。"
        extra={<Seg value={level} onChange={setLevel} options={['全部', '公开', '内部', '机密'].map((v) => ({ value: v, label: v }))} />}
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
            rowKey="id" loading={kbs.loading} dataSource={rows} pagination={false} scroll={{ x: 1100 }}
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
              { title: '密级', dataIndex: 'classification', width: 90, render: (v) => <Pill>{v}</Pill> },
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
      {open && <DocsDrawer kb={open} onClose={() => setOpen(undefined)} onChanged={kbs.reload} />}
    </>
  )
}
