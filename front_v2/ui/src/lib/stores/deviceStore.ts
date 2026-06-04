import { writable, derived, get } from "svelte/store";
import type { DeviceInfo, DeviceStatus } from "../api";
import { api } from "../api";

// Active device selection
export const activeDevNum = writable<number>(1);

// Device list (from /api/v1/devices)
export const deviceList = writable<DeviceInfo[]>([]);

// Per-device status, keyed by device_num
export const deviceStatuses = writable<Record<number, DeviceStatus>>({});

// Derived: status of the active device
export const activeDeviceStatus = derived(
  [activeDevNum, deviceStatuses],
  ([$devNum, $statuses]) => $statuses[$devNum] ?? null,
);

// Derived: whether the active device is connected
export const isConnected = derived(
  activeDeviceStatus,
  ($status) => $status?.is_connected ?? false,
);

// WebSocket connection, one per device
const _sockets: Record<number, WebSocket> = {};

// Status poll timers, one per device
const _pollTimers: Record<number, ReturnType<typeof setTimeout>> = {};

function wsUrl(devNum: number): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/${devNum}`;
}

export function connectDevice(devNum: number): void {
  if (_sockets[devNum]?.readyState === WebSocket.OPEN) return;

  const ws = new WebSocket(wsUrl(devNum));
  _sockets[devNum] = ws;

  ws.onmessage = (e) => {
    let msg: { type: string; payload: unknown };
    try {
      msg = JSON.parse(e.data);
    } catch {
      return;
    }

    switch (msg.type) {
      case "connected":
      case "ping":
        break;
      default:
        // Push every event into the status store so components can react.
        // Full status snapshot arrives as "device_status" type.
        deviceStatuses.update((prev) => {
          const current = prev[devNum] ?? ({} as DeviceStatus);
          if (msg.type === "device_status" && typeof msg.payload === "object") {
            return { ...prev, [devNum]: { ...current, ...(msg.payload as object) } };
          }
          return prev;
        });
    }
  };

  ws.onerror = () => console.warn(`WS error for device ${devNum}`);

  ws.onclose = () => {
    delete _sockets[devNum];
    // Reconnect after 3 s
    setTimeout(() => connectDevice(devNum), 3000);
  };
}

export function disconnectDevice(devNum: number): void {
  _sockets[devNum]?.close();
  delete _sockets[devNum];
  clearTimeout(_pollTimers[devNum]);
  delete _pollTimers[devNum];
}

// Poll device status and reschedule. Uses 5 s when offline, 15 s when online.
async function schedulePoll(devNum: number): Promise<void> {
  let connected = false;
  try {
    const status = await api.devices.status(devNum);
    deviceStatuses.update((prev) => ({ ...prev, [devNum]: status }));
    connected = status.is_connected;
  } catch {
    // Backend unreachable (e.g. service restarting) — drop to loading state,
    // not "offline", so the UI shows the initializing spinner rather than
    // implying the telescope itself is the problem.
    deviceStatuses.update((prev) => {
      const next = { ...prev };
      delete next[devNum];
      return next;
    });
  }
  // Keep deviceList in sync so the Nav dot reflects current connectivity
  deviceList.update((list) =>
    list.map((d) => (d.device_num === devNum ? { ...d, is_connected: connected } : d)),
  );
  _pollTimers[devNum] = setTimeout(
    () => schedulePoll(devNum),
    connected ? 15_000 : 5_000,
  );
}

function startStatusPolling(devNum: number): void {
  clearTimeout(_pollTimers[devNum]);
  schedulePoll(devNum);
}

// Load the device list and connect to all devices
export async function initDevices(): Promise<void> {
  try {
    const devices = await api.devices.list();
    deviceList.set(devices);

    // Set active device to the first connected one
    const firstConnected = devices.find((d) => d.is_connected);
    if (firstConnected) activeDevNum.set(firstConnected.device_num);

    // Start WS connections and status polling (poll does the initial fetch)
    for (const d of devices) {
      connectDevice(d.device_num);
      startStatusPolling(d.device_num);
    }
  } catch (err) {
    console.error("initDevices:", err);
  }
}
