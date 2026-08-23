// Thin fetch wrapper for the recoup API (core/api, mounted onto
// core/ingest/webhook_app.py). Base URL is read from VITE_API_BASE_URL -
// see dashboard/.env.example - defaulting to the local `recoup serve`
// address so `npm run dev` works out of the box against a locally running
// API without any configuration.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText)
    throw new ApiError(resp.status, text || resp.statusText)
  }
  return (await resp.json()) as T
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export { API_BASE_URL }
