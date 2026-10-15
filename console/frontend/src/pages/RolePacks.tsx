import { BookOutlined, CloudServerOutlined, GlobalOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'
import { App, Button, Drawer, Form, Input, InputNumber, Segmented, Select, Skeleton } from 'antd'
import { useState } from 'react'
import { api, type Catalog, type RolePack } from '../api'
import { DEPT_META, useRequest } from '../lib'
import { AvatarStack, DeptTile, PageHeader, Panel, Pill, Seg, Token } from '../ui'

export default function RolePacks() {
  const packs = useRequest(api.rolePacks)
  const catalog = useRequest(api.catalog)
  const [openId, setOpenId] = useState<string>()
  const [filter, setFilter] = useState('全部')

  const list = packs.data?.filter((p) => filter === '全部' || p.status === filter) ?? []

  return (
    <>
      <PageHeader
        title="岗位包"
        sub="岗位包 = 技能 + 知识库 + 工具权限 + 模型与额度。新增一个岗位只需要配置和写技能，不需要改代码；员工的 agent 和外部智能体都受同一套规则约束。"
        extra={<Seg value={filter} onChange={setFilter} options={['全部', '已上线', '规划中'].map((v) => ({ value: v, label: v }))} />}
      />
      {packs.loading ? <Skeleton active /> : (
        <div className="grid g-3">
          {list.map((p) => <PackCard key={p.id} p={p} onClick={() => setOpenId(p.id)} />)}
        </div>
      )}
      {openId && catalog.data && (
        <RolePackDrawer id={openId} catalog={catalog.data} onClose={() => setOpenId(undefined)} onSaved={packs.reload} />
      )}
    </>
  )
}

function PackCard({ p, onClick }: { p: RolePack; onClick: () => void }) {
  const color = (DEPT_META[p.dept] ?? DEPT_META.all).color
  const parts = [
    { label: '技能', n: p.skills.length, icon: <ThunderboltOutlined /> },
    { label: '知识库', n: p.knowledge_bases.length, icon: <BookOutlined /> },
    { label: '工具', n: p.tools.length, icon: <ToolOutlined /> },
    { label: '模型', n: p.models.length, icon: <CloudServerOutlined /> },
  ]
  return (
    <section className="panel" onClick={onClick}
      style={{ cursor: 'pointer', overflow: 'hidden', transition: 'box-shadow .15s, transform .15s' }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = 'var(--shadow)'; e.currentTarget.style.transform = 'translateY(-1px)' }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = ''; e.currentTarget.style.transform = '' }}
    >
      <div style={{ height: 3, background: color, opacity: p.status === '已上线' ? 1 : 0.35 }} />
      <div style={{ padding: '16px 18px 0', display: 'flex', gap: 12, alignItems: 'center' }}>
        <DeptTile dept={p.dept} size={38} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 650, fontSize: 15, letterSpacing: '-0.01em' }}>{p.name}</div>
          <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{p.dept_name}</div>
        </div>
        <Pill>{p.status}</Pill>
      </div>
      <div className="ink2" style={{ padding: '12px 18px 0', lineHeight: 1.6, minHeight: 58, fontSize: 12.5 }}>{p.description}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', margin: '14px 18px 0', border: '1px solid var(--line-2)', borderRadius: 10 }}>
        {parts.map((x, i) => (
          <div key={x.label} style={{ padding: '10px 0', textAlign: 'center', borderLeft: i ? '1px solid var(--line-2)' : undefined }}>
            <div className="num" style={{ fontSize: 17, fontWeight: 650 }}>{x.n}</div>
            <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{x.label}</div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px 16px' }}>
        <span className="muted" style={{ fontSize: 12 }}>
          <span className="num" style={{ color: 'var(--ink)', fontWeight: 600 }}>{p.member_count}</span> 人 · ¥{p.monthly_quota}/人/月
        </span>
        <span className="muted" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
          <GlobalOutlined style={{ color: p.external_access === '关闭' ? 'var(--ink-4)' : 'var(--violet)' }} />
          外部{p.external_access}
        </span>
      </div>
    </section>
  )
}

function Section({ icon, title, hint, children }: { icon: React.ReactNode; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '18px 0', borderTop: '1px solid var(--line-2)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600, marginBottom: hint ? 2 : 10 }}>
        <span style={{ color: 'var(--accent)' }}>{icon}</span>{title}
      </div>
      {hint && <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>{hint}</div>}
      {children}
    </div>
  )
}

function RolePackDrawer({ id, catalog, onClose, onSaved }: {
  id: string
  catalog: Catalog
  onClose: () => void
  onSaved: () => void
}) {
  const { message } = App.useApp()
  const pack = useRequest(() => api.rolePack(id), [id])
  const [form] = Form.useForm<RolePack>()
  const [saving, setSaving] = useState(false)

  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await api.updateRolePack(id, values)
      message.success('已保存，成员下次调用时生效')
      onSaved()
      pack.reload()
    } finally {
      setSaving(false)
    }
  }

  const p = pack.data
  return (
    <Drawer
      open size={720} onClose={onClose} loading={pack.loading}
      title={p && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <DeptTile dept={p.dept} size={32} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{p.name}<Pill>{p.status}</Pill></div>
            <div className="muted" style={{ fontSize: 12, fontWeight: 400 }}>{p.dept_name} · {p.member_count} 名成员</div>
          </div>
        </div>
      )}
      extra={<Button type="primary" loading={saving} onClick={save}>保存更改</Button>}
    >
      {p && (
        <Form form={form} layout="vertical" initialValues={p} key={p.id} requiredMark={false}>
          <Form.Item name="description" style={{ marginBottom: 6 }}>
            <Input.TextArea autoSize={{ minRows: 2 }} variant="filled" />
          </Form.Item>

          <Section icon={<ThunderboltOutlined />} title="技能">
            <Form.Item name="skills" noStyle>
              <Select mode="multiple" optionFilterProp="label" style={{ width: '100%' }}
                options={catalog.skills.map((s) => ({ value: s.id, label: `${s.name} · ${s.dept_name}` }))} />
            </Form.Item>
          </Section>
          <Section icon={<BookOutlined />} title="可检索的知识库" hint="不在列表里的知识库，这个岗位的员工查不到——提示词怎么写都查不到。">
            <Form.Item name="knowledge_bases" noStyle>
              <Select mode="multiple" optionFilterProp="label" style={{ width: '100%' }}
                options={catalog.knowledge_bases.map((k) => ({ value: k.id, label: `${k.name} · ${k.classification}` }))} />
            </Form.Item>
          </Section>
          <Section icon={<ToolOutlined />} title="可调用的工具">
            <Form.Item name="tools" noStyle>
              <Select mode="multiple" optionFilterProp="label" style={{ width: '100%' }}
                options={catalog.tools.map((t) => ({ value: t.id, label: `${t.name} · ${t.risk}` }))} />
            </Form.Item>
          </Section>
          <Section icon={<CloudServerOutlined />} title="模型与额度">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 160px', gap: 12 }}>
              <Form.Item name="models" label="可用模型" style={{ marginBottom: 0 }}>
                <Select mode="multiple" optionFilterProp="label"
                  options={catalog.models.map((m) => ({ value: m.id, label: `${m.name} · ${m.location}` }))} />
              </Form.Item>
              <Form.Item name="monthly_quota" label="每人月额度" style={{ marginBottom: 0 }}>
                <InputNumber min={0} step={50} prefix="¥" style={{ width: '100%' }} />
              </Form.Item>
            </div>
          </Section>
          <Section icon={<GlobalOutlined />} title="安全策略">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <Form.Item name="max_action_level" label="本机动作上限" extra="超过上限直接拒绝；需确认的动作会在员工电脑上弹窗。">
                <Segmented block options={['只读', '需确认', '需二次确认']} />
              </Form.Item>
              <Form.Item name="external_access" label="外部智能体接入" extra="只读：只能查询已开放给外部的知识库。">
                <Segmented block options={['关闭', '只读']} />
              </Form.Item>
            </div>
            <Form.Item name="status" label="状态" style={{ marginBottom: 0 }}>
              <Segmented options={['草稿', '规划中', '已上线']} />
            </Form.Item>
          </Section>
        </Form>
      )}
      {p?.members && (
        <Panel title="成员" sub={`${p.members.length} 人`} flat style={{ marginTop: 8, background: 'var(--surface-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <AvatarStack names={p.members.map((m) => m.name)} max={8} size={28} />
          </div>
          <div className="tagset">{p.members.map((m) => <Token key={m.id}>{m.name} · {m.title}</Token>)}</div>
        </Panel>
      )}
    </Drawer>
  )
}
