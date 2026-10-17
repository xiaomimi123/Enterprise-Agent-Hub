import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'
import { PALETTE, useTheme, type Mode } from '../theme'

// 全站图表主题：细线、浅网格、无多余装饰。亮色 / 暗色各注册一份，切换主题时图表重新初始化
for (const mode of ['light', 'dark'] as Mode[]) {
  const p = PALETTE[mode]
  echarts.registerTheme(`hub-${mode}`, {
    color: p.series,
    backgroundColor: 'transparent',
    textStyle: { fontFamily: 'Inter, -apple-system, "PingFang SC", sans-serif', color: p.ink3 },
    categoryAxis: {
      axisLine: { lineStyle: { color: p.line } },
      axisTick: { show: false },
      axisLabel: { color: p.ink3, fontSize: 11 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: p.ink3, fontSize: 11 },
      splitLine: { lineStyle: { color: p.line2, type: [3, 3] } },
      nameTextStyle: { color: p.ink3, fontSize: 11 },
    },
    legend: { textStyle: { color: p.ink2, fontSize: 12 }, itemWidth: 10, itemHeight: 10, icon: 'roundRect', pageTextStyle: { color: p.ink3 } },
    tooltip: {
      backgroundColor: mode === 'dark' ? '#0f1512' : '#2a2722',
      borderWidth: 0,
      padding: [8, 12],
      textStyle: { color: '#f3efe4', fontSize: 12 },
      extraCssText: 'border-radius:9px;box-shadow:0 8px 24px -6px rgba(0,0,0,.35);',
      axisPointer: { lineStyle: { color: p.ink4 }, shadowStyle: { color: mode === 'dark' ? 'rgba(255,255,255,0.04)' : 'rgba(35,33,28,0.04)' } },
    },
  })
}

/** ECharts 的轻量封装：option 变化时更新，容器尺寸变化时自适应，主题切换时重建 */
export default function EChart({ option, height = 280 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts>(null)
  const optionRef = useRef(option)
  const { mode } = useTheme()

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current, `hub-${mode}`)
    chart.current.setOption(optionRef.current, true)
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
    }
  }, [mode])

  useEffect(() => {
    optionRef.current = option
    chart.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}

/** 面积图渐变（color 必须是 #rrggbb） */
export const areaGradient = (color: string, top = 0.22) =>
  new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: color + Math.round(top * 255).toString(16).padStart(2, '0') },
    { offset: 1, color: color + '00' },
  ])
