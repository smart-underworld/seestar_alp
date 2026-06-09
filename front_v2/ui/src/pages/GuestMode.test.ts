import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";
import type { GuestModeState } from "../lib/api";

const { mockGet, mockGrab, mockRelease } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockGrab: vi.fn(),
  mockRelease: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      guestmode: { get: mockGet, grab: mockGrab, release: mockRelease },
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import GuestMode from "./GuestMode.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

const HANG = new Promise<never>(() => {});

const BASE_STATE: GuestModeState = {
  firmware_ver_int: 775,
  guest_mode: true,
  client_master: false,
  master_index: -1,
  client_list: [],
};

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockGet.mockReset();
  mockGrab.mockReset();
  mockRelease.mockReset();
  mockGet.mockReturnValue(HANG);
  mockGrab.mockResolvedValue({});
  mockRelease.mockResolvedValue({});
});

describe("GuestMode — offline", () => {
  it("shows offline message when not connected", () => {
    render(GuestMode);
    expect(screen.getByText("Device 1 is offline.")).toBeInTheDocument();
  });
});

describe("GuestMode — loading", () => {
  it("shows loading placeholder while fetch is pending", () => {
    mockIsConnected.set(true);
    render(GuestMode);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});

describe("GuestMode — error", () => {
  it("shows error when get fails", async () => {
    mockIsConnected.set(true);
    mockGet.mockRejectedValue(new Error("connection refused"));
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByText(/connection refused/)).toBeInTheDocument(),
    );
  });
});

describe("GuestMode — guest_mode unavailable", () => {
  it("shows unavailable message when firmware does not support guest mode", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, guest_mode: false, firmware_ver_int: 600 });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByText(/not available/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/firmware 600/)).toBeInTheDocument();
  });
});

describe("GuestMode — connected clients", () => {
  it("shows Connected Clients panel with client list", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({
      ...BASE_STATE,
      master_index: 0,
      client_list: ["192.168.1.1", "192.168.1.2"],
    });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByText("Connected Clients")).toBeInTheDocument(),
    );
    expect(screen.getByText("192.168.1.1")).toBeInTheDocument();
    expect(screen.getByText("192.168.1.2")).toBeInTheDocument();
    expect(screen.getByText("Controller")).toBeInTheDocument();
    expect(screen.getByText("Guest")).toBeInTheDocument();
  });

  it("shows no clients message when list is empty", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, client_list: [] });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByText("No clients connected.")).toBeInTheDocument(),
    );
  });
});

describe("GuestMode — actions", () => {
  it("Claim Control is enabled when master_index is -1", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, master_index: -1, client_master: false });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Claim Control" })).not.toBeDisabled(),
    );
  });

  it("Claim Control is disabled when already claimed (master_index >= 0)", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, master_index: 0, client_master: false });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Claim Control" })).toBeDisabled(),
    );
  });

  it("Release Control is enabled when client_master is true", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, master_index: 0, client_master: true });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Release Control" })).not.toBeDisabled(),
    );
  });

  it("calls guestmode.grab when Claim Control is clicked", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, master_index: -1, client_master: false });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Claim Control" })).not.toBeDisabled(),
    );
    screen.getByRole("button", { name: "Claim Control" }).click();
    await waitFor(() => expect(mockGrab).toHaveBeenCalledWith(1));
  });

  it("calls guestmode.release when Release Control is clicked", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, master_index: 0, client_master: true });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Release Control" })).not.toBeDisabled(),
    );
    screen.getByRole("button", { name: "Release Control" }).click();
    await waitFor(() => expect(mockRelease).toHaveBeenCalledWith(1));
  });

  it("shows guest hint when not client_master", async () => {
    mockIsConnected.set(true);
    mockGet.mockResolvedValue({ ...BASE_STATE, client_master: false, master_index: 0 });
    render(GuestMode);
    await waitFor(() =>
      expect(screen.getByText(/currently a guest/)).toBeInTheDocument(),
    );
  });
});
