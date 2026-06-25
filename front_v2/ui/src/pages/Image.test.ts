import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const { mockImageStart, mockImageStop, mockEvents } = vi.hoisted(() => ({
  mockImageStart: vi.fn(),
  mockImageStop: vi.fn(),
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
      image: { start: mockImageStart, stop: mockImageStop },
      events: mockEvents,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Image from "./Image.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;
const mockActiveDeviceStatus = deviceStore.activeDeviceStatus as ReturnType<typeof writable<DeviceStatus | null>>;

const BASE_STATUS: DeviceStatus = {
  device_num: 1, is_connected: true, backend_ready: true,
  view_state: "Idle", mode: "", stage: "", target: "", stacked: "", failed: "",
  mount_mode: "", free_storage: "", battery_capacity: null, temp: null,
  ra: null, dec: null, schedule: null, firmware_ver: "", model: "", focal_position: null,
  auto_power_off: false, heater_enable: false, balance_angle: null,
  compass_direction: null, charge_status: "", battery_temp: null,
  wifi_signal: "", is_master: true, connected_clients: [],
  schedule_state: "", guest_mode_available: false,
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockActiveDeviceStatus.set(null);
  mockImageStart.mockReset();
  mockImageStop.mockReset();
  mockEvents.mockReset();
  mockImageStart.mockResolvedValue({});
  mockImageStop.mockResolvedValue({});
  mockEvents.mockResolvedValue({});
});

describe("Image — offline", () => {
  it("shows offline message when not connected", () => {
    render(Image);
    expect(screen.getByText(/Device 1 is offline/)).toBeInTheDocument();
  });

  it("hides form when offline", () => {
    render(Image);
    expect(screen.queryByLabelText("Exposure (ms)")).not.toBeInTheDocument();
  });
});

describe("Image — form", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("renders target name, exposure, gain, count inputs", () => {
    render(Image);
    expect(screen.getByLabelText("Target Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Exposure (ms)")).toBeInTheDocument();
    expect(screen.getByLabelText("Gain")).toBeInTheDocument();
    expect(screen.getByLabelText("Frame Count")).toBeInTheDocument();
  });

  it("renders Start and Stop buttons", () => {
    render(Image);
    expect(screen.getByRole("button", { name: /▶ Start/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /⏹ Stop/ })).toBeInTheDocument();
  });

  it("shows param summary line with exposure, gain, and continuous mode", () => {
    render(Image);
    // The summary line is the only element containing all three on one line
    expect(screen.getByText(/Continuous/)).toBeInTheDocument();
  });
});

describe("Image — start/stop", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("calls image.start with default params when Start is submitted", async () => {
    render(Image);
    screen.getByRole("button", { name: /▶ Start/ }).click();
    await waitFor(() =>
      expect(mockImageStart).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ exp_ms: 10000, gain: 80, count: 0 }),
      ),
    );
  });

  it("shows success status after start succeeds", async () => {
    render(Image);
    screen.getByRole("button", { name: /▶ Start/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/Imaging session started/)).toBeInTheDocument(),
    );
  });

  it("shows error when start fails", async () => {
    mockImageStart.mockRejectedValue(new Error("camera busy"));
    render(Image);
    screen.getByRole("button", { name: /▶ Start/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/camera busy/)).toBeInTheDocument(),
    );
  });

  it("calls image.stop when Stop is clicked", async () => {
    render(Image);
    screen.getByRole("button", { name: /⏹ Stop/ }).click();
    await waitFor(() => expect(mockImageStop).toHaveBeenCalledWith(1));
  });

  it("shows stopped status after stop succeeds", async () => {
    render(Image);
    screen.getByRole("button", { name: /⏹ Stop/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/Imaging stopped/)).toBeInTheDocument(),
    );
  });
});

describe("Image — session progress", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("shows session progress card when stacked count is set", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 42, failed: 0 });
    render(Image);
    expect(screen.getByText("Session Progress")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("stacked")).toBeInTheDocument();
  });

  it("shows failed count when non-zero", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 10, failed: 3 });
    render(Image);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("shows target name in progress card", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 5, failed: 0, target: "M42" });
    render(Image);
    expect(screen.getByText(/M42/)).toBeInTheDocument();
  });

  it("hides progress card when stacked is empty", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: "", failed: "" });
    render(Image);
    expect(screen.queryByText("Session Progress")).not.toBeInTheDocument();
  });
});
