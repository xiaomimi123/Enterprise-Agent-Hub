import { RefreshCw, Search, Upload as UploadIcon, UserPlus } from 'lucide-react'
import { App, Button, Input, Popconfirm, Select, Table } from 'antd'
import { useState } from 'react'
import { api, type Member } from '../api'
import { useSession } from '../auth'
import { DEPT_META, fromNow, useRequest } from '../lib'
import { Avatar, PageHeader, Panel, Pill, Seg } from '../ui'
import { ImportModal, MemberDrawer, PasswordNotice } from './MemberAdmin'

export default function Members() {
  const { message } = App.useApp()
  const live = useSession().mode !== 'demo'
  const [dept, setDept] = useState<string>()
  const [q, setQ] = useState<string>()
  const [status, setStatus] = useState('全部')
  const depts = useRequest(api.departments)
  const packs = useRequest(api.rolePacks)
  const members = useRequest(() => api.members({ dept, q }), [dept, q])
  const [editing, setEditing] = useState<Member | 'new'>()
  const [importing, setImporting] = useState(false)
  const [notice, setNotice] = useState<{ id: string; name?: string; password: string }>()

  const reload = () => {
    members.reload()
    depts.reload()
  }
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      message.success(ok)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const resetPassword = async (m: Member) => {
    try {
      const out = await api.resetMemberPassword(m.id)
      setNotice({ id: m.id, name: m.name, password: out.initial_password })
    } catch (e) {
      message.error((e as Error).message)
    }
  }

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
        sub="成员账号由 Casdoor 统一管理：在这里新建、导入、重置密码；停用成员会立即禁止登录并回收他的模型 key，已签发的令牌最多 30 秒内失效。"
        extra={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span className="chip"><RefreshCw />{live ? '数据来自 Casdoor · 30 秒缓存' : '演示数据'}</span>
            {live && <Button icon={<UploadIcon size={14} />} onClick={() => setImporting(true)}>批量导入</Button>}
            {live && <Button type="primary" icon={<UserPlus size={14} />} onClick={() => setEditing('new')}>新建成员</Button>}
          </div>
        }
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: m.enabled === false ? 0.55 : 1 }}>
                    <Avatar name={v} size={30} />
                    <div style={{ lineHeight: 1.35 }}>
                      <div style={{ fontWeight: 600 }}>{v}{m.enabled === false && <span style={{ marginLeft: 8 }}><Pill tone="red" dot={false}>已停用</Pill></span>}{m.must_change_password && m.enabled !== false && <span style={{ marginLeft: 8 }}><Pill tone="amber" dot={false}>待改密</Pill></span>}</div>
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
                    {v !== '未安装' && <span className="muted mono" style={{ fontSize: 11 }}>{[m.os, m.agent_version && `v${m.agent_version}`].filter(Boolean).join(' · ')}</span>}
                  </div>
                ),
              },
              { title: '最近活跃', dataIndex: 'last_active', align: 'right', render: (v) => <span className="muted">{fromNow(v)}</span> },
              ...(live ? [{
                title: '', width: 230, render: (_: unknown, m: Member) => (
                  <span style={{ display: 'inline-flex', gap: 2, whiteSpace: 'nowrap' }}>
                    <Button size="small" type="text" onClick={() => setEditing(m)}>编辑</Button>
                    <Popconfirm title={`重置「${m.name}」的密码？`} description="会生成新的初始密码，首次登录需修改。" okText="重置" cancelText="取消" onConfirm={() => resetPassword(m)}>
                      <Button size="small" type="text">重置密码</Button>
                    </Popconfirm>
                    {m.enabled === false
                      ? <Button size="small" type="text" onClick={() => run(() => api.setMemberEnabled(m.id, true), `已启用 ${m.name}`)}>启用</Button>
                      : <Popconfirm title={`停用「${m.name}」？`} description="立即禁止登录并回收他的模型 key；已签发的令牌最多 30 秒内失效。" okText="停用" cancelText="取消" disabled={m.is_admin}
                          onConfirm={() => run(() => api.setMemberEnabled(m.id, false), `已停用 ${m.name}`)}>
                          <Button size="small" type="text" danger disabled={m.is_admin} title={m.is_admin ? '管理员账号不能停用' : undefined}>停用</Button>
                        </Popconfirm>}
                    <Popconfirm title={`删除「${m.name}」？`} description="账号将被永久删除且不可恢复；通常建议停用。" okText="删除" cancelText="取消" disabled={m.is_admin}
                      onConfirm={() => run(() => api.deleteMember(m.id), `已删除 ${m.name}`)}>
                      <Button size="small" type="text" danger disabled={m.is_admin}>删除</Button>
                    </Popconfirm>
                  </span>
                ),
              }] : []),
            ]}
          />
        </Panel>
      </div>
      {editing && (
        <MemberDrawer target={editing} depts={depts.data ?? []} onClose={() => setEditing(undefined)}
          onDone={(created) => { reload(); if (created) setNotice(created) }} />
      )}
      <ImportModal open={importing} onClose={() => setImporting(false)} onDone={reload} />
      <PasswordNotice info={notice} onClose={() => setNotice(undefined)} />
    </>
  )
}
