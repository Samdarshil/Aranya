import type { Alert, ChatReply, Consultation, Recommendation } from '../types';

const SESSION_KEY = 'aranya_session';
const API_OVERRIDE_KEY = 'aranya_api_base';
export type Session = { access_token: string; token_type: string; farm_id?: number };
export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

export const sessionStore = {
  get(): Session | null {
    try { return JSON.parse(localStorage.getItem(SESSION_KEY) || 'null') as Session | null; }
    catch { return null; }
  },
  set(session: Session) { localStorage.setItem(SESSION_KEY, JSON.stringify(session)); },
  clear() { localStorage.removeItem(SESSION_KEY); },
};

export function getApiBase() {
  return (localStorage.getItem(API_OVERRIDE_KEY) || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
}
export function setApiBase(base: string) { localStorage.setItem(API_OVERRIDE_KEY, base.replace(/\/$/, '')); }

async function request<T>(path: string, options: { method?: string; form?: Record<string, unknown>; query?: Record<string, unknown>; auth?: boolean } = {}): Promise<T> {
  let url: URL;
  try { url = new URL(`${getApiBase()}${path}`); }
  catch { throw new ApiError('The API address is not a valid URL. Update it in Server connection settings.', 0); }
  for (const [key, value] of Object.entries(options.query || {})) {
    if (value !== null && value !== undefined && value !== '') url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = {};
  const session = sessionStore.get();
  if (options.auth !== false && session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
  let body: FormData | undefined;
  if (options.form) {
    body = new FormData();
    for (const [key, value] of Object.entries(options.form)) if (value !== null && value !== undefined) body.append(key, value instanceof Blob ? value : String(value));
  }
  let response: Response;
  try { response = await fetch(url, { method: options.method || 'GET', headers, body }); }
  catch { throw new ApiError(`Could not reach Aranya at ${getApiBase()}. Check the server address and connection.`, 0); }
  if (!response.ok) {
    let message = response.statusText || `Request failed (${response.status})`;
    try { const payload = await response.json() as { detail?: string }; message = payload.detail || message; } catch { /* retain status text */ }
    if (response.status === 401) { sessionStore.clear(); window.dispatchEvent(new Event('aranya:session-expired')); }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  requestOtp: (phone: string, email: string) => request<{ debug_code?: string; delivered_via?: string[] }>('/api/v1/auth/request-otp', { method: 'POST', auth: false, form: { phone, email: email || null } }),
  verifyOtp: (phone: string, code: string, name: string, email: string) => request<Session>('/api/v1/auth/verify-otp', { method: 'POST', auth: false, form: { phone, code, name: name || 'New Farmer', email: email || null } }),
  cropScan: (farmId: number, fieldRef: string, cropName: string, image: File) => request<Recommendation>('/api/v1/vision/crop-scan', { method: 'POST', form: { farm_id: farmId, field_ref: fieldRef, crop_name: cropName, image, is_demo: false } }),
  livestockScan: (farmId: number, animalRef: string, species: string, image: File) => request<Recommendation>('/api/v1/vision/livestock-scan', { method: 'POST', form: { farm_id: farmId, animal_ref: animalRef, species, image, is_demo: false } }),
  weather: (farmId: number, lat: number, lng: number) => request<Recommendation>(`/api/v1/farms/${farmId}/weather`, { query: { lat, lng } }),
  soil: (farmId: number, fields: Record<string, unknown>) => request<Recommendation>(`/api/v1/farms/${farmId}/soil-test`, { method: 'POST', form: fields }),
  planning: (farmId: number, fields: Record<string, unknown>) => request<Recommendation>(`/api/v1/farms/${farmId}/planning`, { query: fields }),
  market: (farmId: number, crop_name: string, market_name: string) => request<Recommendation>(`/api/v1/farms/${farmId}/market`, { query: { crop_name, market_name } }),
  logExpense: (farmId: number, fields: Record<string, unknown>) => request<{ id: number; status: string }>(`/api/v1/farms/${farmId}/expenses`, { method: 'POST', form: fields }),
  logSale: (farmId: number, fields: Record<string, unknown>) => request<{ id: number; status: string }>(`/api/v1/farms/${farmId}/sales`, { method: 'POST', form: fields }),
  economics: (farmId: number, field_ref: string, crop_name: string) => request<Recommendation>(`/api/v1/farms/${farmId}/economics`, { query: { field_ref, crop_name } }),
  newCycle: (farmId: number, field_ref: string, new_crop_name: string) => request<{ id: number; status: string }>(`/api/v1/farms/${farmId}/crop-cycles`, { method: 'POST', form: { field_ref, new_crop_name } }),
  schemes: (farmId: number, query: Record<string, unknown>) => request<Recommendation>(`/api/v1/farms/${farmId}/schemes`, { query }),
  research: (farmId: number, query: string, crop_name: string) => request<Recommendation>(`/api/v1/farms/${farmId}/research`, { query: { query, crop_name } }),
  history: (farmId: number, field_ref: string, crop_name: string) => request<{ field_ref: string; scan_count: number; latest_status?: string; latest_affected_area_pct?: number; latest_timestamp?: string; message?: string }>(`/api/v1/farms/${farmId}/fields/${encodeURIComponent(field_ref)}/history`, { query: { crop_name } }),
  alerts: (farmId: number) => request<Alert[]>(`/api/v1/farms/${farmId}/alerts`),
  acknowledge: (farmId: number, alertId: number) => request<{ status: string }>(`/api/v1/farms/${farmId}/alerts/${alertId}/acknowledge`, { method: 'POST' }),
  consultations: (farmId: number) => request<Consultation[]>(`/api/v1/farms/${farmId}/consultations`),
  resolveConsultation: (farmId: number, consultationId: number, expert_name: string, notes: string) => request<Record<string, unknown>>(`/api/v1/farms/${farmId}/consultations/${consultationId}/resolve`, { method: 'POST', form: { expert_name, notes } }),
  outcome: (farmId: number, source_agent: string, followed_advice: boolean, outcome: string) => request<{ id: number; status: string }>(`/api/v1/farms/${farmId}/outcomes`, { method: 'POST', form: { source_agent, followed_advice, outcome } }),
  chat: (farmId: number, message: string, lat?: number, lng?: number) => request<ChatReply>(`/api/v1/farms/${farmId}/chat`, { method: 'POST', form: { message, lat, lng } }),
  voice: (farmId: number, audio: File, language_hint?: string) => request<ChatReply>(`/api/v1/farms/${farmId}/voice`, { method: 'POST', form: { audio, language_hint } }),
};
