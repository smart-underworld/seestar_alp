import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

const { mockSettingsGet, mockSettingsSave } = vi.hoisted(() => ({
  mockSettingsGet: vi.fn(),
  mockSettingsSave: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      settings: { get: mockSettingsGet, save: mockSettingsSave },
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Settings from "./Settings.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

const HANG = new Promise<never>(() => {});

const SAMPLE_SETTINGS = {
  merged: {
    exp_ms_stack_l: 10000,       // Imaging
    stack_dither_enable: true,   // Mount & Focus (contains "dither")
    heater_enable: false,        // Environment
    auto_power_off: true,        // General
  },
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockSettingsGet.mockReset();
  mockSettingsSave.mockReset();
  mockSettingsGet.mockReturnValue(HANG);
  mockSettingsSave.mockResolvedValue({});
});

describe("Settings — offline", () => {
  it("shows offline message when not connected", () => {
    render(Settings);
    expect(screen.getByText(/Device 1 is offline/)).toBeInTheDocument();
  });
});

describe("Settings — loading", () => {
  it("shows loading indicator while settings are fetching", () => {
    mockIsConnected.set(true);
    render(Settings);
    expect(screen.getByText(/Loading settings/)).toBeInTheDocument();
  });
});

describe("Settings — error", () => {
  it("shows error when settings fetch fails", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockRejectedValue(new Error("forbidden"));
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText(/forbidden/)).toBeInTheDocument(),
    );
  });
});

describe("Settings — loaded", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue(SAMPLE_SETTINGS);
  });

  it("renders grouped setting rows", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText("Stacking Exposure (ms)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Dew Heater")).toBeInTheDocument();
    expect(screen.getByText("Auto Power Off")).toBeInTheDocument();
  });

  it("shows number input for numeric settings", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("10000")).toBeInTheDocument(),
    );
  });

  it("shows radio Enable/Disable for boolean settings", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getAllByText("Enable").length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("Disable").length).toBeGreaterThan(0);
  });

  it("Save Changes button is disabled when no changes made", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText("Stacking Exposure (ms)")).toBeInTheDocument(),
    );
    const saveButtons = screen.getAllByRole("button", { name: /Save Changes/ });
    expect(saveButtons[0]).toBeDisabled();
  });

  it("calls settings.save when Save Changes is clicked after a change", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("10000")).toBeInTheDocument(),
    );
    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    input.value = "20000";
    input.dispatchEvent(new Event("input"));
    await waitFor(() => {
      const saveButtons = screen.getAllByRole("button", { name: /Save Changes/ });
      expect(saveButtons[0]).not.toBeDisabled();
    });
    const saveButtons = screen.getAllByRole("button", { name: /Save Changes/ });
    saveButtons[0].click();
    await waitFor(() =>
      expect(mockSettingsSave).toHaveBeenCalledWith(1, expect.any(Object)),
    );
  });

  it("shows unsaved changes pill when settings are modified", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("10000")).toBeInTheDocument(),
    );
    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    input.value = "5000";
    input.dispatchEvent(new Event("input"));
    await waitFor(() =>
      expect(screen.getByText(/Unsaved Changes/)).toBeInTheDocument(),
    );
  });

  it("shows success message after save", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("10000")).toBeInTheDocument(),
    );
    const input = screen.getByDisplayValue("10000") as HTMLInputElement;
    input.value = "5000";
    input.dispatchEvent(new Event("input"));
    // Svelte DOM updates are async — wait for the button to become enabled
    await waitFor(() => {
      const btns = screen.getAllByRole("button", { name: /Save Changes/ });
      expect(btns[0]).not.toBeDisabled();
    });
    screen.getAllByRole("button", { name: /Save Changes/ })[0].click();
    await waitFor(() =>
      expect(screen.getByText(/saved successfully/i)).toBeInTheDocument(),
    );
  });
});
