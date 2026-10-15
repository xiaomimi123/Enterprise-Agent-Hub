import { CheckCircleFilled, SyncOutlined } from '@ant-design/icons'
import { App, Badge, Card, Col, Input, Row, Select, Space, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { api, type Member } from '../api'
import { fromNow, StatusTag, useRequest } from '../components/common'

const { Text } = Typography

export default function Members() {
  const { message } = App.useApp()
  const [dept, setDept] = useState<string>()
  const [q, setQ] = useState<string>()
  const depts = useRequest(api.departments)
  const packs = useRequest(api.rolePacks)
  const members = useRequest(() => api.members({ dept, q }), [dept, q])

  const assign = async (m: Member, rolePackId: string) => {
    const updated = await api.assignRolePack(m.id, rolePackId)
    members.setData(members.data?.map((x) => (x.id === m.id ? updated : x)))
    message.success(`已把「${m.name}」的岗位包改为「${updated.role_pack_name}」，下次调用立即生效`)
  }

  const total = depts.data?.reduce((n, d) => n + d.member_count, 0) ?? 0

  return (
    <Row gutter={16}>
      <Col xs={24} lg={6}>
        <Card
          title="组织架构"
          extra={<Text type="secondary" style={{ fontSize: 12 }}><SyncOutlined /> 钉钉同步</Text>}
          styles={{ body: { padding: 8 } }}
          loading={depts.loading}
        >
          {[{ id: undefined, name: '全部成员', member_count: total, online: undefined, role_pack_name: undefined }, ...(depts.data ?? [])].map((d) => (
            <div
              key={d.id ?? 'all'}
              onClick={() => setDept(d.id)}
              style={{
                padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
                background: dept === d.id ? '#edf2ff' : undefined,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text strong={dept === d.id}>{d.name}</Text>
                <Text type="secondary">{d.member_count} 人</Text>
              </div>
              {d.role_pack_name && (
                <Text type="secondary" style={{ fontSize: 12 }}>默认岗位包：{d.role_pack_name} · 在线 {d.online}</Text>
              )}
            </div>
          ))}
        </Card>
        <Card size="small" style={{ marginTop: 16 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            人员和部门来自钉钉通讯录，入职自动开通，离职自动吊销令牌，不需要单独维护人员表。
          </Text>
        </Card>
      </Col>
      <Col xs={24} lg={18}>
        <Card
          title={`成员（${members.data?.length ?? 0}）`}
          extra={<Input.Search allowClear placeholder="搜索姓名或岗位" onSearch={(v) => setQ(v || undefined)} style={{ width: 220 }} />}
        >
          <Table<Member>
            rowKey="id"
            size="middle"
            loading={members.loading}
            dataSource={members.data}
            pagination={{ pageSize: 12, hideOnSinglePage: true }}
            columns={[
              {
                title: '姓名', dataIndex: 'name', render: (v, m) => (
                  <Space>
                    <Text strong>{v}</Text>
                    {m.dingtalk_bound && <CheckCircleFilled style={{ color: '#3b5bdb', fontSize: 12 }} title="已绑定钉钉" />}
                  </Space>
                ),
              },
              { title: '部门', dataIndex: 'dept_name' },
              { title: '岗位', dataIndex: 'title' },
              {
                title: '岗位包', dataIndex: 'role_pack', width: 180, render: (v, m) => (
                  <Select
                    size="small" value={v} style={{ width: 160 }}
                    options={packs.data?.map((p) => ({ value: p.id, label: p.name }))}
                    onChange={(val) => assign(m, val)}
                  />
                ),
              },
              {
                title: 'agent', dataIndex: 'agent_status', render: (v, m) => (
                  <Space size={4}>
                    <Badge status={v === '在线' ? 'success' : v === '离线' ? 'default' : 'warning'} />
                    <span>{v}</span>
                    {v !== '未安装' && <Tag style={{ marginLeft: 4 }}>{m.os} · v{m.agent_version}</Tag>}
                  </Space>
                ),
                filters: ['在线', '离线', '未安装'].map((x) => ({ text: x, value: x })),
                onFilter: (val, m) => m.agent_status === val,
              },
              { title: '最近活跃', dataIndex: 'last_active', render: (v) => <Text type="secondary">{fromNow(v)}</Text> },
              { title: '', key: 'st', width: 1, render: (_, m) => m.agent_status === '未安装' ? <StatusTag value="未安装" /> : null },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}
