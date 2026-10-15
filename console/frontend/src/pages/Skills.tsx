import { FileMarkdownOutlined } from '@ant-design/icons'
import { Alert, Card, Descriptions, Drawer, Input, Segmented, Space, Table, Tag, Typography } from 'antd'
import { useMemo, useState } from 'react'
import Markdown from 'react-markdown'
import { api, type Skill } from '../api'
import { fromNow, StatusTag, useRequest } from '../components/common'

const { Text } = Typography

export default function Skills() {
  const skills = useRequest(api.skills)
  const [dept, setDept] = useState('全部')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<string>()

  const depts = useMemo(() => ['全部', ...new Set(skills.data?.map((s) => s.dept_name))], [skills.data])
  const rows = skills.data?.filter((s) => (dept === '全部' || s.dept_name === dept) && (!q || s.name.includes(q) || s.description.includes(q)))

  return (
    <>
      <Alert
        type="info" showIcon style={{ marginBottom: 16 }}
        title="写 SOP 就是写技能"
        description="技能是 Markdown 文件（SKILL.md），业务人员在 Obsidian 里直接编辑，提交到 git 后由中枢统一下发到员工的 agent，不需要逐台更新。"
      />
      <Card
        title={`技能库（${rows?.length ?? 0}）`}
        extra={
          <Space wrap>
            <Segmented value={dept} onChange={setDept} options={depts} />
            <Input.Search allowClear placeholder="搜索技能" onSearch={setQ} style={{ width: 200 }} />
          </Space>
        }
      >
        <Table<Skill>
          rowKey="id" loading={skills.loading} dataSource={rows} pagination={false}
          onRow={(s) => ({ onClick: () => setOpenId(s.id), style: { cursor: 'pointer' } })}
          columns={[
            { title: '技能', dataIndex: 'name', render: (v, s) => <Space><FileMarkdownOutlined /><Text strong>{v}</Text><Text type="secondary">v{s.version}</Text></Space> },
            { title: '说明', dataIndex: 'description', ellipsis: true },
            { title: '部门', dataIndex: 'dept_name', width: 100 },
            { title: '状态', dataIndex: 'status', width: 90, render: (v) => <StatusTag value={v} /> },
            { title: '所属岗位包', dataIndex: 'role_packs', render: (v: string[]) => v.map((x) => <Tag key={x}>{x}</Tag>) },
            { title: '近 7 天调用', dataIndex: 'used_7d', width: 110, sorter: (a, b) => a.used_7d - b.used_7d },
            { title: '更新', dataIndex: 'updated_at', width: 110, render: (v) => <Text type="secondary">{fromNow(v)}</Text> },
          ]}
        />
      </Card>
      {openId && <SkillDrawer id={openId} onClose={() => setOpenId(undefined)} />}
    </>
  )
}

function SkillDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const skill = useRequest(() => api.skill(id), [id])
  const s = skill.data
  // 去掉 frontmatter，只渲染正文
  const body = s?.content?.replace(/^---[\s\S]*?---\s*/, '') ?? ''
  return (
    <Drawer open size={720} onClose={onClose} loading={skill.loading} title={s && <Space>{s.name}<StatusTag value={s.status} /></Space>}>
      {s && (
        <>
          <Descriptions size="small" column={2} bordered items={[
            { key: 'dept', label: '部门', children: s.dept_name },
            { key: 'ver', label: '版本', children: `v${s.version}` },
            { key: 'author', label: '维护人', children: s.author },
            { key: 'used', label: '近 7 天调用', children: s.used_7d },
            { key: 'packs', label: '所属岗位包', span: 2, children: s.role_packs.map((x) => <Tag key={x}>{x}</Tag>) },
            { key: 'src', label: '源文件', span: 2, children: <Text code>{s.source}</Text> },
          ]} />
          <Card size="small" style={{ marginTop: 16 }} title="SKILL.md">
            <div className="skill-md"><Markdown>{body}</Markdown></div>
          </Card>
        </>
      )}
    </Drawer>
  )
}
