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
  backend_ready: boolean;
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
  firmware_ver: string;
  focal_position: number | null;
  auto_power_off: boolean;
  heater_enable: boolean;
  balance_angle: number | null;
  compass_direction: number | null;
  charge_status: string;
  battery_temp: number | null;
  wifi_signal: string;
  is_master: boolean;
  connected_clients: unknown[];
  schedule_state: string;
}

export interface ScheduleItem {
  action: string;
  params: Record<string, unknown>;
  schedule_item_id: string;
  state?: string;
}

export interface ScheduleData {
  state?: string;
  list?: ScheduleItem[];
  schedule_id?: string;
  [key: string]: unknown;
}

export interface LiveExposure {
  exp_ms: number;
  gain: number;
}

export interface GuestModeState {
  firmware_ver_int: number;
  guest_mode: boolean;
  client_master: boolean;
  master_index: number;
  client_list: string[];
}

export interface MosaicRequest {
  target_name: string;
  ra: string;
  dec: string;
  is_j2000?: boolean;
  ra_num?: number;
  dec_num?: number;
  panel_overlap_percent?: number;
  panel_time_sec?: number;
  gain?: number;
  is_use_lp_filter?: boolean;
  is_use_autofocus?: boolean;
  num_tries?: number;
  retry_wait_s?: number;
  stack_type?: string;
  federation_mode?: string;
  max_devices?: number;
}

export interface EventState {
  state?: string;
  error?: string;
  percent?: number;
  position?: number;
  eq_offset_alt?: number;
  eq_offset_az?: number;
  cur_scheduler_item?: { type?: string };
  stacked_frame?: number;
  dropped_frame?: number;
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
    startup: (devNum: number, params: Record<string, unknown>) =>
      post(`/api/v1/devices/${devNum}/startup`, params),
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
    events: (devNum: number) => get<Record<string, EventState>>(`/api/v1/devices/${devNum}/events`),
    guestmode: {
      get: (devNum: number) => get<GuestModeState>(`/api/v1/devices/${devNum}/guestmode`),
      grab: (devNum: number) => post(`/api/v1/devices/${devNum}/guestmode/grab`),
      release: (devNum: number) => post(`/api/v1/devices/${devNum}/guestmode/release`),
    },
    mosaic: {
      start: (devNum: number, body: MosaicRequest) =>
        post(`/api/v1/devices/${devNum}/mosaic/start`, body),
    },
    schedule: {
      get: (devNum: number) => get<ScheduleData>(`/api/v1/devices/${devNum}/schedule`),
      clear: (devNum: number) => del(`/api/v1/devices/${devNum}/schedule`),
      addItem: (devNum: number, action: string, params: Record<string, unknown> = {}) =>
        post(`/api/v1/devices/${devNum}/schedule/item`, { action, params }),
      insertItem: (devNum: number, action: string, params: Record<string, unknown>, before_id: string) =>
        post(`/api/v1/devices/${devNum}/schedule/item/insert`, { action, params, before_id }),
      deleteItem: (devNum: number, itemId: string) =>
        del(`/api/v1/devices/${devNum}/schedule/item/${encodeURIComponent(itemId)}`),
      setState: (devNum: number, state: "start" | "stop" | "pause") =>
        post(`/api/v1/devices/${devNum}/schedule/state?state=${encodeURIComponent(state)}`),
    },
  },
};
