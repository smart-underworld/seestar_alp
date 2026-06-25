import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const {
  mockStartMode,
  mockStopMode,
  mockGetFocus,
  mockMoveFocus,
  mockAutoFocus,
  mockGetExposure,
  mockSetExposure,
  mockSetGain,
  mockMove,
  mockRecord,
  mockStatus,
} = vi.hoisted(() => ({
  mockStartMode: vi.fn(),
  mockStopMode: vi.fn(),
  mockGetFocus: vi.fn(),
  mockMoveFocus: vi.fn(),
  mockAutoFocus: vi.fn(),
  mockGetExposure: vi.fn(),
  mockSetExposure: vi.fn(),
  mockSetGain: vi.fn(),
  mockMove: vi.fn(),
  mockRecord: vi.fn(),
  mockStatus: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  activeDeviceStatus: writable<DeviceStatus | null>(null),
  isConnected: writable<boolean>(true),
  deviceList: writable([]),
  deviceStatuses: writable<Record<number, DeviceStatus>>({}),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      status: mockStatus,
      live: {
        startMode: mockStartMode,
        stopMode: mockStopMode,
        getFocus: mockGetFocus,
        moveFocus: mockMoveFocus,
        autoFocus: mockAutoFocus,
        getExposure: mockGetExposure,
        setExposure: mockSetExposure,
        setGain: mockSetGain,
        move: mockMove,
        record: mockRecord,
      },
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Live from "./Live.svelte";

const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;
const mockActiveDeviceStatus = deviceStore.activeDeviceStatus as ReturnType<typeof writable<DeviceStatus | null>>;
const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;

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
  mockActiveDevNum.set(1);
  mockIsConnected.set(true);
  mockActiveDeviceStatus.set(null);

  mockStartMode.mockReset().mockResolvedValue({ status: "ok" });
  mockStopMode.mockReset().mockResolvedValue({ status: "ok" });
  mockGetFocus.mockReset().mockResolvedValue({ position: 1500 });
  mockMoveFocus.mockReset().mockResolvedValue({ position: 1500 });
  mockAutoFocus.mockReset().mockResolvedValue({});
  mockGetExposure.mockReset().mockResolvedValue({ exp_ms: 10000, gain: 80 });
  mockSetExposure.mockReset().mockResolvedValue({});
  mockSetGain.mockReset().mockResolvedValue({});
  mockMove.mockReset().mockResolvedValue({});
  mockRecord.mockReset().mockResolvedValue({});
  mockStatus.mockReset().mockResolvedValue(BASE_STATUS);
});

describe("Live — syncing active mode from device status", () => {
  it("activates the matching mode and shows the live feed when imaging is already in progress", async () => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      view_state: "working",
      mode: "star",
      stacked: 12,
      schedule_state: "working",
    });

    render(Live);

    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const starBtn = screen.getByTitle("Deep sky / star mode");
    expect(starBtn.classList.contains("active")).toBe(true);
  });

  it("does not auto-activate a mode when the device is idle", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, view_state: "Idle", mode: "", stacked: "" });

    render(Live);

    expect(screen.queryByText("Live Feed")).not.toBeInTheDocument();
  });

  it("syncs even on a cold load, once the first status poll resolves after mount", async () => {
    // Simulates closing the browser and reopening: the store is empty at
    // mount time and only gets populated once the poll/WS response arrives.
    mockActiveDeviceStatus.set(null);

    render(Live);
    expect(screen.queryByText("Live Feed")).not.toBeInTheDocument();

    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      view_state: "working",
      mode: "star",
      stacked: 7,
      schedule_state: "working",
    });

    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const starBtn = screen.getByTitle("Deep sky / star mode");
    expect(starBtn.classList.contains("active")).toBe(true);
  });
});

describe("Live — confirmation before interrupting an active imaging session", () => {
  it("warns and blocks the mode switch when the user cancels", async () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 5, schedule_state: "working" });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(Live);
    const starBtn = screen.getByTitle("Deep sky / star mode");
    await starBtn.click();

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockStartMode).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("proceeds with the mode switch when the user confirms", async () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: 5, schedule_state: "working" });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(Live);
    const starBtn = screen.getByTitle("Deep sky / star mode");
    await starBtn.click();

    await waitFor(() => expect(mockStartMode).toHaveBeenCalledWith(1, "star"));
    confirmSpy.mockRestore();
  });

  it("does not warn when no imaging session is active", async () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, stacked: "", schedule_state: "" });
    const confirmSpy = vi.spyOn(window, "confirm");

    render(Live);
    const starBtn = screen.getByTitle("Deep sky / star mode");
    await starBtn.click();

    expect(confirmSpy).not.toHaveBeenCalled();
    await waitFor(() => expect(mockStartMode).toHaveBeenCalledWith(1, "star"));
    confirmSpy.mockRestore();
  });

  it("warns before stopping live view too, when imaging is active", async () => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      view_state: "working",
      mode: "star",
      stacked: 5,
      schedule_state: "working",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());

    const stopBtn = screen.getByTitle("Stop live view");
    await stopBtn.click();

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockStopMode).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("re-selecting the already-active mode still warns, since the firmware restarts the pipeline", async () => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      view_state: "working",
      mode: "star",
      stacked: 5,
      schedule_state: "working",
    });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());

    const starBtn = screen.getByTitle("Deep sky / star mode");
    await starBtn.click();

    expect(confirmSpy).toHaveBeenCalled();
    expect(mockStartMode).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});

describe("Live — offline", () => {
  it("shows an offline message when the device is not connected", () => {
    mockIsConnected.set(false);
    render(Live);
    expect(screen.getByText(/is offline or not connected/)).toBeInTheDocument();
  });
});

