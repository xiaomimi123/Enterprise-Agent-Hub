import { Card, Col, Progress, Row, Segmented, Skeleton, Space, Statistic, Table, Typography } from 'antd'
import type { EChartsOption } from 'echarts'
import { useMemo, useState } from 'react'
import { api } from '../api'
import EChart, { PALETTE } from '../components/EChart'
import { tokens, useRequest, yuan } from '../components/common'

const { Text } = Typography

export default function UsagePage() {
  const [days, setDays] = useState(30)
  const { data, loading } = useRequest(() => api.usage(days), [days])

  const dailyOption = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    tooltip: { trigger: 'axis', valueFormatter: (v) => `¥${v}` },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 48, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: data?.daily.map((d) => String(d.date).slice(5)) ?? [] },
    yAxis: { type: 'value', name: '元' },
    series: (data?.departments ?? []).map((dept) => ({
      name: dept, type: 'bar', stack: 'cost', barMaxWidth: 22,
      data: data?.daily.map((d) => d[dept] as number) ?? [],
    })),
  }), [data])

  const modelOption = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    tooltip: { trigger: 'item', formatter: '{b}<br/>{c} token（{d}%）' },
    legend: { bottom: 0, itemWidth: 10, itemHeight: 10 },
    series: [{
      type: 'pie', radius: ['40%', '68%'], center: ['50%', '44%'], label: { formatter: '{d}%' },
      data: data?.by_model.map((m) => ({ name: `${m.model}（${m.location}）`, value: m.tokens })) ?? [],
    }],
  }), [data])

  if (loading || !data) return <Skeleton active paragraph={{ rows: 12 }} />

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Segmented value={days} onChange={setDays} options={[{ label: '近 7 天', value: 7 }, { label: '近 30 天', value: 30 }]} />
      </div>
      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}><Card><Statistic title="模型花费" value={data.total_cost} prefix="¥" precision={0} /></Card></Col>
        <Col xs={12} lg={6}><Card><Statistic title="Token 用量" value={tokens(data.total_tokens)} /></Card></Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="本地模型占比" value={Math.round(data.local_ratio * 100)} suffix="%" />
            <Text type="secondary" style={{ fontSize: 12 }}>财务、人事等敏感请求只走本地</Text>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="人均花费" value={data.total_cost / 50} prefix="¥" precision={1} />
            <Text type="secondary" style={{ fontSize: 12 }}>按 50 人计</Text>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="每日花费 · 按部门"><EChart option={dailyOption} height={320} /></Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="模型分布"><EChart option={modelOption} height={320} /></Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="部门花费与额度">
            <Table
              rowKey="dept" size="small" pagination={false} dataSource={data.by_dept}
              columns={[
                { title: '部门', dataIndex: 'dept' },
                { title: 'Token', dataIndex: 'tokens', render: (v) => tokens(v) },
                { title: '花费', dataIndex: 'cost', render: (v) => yuan(v) },
                {
                  title: '月额度使用', key: 'q', width: 200,
                  render: (_, r) => {
                    // 近 7 天时按比例折算到月
                    const monthly = days === 30 ? r.cost : (r.cost / 7) * 30
                    const pct = r.quota ? Math.round((monthly / r.quota) * 100) : 0
                    return <Progress percent={pct} size="small" status={pct > 90 ? 'exception' : 'normal'} format={() => `${pct}% / ¥${r.quota}`} />
                  },
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="个人用量 TOP 10（本月）">
            <Table
              rowKey="member_id" size="small" pagination={false} dataSource={data.top_members}
              columns={[
                { title: '#', key: 'i', width: 40, render: (_, __, i) => i + 1 },
                { title: '成员', dataIndex: 'member', render: (v) => <Text strong>{v}</Text> },
                { title: '部门', dataIndex: 'dept_name' },
                { title: '调用', dataIndex: 'calls' },
                { title: 'Token', dataIndex: 'tokens', render: (v) => tokens(v) },
                { title: '花费', dataIndex: 'cost', render: (v) => yuan(v) },
              ]}
            />
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
