import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

/** ECharts 的轻量封装：option 变化时更新，容器尺寸变化时自适应 */
export default function EChart({ option, height = 280 }: { option: echarts.EChartsOption; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts>(null)

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current)
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(ref.current)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(option, true)
  }, [option])

  return <div ref={ref} style={{ width: '100%', height }} />
}

export const PALETTE = ['#3b5bdb', '#12b886', '#fab005', '#f76707', '#7048e8', '#15aabf', '#e64980', '#82c91e', '#868e96']
