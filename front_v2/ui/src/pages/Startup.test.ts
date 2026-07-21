import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

// pollEvents() ends with: pollTimer = setTimeout(pollEvents, interval)
// That assignment is read by the $: reactive block, which re-calls pollEvents() directly.
// mockResolvedValue({}) makes this loop spin at microtask speed → OOM.
// HANG makes pollEvents await forever after call #1, pollTimer never assigned, loop never fires.
//
// HANG must live inside vi.hoisted — vi.mock factories are hoisted before top-level const declarations.
const { HANG, mockEvents, mockStartup, mockScheduleSetState, mockPaStart, mockPaStop } = vi.hoisted(() => ({
  HANG: new Promise<never>(() => {}),
  mockEvents: vi.fn(),
  mockStartup: vi.fn(),
  mockScheduleSetState: vi.fn(),
  mockPaStart: vi.fn(),
  mockPaStop: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable<DeviceStatus | null>(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      events: mockEvents,
      startup: mockStartup,
      schedule: { setState: mockScheduleSetState },
      paRefine: { start: mockPaStart, stop: mockPaStop, data: vi.fn() },
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Startup from "./Startup.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;
const mockActiveDeviceStatus = deviceStore.activeDeviceStatus as ReturnType<typeof writable<DeviceStatus | null>>;

const BASE_STATUS: DeviceStatus = {
  device_num: 1, is_connected: true, backend_ready: true, view_state: "", mode: "",
  stage: "", target: "", stacked: "", failed: "", mount_mode: "", free_storage: "",
  battery_capacity: null, temp: null, ra: null, dec: null, schedule: null,
  firmware_ver: "", model: "", focal_position: null, auto_power_off: false, heater_enable: false,
  balance_angle: null, compass_direction: null, charge_status: "", battery_temp: null,
  wifi_signal: "", is_master: true, connected_clients: [], schedule_state: "",
  guest_mode_available: false,
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockActiveDeviceStatus.set(null);
  mockEvents.mockReset();
  mockStartup.mockReset();
  mockScheduleSetState.mockReset();
  mockPaStart.mockReset();
  mockPaStop.mockReset();
  mockEvents.mockReturnValue(HANG);
  mockStartup.mockReturnValue(HANG);
  mockScheduleSetState.mockResolvedValue({});
  mockPaStart.mockReturnValue(HANG);
  mockPaStop.mockResolvedValue({});
});

// ── Offline ──────────────────────────────────────────────────────────────────

describe("Startup — offline", () => {
  it("shows the offline message", () => {
    render(Startup);
    expect(screen.getByText("Device 1 is offline.")).toBeInTheDocument();
  });

  it("hides the event grid and options form", () => {
    render(Startup);
    expect(screen.queryByText("Event Status")).not.toBeInTheDocument();
    expect(screen.queryByText("Startup Options")).not.toBeInTheDocument();
  });

  it("does not poll when offline", () => {
    render(Startup);
    expect(mockEvents).not.toHaveBeenCalled();
  });
});

// ── Event grid ───────────────────────────────────────────────────────────────

describe("Startup — event grid", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
  });

  it("shows the Event Status panel", () => {
    render(Startup);
    expect(screen.getByText("Event Status")).toBeInTheDocument();
  });

  it("starts polling immediately on connect", () => {
    render(Startup);
    expect(mockEvents).toHaveBeenCalledWith(1);
  });

  it("renders all six event tiles in idle state when no data", () => {
    render(Startup);
    // Plate Solve / Filter Wheel / Scheduler are unique to the events grid
    expect(screen.getByText("Plate Solve")).toBeInTheDocument();
    expect(screen.getByText("Filter Wheel")).toBeInTheDocument();
    expect(screen.getByText("Scheduler")).toBeInTheDocument();
    expect(screen.getAllByText("Idle").length).toBe(6);
  });

  it("shows 3PPA state and progress percent from poll data", async () => {
    mockEvents
      .mockResolvedValueOnce({ "3PPA": { state: "in progress", percent: 55 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("in progress")).toBeInTheDocument();
      expect(screen.getByText("55%")).toBeInTheDocument();
    });
  });

  it("shows 3PPA firmware sub-states (delay/calc) as text and lights the tile up as progress, not idle", async () => {
    // Regression: real firmware cycles PolarAlign through internal states
    // like "delay1"/"delay2"/"calc3" (and PlateSolve through "solving")
    // while it works the 3 points — none of those literal strings were in
    // stateClass()'s enumerated "progress" list, so the tile fell through
    // to state-idle and looked inert even though the label text was correct.
    mockEvents
      .mockResolvedValueOnce({ "3PPA": { state: "calc3" } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => expect(screen.getByText("calc3")).toBeInTheDocument());
    const tile = screen.getByText("calc3").closest(".event-tile");
    expect(tile).toHaveClass("state-progress");
    expect(tile).not.toHaveClass("state-idle");
  });

  it("shows 3PPA alt/az offset errors", async () => {
    mockEvents
      .mockResolvedValueOnce({ "3PPA": { state: "in progress", eq_offset_alt: 0.123, eq_offset_az: -0.456 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText(/Alt err:/)).toBeInTheDocument();
      expect(screen.getByText(/Az err:/)).toBeInTheDocument();
    });
  });

  it("shows AutoFocus focal position from poll data", async () => {
    mockEvents
      .mockResolvedValueOnce({ AutoFocus: { state: "complete", position: 1234 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("Pos: 1234")).toBeInTheDocument();
    });
  });

  it("shows DarkLibrary percent and progress bar", async () => {
    mockEvents
      .mockResolvedValueOnce({ DarkLibrary: { state: "in progress", percent: 42.5 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("42.5%")).toBeInTheDocument();
    });
  });

  it("shows WheelMove filter name for position 1 (IR Cut)", async () => {
    mockEvents
      .mockResolvedValueOnce({ WheelMove: { state: "complete", position: 1 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("IR Cut")).toBeInTheDocument();
    });
  });

  it("shows WheelMove filter name for position 0 (Dark)", async () => {
    mockEvents
      .mockResolvedValueOnce({ WheelMove: { state: "complete", position: 0 } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("Dark")).toBeInTheDocument();
    });
  });

  it("shows Scheduler current item type when present", async () => {
    mockEvents
      .mockResolvedValueOnce({ Scheduler: { state: "in progress", cur_scheduler_item: { type: "mosaic" } } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("mosaic")).toBeInTheDocument();
    });
  });

  it("shows error text on a failed event", async () => {
    mockEvents
      .mockResolvedValueOnce({ AutoFocus: { state: "fail", error: "focus timeout" } })
      .mockReturnValue(HANG);
    render(Startup);
    await waitFor(() => {
      expect(screen.getByText("focus timeout")).toBeInTheDocument();
    });
  });
});

