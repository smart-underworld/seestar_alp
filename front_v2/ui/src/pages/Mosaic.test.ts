import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { DeviceStatus } from "../lib/api";

const { mockMosaicStart, mockEvents } = vi.hoisted(() => ({
  mockMosaicStart: vi.fn(),
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
      mosaic: { start: mockMosaicStart },
      events: mockEvents,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Mosaic from "./Mosaic.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockMosaicStart.mockReset();
  mockEvents.mockReset();
  mockMosaicStart.mockResolvedValue({});
  mockEvents.mockResolvedValue({});
});

describe("Mosaic — offline", () => {
  it("shows offline message when not connected", () => {
    render(Mosaic);
    expect(screen.getByText("Device 1 is offline.")).toBeInTheDocument();
  });

  it("hides the form when offline", () => {
    render(Mosaic);
    expect(screen.queryByText("Start Mosaic")).not.toBeInTheDocument();
  });
});

describe("Mosaic — form structure", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("renders the Target section", () => {
    render(Mosaic);
    expect(screen.getByText("Target")).toBeInTheDocument();
    expect(screen.getByLabelText("Target Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Right Ascension")).toBeInTheDocument();
    expect(screen.getByLabelText("Declination")).toBeInTheDocument();
  });

  it("renders the Panels section with RA/Dec/Overlap inputs", () => {
    render(Mosaic);
    expect(screen.getByText("Panels")).toBeInTheDocument();
    expect(screen.getByLabelText("RA Panels")).toBeInTheDocument();
    expect(screen.getByLabelText("Dec Panels")).toBeInTheDocument();
    expect(screen.getByLabelText("Overlap (%)")).toBeInTheDocument();
  });

  it("renders the Exposure section", () => {
    render(Mosaic);
    expect(screen.getByText("Exposure")).toBeInTheDocument();
    expect(screen.getByLabelText("Time per Panel")).toBeInTheDocument();
    expect(screen.getByLabelText("Gain")).toBeInTheDocument();
    expect(screen.getByLabelText("Stack Mode")).toBeInTheDocument();
  });

  it("renders the Retry section", () => {
    render(Mosaic);
    expect(screen.getByText("Retry")).toBeInTheDocument();
    expect(screen.getByLabelText("Retries")).toBeInTheDocument();
    expect(screen.getByLabelText("Retry Delay (s)")).toBeInTheDocument();
  });

  it("shows panel summary count", () => {
    render(Mosaic);
    expect(screen.getByText(/2 × 2 = 4 panels/)).toBeInTheDocument();
  });

  it("shows LP Filter and Auto-focus checkboxes", () => {
    render(Mosaic);
    expect(screen.getByText("Use Light Pollution Filter")).toBeInTheDocument();
    expect(screen.getByText("Auto-focus each panel")).toBeInTheDocument();
  });

  it("renders Start Mosaic submit button", () => {
    render(Mosaic);
    expect(
      screen.getByRole("button", { name: "Start Mosaic" }),
    ).toBeInTheDocument();
  });
});

describe("Mosaic — submit", () => {
  beforeEach(() => mockIsConnected.set(true));

  // Helper: fill required fields (RA, Dec, Target) so HTML5 validation passes
  function fillRequired() {
    const targetInput = screen.getByLabelText("Target Name") as HTMLInputElement;
    const raInput = screen.getByLabelText("Right Ascension") as HTMLInputElement;
    const decInput = screen.getByLabelText("Declination") as HTMLInputElement;
    targetInput.value = "M42"; raInput.value = "05h35m"; decInput.value = "-05d23m";
    targetInput.dispatchEvent(new Event("input"));
    raInput.dispatchEvent(new Event("input"));
    decInput.dispatchEvent(new Event("input"));
  }

  it("calls mosaic.start when submitted", async () => {
    render(Mosaic);
    fillRequired();
    screen.getByRole("button", { name: "Start Mosaic" }).click();
    await waitFor(() =>
      expect(mockMosaicStart).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ ra_num: 2, dec_num: 2, gain: 80, stack_type: "DeepSky" }),
      ),
    );
  });

  it("shows success message after start", async () => {
    render(Mosaic);
    fillRequired();
    screen.getByRole("button", { name: "Start Mosaic" }).click();
    await waitFor(() =>
      expect(screen.getByText(/Mosaic started successfully/)).toBeInTheDocument(),
    );
  });

  it("shows error when start fails", async () => {
    mockMosaicStart.mockRejectedValue(new Error("device busy"));
    render(Mosaic);
    fillRequired();
    screen.getByRole("button", { name: "Start Mosaic" }).click();
    await waitFor(() =>
      expect(screen.getByText(/device busy/)).toBeInTheDocument(),
    );
  });
});

describe("Mosaic — federation mode", () => {
  it("shows Federation section when device is 0 (all devices)", () => {
    mockIsConnected.set(true);
    mockActiveDevNum.set(0);
    render(Mosaic);
    expect(screen.getByText("Federation")).toBeInTheDocument();
    expect(screen.getByLabelText("Mode")).toBeInTheDocument();
    expect(screen.getByLabelText("Max Devices")).toBeInTheDocument();
  });

  it("hides Federation section for a normal device", () => {
    mockIsConnected.set(true);
    render(Mosaic);
    expect(screen.queryByText("Federation")).not.toBeInTheDocument();
  });
});
