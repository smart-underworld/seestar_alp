/**
 * Typed fetch wrappers for the front_v2 FastAPI backend.
 * Base URL is always same-origin (FastAPI serves the SPA).
 */

const BASE = "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// ---- Devices ---------------------------------------------------------------

export interface DeviceInfo {
  device_num: number;
  name: string;
  ip_address: string;
  is_connected: boolean;
}

export interface DeviceStatus {
  device_num: number;
  is_connected: boolean;
  view_state: string;
  mode: string;
  stage: string;
  target: string;
  stacked: string | number;
  failed: string | number;
  mount_mode: string;
  free_storage: string;
  battery_capacity: number | null;
  temp: number | null;
  ra: number | null;
  dec: number | null;
  schedule: unknown;
}

export interface LiveExposure {
  exp_ms: number;
  gain: number;
}

export const api = {
  devices: {
    list: () => get<DeviceInfo[]>("/api/v1/devices"),
    status: (devNum: number) => get<DeviceStatus>(`/api/v1/devices/${devNum}/status`),
    settings: {
      get: (devNum: number) => get<Record<string, unknown>>(`/api/v1/devices/${devNum}/settings`),
      save: (devNum: number, payload: Record<string, unknown>) =>
        post(`/api/v1/devices/${devNum}/settings`, { payload }),
    },
    command: (devNum: number, method: string, params: Record<string, unknown> = {}) =>
      post(`/api/v1/devices/${devNum}/command`, { method, params }),
    goto: (devNum: number, ra: string, dec: string, targetName = "", isJ2000 = true) =>
      post(`/api/v1/devices/${devNum}/goto`, { ra, dec, target_name: targetName, is_j2000: isJ2000 }),
    image: {
      start: (devNum: number, body: Record<string, unknown>) =>
        post(`/api/v1/devices/${devNum}/image/start`, body),
      stop: (devNum: number) => post(`/api/v1/devices/${devNum}/image/stop`),
      status: (devNum: number) => get(`/api/v1/devices/${devNum}/image/status`),
    },
    live: {
      startMode: (devNum: number, mode: string) =>
        post(`/api/v1/devices/${devNum}/live/mode`, { mode }),
      stopMode: (devNum: number) => del(`/api/v1/devices/${devNum}/live/mode`),
      getFocus: (devNum: number) =>
        get<{ position: number }>(`/api/v1/devices/${devNum}/live/focus`),
      moveFocus: (devNum: number, inc: number) =>
        post<{ position: number }>(`/api/v1/devices/${devNum}/live/focus`, { inc }),
      autoFocus: (devNum: number) => post(`/api/v1/devices/${devNum}/live/auto-focus`),
      getExposure: (devNum: number) =>
        get<LiveExposure>(`/api/v1/devices/${devNum}/live/exposure`),
      setExposure: (devNum: number, exp_ms: number) =>
        post(`/api/v1/devices/${devNum}/live/exposure`, { exp_ms }),
      setGain: (devNum: number, gain: number) =>
        post(`/api/v1/devices/${devNum}/live/gain`, { gain }),
    },
    schedule: {
      get: (devNum: number) => get(`/api/v1/devices/${devNum}/schedule`),
      clear: (devNum: number) => del(`/api/v1/devices/${devNum}/schedule`),
    },
  },
};
