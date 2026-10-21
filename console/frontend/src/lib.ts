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
export const yuan = (n: number, digits = 2) => `¥${n.toLocaleString('zh-CN', { maximumFractionDigits: digits })}`
export const tokens = (n: number) =>
  n >= 1e8 ? `${(n / 1e8).toFixed(2)} 亿` : n >= 1e4 ? `${(n / 1e4).toFixed(1)} 万` : `${n}`

export function greeting() {
  const h = new Date().getHours()
  return h < 6 ? '夜深了' : h < 11 ? '早上好' : h < 13 ? '中午好' : h < 18 ? '下午好' : '晚上好'
}

/** 部门的颜色与简称，全站统一 */
export const DEPT_META: Record<string, { color: string; short: string }> = {
  ops: { color: '#e5603f', short: '运' },
  design: { color: '#9a6ad0', short: '设' },
  video: { color: '#4f7ee0', short: '视' },
  sales: { color: '#3d9a73', short: '销' },
  cs: { color: '#2a9d8f', short: '客' },
  finance: { color: '#d9a21b', short: '财' },
  hr: { color: '#d4609f', short: '人' },
  tech: { color: '#6b74d6', short: '技' },
  ceo: { color: '#8a7a5c', short: '总' },
  all: { color: '#8b8578', short: '全' },
}

/** 浅色底：同一个颜色按比例混进透明，亮 / 暗主题都不刺眼 */
export const softOf = (color: string, pct = 16) => `color-mix(in srgb, ${color} ${pct}%, transparent)`

export const DEPT_BY_NAME: Record<string, string> = {
  运营部: 'ops', 设计部: 'design', 视频部: 'video', 销售部: 'sales', 客服部: 'cs',
  财务部: 'finance', 人事行政部: 'hr', 技术部: 'tech', 总经办: 'ceo', 全公司: 'all',
}

export const deptColor = (key: string) => (DEPT_META[key] ?? DEPT_META[DEPT_BY_NAME[key]] ?? DEPT_META.all).color

/** 状态文字 → 胶囊色调 */
export const TONE: Record<string, string> = {
  已上线: 'green', 已发布: 'green', 在线: 'green', 成功: 'green', 通过: 'green', 已索引: 'green', 空闲: 'green', 正常: 'green',
  测试中: 'blue', 索引中: 'blue', 生成中: 'blue', 已完成: 'green', 排队中: 'amber', 失败: 'red', 待索引: 'gray', 已取消: 'gray', 索引失败: 'red',
  规划中: 'gray', 草稿: 'gray', 离线: 'gray', 关闭: 'gray',
  忙碌: 'amber', 繁忙: 'amber', 未安装: 'amber', 待审批: 'amber', 待确认: 'amber', 需确认: 'amber',
  被拦截: 'red', 拒绝: 'red', 需二次确认: 'red', 机密: 'red', 异常: 'red',
  公开: 'teal', 内部: 'blue', 只读: 'green',
}

/** 复制文本。navigator.clipboard 只在 HTTPS / localhost 可用，内网 http 访问时退回 execCommand。 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 退回下面的方式
  }
  const area = Object.assign(document.createElement('textarea'), { value: text })
  area.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}
