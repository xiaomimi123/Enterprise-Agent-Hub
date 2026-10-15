import { ClockCircleOutlined, StopOutlined } from '@ant-design/icons'
import { Alert, Card, Col, Empty, Progress, Row, Skeleton, Space, Statistic, Typography } from 'antd'
import type { EChartsOption } from 'echarts'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import EChart, { PALETTE } from '../components/EChart'
import { fmtTime, fromNow, StatusTag, tokens, useRequest, yuan } from '../components/common'

const { Text } = Typography

export default function Overview() {
  const { data, loading, error } = useRequest(api.overview)
  const nav = useNavigate()

  const trendOption = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    tooltip: { trigger: 'axis' },
    legend: { data: ['Token 用量（万）', '花费（元）'], top: 0 },
    grid: { left: 48, right: 48, top: 36, bottom: 28 },
    xAxis: { type: 'category', data: data?.trend.map((t) => t.date.slice(5)) ?? [] },
    yAxis: [{ type: 'value', name: '万' }, { type: 'value', name: '元' }],
    series: [
      { name: 'Token 用量（万）', type: 'bar', barMaxWidth: 18, data: data?.trend.map((t) => Math.round(t.tokens / 1e4)) ?? [] },
      { name: '花费（元）', type: 'line', smooth: true, yAxisIndex: 1, data: data?.trend.map((t) => t.cost) ?? [] },
    ],
  }), [data])

  const deptOption = useMemo<EChartsOption>(() => ({
    color: PALETTE,
    tooltip: { trigger: 'item', formatter: '{b}<br/>¥{c}（{d}%）' },
    legend: { orient: 'vertical', right: 0, top: 'middle', itemWidth: 10, itemHeight: 10 },
    series: [{
      type: 'pie', radius: ['48%', '75%'], center: ['36%', '50%'],
      label: { show: false },
      // 只走本地模型的部门花费为 0，不画扇区
      data: data?.cost_by_dept.filter((d) => d.cost > 0).map((d) => ({ name: d.dept, value: d.cost })) ?? [],
    }],
  }), [data])

  if (error) return <Alert type="error" title="加载失败" description={error} showIcon />
  if (loading || !data) return <Skeleton active paragraph={{ rows: 12 }} />
  const s = data.stats

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="在线 agent" value={s.agents_online} suffix={`/ ${s.members} 人`} />
            <Text type="secondary">已安装 {s.agents_installed} 台</Text>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="今日任务" value={s.tasks_today} suffix="次" />
            <Text type="secondary">今日 Token {tokens(s.tokens_today)}</Text>
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="本月模型花费" value={s.cost_month} prefix="¥" precision={0} />
            <Progress percent={Math.round((s.cost_month / s.budget_month) * 100)} size="small"
              format={() => `预算 ${yuan(s.budget_month)}`} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card>
            <Statistic title="今日越权拦截" value={s.denied_today} suffix="次" styles={{ content: { color: '#e03131' } }} />
            <Text type="secondary">待审批动作 {s.pending_approvals} 个</Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="近 14 天用量趋势">
            <EChart option={trendOption} height={300} />
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title="本月花费 · 按部门">
            <EChart option={deptOption} height={300} />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}>
          <Card title="GPU 能力节点" extra={<Text type="secondary">全公司共享</Text>}>
            <Space orientation="vertical" size={16} style={{ width: '100%' }}>
              {data.gpu_nodes.map((n) => (
                <div key={n.id}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Text strong>{n.name}</Text>
                    <StatusTag value={n.status} />
                  </div>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {n.gpu} · 排队 {n.queue} · 今日 {n.jobs_today} 个任务 · {n.workflows.join(' / ')}
                  </Text>
                  <Progress percent={n.utilization} size="small" status={n.utilization > 80 ? 'exception' : 'normal'}
                    format={(p) => `${p}%`} />
                </div>
              ))}
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={<><ClockCircleOutlined /> 待员工确认的动作</>}>
            {data.pending.length === 0 ? <Empty description="没有待确认的动作" /> : (
              <Space orientation="vertical" size={12} style={{ width: '100%' }}>
                {data.pending.map((p) => (
                  <div key={p.trace_id + p.tool} style={{ cursor: 'pointer' }} onClick={() => nav(`/audit?trace=${p.trace_id}`)}>
                    <div><Text strong>{p.member}</Text> <Text type="secondary">· {p.dept_name} · {fromNow(p.time)}</Text></div>
                    <Text style={{ fontSize: 13 }}>{p.detail}</Text>
                  </div>
                ))}
              </Space>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={8}>
          <Card title={<><StopOutlined /> 最近的越权拦截</>} extra={<a onClick={() => nav('/audit?outcome=被拦截')}>全部</a>}>
            <Space orientation="vertical" size={12} style={{ width: '100%' }}>
              {data.recent_denied.map((t) => (
                <div key={t.id} style={{ cursor: 'pointer' }} onClick={() => nav(`/audit?trace=${t.id}`)}>
                  <div><Text strong>{t.member}</Text> <Text type="secondary">· {t.dept_name} · {fmtTime(t.started_at)}</Text></div>
                  <Text style={{ fontSize: 13 }}>{t.summary}</Text>
                  {t.channel !== '官方 agent' && <Text type="warning" style={{ fontSize: 12 }}>（{t.channel}）</Text>}
                </div>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col span={24}>
          <Card size="small">
            <Space size={32} wrap>
              <Text>岗位包：<Text strong>{s.role_packs_live}</Text> 个已上线 / 共 {s.role_packs_total} 个</Text>
              <Text>技能：<Text strong>{s.skills}</Text> 个</Text>
              <Text>知识文档：<Text strong>{s.knowledge_docs}</Text> 份</Text>
              <Text type="secondary">权限在中枢强制执行，与提示词无关；所有调用全程留痕</Text>
            </Space>
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