describe("Live — video feed URL", () => {
  const originalLocation = window.location;

  afterEach(() => {
    Object.defineProperty(window, "location", { value: originalLocation, writable: true });
  });

  it("builds the feed URL from the page's own protocol instead of a hardcoded http://", async () => {
    Object.defineProperty(window, "location", {
      value: { ...originalLocation, protocol: "https:", hostname: "scope.local" },
      writable: true,
    });
    mockActiveDeviceStatus.set({ ...BASE_STATUS, view_state: "working", mode: "star" });

    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const img = screen.getByAltText("Live telescope feed") as HTMLImageElement;
    expect(img.src).toMatch(/^https:\/\/scope\.local:7556\/1\/vid\?t=\d+$/);
  });

  it("still works over plain http", async () => {
    Object.defineProperty(window, "location", {
      value: { ...originalLocation, protocol: "http:", hostname: "scope.local" },
      writable: true,
    });
    mockActiveDeviceStatus.set({ ...BASE_STATUS, view_state: "working", mode: "star" });

    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const img = screen.getByAltText("Live telescope feed") as HTMLImageElement;
    expect(img.src).toMatch(/^http:\/\/scope\.local:7556\/1\/vid\?t=\d+$/);
  });

  it("reconnects the feed once polling confirms the device transitioned to live", async () => {
    Object.defineProperty(window, "location", {
      value: { ...originalLocation, protocol: "http:", hostname: "scope.local" },
      writable: true,
    });
    // Monotonically increasing, rather than a fixed value, so the assertion
    // below can't pass merely because two calls landed in the same
    // millisecond — every call (ours or any library internals) gets a
    // distinct value, so "changed" is a precise signal of a real reconnect.
    let nowCounter = 1000;
    const nowSpy = vi.spyOn(Date, "now").mockImplementation(() => nowCounter++);
    // Mirrors the real race: the device hasn't started streaming yet when the
    // mode is first selected, so the initial connection would freeze on the
    // backend's "Idle" placeholder frame.
    mockActiveDeviceStatus.set({ ...BASE_STATUS, view_state: "Idle", mode: "", stacked: "" });

    render(Live);
    const starBtn = screen.getByTitle("Deep sky / star mode");
    await starBtn.click();
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());

    const img = screen.getByAltText("Live telescope feed") as HTMLImageElement;
    const srcAfterClick = img.src;
    expect(srcAfterClick).toMatch(/^http:\/\/scope\.local:7556\/1\/vid\?t=\d+$/);

    // Polling now confirms the device is actually streaming — the feed must
    // reconnect with a new nonce, not stay frozen on the stale connection.
    mockActiveDeviceStatus.set({ ...BASE_STATUS, view_state: "working", mode: "star", stacked: "" });

    await waitFor(() => expect(img.src).not.toBe(srcAfterClick));
    nowSpy.mockRestore();
  });
});

describe("Live — zoom and pan", () => {
  beforeEach(() => {
    mockActiveDeviceStatus.set({
      ...BASE_STATUS,
      view_state: "working",
      mode: "star",
      stacked: 7,
      schedule_state: "working",
    });
  });

  // jsdom has no PointerEvent constructor; a plain Event with the same
  // fields the handlers read (pointerId/clientX/clientY) works just as well.
  function pointerEvent(type: string, init: { pointerId: number; clientX: number; clientY: number }) {
    return Object.assign(new Event(type), init);
  }

  it("does not mark the feed pannable at the default 1x zoom", async () => {
    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const img = screen.getByAltText("Live telescope feed");
    expect(img.classList.contains("pannable")).toBe(false);
  });

  it("marks the feed pannable once zoomed in", async () => {
    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    const img = screen.getByAltText("Live telescope feed");
    screen.getByRole("button", { name: "Zoom in" }).click();
    await waitFor(() => expect(img.classList.contains("pannable")).toBe(true));
  });

  it("pans the feed via pointer drag once zoomed in", async () => {
    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    screen.getByRole("button", { name: "Zoom in" }).click();

    const img = screen.getByAltText("Live telescope feed") as HTMLImageElement;
    img.setPointerCapture = vi.fn();
    img.releasePointerCapture = vi.fn();

    img.dispatchEvent(pointerEvent("pointerdown", { pointerId: 1, clientX: 100, clientY: 100 }));
    img.dispatchEvent(pointerEvent("pointermove", { pointerId: 1, clientX: 140, clientY: 130 }));
    img.dispatchEvent(pointerEvent("pointerup", { pointerId: 1, clientX: 140, clientY: 130 }));

    await waitFor(() => expect(img.style.transform).toContain("translate(40px, 30px)"));
  });

  it("resets pan when zoom is reset to 1x", async () => {
    render(Live);
    await waitFor(() => expect(screen.getByText("Live Feed")).toBeInTheDocument());
    screen.getByRole("button", { name: "Zoom in" }).click();

    const img = screen.getByAltText("Live telescope feed") as HTMLImageElement;
    img.setPointerCapture = vi.fn();
    img.releasePointerCapture = vi.fn();
    img.dispatchEvent(pointerEvent("pointerdown", { pointerId: 1, clientX: 0, clientY: 0 }));
    img.dispatchEvent(pointerEvent("pointermove", { pointerId: 1, clientX: 50, clientY: 50 }));
    img.dispatchEvent(pointerEvent("pointerup", { pointerId: 1, clientX: 50, clientY: 50 }));
    await waitFor(() => expect(img.style.transform).toContain("translate"));

    screen.getByRole("button", { name: "Reset zoom to 1×" }).click();
    await waitFor(() => expect(img.classList.contains("pannable")).toBe(false));
    expect(img.style.transform).not.toContain("translate");
  });
});
