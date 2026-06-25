import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const { mockStatus, mockBalance } = vi.hoisted(() => ({
  mockStatus: vi.fn(),
  mockBalance: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      status: mockStatus,
      balanceSensor: mockBalance,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Stats from "./Stats.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

const HANG = new Promise<never>(() => {});

const STATUS: DeviceStatus = {
  device_num: 1, is_connected: true, backend_ready: true,
  view_state: "Idle", mode: "", stage: "", target: "", stacked: "", failed: "",
  mount_mode: "Alt Azimuth", free_storage: "32.0 GB / 64.0 GB",
  battery_capacity: 75, temp: 22.5, ra: 10.75, dec: -5.12,
  schedule: null, firmware_ver: "3.14", focal_position: 1500,
  auto_power_off: true, heater_enable: false, balance_angle: 4,
  compass_direction: 180, charge_status: "discharging", battery_temp: 24.6,
  wifi_signal: "-65dBm", is_master: true, connected_clients: [],
  schedule_state: "", guest_mode_available: true,
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockStatus.mockReset();
  mockBalance.mockReset();
  mockStatus.mockReturnValue(HANG);
  mockBalance.mockReturnValue(HANG);
});

describe("Stats — offline", () => {
  it("shows offline message when not connected", () => {
    render(Stats);
    expect(screen.getByText("Device 1 is offline.")).toBeInTheDocument();
  });
});

describe("Stats — loading", () => {
  it("shows loading placeholder while fetch is pending", () => {
    mockIsConnected.set(true);
    render(Stats);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});

describe("Stats — error", () => {
  it("shows error alert when status fetch fails", async () => {
    mockIsConnected.set(true);
    mockStatus.mockRejectedValue(new Error("network error"));
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText(/network error/)).toBeInTheDocument(),
    );
  });
});

describe("Stats — connected with data", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
    mockStatus.mockResolvedValue(STATUS);
  });

  it("renders the Device Status panel", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Device Status")).toBeInTheDocument(),
    );
  });

  it("shows mount mode row", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Mount Mode")).toBeInTheDocument(),
    );
    expect(screen.getByText("Alt Azimuth")).toBeInTheDocument();
  });

  it("shows battery percentage with bar", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Battery")).toBeInTheDocument(),
    );
    expect(screen.getByText("75 %")).toBeInTheDocument();
  });

  it("shows temperature row", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Temp")).toBeInTheDocument(),
    );
    expect(screen.getByText("22.5 °C")).toBeInTheDocument();
  });

  it("shows RA and Dec formatted rows", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("RA")).toBeInTheDocument(),
    );
    expect(screen.getByText(/10\.7500 h/)).toBeInTheDocument();
    expect(screen.getByText(/-5\.1200°/)).toBeInTheDocument();
  });

  it("shows firmware version row", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Firmware")).toBeInTheDocument(),
    );
    expect(screen.getByText("3.14")).toBeInTheDocument();
  });

  it("shows focal position row", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Focal Position")).toBeInTheDocument(),
    );
    expect(screen.getByText("1500")).toBeInTheDocument();
  });

  it("shows Orientation panel", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Orientation")).toBeInTheDocument(),
    );
  });

  it("shows free storage with bar", async () => {
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Free Storage")).toBeInTheDocument(),
    );
    expect(screen.getByText("32.0 GB / 64.0 GB")).toBeInTheDocument();
  });

  it("colors the Free Storage bar green when plenty of space is free", async () => {
    mockStatus.mockResolvedValue({ ...STATUS, free_storage: "95.0 GB / 100.0 GB" });
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Free Storage")).toBeInTheDocument(),
    );
    const fill = screen
      .getByText("Free Storage")
      .closest(".stat-row")
      ?.querySelector(".metric-bar-fill");
    expect(fill).toHaveClass("success");
    expect(fill).not.toHaveClass("danger");
  });

  it("colors the Free Storage bar red when space is nearly full", async () => {
    mockStatus.mockResolvedValue({ ...STATUS, free_storage: "5.0 GB / 100.0 GB" });
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Free Storage")).toBeInTheDocument(),
    );
    const fill = screen
      .getByText("Free Storage")
      .closest(".stat-row")
      ?.querySelector(".metric-bar-fill");
    expect(fill).toHaveClass("danger");
    expect(fill).not.toHaveClass("success");
  });

  it("shows mode and stage rows only when view_state is not Idle", async () => {
    mockStatus.mockResolvedValue({
      ...STATUS,
      view_state: "Working",
      mode: "star",
      stage: "stacking",
      target: "M42",
    });
    render(Stats);
    await waitFor(() =>
      expect(screen.getByText("Mode")).toBeInTheDocument(),
    );
    expect(screen.getByText("star")).toBeInTheDocument();
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByText("M42")).toBeInTheDocument();
  });
});