// ── Polling cadence ───────────────────────────────────────────────────────────
// Regression coverage for the bug where the $: reactive block driving
// pollEvents() also depended on pollTimer, which pollEvents() itself
// reassigns — causing every poll tick to immediately re-trigger another
// poll instead of waiting out the interval. With HANG-based mocks (used
// everywhere else in this file) the loop never gets far enough to expose
// this, so this block uses a resolving mock + fake timers instead.
describe("Startup — polling cadence", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
    mockEvents.mockReset();
    mockEvents.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls once per interval, not back-to-back", async () => {
    vi.useFakeTimers();
    try {
      render(Startup);

      // Initial poll fires immediately on connect.
      await vi.advanceTimersByTimeAsync(0);
      expect(mockEvents).toHaveBeenCalledTimes(1);

      // schedule_state is unset → isRunning is false → 3000ms interval.
      // Advancing by less than the interval must not produce another call.
      await vi.advanceTimersByTimeAsync(1500);
      expect(mockEvents).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(1500);
      expect(mockEvents).toHaveBeenCalledTimes(2);

      await vi.advanceTimersByTimeAsync(3000);
      expect(mockEvents).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops polling once disconnected", async () => {
    vi.useFakeTimers();
    try {
      render(Startup);
      await vi.advanceTimersByTimeAsync(0);
      expect(mockEvents).toHaveBeenCalledTimes(1);

      mockIsConnected.set(false);
      await vi.advanceTimersByTimeAsync(10000);
      expect(mockEvents).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ── Options form ─────────────────────────────────────────────────────────────

describe("Startup — options form", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
  });

  it("renders the Startup Options panel", () => {
    render(Startup);
    expect(screen.getByText("Startup Options")).toBeInTheDocument();
  });

  it("renders the Dec Offset picker label", () => {
    render(Startup);
    expect(screen.getByText("Dec Offset")).toBeInTheDocument();
  });

  it("renders latitude and longitude inputs", () => {
    render(Startup);
    expect(screen.getByLabelText("Latitude")).toBeInTheDocument();
    expect(screen.getByLabelText("Longitude")).toBeInTheDocument();
  });

  it("shows the Run Startup Sequence button enabled when idle", () => {
    render(Startup);
    expect(screen.getByRole("button", { name: /Run Startup Sequence/ })).not.toBeDisabled();
  });

  it("hides the Stop button when not running", () => {
    render(Startup);
    expect(screen.queryByRole("button", { name: /Stop/ })).not.toBeInTheDocument();
  });

  it("shows all three polar-align On/Off radio pairs", () => {
    const { container } = render(Startup);
    const radios = container.querySelectorAll("input[type='radio']");
    // Polar Align (2) + Auto Focus (2) + Dark Frames (2) + dec offset (5) = 11
    expect(radios.length).toBe(11);
  });
});

