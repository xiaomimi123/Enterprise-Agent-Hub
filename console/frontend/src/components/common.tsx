import { Tag } from 'antd'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'
import { useCallback, useEffect, useState } from 'react'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

/** 简单的数据请求 hook：返回数据、加载状态、错误和刷新函数 */
export function useRequest<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  const run = useCallback(() => {
    setLoading(true)
    fn()
      .then((d) => {
        setData(d)
        setError(undefined)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(run, [run])
  return { data, loading, error, reload: run, setData }
}

export const fromNow = (t: string) => dayjs(t).fromNow()
export const fmtTime = (t: string) => dayjs(t).format('MM-DD HH:mm')
export const fmtSec = (t: string) => dayjs(t).format('HH:mm:ss')
export const yuan = (n: number) => `¥${n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
export const tokens = (n: number) =>
  n >= 1e8 ? `${(n / 1e8).toFixed(2)} 亿` : n >= 1e4 ? `${(n / 1e4).toFixed(1)} 万` : `${n}`

const COLORS: Record<string, string> = {
  // 状态
  已上线: 'green', 已发布: 'green', 在线: 'green', 成功: 'green', 通过: 'green', 已索引: 'green', 空闲: 'green',
  测试中: 'blue', 规划中: 'default', 草稿: 'default', 离线: 'default', 索引中: 'processing', 忙碌: 'orange',
  未安装: 'warning', 待审批: 'gold', 待确认: 'gold',
  被拦截: 'red', 拒绝: 'red',
  // 密级 / 风险
  公开: 'cyan', 内部: 'blue', 机密: 'magenta',
  只读: 'green', 需确认: 'gold', 需二次确认: 'red',
  关闭: 'default',
}

export function StatusTag({ value }: { value: string }) {
  return <Tag color={COLORS[value] ?? 'default'}>{value}</Tag>
}
