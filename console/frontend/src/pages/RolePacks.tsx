import { BookOutlined, CloudServerOutlined, TeamOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'
import {
  Alert, App, Button, Card, Col, Descriptions, Drawer, Form, Input, InputNumber, Row, Segmented, Select, Space, Tag, Typography,
} from 'antd'
import { useState } from 'react'
import { api, type Catalog, type RolePack } from '../api'
import { StatusTag, useRequest } from '../components/common'

const { Text, Paragraph } = Typography

function Count({ icon, n, label }: { icon: React.ReactNode; n: number; label: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 18, fontWeight: 600 }}>{icon} {n}</div>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
    </div>
  )
}

export default function RolePacks() {
  const packs = useRequest(api.rolePacks)
  const catalog = useRequest(api.catalog)
  const [openId, setOpenId] = useState<string>()

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        title="岗位包 = 一组技能 + 一组知识库 + 一组工具权限 + 模型与额度"
        description="新增一个岗位只需要配置和写技能，不需要改代码。权限在中枢强制执行，员工的 agent 和外部智能体都受同一套规则约束。"
      />
      <Row gutter={[16, 16]}>
        {packs.data?.map((p) => (
          <Col key={p.id} xs={24} md={12} xl={8}>
            <Card
              hoverable onClick={() => setOpenId(p.id)}
              title={<Space>{p.name}<StatusTag value={p.status} /></Space>}
              extra={<Text type="secondary">{p.dept_name}</Text>}
            >
              <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ minHeight: 44 }}>{p.description}</Paragraph>
              <Row>
                <Col span={6}><Count icon={<ThunderboltOutlined />} n={p.skills.length} label="技能" /></Col>
                <Col span={6}><Count icon={<BookOutlined />} n={p.knowledge_bases.length} label="知识库" /></Col>
                <Col span={6}><Count icon={<ToolOutlined />} n={p.tools.length} label="工具" /></Col>
                <Col span={6}><Count icon={<TeamOutlined />} n={p.member_count} label="成员" /></Col>
              </Row>
              <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>月额度 ¥{p.monthly_quota}/人</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>外部智能体：{p.external_access}</Text>
              </div>
            </Card>
          </Col>
        ))}
      </Row>
      {openId && catalog.data && (
        <RolePackDrawer
          id={openId}
          catalog={catalog.data}
          onClose={() => setOpenId(undefined)}
          onSaved={packs.reload}
        />
      )}
    </>
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
      message.success('岗位包已保存，成员下次调用时生效')
      onSaved()
      pack.reload()
    } finally {
      setSaving(false)
    }
  }

  const p = pack.data
  return (
    <Drawer
      open size={760} onClose={onClose} loading={pack.loading}
      title={p && <Space>{p.name}<StatusTag value={p.status} /><Text type="secondary" style={{ fontWeight: 400 }}>{p.dept_name}</Text></Space>}
      extra={<Button type="primary" loading={saving} onClick={save}>保存</Button>}
    >
      {p && (
        <Form form={form} layout="vertical" initialValues={p} key={p.id}>
          <Form.Item name="description" label="说明">
            <Input.TextArea autoSize={{ minRows: 2 }} />
          </Form.Item>
          <Form.Item name="skills" label={<><ThunderboltOutlined />&nbsp;技能</>}>
            <Select mode="multiple" optionFilterProp="label"
              options={catalog.skills.map((s) => ({ value: s.id, label: `${s.name}（${s.dept_name}）` }))} />
          </Form.Item>
          <Form.Item name="knowledge_bases" label={<><BookOutlined />&nbsp;可检索的知识库</>}
            extra="不在列表里的知识库，这个岗位的员工查不到，提示词怎么写都查不到。">
            <Select mode="multiple" optionFilterProp="label"
              options={catalog.knowledge_bases.map((k) => ({ value: k.id, label: `${k.name}（${k.dept_name} · ${k.classification}）` }))} />
          </Form.Item>
          <Form.Item name="tools" label={<><ToolOutlined />&nbsp;可调用的工具</>}>
            <Select mode="multiple" optionFilterProp="label"
              options={catalog.tools.map((t) => ({ value: t.id, label: `${t.name}（${t.risk}）` }))} />
          </Form.Item>
          <Form.Item name="models" label={<><CloudServerOutlined />&nbsp;可用模型</>}>
            <Select mode="multiple" optionFilterProp="label"
              options={catalog.models.map((m) => ({ value: m.id, label: `${m.name}（${m.location}）` }))} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="monthly_quota" label="每人月额度（元）">
                <InputNumber min={0} step={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="max_action_level" label="本机动作上限" extra="超过上限的动作直接拒绝；需确认的动作会在员工电脑上弹窗。">
                <Segmented options={['只读', '需确认', '需二次确认']} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="external_access" label="外部智能体接入（ChatGPT、Claude 等通过 MCP）"
            extra="只读：只能查询已开放给外部的知识库；关闭：外部智能体完全不能接入。">
            <Segmented options={['关闭', '只读']} />
          </Form.Item>
          <Form.Item name="status" label="状态">
            <Segmented options={['草稿', '规划中', '已上线']} />
          </Form.Item>
        </Form>
      )}
      {p?.members && (
        <Card size="small" title={`使用此岗位包的成员（${p.members.length}）`}>
          <Space wrap>
            {p.members.map((m) => <Tag key={m.id}>{m.name} · {m.title}</Tag>)}
          </Space>
        </Card>
      )}
      {p && (
        <Descriptions size="small" column={1} style={{ marginTop: 16 }} items={[
          { key: 'tools', label: '工具风险说明', children: '只读：直接执行 · 需确认：员工点确认后执行 · 需二次确认：删除、对外发送等，二次确认或主管审批' },
        ]} />
      )}
    </Drawer>
  )
}
