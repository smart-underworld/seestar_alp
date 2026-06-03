import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/svelte";
import { writable } from "svelte/store";
import Nav from "./Nav.svelte";

// Mock the deviceStore so we can inject test values
vi.mock("../stores/deviceStore", () => ({
  deviceList:   writable([]),
  activeDevNum: writable(1),
}));

import * as deviceStore from "../stores/deviceStore";

const { deviceList, activeDevNum } = deviceStore as {
  deviceList: ReturnType<typeof writable>;
  activeDevNum: ReturnType<typeof writable>;
};

beforeEach(() => {
  deviceList.set([]);
  activeDevNum.set(1);
});

describe("Nav", () => {
  it("renders the brand link", () => {
    render(Nav);
    expect(screen.getByText(/seestar alp/i)).toBeInTheDocument();
  });

  it("renders all seven nav links", () => {
    render(Nav);
    const labels = ["Home", "Live", "GoTo", "Image", "Schedule", "Settings", "Command"];
    for (const label of labels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows 'No devices' chip when device list is empty", () => {
    render(Nav);
    expect(screen.getByText(/no devices/i)).toBeInTheDocument();
  });

  it("shows a single device chip when one device is configured", () => {
    deviceList.set([{ device_num: 1, name: "Seestar S50", ip_address: "192.168.1.10", is_connected: true }]);
    render(Nav);
    expect(screen.getByText(/seestar s50/i)).toBeInTheDocument();
  });

  it("shows a connected dot indicator for a connected device", () => {
    deviceList.set([{ device_num: 1, name: "MyStar", ip_address: "10.0.0.1", is_connected: true }]);
    const { container } = render(Nav);
    const dot = container.querySelector(".dot.online");
    expect(dot).toBeInTheDocument();
  });

  it("shows an offline dot indicator for an offline device", () => {
    deviceList.set([{ device_num: 1, name: "MyStar", ip_address: "10.0.0.1", is_connected: false }]);
    const { container } = render(Nav);
    const dot = container.querySelector(".dot");
    expect(dot).toBeInTheDocument();
    expect(dot).not.toHaveClass("online");
  });

  it("renders a select when multiple devices are present", () => {
    deviceList.set([
      { device_num: 1, name: "Seestar A", ip_address: "10.0.0.1", is_connected: true },
      { device_num: 2, name: "Seestar B", ip_address: "10.0.0.2", is_connected: false },
    ]);
    const { container } = render(Nav);
    expect(container.querySelector("select.device-select")).toBeInTheDocument();
  });

  it("multi-device select contains each device name", () => {
    deviceList.set([
      { device_num: 1, name: "Alpha", ip_address: "10.0.0.1", is_connected: true },
      { device_num: 2, name: "Beta",  ip_address: "10.0.0.2", is_connected: false },
    ]);
    render(Nav);
    expect(screen.getByText(/alpha/i)).toBeInTheDocument();
    expect(screen.getByText(/beta.*offline/i)).toBeInTheDocument();
  });
});
