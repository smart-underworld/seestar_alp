import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus, DeviceInfo } from "../lib/api";

vi.mock("../lib/stores/deviceStore", () => ({
  activeDeviceStatus: writable<DeviceStatus | null>(null),
  isConnected: writable<boolean>(false),
  activeDevNum: writable<number>(1),
  deviceList: writable<DeviceInfo[]>([]),
  deviceStatuses: writable<Record<number, DeviceStatus>>({}),
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Home from "./Home.svelte";

const mockActiveDeviceStatus = deviceStore.activeDeviceStatus as ReturnType<typeof writable<DeviceStatus | null>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;
const mockDeviceList = deviceStore.deviceList as ReturnType<typeof writable<DeviceInfo[]>>;

const DEVICE: DeviceInfo = {
  device_num: 1,
  name: "Seestar S50",
  ip_address: "192.168.1.42",
  is_connected: true,
};

const BASE_STATUS: DeviceStatus = {
  device_num: 1,
  is_connected: true,
  backend_ready: true,
  view_state: "Idle",
  mode: "",
  stage: "",
  target: "",
  stacked: "",
  failed: "",
  mount_mode: "Alt Azimuth",
  free_storage: "32.0 GB / 64.0 GB",
  battery_capacity: 80,
  temp: 22.5,
  ra: 10.75,
  dec: -5.123,
  schedule: null,
  firmware_ver: "3.14",
  focal_position: 1500,
  auto_power_off: true,
  heater_enable: false,
  balance_angle: 4,
  compass_direction: 180,
  charge_status: "discharging",
  battery_temp: 24.6,
  wifi_signal: "-65dBm",
  is_master: true,
  connected_clients: [],
  schedule_state: "",
  guest_mode_available: true,
};

beforeEach(() => {
  mockDeviceList.set([]);
  mockActiveDevNum.set(1);
  mockActiveDeviceStatus.set(null);
});

describe("Home — initializing / no status", () => {
  it("shows the initializing card when there is no status yet", () => {
    render(Home);
    expect(screen.getByText("Initializing…")).toBeInTheDocument();
  });

  it("shows the initializing card when backend_ready is false", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, backend_ready: false });
    render(Home);
    expect(screen.getByText("Initializing…")).toBeInTheDocument();
  });

  it("falls back to 'Telescope' as the heading when no device is configured", () => {
    render(Home);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Telescope");
  });
});

describe("Home — offline state", () => {
  beforeEach(() => {
    mockDeviceList.set([{ ...DEVICE, is_connected: false }]);
    mockActiveDeviceStatus.set({ ...BASE_STATUS, is_connected: false });
  });

  it("shows the offline card when the device is disconnected", () => {
    render(Home);
    expect(screen.getByText("Telescope Offline")).toBeInTheDocument();
    expect(screen.getByText(/is not reachable/)).toBeInTheDocument();
  });

  it("mentions the device name in the offline description and the page title", () => {
    render(Home);
    const matches = screen.getAllByText(/seestar s50/i);
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });
});

describe("Home — connected state with status", () => {
  beforeEach(() => {
    mockDeviceList.set([DEVICE]);
    mockActiveDeviceStatus.set(BASE_STATUS);
  });

  it("shows the device name as page title and IP as subtitle", () => {
    render(Home);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Seestar S50");
    expect(screen.getByText("192.168.1.42")).toBeInTheDocument();
  });

  it("renders the State and Mount cards", () => {
    render(Home);
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(screen.getByText("Alt Azimuth")).toBeInTheDocument();
  });

  it("renders battery percentage, temperature and free storage", () => {
    render(Home);
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText(/22\.5°C/)).toBeInTheDocument();
    expect(screen.getByText(/32\.0 GB \/ 64\.0 GB/)).toBeInTheDocument();
  });

  it("renders RA/Dec coordinates with sign formatting", () => {
    render(Home);
    expect(screen.getByText(/10\.75000/)).toBeInTheDocument();
    expect(screen.getByText(/-5\.12300/)).toBeInTheDocument();
  });

  it("renders the Telescope card fields", () => {
    render(Home);
    expect(screen.getByText("3.14")).toBeInTheDocument();
    expect(screen.getByText("1500")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("180")).toBeInTheDocument();
    expect(screen.getByText("On")).toBeInTheDocument(); // Auto Off
    expect(screen.getByText("Off")).toBeInTheDocument(); // Heater
  });

  it("shows a placeholder dash for unknown balance/compass/firmware fields", () => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      balance_angle: null,
      compass_direction: null,
      firmware_ver: "",
      charge_status: "",
    });
    render(Home);
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});

describe("Home — capture progress", () => {
  beforeEach(() => {
    mockDeviceList.set([DEVICE]);
  });

  it("shows the stacked count and failed frames when imaging is active", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 42, failed: 3 });
    const { container } = render(Home);

    const bigValue = container.querySelector(".big-value.success");
    expect(bigValue).toHaveTextContent("42");
    expect(screen.getByText((_, el) => el?.textContent?.trim() === "3 failed")).toBeInTheDocument();
  });

  it("shows an idle placeholder when there is no active session", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: "", failed: "" });
    render(Home);
    expect(screen.getByText("No active imaging session")).toBeInTheDocument();
  });

  it("shows the target name and mode/stage sub-line while working", () => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      target: "M42",
      view_state: "Working",
      mode: "star",
      stage: "stacking",
    });
    render(Home);
    expect(screen.getByText(/M42/)).toBeInTheDocument();
    expect(screen.getByText(/star\s*·\s*stacking/)).toBeInTheDocument();
  });

  it("shows a schedule-state badge when present", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "Running" });
    render(Home);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });
});
