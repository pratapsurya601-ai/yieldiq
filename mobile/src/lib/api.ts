/**
 * Mobile API client — mirrors frontend/src/lib/api.ts shape so the same
 * mental model applies on both clients.
 *
 * Differences from web:
 *  - Token persisted via expo-secure-store (Keychain / Keystore), not
 *    cookies. expo-secure-store is preferred over AsyncStorage because
 *    auth tokens are sensitive.
 *  - X-Analyses-Today / X-Analyses-Limit headers are still parsed and
 *    pushed into the auth store, matching the web behavior.
 *  - No cookie-based auth — pure Bearer.
 */

import Constants from 'expo-constants';
import * as SecureStore from 'expo-secure-store';
import { useAuthStore } from '@/store/authStore';

const TOKEN_KEY = 'yieldiq_token';

// app.json -> extra.apiBaseUrl. Falls back to prod for safety.
const API_BASE: string =
  (Constants.expoConfig?.extra?.apiBaseUrl as string | undefined) ??
  'https://api.yieldiq.in';

export async function getStoredToken(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    return null;
  }
}

export async function setStoredToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearStoredToken(): Promise<void> {
  await SecureStore.deleteItemAsync(TOKEN_KEY);
}

export interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  body?: unknown;
  // Set false for unauthenticated endpoints (login, signup, public/*).
  auth?: boolean;
  // Override base URL for tests.
  baseUrl?: string;
}

export class ApiError extends Error {
  status: number;
  data: unknown;
  constructor(status: number, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/**
 * Single fetch helper. Keep this thin — individual endpoint helpers
 * (login, getWatchlist, getAnalysis) wrap apiFetch with typed return
 * values, mirroring how frontend/src/lib/api.ts does it.
 */
export async function apiFetch<T = unknown>(
  endpoint: string,
  opts: ApiFetchOptions = {},
): Promise<T> {
  const { body, auth = true, baseUrl = API_BASE, headers, ...rest } = opts;

  const finalHeaders: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...(headers as Record<string, string> | undefined),
  };

  if (auth) {
    const token = await getStoredToken();
    if (token) finalHeaders.Authorization = `Bearer ${token}`;
  }

  const url = endpoint.startsWith('http')
    ? endpoint
    : `${baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;

  const res = await fetch(url, {
    ...rest,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Mirror analyses headers into auth store (parity with web client).
  syncAnalysesHeaders(res.headers);

  const contentType = res.headers.get('content-type') ?? '';
  const payload = contentType.includes('application/json')
    ? await res.json().catch(() => null)
    : await res.text().catch(() => null);

  if (!res.ok) {
    const detail =
      (payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as { detail: unknown }).detail)
        : null) ?? res.statusText;
    throw new ApiError(res.status, detail, payload);
  }

  return payload as T;
}

function syncAnalysesHeaders(headers: Headers): void {
  const today = headers.get('x-analyses-today') ?? headers.get('X-Analyses-Today');
  const limit = headers.get('x-analyses-limit') ?? headers.get('X-Analyses-Limit');
  if (today === null && limit === null) return;
  try {
    const s = useAuthStore.getState();
    const nextToday = today !== null ? Number(today) : s.analysesToday;
    const nextLimit = limit !== null ? Number(limit) : s.analysisLimit;
    if (Number.isFinite(nextToday) && Number.isFinite(nextLimit)) {
      useAuthStore.setState({ analysesToday: nextToday, analysisLimit: nextLimit });
    }
  } catch {
    // Don't let sync errors block responses (parity with web client).
  }
}

// ---------- Typed endpoint helpers ----------

export interface LoginResponse {
  access_token: string;
  user_id: string;
  email: string;
  tier: 'free' | 'pro' | 'enterprise';
  analyses_today?: number;
  analysis_limit?: number;
  display_name?: string | null;
  display_name_edits_remaining?: number;
  feature_flags?: Record<string, boolean>;
}

export function login(email: string, password: string) {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    auth: false,
    body: { email, password },
  });
}

export interface WatchlistItem {
  ticker: string;
  added_at?: string;
  fair_value?: number | null;
  margin_of_safety?: number | null;
  score?: number | null;
  grade?: string | null;
  current_price?: number | null;
}

export function getWatchlist() {
  return apiFetch<{ items: WatchlistItem[] }>('/api/v1/watchlist');
}

export interface AnalysisResponse {
  ticker: string;
  fair_value: number;
  margin_of_safety: number;
  score: number;
  grade: string;
  current_price?: number;
  scenarios?: Array<{ name: string; fair_value: number; weight?: number }>;
  hex_axes?: Record<string, number>;
}

export function getAnalysis(ticker: string) {
  return apiFetch<AnalysisResponse>(
    `/api/v1/analyze/${encodeURIComponent(ticker)}`,
  );
}

export function getAllTickers() {
  return apiFetch<{ tickers: Array<{ ticker: string; name: string }> }>(
    '/api/v1/public/all-tickers',
    { auth: false },
  );
}
