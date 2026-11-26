import type { AxiosResponse } from 'axios'
import request from '@/utils/request'

export interface AdminMonitorStats {
  current_jobs: number
  total_jobs: number
  total_users: number
}

export interface AdminMonitorJob {
  id: string
  owner_user_id: string
  owner_email: string
  owner_username: string
  job_type: string
  status: string
  priority: number
  params: Record<string, any>
  summary: Record<string, any>
  is_deleted: boolean
  deleted_at?: string | null
  created_at: string
  updated_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface AdminMonitorResponse {
  stats: AdminMonitorStats
  total_matched: number
  items: AdminMonitorJob[]
}

export async function getAdminMonitor(params?: {
  email?: string
  status?: string
  limit?: number
  offset?: number
}): Promise<AxiosResponse<AdminMonitorResponse>> {
  return request.get<AdminMonitorResponse>('/api/v1/admin/monitor', {
    params: {
      email: params?.email || undefined,
      status: params?.status || undefined,
      limit: params?.limit ?? 200,
      offset: params?.offset ?? 0,
    },
  })
}
