import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

import Support from "./Support.svelte";

function stubFetch(versionOverride = "") {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (String(url).includes("version")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ version: versionOverride }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({}),
        blob: async () => new Blob(["zip"], { type: "application/zip" }),
        headers: { get: () => 'filename="bundle.zip"' },
      });
    }),
  );
}

beforeEach(() => stubFetch());
afterEach(() => vi.unstubAllGlobals());

describe("Support — static content", () => {
  it("renders the four main panels", () => {
    render(Support);
    expect(screen.getByText("Documentation")).toBeInTheDocument();
    expect(screen.getByText("Community")).toBeInTheDocument();
    expect(screen.getByText(/Bug Reports/)).toBeInTheDocument();
    expect(screen.getByText("Support Bundle")).toBeInTheDocument();
  });

  it("renders GitHub documentation links", () => {
    render(Support);
    expect(screen.getByText("README.md")).toBeInTheDocument();
    expect(screen.getByText("GitHub Wiki")).toBeInTheDocument();
  });

  it("renders Discord community link", () => {
    render(Support);
    expect(screen.getByText("Join Discord Server")).toBeInTheDocument();
  });

  it("renders GitHub issue links", () => {
    render(Support);
    expect(screen.getByText("Browse existing issues")).toBeInTheDocument();
    expect(screen.getByText("Open a new issue")).toBeInTheDocument();
  });

  it("renders the Download Support Bundle button", () => {
    render(Support);
    expect(
      screen.getByRole("button", { name: /Download Support Bundle/ }),
    ).toBeInTheDocument();
  });

  it("renders the Problem Description textarea", () => {
    render(Support);
    expect(screen.getByLabelText("Problem Description")).toBeInTheDocument();
  });

  it("renders the seestar logs checkbox", () => {
    render(Support);
    expect(
      screen.getByText(/Collect embedded logs from the Seestar device/),
    ).toBeInTheDocument();
  });
});

describe("Support — download button state", () => {
  it("Download button is enabled by default", () => {
    render(Support);
    expect(
      screen.getByRole("button", { name: /Download Support Bundle/ }),
    ).not.toBeDisabled();
  });
});
