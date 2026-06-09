import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import { writable } from "svelte/store";

// Planning.svelte uses fetch() from onMount for its data — mocking that reliably
// in jsdom/onMount context is not supported here. These tests cover the static
// template structure (section cards, controls) which render independently of data.

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: { devices: { schedule: { addItem: vi.fn().mockResolvedValue({}) } } },
}));

// Provide a no-op fetch so the onMount doesn't throw; data-display tests are
// intentionally omitted — they'd require jsdom fetch interception.
vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ lat: 0, lon: 0, utc_offset: 0, twilight: {}, clear_dark_sky: {} }),
}));

import Planning from "./Planning.svelte";

describe("Planning — page structure", () => {
  it("renders the Planning page heading", () => {
    render(Planning);
    expect(screen.getByRole("heading", { name: "Planning" })).toBeInTheDocument();
  });

  it("renders all five section card headings", () => {
    render(Planning);
    expect(screen.getByText("AstroMosaic")).toBeInTheDocument();
    expect(screen.getByText("Twilight Times")).toBeInTheDocument();
    expect(screen.getByText("Clear Dark Sky")).toBeInTheDocument();
    expect(screen.getByText("Astrospheric")).toBeInTheDocument();
    expect(screen.getByText("Clear Outside")).toBeInTheDocument();
  });

  it("renders AstroMosaic search input and model selector", () => {
    render(Planning);
    expect(screen.getByLabelText("Seestar Model")).toBeInTheDocument();
    expect(screen.getByLabelText("Search")).toBeInTheDocument();
  });

  it("renders AstroMosaic grid controls", () => {
    render(Planning);
    expect(screen.getByLabelText("Grid (X × Y)")).toBeInTheDocument();
    expect(screen.getByLabelText("Overlap %")).toBeInTheDocument();
  });

  it("renders Send to Schedule button (disabled when offline)", () => {
    render(Planning);
    const btn = screen.getByRole("button", { name: /Send/ });
    expect(btn).toBeDisabled();
  });
});
