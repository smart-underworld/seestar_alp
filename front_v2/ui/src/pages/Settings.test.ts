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

describe("Settings — real device key labels", () => {
  // device_client.py merges the device's "stack" sub-object verbatim (no
  // "stack_" prefix renaming), and several other real fields had no label
  // at all. These must show plain labels, not the raw key.
  beforeEach(() => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: {
        dbe: false,
        star_trails: false,
        cont_capt: false,
        drizzle2x: false,
        isp_exp_ms: -999000,
        isp_gain: -9990,
        manual_exp: false,
        wifi_country: "",
        lang: "en",
      },
      firmware_ver_int: 2582,
    });
  });

  it("labels real stack sub-object keys instead of showing the raw key", async () => {
    render(Settings);
    await waitFor(() => expect(screen.getByText("Stack DBE")).toBeInTheDocument());
    expect(screen.getByText("Stack Star Trails")).toBeInTheDocument();
    expect(screen.getByText("Continuous Capture Mode")).toBeInTheDocument();
    expect(screen.getByText("4K Live Stack (2× Drizzle)")).toBeInTheDocument();
    expect(screen.queryByText("dbe")).not.toBeInTheDocument();
    expect(screen.queryByText("star_trails")).not.toBeInTheDocument();
  });

  it("labels previously-unlabeled fields instead of showing the raw key", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText("ISP Exposure (ms)")).toBeInTheDocument(),
    );
    expect(screen.getByText("ISP Gain")).toBeInTheDocument();
    expect(screen.getByText("Manual Exposure")).toBeInTheDocument();
    expect(screen.getByText("WiFi Country Code")).toBeInTheDocument();
    expect(screen.getByText("Language")).toBeInTheDocument();
  });
});

describe("Settings — manual_exp gating", () => {
  it("disables isp_exp_ms/isp_gain when manual_exp is false", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: { manual_exp: false, isp_exp_ms: -999000, isp_gain: -9990 },
    });
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("-999000")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("-999000")).toBeDisabled();
    expect(screen.getByDisplayValue("-9990")).toBeDisabled();
    expect(screen.getAllByText(/Enable Manual Exposure to edit/).length).toBe(2);
  });

  it("enables isp_exp_ms/isp_gain when manual_exp is true", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: { manual_exp: true, isp_exp_ms: 5000, isp_gain: 100 },
    });
    render(Settings);
    await waitFor(() =>
      expect(screen.getByDisplayValue("5000")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("5000")).not.toBeDisabled();
    expect(screen.getByDisplayValue("100")).not.toBeDisabled();
    expect(screen.queryByText(/Enable Manual Exposure to edit/)).not.toBeInTheDocument();
  });
});

describe("Settings — firmware_ver_int plumbing", () => {
  it("renders normally when firmware_ver_int is absent from the response", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({ merged: { heater_enable: false } });
    render(Settings);
    await waitFor(() => expect(screen.getByText("Dew Heater")).toBeInTheDocument());
  });

  it("does not hide any field yet, since no FIRMWARE_MIN thresholds are set", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: { heater_enable: false },
      firmware_ver_int: 0,
    });
    render(Settings);
    await waitFor(() => expect(screen.getByText("Dew Heater")).toBeInTheDocument());
  });
});
