import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const { mockMosaicStart, mockImageStop, mockEvents } = vi.hoisted(() => ({
  mockMosaicStart: vi.fn(),
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
      image: { stop: mockImageStop },
      mosaic: { start: mockMosaicStart },
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
  mockMosaicStart.mockReset();
  mockImageStop.mockReset();
  mockEvents.mockReset();
  mockMosaicStart.mockResolvedValue({});
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
    expect(screen.queryByLabelText("RA")).not.toBeInTheDocument();
  });
});

describe("Image — form", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("renders target name, RA, Dec, gain inputs", () => {
    render(Image);
    expect(screen.getByLabelText("Target Name")).toBeInTheDocument();
    expect(screen.getByLabelText("RA")).toBeInTheDocument();
    expect(screen.getByLabelText("Dec")).toBeInTheDocument();
    expect(screen.getByLabelText("Gain")).toBeInTheDocument();
  });

  it("renders panel time and end time inputs", () => {
    render(Image);
    expect(screen.getByLabelText("Panel Time (s)")).toBeInTheDocument();
    expect(screen.getByLabelText(/End Time/)).toBeInTheDocument();
  });

  it("renders LP Filter and Auto Focus toggles", () => {
    render(Image);
    expect(screen.getByText("LP Filter")).toBeInTheDocument();
    expect(screen.getByText("Auto Focus")).toBeInTheDocument();
  });

  it("renders retry fields", () => {
    render(Image);
    expect(screen.getByLabelText("Number of Retries")).toBeInTheDocument();
    expect(screen.getByLabelText("Retry Delay (s)")).toBeInTheDocument();
  });

  it("renders Start and Stop buttons", () => {
    render(Image);
    expect(screen.getByRole("button", { name: /▶ Start/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /⏹ Stop/ })).toBeInTheDocument();
  });
});

describe("Image — start/stop", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("calls mosaic.start with default params when Start is submitted", async () => {
    render(Image);
    screen.getByRole("button", { name: /▶ Start/ }).click();
    await waitFor(() =>
      expect(mockMosaicStart).toHaveBeenCalledWith(
        1,
        expect.objectContaining({
          ra_num: 1,
          dec_num: 1,
          panel_overlap_percent: 100,
          gain: 80,
          is_use_lp_filter: false,
          is_use_autofocus: true,
          num_tries: 1,
        }),
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
    mockMosaicStart.mockRejectedValue(new Error("camera busy"));
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
