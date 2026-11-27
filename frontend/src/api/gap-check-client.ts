/** 缺测核验 API 客户端：补测提交、受理、凭据查询与干燥台领料。 */
import { request } from './client'

const API = '/api/gap_check'

export interface Supplement {
  补测ID: number
  来源: string
  补测数值: string
  签字人: string
  设备编号: string
  请求号: string
  翻堆时段: string
  状态: string
  受理结论: string
  提交时间: string
}

export interface GapCredential {
  核验单ID: number
  批次号: string
  发酵记录ID: number
  翻堆时段: string
  缺测项目: string
  状态: string
  可转干燥: boolean
  核验单版本: number
  受理补测: Supplement | null
  补测列表: Supplement[]
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  const data = await response.json()
  if (!response.ok) throw new Error(data?.detail || '缺测核验操作失败')
  return data as T
}

export async function submitSupplement(
  ticketId: number,
  payload: { 来源: string; 补测数值: string; 签字人?: string; 设备编号?: string; 请求号?: string; 翻堆时段?: string },
): Promise<{ ok: boolean; message: string; entry: Record<string, any> }> {
  return postJson(`${API}/${ticketId}/supplements`, payload)
}

export async function acceptSupplement(
  ticketId: number,
  supplementId: number,
): Promise<{ ok: boolean; message: string; entry: Record<string, any> }> {
  return postJson(`${API}/${ticketId}/accept`, { 补测ID: supplementId })
}

export async function fetchCredential(ticketId: number): Promise<{ ok: boolean; credential: GapCredential }> {
  const response = await request(`${API}/${ticketId}/credential`)
  const data = await response.json()
  if (!response.ok) throw new Error(data?.detail || '凭据查询失败')
  return data
}

export async function claimDrying(
  fermentationId: number,
  values: Record<string, string> = {},
  requestId = '',
): Promise<{ ok: boolean; message: string; entry: Record<string, any> }> {
  return postJson(`${API}/drying-claim`, { 发酵记录ID: fermentationId, 请求号: requestId, values })
}
