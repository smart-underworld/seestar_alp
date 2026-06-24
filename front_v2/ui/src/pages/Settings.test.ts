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
        auto_af: false,
        stack_after_goto: false,
        guest_mode: false,
        user_stack_sim: false,
        usb_en_eth: false,
        light_duration_min: -1,
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

  it("labels device-reported fields that previously fell back to the raw key", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText("Auto-Focus Before Capture")).toBeInTheDocument(),
    );
    expect(screen.getByText("Stack After Goto")).toBeInTheDocument();
    expect(screen.getByText("Guest Mode")).toBeInTheDocument();
    expect(screen.getByText("Simulate Stacking")).toBeInTheDocument();
    expect(screen.getByText("USB-to-Ethernet")).toBeInTheDocument();
    expect(screen.getByText("Light Duration Min")).toBeInTheDocument();
    expect(screen.queryByText("auto_af")).not.toBeInTheDocument();
    expect(screen.queryByText("stack_after_goto")).not.toBeInTheDocument();
    expect(screen.queryByText("guest_mode")).not.toBeInTheDocument();
    expect(screen.queryByText("user_stack_sim")).not.toBeInTheDocument();
    expect(screen.queryByText("usb_en_eth")).not.toBeInTheDocument();
  });

  it("shows helper description text for the newly-labeled fields", async () => {
    render(Settings);
    await waitFor(() =>
      expect(
        screen.getByText(/Automatically run autofocus before each capture/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Automatically begin stacking once a goto\/slew completes/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Allow multiple app clients to connect at once/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Simulate the stacking process without real frames/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Enable USB-to-Ethernet adapter support/),
    ).toBeInTheDocument();
  });
});

describe("Settings — newer firmware's flattened stack sub-object", () => {
  // On firmware 7.32 the device's "stack" sub-object reports bare keys
  // (capt_type, capt_num, brightness, contrast, saturation, goto,
  // move_sleep_sec, dbe_enable) rather than the "stack_"-prefixed names
  // used elsewhere. device_client.py flattens these verbatim, so both
  // naming variants must resolve to a label, not a raw key.
  beforeEach(() => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: {
        dbe: false,
        dbe_enable: false,
        capt_type: "stack",
        capt_num: 50,
        brightness: 0,
        contrast: 0,
        saturation: 0,
        goto: true,
        move_sleep_sec: 1,
      },
      firmware_ver_int: 2732,
    });
  });

  it("labels the bare stack-object keys instead of showing the raw key", async () => {
    render(Settings);
    await waitFor(() =>
      expect(screen.getByText("Stack Capture Type")).toBeInTheDocument(),
    );
    expect(screen.getByText("Stack Capture Count")).toBeInTheDocument();
    expect(screen.getByText("Stack Brightness")).toBeInTheDocument();
    expect(screen.getByText("Stack Contrast")).toBeInTheDocument();
    expect(screen.getByText("Stack Saturation")).toBeInTheDocument();
    expect(screen.getByText("Stack Goto")).toBeInTheDocument();
    expect(screen.getByText("Mount Move Settle Time (s)")).toBeInTheDocument();
    expect(screen.getByText("Stack DBE (Enable)")).toBeInTheDocument();
    expect(screen.queryByText("capt_type")).not.toBeInTheDocument();
    expect(screen.queryByText("move_sleep_sec")).not.toBeInTheDocument();
    expect(screen.queryByText("dbe_enable")).not.toBeInTheDocument();
  });
});

describe("Settings — manual_exp gating", () => {
  it("disables isp_exp_ms/isp_gain when manual_exp is false, showing Auto instead of the raw sentinel", async () => {
    mockIsConnected.set(true);
    mockSettingsGet.mockResolvedValue({
      merged: { manual_exp: false, isp_exp_ms: -999000, isp_gain: -9990 },
    });
    render(Settings);
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Auto").length).toBe(2),
    );
    const autoInputs = screen.getAllByPlaceholderText("Auto") as HTMLInputElement[];
    for (const input of autoInputs) {
      expect(input).toBeDisabled();
      expect(input.value).toBe("");
    }
    expect(screen.getAllByText(/Enable Manual Exposure to edit/).length).toBe(2);
    expect(screen.queryByDisplayValue("-999000")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("-9990")).not.toBeInTheDocument();
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
