import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

const { mockCommand, mockScheduleSetState, mockEvents } = vi.hoisted(() => ({
  mockCommand: vi.fn(),
  mockScheduleSetState: vi.fn(),
  mockEvents: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      command: mockCommand,
      schedule: { setState: mockScheduleSetState },
      events: mockEvents,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Command from "./Command.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockCommand.mockReset();
  mockScheduleSetState.mockReset();
  mockEvents.mockReset();
  mockCommand.mockResolvedValue({ result: "ok" });
  mockScheduleSetState.mockResolvedValue({});
  mockEvents.mockResolvedValue({});
});

describe("Command — offline", () => {
  it("shows offline message when not connected", () => {
    render(Command);
    expect(screen.getByText(/Device 1 is offline/)).toBeInTheDocument();
  });

  it("does not show Quick Actions when offline", () => {
    render(Command);
    expect(screen.queryByText("Quick Actions")).not.toBeInTheDocument();
  });
});

describe("Command — connected layout", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("shows Quick Actions panel", () => {
    render(Command);
    expect(screen.getByText("Quick Actions")).toBeInTheDocument();
  });

  it("renders all quick action buttons including mount mode toggle", () => {
    const { container } = render(Command);
    // Quick-action buttons carry class "action-btn": 5 from QUICK_ACTIONS + 1 mount mode toggle
    const actionBtns = container.querySelectorAll("button.action-btn");
    expect(actionBtns.length).toBe(6);
    // "Stop Scheduler" and "Open to Horizon" are unique to the quick-actions panel
    expect(screen.getByText("Stop Scheduler")).toBeInTheDocument();
    expect(screen.getByText("Open to Horizon")).toBeInTheDocument();
  });

  it("shows Commands panel with groups", () => {
    render(Command);
    expect(screen.getByText("Commands")).toBeInTheDocument();
    expect(screen.getByText("Startup / Shutdown")).toBeInTheDocument();
    expect(screen.getByText("AutoFocus")).toBeInTheDocument();
    expect(screen.getByText("Imaging")).toBeInTheDocument();
  });

  it("shows Magnetic Declination panel", () => {
    render(Command);
    expect(screen.getByText("Magnetic Declination Adjustment")).toBeInTheDocument();
    expect(screen.getByLabelText(/Add Offset/)).toBeInTheDocument();
  });

  it("shows Raw Command panel with method and params fields", () => {
    render(Command);
    expect(screen.getByText("Raw Command")).toBeInTheDocument();
    expect(screen.getByLabelText("Method")).toBeInTheDocument();
    expect(screen.getByLabelText(/Parameters/)).toBeInTheDocument();
  });

  it("shows placeholder in result area", () => {
    render(Command);
    expect(screen.getByText("Response will appear here")).toBeInTheDocument();
  });
});

describe("Command — quick actions", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("calls api.devices.command when a quick action is clicked", async () => {
    render(Command);
    screen.getByText("Stop View").click();
    await waitFor(() =>
      expect(mockCommand).toHaveBeenCalledWith(1, "iscope_stop_view", {}),
    );
  });

  it("calls schedule.setState for Stop Scheduler quick action", async () => {
    render(Command);
    screen.getByText("Stop Scheduler").click();
    await waitFor(() =>
      expect(mockScheduleSetState).toHaveBeenCalledWith(1, "stop"),
    );
  });

  it("shows response panel when command returns a result", async () => {
    mockCommand.mockResolvedValue({ status: "stopped" });
    const { container } = render(Command);
    // Click the first quick-action button (Stop View — unique label)
    screen.getByText("Stop View").click();
    await waitFor(() =>
      expect(screen.getByText("Response")).toBeInTheDocument(),
    );
  });

  it("shows error alert when command throws", async () => {
    mockCommand.mockRejectedValue(new Error("device unreachable"));
    render(Command);
    screen.getByText("Stop View").click();
    await waitFor(() =>
      expect(screen.getByText(/device unreachable/)).toBeInTheDocument(),
    );
  });
});

describe("Command — raw command", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("Send button is disabled when method is empty", () => {
    render(Command);
    expect(
      screen.getByRole("button", { name: /▶ Send/ }),
    ).toBeDisabled();
  });

  it("shows error for invalid JSON params", async () => {
    render(Command);
    const methodInput = screen.getByLabelText("Method") as HTMLInputElement;
    const paramsTextarea = screen.getByLabelText(/Parameters/) as HTMLTextAreaElement;
    methodInput.value = "get_device_state";
    paramsTextarea.value = "not-json{";
    // dispatch input event so Svelte bindings update
    methodInput.dispatchEvent(new Event("input"));
    paramsTextarea.dispatchEvent(new Event("input"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /▶ Send/ }),
      ).not.toBeDisabled(),
    );
    screen.getByRole("button", { name: /▶ Send/ }).click();
    await waitFor(() =>
      expect(screen.getByText(/SyntaxError|JSON/)).toBeInTheDocument(),
    );
  });
});
