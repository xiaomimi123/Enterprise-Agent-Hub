import { App, Button, Input, Modal, Popconfirm, Select, Skeleton, Table } from 'antd'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { api, type OrgDept } from '../api'
import { useRequest } from '../lib'
import { PageHeader, Panel } from '../ui'

export default function OrgPage() {
  const { message } = App.useApp()
  const { data, loading, reload } = useRequest(api.org)
  const [naming, setNaming] = useState<{ id?: string; name: string }>()
  const [busy, setBusy] = useState(false)

  if (loading && !data) return <Skeleton active paragraph={{ rows: 10 }} style={{ marginTop: 24 }} />
  if (!data) return <Panel><div style={{ padding: 18 }}>加载失败，请刷新重试。</div></Panel>
  const memberOptions = data.members.map((m) => ({ value: m.id, label: `${m.name}（${m.id}）` }))

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      message.success(ok)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    }
  }
  const saveName = async () => {
    if (!naming) return
    setBusy(true)
    try {
      await (naming.id ? api.renameDept(naming.id, naming.name) : api.createDept(naming.name))
      message.success(naming.id ? '已改名' : '已新建部门')
      setNaming(undefined)
      reload()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        title="部门与角色"
        sub="谁能进控制台、能看哪些部门：老板看全公司；部门主管只能看和管自己负责的部门；系统管理员做配置。员工没有这些身份就进不了控制台。"
        extra={<Button type="primary" icon={<Plus size={14} />} onClick={() => setNaming({ name: '' })}>新建部门</Button>}
      />
      <div className="stack">
        <Panel title="老板" sub="看全公司的成员、技能、知识库、工作看板和审计；老板的 agent 也能拉全公司日报">
          <Select
            mode="multiple" style={{ width: '100%', maxWidth: 560 }} placeholder="选择老板" optionFilterProp="label"
            value={data.bosses} options={memberOptions}
            onChange={(users) => run(() => api.setBosses(users), '老板名单已保存')}
          />
        </Panel>

        <Panel title="部门" sub="主管只能看自己负责的部门，可以设多个；默认岗位包给没有单独分配岗位包的成员用" tight>
          <Table<OrgDept>
            rowKey="id" dataSource={data.departments} pagination={false} scroll={{ x: 860 }}
            columns={[
              { title: '部门', dataIndex: 'name', width: 170, render: (v, d) => (
                <span style={{ fontWeight: 500 }}>{v} <Button size="small" type="text" onClick={() => setNaming({ id: d.id, name: d.name })}>改名</Button></span>
              ) },
              { title: '成员', dataIndex: 'member_count', width: 70, align: 'right', render: (v) => <span className="num">{v}</span> },
              { title: '部门主管', dataIndex: 'managers', render: (v: string[], d) => (
                <Select mode="multiple" size="small" variant="filled" style={{ minWidth: 220 }} placeholder="未设置" optionFilterProp="label"
                  value={v} options={memberOptions} onChange={(users) => run(() => api.setDeptManagers(d.id, users), `已保存「${d.name}」的主管`)} />
              ) },
              { title: '默认岗位包', dataIndex: 'default_pack', width: 210, render: (v: string | null, d) => (
                <Select size="small" variant="filled" style={{ width: 190 }} value={v ?? ''} popupMatchSelectWidth={false}
                  options={[{ value: '', label: `内置映射（${d.effective_pack_name}）` }, ...data.role_packs.map((p) => ({ value: p.id, label: p.name }))]}
                  onChange={(val) => run(() => api.setDeptPack(d.id, val || null), `已保存「${d.name}」的默认岗位包`)} />
              ) },
              { title: '', width: 80, render: (_, d) => (
                <Popconfirm title={`删除部门「${d.name}」？`} description="只有没有成员的部门才能删除。" okText="删除" cancelText="取消"
                  disabled={d.member_count > 0} onConfirm={() => run(() => api.deleteDept(d.id), '已删除')}>
                  <Button size="small" type="text" danger disabled={d.member_count > 0}>删除</Button>
                </Popconfirm>
              ) },
            ]}
          />
        </Panel>
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
          提示：技能库目前按部门中文名对应 skills/ 下的文件夹，部门改名后，技能文件夹名要同步改，否则技能会显示在「全公司」下（下一期把技能改成按部门 id 归属）。
        </div>
      </div>

      <Modal open={!!naming} title={naming?.id ? '部门改名' : '新建部门'} okText="保存" cancelText="取消" confirmLoading={busy}
        onOk={saveName} onCancel={() => setNaming(undefined)} okButtonProps={{ disabled: !naming?.name.trim() }}>
        <Input autoFocus maxLength={20} placeholder="部门名称，如：业务部" value={naming?.name} onChange={(e) => setNaming((n) => n && { ...n, name: e.target.value })}
          onPressEnter={saveName} />
      </Modal>
    </>
  )
}
