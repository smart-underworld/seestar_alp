import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const { mockGoto, mockEvents } = vi.hoisted(() => ({
  mockGoto: vi.fn(),
  mockEvents: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable<DeviceStatus | null>(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      goto: mockGoto,
      events: mockEvents,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Goto from "./Goto.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;
const mockActiveDeviceStatus = deviceStore.activeDeviceStatus as ReturnType<typeof writable<DeviceStatus | null>>;

const BASE_STATUS: DeviceStatus = {
  device_num: 1, is_connected: true, backend_ready: true,
  view_state: "Idle", mode: "", stage: "", target: "", stacked: "", failed: "",
  mount_mode: "Alt Azimuth", free_storage: "",
  battery_capacity: null, temp: null, ra: 10.75, dec: -5.12,
  schedule: null, firmware_ver: "", focal_position: null,
  auto_power_off: false, heater_enable: false, balance_angle: null,
  compass_direction: null, charge_status: "", battery_temp: null,
  wifi_signal: "", is_master: true, connected_clients: [],
  schedule_state: "", guest_mode_available: false,
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockActiveDeviceStatus.set(null);
  mockGoto.mockReset();
  mockEvents.mockReset();
  mockGoto.mockResolvedValue({});
  mockEvents.mockResolvedValue({});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
});

afterEach(() => vi.unstubAllGlobals());

describe("Goto — offline", () => {
  it("shows offline message when not connected", () => {
    render(Goto);
    expect(screen.getByText(/Device 1 is offline/)).toBeInTheDocument();
  });

  it("hides the form when offline", () => {
    render(Goto);
    expect(screen.queryByLabelText("Right Ascension (J2000)")).not.toBeInTheDocument();
  });
});

describe("Goto — form", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("renders RA and Dec input fields", () => {
    render(Goto);
    expect(screen.getByLabelText("Right Ascension (J2000)")).toBeInTheDocument();
    expect(screen.getByLabelText("Declination (J2000)")).toBeInTheDocument();
  });

  it("renders optional target name field", () => {
    render(Goto);
    expect(screen.getByLabelText("Target Name")).toBeInTheDocument();
  });

  it("renders GoTo and Stop buttons", () => {
    render(Goto);
    expect(screen.getByRole("button", { name: /GoTo/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();
  });
});

describe("Goto — submit", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("calls api.devices.goto when GoTo is submitted", async () => {
    render(Goto);
    const ra = screen.getByLabelText("Right Ascension (J2000)") as HTMLInputElement;
    const dec = screen.getByLabelText("Declination (J2000)") as HTMLInputElement;
    ra.value = "10h 45m";
    dec.value = "-5deg";
    ra.dispatchEvent(new Event("input"));
    dec.dispatchEvent(new Event("input"));
    await waitFor(() => expect(ra.value).toBe("10h 45m"));
    screen.getByRole("button", { name: /GoTo/ }).click();
    await waitFor(() => expect(mockGoto).toHaveBeenCalledWith(1, "10h 45m", "-5deg", ""));
  });

  it("shows success status after goto succeeds", async () => {
    render(Goto);
    const ra = screen.getByLabelText("Right Ascension (J2000)") as HTMLInputElement;
    const dec = screen.getByLabelText("Declination (J2000)") as HTMLInputElement;
    ra.value = "10h 45m"; dec.value = "-5deg";
    ra.dispatchEvent(new Event("input")); dec.dispatchEvent(new Event("input"));
    screen.getByRole("button", { name: /GoTo/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/telescope is slewing/i)).toBeInTheDocument(),
    );
  });

  it("shows error when goto fails", async () => {
    mockGoto.mockRejectedValue(new Error("slew failed"));
    render(Goto);
    const ra = screen.getByLabelText("Right Ascension (J2000)") as HTMLInputElement;
    const dec = screen.getByLabelText("Declination (J2000)") as HTMLInputElement;
    ra.value = "10h"; dec.value = "-5deg";
    ra.dispatchEvent(new Event("input")); dec.dispatchEvent(new Event("input"));
    screen.getByRole("button", { name: /GoTo/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/slew failed/)).toBeInTheDocument(),
    );
  });
});

describe("Goto — current position card", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("shows current position when status has RA", () => {
    mockActiveDeviceStatus.set(BASE_STATUS);
    render(Goto);
    expect(screen.getByText("Current Position")).toBeInTheDocument();
    expect(screen.getByText(/10\.750000°/)).toBeInTheDocument();
  });

  it("shows mount mode in position card", () => {
    mockActiveDeviceStatus.set(BASE_STATUS);
    render(Goto);
    expect(screen.getByText("Alt Azimuth")).toBeInTheDocument();
  });

  it("shows last target when status has target", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, target: "M31" });
    render(Goto);
    expect(screen.getByText("M31")).toBeInTheDocument();
  });

  it("hides position card when status is null", () => {
    render(Goto);
    expect(screen.queryByText("Current Position")).not.toBeInTheDocument();
  });
});