// ── Start action ─────────────────────────────────────────────────────────────

describe("Startup — start action", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
  });

  it("calls api.devices.startup with default params when Run is clicked", async () => {
    render(Startup);
    const btn = screen.getByRole("button", { name: /Run Startup Sequence/ });
    btn.click();
    expect(mockStartup).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        auto_focus: true,
        "3ppa": true,
        dark_frames: false,
        dec_pos_index: 3,
      }),
    );
  });

  it("does not include lat/lon when fields are blank", async () => {
    render(Startup);
    screen.getByRole("button", { name: /Run Startup Sequence/ }).click();
    const call = mockStartup.mock.calls[0][1] as Record<string, unknown>;
    expect(call).not.toHaveProperty("lat");
    expect(call).not.toHaveProperty("lon");
  });

  it("keeps the Run button disabled after the start POST resolves, before isRunning is confirmed", async () => {
    // Regression: the button used to re-enable itself as soon as the POST
    // resolved (a couple seconds), well before the next status poll (up to
    // 15s later) noticed the sequence was actually running — a window where
    // a second click was possible.
    mockStartup.mockResolvedValueOnce({});
    render(Startup);
    const btn = screen.getByRole("button", { name: /Run Startup Sequence/ });
    btn.click();
    await waitFor(() => expect(mockStartup).toHaveBeenCalled());
    expect(btn).toBeDisabled();
    expect(screen.getByText("Starting…")).toBeInTheDocument();
  });

  it("shows Running… and stays disabled once isRunning is confirmed, then re-enables once the sequence completes", async () => {
    mockStartup.mockResolvedValueOnce({});
    render(Startup);
    const btn = screen.getByRole("button", { name: /Run Startup Sequence/ });
    btn.click();
    await waitFor(() => expect(btn).toBeDisabled());

    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "working" });
    await waitFor(() => expect(screen.getByText("Running…")).toBeInTheDocument());
    expect(btn).toBeDisabled();

    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "complete" });
    await waitFor(() => expect(btn).not.toBeDisabled());
  });

  it("hands off to isRunning as soon as the faster local events poll sees Scheduler working", async () => {
    // events.Scheduler is polled every 1-3s by this component itself —
    // much faster than the 15s activeDeviceStatus poll — so it should be
    // able to confirm isRunning well before that slower poll would.
    mockStartup.mockResolvedValueOnce({});
    mockEvents.mockResolvedValueOnce({ Scheduler: { state: "working" } }).mockReturnValue(HANG);
    render(Startup);
    screen.getByRole("button", { name: /Run Startup Sequence/ }).click();
    await waitFor(() => expect(screen.getByText("Running…")).toBeInTheDocument());
  });
});

