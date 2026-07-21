import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { EventState } from "../api";

const { mockEvents } = vi.hoisted(() => ({ mockEvents: vi.fn() }));

vi.mock("../stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
}));

vi.mock("../api", () => ({
  api: { devices: { events: mockEvents } },
}));

import * as deviceStore from "../stores/deviceStore";

const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

import EventStatusPanel from "./EventStatusPanel.svelte";

const EVENTS = ["WheelMove", "AutoFocus", "DarkLibrary", "3PPA", "PlateSolve", "Scheduler"];

beforeEach(() => {
  mockActiveDevNum.set(1);
  mockEvents.mockReset();
});

describe("EventStatusPanel", () => {
  it("shows the heading", async () => {
    mockEvents.mockResolvedValue({});
    render(EventStatusPanel, { events: EVENTS });
    expect(screen.getByText("Current Status of Devices")).toBeInTheDocument();
  });

  it("renders a card per configured event in idle state when no data", async () => {
    mockEvents.mockResolvedValue({});
    render(EventStatusPanel, { events: EVENTS });
    await waitFor(() => {
      expect(screen.getByText("PolarAlign")).toBeInTheDocument();
      expect(screen.getByText("FilterWheel")).toBeInTheDocument();
    });
    const idleLabels = screen.getAllByText("Idle");
    expect(idleLabels.length).toBe(EVENTS.length);
  });

  it("shows event state and detail fields for a flat (single-device) result", async () => {
    const result: Record<string, EventState> = {
      Stack: { state: "in progress", stacked_frame: 10, dropped_frame: 2 },
      AutoFocus: { state: "complete", position: 1234 },
    };
    mockEvents.mockResolvedValue(result);
    render(EventStatusPanel, { events: ["AutoFocus", "Stack"] });
    await waitFor(() => {
      expect(screen.getByText("complete")).toBeInTheDocument();
      expect(screen.getByText("in progress")).toBeInTheDocument();
    });
    expect(screen.getByText("1234")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("treats unrecognized firmware sub-states (e.g. 3PPA delay/calc) as progress, not idle", async () => {
    // Regression: stateClass()'s switch only recognized the literal
    // "in progress", so real firmware sub-states like "delay1"/"calc3"
    // (3PPA) or "solving" (PlateSolve) fell to the "card-idle" default —
    // visually indistinguishable from a tile with no data at all.
    const result: Record<string, EventState> = {
      "3PPA": { state: "calc3" },
    };
    mockEvents.mockResolvedValue(result);
    render(EventStatusPanel, { events: ["3PPA"] });
    await waitFor(() => expect(screen.getByText("calc3")).toBeInTheDocument());
    const card = screen.getByText("calc3").closest(".event-card");
    expect(card).toHaveClass("card-progress");
    expect(card).not.toHaveClass("card-idle");
  });

  it("groups results by DeviceID when present", async () => {
    const result: Record<string, unknown> = {
      WheelMove: { state: "complete", position: 2, DeviceID: "device-A" },
      AutoFocus: { state: "fail", error: "timeout", DeviceID: "device-B" },
    };
    mockEvents.mockResolvedValue(result);
    render(EventStatusPanel, { events: ["WheelMove", "AutoFocus"] });
    await waitFor(() => {
      expect(screen.getByText("Device ID: device-A")).toBeInTheDocument();
      expect(screen.getByText("Device ID: device-B")).toBeInTheDocument();
    });
    expect(screen.getByText("LP")).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
  });
});
