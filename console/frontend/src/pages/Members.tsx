import { RefreshCw, Search } from 'lucide-react'
import { App, Input, Select, Table } from 'antd'
import { useState } from 'react'
import { api, type Member } from '../api'
import { useSession } from '../auth'
import { DEPT_META, fromNow, useRequest } from '../lib'
import { Avatar, PageHeader, Panel, Pill, Seg } from '../ui'

export default function Members() {
  const { message } = App.useApp()
  const live = useSession().mode !== 'demo'
  const [dept, setDept] = useState<string>()
  const [q, setQ] = useState<string>()
  const [status, setStatus] = useState('全部')
  const depts = useRequest(api.departments)
  const packs = useRequest(api.rolePacks)
  const members = useRequest(() => api.members({ dept, q }), [dept, q])

  const assign = async (m: Member, rolePackId: string) => {
    const updated = await api.assignRolePack(m.id, rolePackId)
    members.setData(members.data?.map((x) => (x.id === m.id ? updated : x)))
    message.success(`${m.name} 已切换为「${updated.role_pack_name}」，下次调用立即生效`)
  }

  const total = depts.data?.reduce((n, d) => n + d.member_count, 0) ?? 0
  const online = depts.data?.reduce((n, d) => n + d.online, 0) ?? 0
  const rows = members.data?.filter((m) => status === '全部' || m.agent_status === status)

  return (
    <>
      <PageHeader
        title="成员与组织"
        sub="人员和部门来自钉钉通讯录（经 Casdoor 同步）：入职自动开通，离职自动吊销令牌，不需要单独维护人员表。"
        extra={<span className="chip"><RefreshCw />{live ? '数据来自 Casdoor · 30 秒缓存' : '演示数据'}</span>}
      />
      <div className="split">
        <Panel title="组织架构" tight style={{ position: 'sticky', top: 72 }}>
          <div style={{ padding: 6 }}>
            {[{ id: undefined, name: '全部成员', member_count: total, online, role_pack_name: '' }, ...(depts.data ?? [])].map((d) => {
              const on = dept === d.id
              const meta = d.id ? DEPT_META[d.id] : undefined
              return (
                <div key={d.id ?? 'all'} onClick={() => setDept(d.id)} className="nav-item"
                  style={{ height: 'auto', padding: '8px 10px', background: on ? 'var(--accent-soft)' : undefined, color: on ? 'var(--accent-ink)' : undefined }}>
                  <span className="dot" style={{ background: meta?.color ?? 'var(--ink)' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: on ? 600 : 500 }}>{d.name}</div>
                    {d.role_pack_name && <div className="muted" style={{ fontSize: 11.5, fontWeight: 400 }}>{d.role_pack_name}</div>}
                  </div>
                  <span className="num muted" style={{ fontSize: 12 }}>{d.online}/{d.member_count}</span>
                </div>
              )
            })}
          </div>
        </Panel>

        <Panel
          title={depts.data?.find((d) => d.id === dept)?.name ?? '全部成员'}
          sub={`${rows?.length ?? 0} 人`}
          tight
          extra={
            <div style={{ display: 'flex', gap: 8 }}>
              <Seg value={status} onChange={setStatus} options={['全部', '在线', '离线', '未安装'].map((v) => ({ value: v, label: v }))} />
              <Input allowClear prefix={<Search className="muted" />} placeholder="搜索姓名或岗位"
                onChange={(e) => setQ(e.target.value || undefined)} style={{ width: 200 }} />
            </div>
          }
        >
          <Table<Member>
            rowKey="id"
            loading={members.loading}
            dataSource={rows}
            scroll={{ x: 820 }}
            pagination={{ pageSize: 12, hideOnSinglePage: true, size: 'small' }}
            columns={[
              {
                title: '成员', dataIndex: 'name', render: (v, m) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Avatar name={v} size={30} />
                    <div style={{ lineHeight: 1.35 }}>
                      <div style={{ fontWeight: 600 }}>{v}</div>
                      <div className="muted" style={{ fontSize: 12 }}>{m.title}</div>
                    </div>
                  </div>
                ),
              },
              {
                title: '部门', dataIndex: 'dept_name', render: (v, m) => (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    <span className="dot" style={{ background: DEPT_META[m.dept]?.color }} />{v}
                  </span>
                ),
              },
              {
                title: '岗位包', dataIndex: 'role_pack', width: 190, render: (v, m) => (
                  <Select size="small" value={v} variant="filled" style={{ width: 168 }} popupMatchSelectWidth={false}
                    options={packs.data?.map((p) => ({ value: p.id, label: p.name }))}
                    onChange={(val) => assign(m, val)} />
                ),
              },
              {
                title: 'Agent', dataIndex: 'agent_status', render: (v, m) => (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Pill>{v}</Pill>
                    {v !== '未安装' && <span className="muted mono" style={{ fontSize: 11 }}>{m.os} · v{m.agent_version}</span>}
                  </div>
                ),
              },
              { title: '最近活跃', dataIndex: 'last_active', align: 'right', render: (v) => <span className="muted">{fromNow(v)}</span> },
            ]}
          />
        </Panel>
      </div>
    </>
  )
}