// ── Stop action ───────────────────────────────────────────────────────────────

describe("Startup — stop action", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
  });

  it("shows Stop button when schedule_state is running", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "running" });
    render(Startup);
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();
  });

  it("shows Stop button when schedule_state is working", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "working" });
    render(Startup);
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();
  });

  it("disables Run button while schedule is running", () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "running" });
    render(Startup);
    // Label switches to "Running…" while isRunning is true (see the
    // start-action describe block below), so it's no longer queryable by
    // its idle "Run Startup Sequence" name.
    expect(screen.getByRole("button", { name: /Running/ })).toBeDisabled();
  });

  it("calls schedule.setState stop when Stop is clicked", async () => {
    mockActiveDeviceStatus.set({ ...BASE_STATUS, schedule_state: "running" });
    render(Startup);
    screen.getByRole("button", { name: /Stop/ }).click();
    await waitFor(() => {
      expect(mockScheduleSetState).toHaveBeenCalledWith(1, "stop");
    });
  });
});

// ── PA Refinement ─────────────────────────────────────────────────────────────

describe("Startup — PA Refinement", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
  });

  it("shows the PA Refinement section heading", () => {
    render(Startup);
    expect(screen.getByText("PA Refinement")).toBeInTheDocument();
  });

  it("collapses the PA body by default", () => {
    render(Startup);
    expect(screen.queryByText(/plate-solve loop/i)).not.toBeInTheDocument();
  });

  it("expands the PA body when the header is clicked", async () => {
    render(Startup);
    screen.getByRole("button", { name: /PA Refinement/ }).click();
    await waitFor(() => {
      // "plate-solve loop" appears in both the desc paragraph and instructions list
      expect(screen.getAllByText(/plate-solve loop/i).length).toBeGreaterThan(0);
    });
  });

  it("shows the PA Start button when expanded", async () => {
    render(Startup);
    screen.getByRole("button", { name: /PA Refinement/ }).click();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "▶ Start" })).toBeInTheDocument();
    });
  });

  it("calls paRefine.start with device number when PA Start is clicked", async () => {
    render(Startup);
    screen.getByRole("button", { name: /PA Refinement/ }).click();
    const startBtn = await screen.findByRole("button", { name: "▶ Start" });
    startBtn.click();
    expect(mockPaStart).toHaveBeenCalledWith(1);
  });

  it("shows PA error text when paRefine.start returns ok:false", async () => {
    mockPaStart.mockResolvedValue({ ok: false, error: "PA start failed" });
    render(Startup);
    screen.getByRole("button", { name: /PA Refinement/ }).click();
    const startBtn = await screen.findByRole("button", { name: "▶ Start" });
    startBtn.click();
    await waitFor(() => {
      expect(screen.getByText("PA start failed")).toBeInTheDocument();
    });
  });

  it("collapses again when the header is clicked a second time", async () => {
    render(Startup);
    const header = screen.getByRole("button", { name: /PA Refinement/ });
    header.click();
    await waitFor(() => expect(screen.getAllByText(/plate-solve loop/i).length).toBeGreaterThan(0));
    header.click();
    await waitFor(() => expect(screen.queryAllByText(/plate-solve loop/i).length).toBe(0));
  });
});
