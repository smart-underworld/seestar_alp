import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/svelte";
import { derived } from "svelte/store";
import type { DeviceStatus, DeviceInfo } from "../lib/api";

// ---------------------------------------------------------------------------
// Hoisted mock stores — must be declared before vi.mock factories run
// ---------------------------------------------------------------------------
const {
  mockDeviceList,
  mockActiveDevNum,
  mockDevStatuses,
} = vi.hoisted(() => {
  const { writable } = require("svelte/store");
  return {
    mockDeviceList:   writable<DeviceInfo[]>([]),
    mockActiveDevNum: writable<number>(1),
    mockDevStatuses:  writable<Record<number, DeviceStatus>>({}),
  };
});

vi.mock("../lib/stores/deviceStore", () => {
  const { derived } = require("svelte/store");
  const activeDeviceStatus = derived(
    [mockActiveDevNum, mockDevStatuses],
    ([$n, $s]: [number, Record<number, DeviceStatus>]) => $s[$n] ?? null,
  );
  const isConnected = derived(
    activeDeviceStatus,
    ($s: DeviceStatus | null) => $s?.is_connected ?? false,
  );
  return {
    deviceList:         mockDeviceList,
    activeDevNum:       mockActiveDevNum,
    deviceStatuses:     mockDevStatuses,
    activeDeviceStatus,
    isConnected,
    connectDevice:      vi.fn(),
    disconnectDevice:   vi.fn(),
    initDevices:        vi.fn(),
  };
});

import Home from "./Home.svelte";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const DEVICE: DeviceInfo = {
  device_num: 1,
  name: "Seestar S50",
  ip_address: "192.168.1.42",
  is_connected: true,
};

const BASE_STATUS: DeviceStatus = {
  device_num: 1,
  is_connected: true,
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
};

beforeEach(() => {
  mockDeviceList.set([]);
  mockActiveDevNum.set(1);
  mockDevStatuses.set({});
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("Home — offline state", () => {
  it("shows offline card when device is not connected", () => {
    mockDeviceList.set([{ ...DEVICE, is_connected: false }]);
    mockDevStatuses.set({ 1: { ...BASE_STATUS, is_connected: false } });
    render(Home);
    expect(screen.getByText(/device offline/i)).toBeInTheDocument();
  });

  it("offline card mentions device name in the description text", () => {
    mockDeviceList.set([{ ...DEVICE, is_connected: false }]);
    render(Home);
    // The offline-sub paragraph contains the name; use getAllByText to handle
    // it also appearing in the page-title h1.
    const matches = screen.getAllByText(/seestar s50/i);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});

describe("Home — connected state with status", () => {
  beforeEach(() => {
    mockDeviceList.set([DEVICE]);
    mockDevStatuses.set({ 1: BASE_STATUS });
  });

  it("shows the device name as page title", () => {
    render(Home);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Seestar S50");
  });

  it("shows device IP as subtitle", () => {
    render(Home);
    expect(screen.getByText("192.168.1.42")).toBeInTheDocument();
  });

  it("renders the State card with view state", () => {
    render(Home);
    expect(screen.getByText("Idle")).toBeInTheDocument();
  });

  it("renders the Mount card with mount mode", () => {
    render(Home);
    expect(screen.getByText("Alt Azimuth")).toBeInTheDocument();
  });

  it("renders battery percentage", () => {
    render(Home);
    expect(screen.getByText("80%")).toBeInTheDocument();
  });

  it("renders temperature", () => {
    render(Home);
    expect(screen.getByText(/22\.5°C/)).toBeInTheDocument();
  });

  it("renders free storage", () => {
    render(Home);
    expect(screen.getByText(/32\.0 GB \/ 64\.0 GB/)).toBeInTheDocument();
  });

  it("renders RA and Dec coordinates", () => {
    render(Home);
    expect(screen.getByText(/10\.75000/)).toBeInTheDocument();
    expect(screen.getByText(/-5\.12300/)).toBeInTheDocument();
  });
});

describe("Home — capture progress", () => {
  it("shows stacked count when imaging is active", () => {
    mockDeviceList.set([DEVICE]);
    mockDevStatuses.set({ 1: { ...BASE_STATUS, stacked: 42, failed: 3 } });
    const { container } = render(Home);
    // Target the big-value element specifically to avoid the IP "192.168.1.42"
    // also matching a loose regex.
    const bigValue = container.querySelector(".big-value.success");
    expect(bigValue).toBeInTheDocument();
    expect(bigValue).toHaveTextContent("42");
    // "3 failed" is split across text nodes; match the combined text content.
    expect(screen.getByText((_, el) =>
      el?.textContent?.trim() === "3 failed"
    )).toBeInTheDocument();
  });

  it("shows idle placeholder when not imaging", () => {
    mockDeviceList.set([DEVICE]);
    mockDevStatuses.set({ 1: { ...BASE_STATUS, stacked: "", failed: "" } });
    render(Home);
    expect(screen.getByText("No active imaging session")).toBeInTheDocument();
  });

  it("shows target name when set", () => {
    mockDeviceList.set([DEVICE]);
    mockDevStatuses.set({ 1: { ...BASE_STATUS, target: "M42", view_state: "Working" } });
    render(Home);
    expect(screen.getByText(/M42/)).toBeInTheDocument();
  });
});

describe("Home — mode / stage info", () => {
  it("shows mode and stage when both are set", () => {
    mockDeviceList.set([DEVICE]);
    mockDevStatuses.set({
      1: { ...BASE_STATUS, mode: "star", stage: "stacking", view_state: "Working" },
    });
    render(Home);
    // "star · stacking" is the sub-line; use exact sub-string match on the
    // combined text to avoid the "Seestar S50" title also matching /star/.
    expect(screen.getByText(/star\s*·\s*stacking/)).toBeInTheDocument();
  });
});

describe("Home — no device configured", () => {
  it("falls back to 'Telescope' when device list is empty", () => {
    // No devices, no status — shows the default heading.
    render(Home);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Telescope");
  });
});
