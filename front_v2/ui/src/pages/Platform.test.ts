import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";

const { mockGet, mockAction } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockAction: vi.fn(),
}));

vi.mock("../lib/api", () => ({
  api: { platform: { get: mockGet, action: mockAction } },
}));

import Platform from "./Platform.svelte";

beforeEach(() => {
  mockGet.mockReset();
  mockAction.mockReset();
  mockAction.mockResolvedValue({ status: "ok", message: "done" });
});

describe("Platform — non-Raspberry-Pi host", () => {
  it("shows an unavailable message", async () => {
    mockGet.mockResolvedValue({ platform: "linux" });
    render(Platform);
    await waitFor(() => {
      expect(screen.getByText(/not available for your platform/i)).toBeInTheDocument();
    });
  });
});

describe("Platform — Raspberry Pi host", () => {
  beforeEach(() => {
    mockGet.mockResolvedValue({ platform: "raspberry_pi" });
  });

  it("renders all four service/power action buttons", async () => {
    render(Platform);
    await waitFor(() => {
      expect(screen.getByText("Restart SSC/Alp service")).toBeInTheDocument();
    });
    expect(screen.getByText("Restart INDI service")).toBeInTheDocument();
    expect(screen.getByText("Reboot Rpi")).toBeInTheDocument();
    expect(screen.getByText("Shutdown Rpi")).toBeInTheDocument();
  });

  it("runs an action without confirmation and shows the returned message", async () => {
    render(Platform);
    const btn = await screen.findByText("Restart SSC/Alp service");
    await btn.click();
    await waitFor(() => {
      expect(mockAction).toHaveBeenCalledWith("restart_alp");
      expect(screen.getByText("done")).toBeInTheDocument();
    });
  });

  it("requires confirmation before running reboot/shutdown", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(Platform);
    const btn = await screen.findByText("Reboot Rpi");
    await btn.click();
    expect(confirmSpy).toHaveBeenCalled();
    expect(mockAction).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
