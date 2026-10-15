import { GlobalOutlined, LockOutlined } from '@ant-design/icons'
import { Alert, Card, Col, Drawer, Row, Space, Statistic, Table, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'
import { api, type KbDocument, type KnowledgeBase } from '../api'
import { fmtTime, fromNow, StatusTag, useRequest } from '../components/common'

const { Text } = Typography

export default function Knowledge() {
  const kbs = useRequest(api.knowledgeBases)
  const [open, setOpen] = useState<KnowledgeBase>()
  const data = kbs.data ?? []

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        title="Obsidian 是知识的「源码」，中枢负责检索和权限"
        description="知识按部门和密级打标签。员工电脑上不放完整知识库，每次查询由中枢按身份过滤后，只返回有权限的片段。"
      />
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col xs={12} lg={6}><Card><Statistic title="知识库" value={data.length} suffix="个" /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="文档" value={data.reduce((n, k) => n + k.doc_count, 0)} suffix="份" /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="知识片段" value={data.reduce((n, k) => n + k.chunk_count, 0)} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="机密知识库" value={data.filter((k) => k.classification === '机密').length} suffix="个" /></Card></Col>
      </Row>
      <Card title="知识库">
        <Table<KnowledgeBase>
          rowKey="id" loading={kbs.loading} dataSource={data} pagination={false} scroll={{ x: 1250 }}
          onRow={(k) => ({ onClick: () => setOpen(k), style: { cursor: 'pointer' } })}
          columns={[
            { title: '名称', dataIndex: 'name', width: 170, render: (v, k) => <Space>{k.classification === '机密' && <LockOutlined style={{ color: '#c2255c' }} />}<Text strong>{v}</Text></Space> },
            { title: '部门', dataIndex: 'dept_name', width: 110 },
            {
              title: '密级', dataIndex: 'classification', width: 90, render: (v) => <StatusTag value={v} />,
              filters: ['公开', '内部', '机密'].map((x) => ({ text: x, value: x })), onFilter: (v, k) => k.classification === v,
            },
            { title: '来源', dataIndex: 'source', width: 100, render: (v) => <Tag>{v}</Tag> },
            { title: '文档', dataIndex: 'doc_count', width: 70 },
            { title: '片段', dataIndex: 'chunk_count', width: 70 },
            {
              title: '外部智能体', dataIndex: 'external_access', width: 110,
              render: (v) => v
                ? <Tooltip title="允许 ChatGPT 等外部智能体只读检索"><Tag icon={<GlobalOutlined />} color="green">可读</Tag></Tooltip>
                : <Tag>不开放</Tag>,
            },
            { title: '授权岗位包', dataIndex: 'role_packs', render: (v: string[]) => v.map((x) => <Tag key={x}>{x}</Tag>) },
            { title: '近 7 天检索', dataIndex: 'queries_7d', width: 110, sorter: (a, b) => a.queries_7d - b.queries_7d },
            { title: '更新', dataIndex: 'updated_at', width: 100, render: (v) => <Text type="secondary">{fromNow(v)}</Text> },
          ]}
        />
      </Card>
      {open && <DocsDrawer kb={open} onClose={() => setOpen(undefined)} />}
    </>
  )
}

function DocsDrawer({ kb, onClose }: { kb: KnowledgeBase; onClose: () => void }) {
  const docs = useRequest(() => api.kbDocuments(kb.id), [kb.id])
  return (
    <Drawer open size={640} onClose={onClose} title={<Space>{kb.name}<StatusTag value={kb.classification} /></Space>}>
      <Space orientation="vertical" style={{ width: '100%' }} size={16}>
        <Text type="secondary">
          {kb.dept_name} · 来源 {kb.source} · 授权给：{kb.role_packs.join('、') || '无'}
        </Text>
        <Table<KbDocument>
          rowKey="id" size="small" loading={docs.loading} dataSource={docs.data} pagination={false}
          columns={[
            { title: '文档', dataIndex: 'title' },
            { title: '类型', dataIndex: 'type', width: 70, render: (v) => <Tag>{v}</Tag> },
            { title: '片段', dataIndex: 'chunks', width: 70 },
            { title: '状态', dataIndex: 'status', width: 90, render: (v) => <StatusTag value={v} /> },
            { title: '更新', dataIndex: 'updated_at', width: 110, render: (v) => fmtTime(v) },
          ]}
        />
      </Space>
    </Drawer>
  )
}
