import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

import Config from "./Config.svelte";

const SAMPLE_CONFIG = {
  networking: { ip_address: "0.0.0.0", port: 4030, timeout: 60 },
  webui: { uiport: 5432, ui_theme: "dark", experimental: false },
  logging: { log_level: "INFO", log_to_stdout: true, max_log_size_mb: 10 },
  init: { latitude: 37.7, longitude: -122.4, gain: 80 },
  devices: [
    { device_num: 1, name: "My Seestar", ip_address: "192.168.1.10" },
  ],
};

function stubFetch(configOverride = SAMPLE_CONFIG) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      const method = opts?.method?.toUpperCase() ?? "GET";
      if (String(url).includes("/config/devices") && method === "POST") {
        return Promise.resolve({
          ok: true,
          json: async () => ({ devices: configOverride.devices }),
        });
      }
      if (String(url).includes("/config") && method === "POST") {
        return Promise.resolve({ ok: true, json: async () => ({}) });
      }
      return Promise.resolve({
        ok: true,
        json: async () => configOverride,
      });
    }),
  );
}

beforeEach(() => stubFetch());
afterEach(() => vi.unstubAllGlobals());

describe("Config — loading", () => {
  it("shows loading indicator initially", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(Config);
    expect(screen.getByText(/Loading/)).toBeInTheDocument();
  });
});

describe("Config — error", () => {
  it("shows error when config fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );
    render(Config);
    await waitFor(() =>
      expect(screen.getByText(/network down/)).toBeInTheDocument(),
    );
  });
});

describe("Config — sections", () => {
  it("renders Networking section", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Networking")).toBeInTheDocument(),
    );
    expect(screen.getByText("Bind IP Address")).toBeInTheDocument();
    expect(screen.getByText("Alpaca Port")).toBeInTheDocument();
  });

  it("renders WebUI section", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Web UI")).toBeInTheDocument(),
    );
    expect(screen.getByText("UI Port")).toBeInTheDocument();
    expect(screen.getByText("UI Theme")).toBeInTheDocument();
  });

  it("renders Logging section", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Logging")).toBeInTheDocument(),
    );
    expect(screen.getByText("Log Level")).toBeInTheDocument();
  });

  it("renders Seestar Init Defaults section", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Seestar Init Defaults")).toBeInTheDocument(),
    );
    expect(screen.getByText("Latitude")).toBeInTheDocument();
    expect(screen.getByText("Longitude")).toBeInTheDocument();
  });

  it("renders Devices section with device list", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Devices")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("My Seestar")).toBeInTheDocument();
    expect(screen.getByDisplayValue("192.168.1.10")).toBeInTheDocument();
  });
});

describe("Config — Save to config.toml", () => {
  it("Save button is disabled when no changes made", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByText("Networking")).toBeInTheDocument(),
    );
    // Button text is "Save to config.toml"; may appear twice (header + footer)
    const saveBtns = screen.getAllByRole("button", { name: /Save to config\.toml/ });
    expect(saveBtns.length).toBeGreaterThan(0);
    expect(saveBtns[0]).toBeDisabled();
  });
});

describe("Config — device management", () => {
  it("adds a new device row when Add Device is clicked", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add Device" })).toBeInTheDocument(),
    );
    const before = screen.getAllByPlaceholderText("Name").length;
    screen.getByRole("button", { name: "Add Device" }).click();
    await waitFor(() =>
      expect(screen.getAllByPlaceholderText("Name").length).toBe(before + 1),
    );
  });

  it("shows Save Devices button", async () => {
    render(Config);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Devices" })).toBeInTheDocument(),
    );
  });
});
