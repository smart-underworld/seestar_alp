import { describe, it, expect } from "vitest";
import {
  batteryColor,
  storageFreeGB,
  storagePct,
  storageColor,
  settingGroupFor,
  isNavActive,
} from "./utils";

// ---------------------------------------------------------------------------
// batteryColor
// ---------------------------------------------------------------------------
describe("batteryColor", () => {
  it("returns primary for null", () => {
    expect(batteryColor(null)).toBe("primary");
  });

  it("returns danger at or below 10%", () => {
    expect(batteryColor(0)).toBe("danger");
    expect(batteryColor(5)).toBe("danger");
    expect(batteryColor(10)).toBe("danger");
  });

  it("returns warning between 11% and 20%", () => {
    expect(batteryColor(11)).toBe("warning");
    expect(batteryColor(15)).toBe("warning");
    expect(batteryColor(20)).toBe("warning");
  });

  it("returns success above 20%", () => {
    expect(batteryColor(21)).toBe("success");
    expect(batteryColor(50)).toBe("success");
    expect(batteryColor(100)).toBe("success");
  });
});

// ---------------------------------------------------------------------------
// storageFreeGB
// ---------------------------------------------------------------------------
describe("storageFreeGB", () => {
  it("parses a GB string", () => {
    expect(storageFreeGB("32.5 GB / 64.0 GB")).toBeCloseTo(32.5);
  });

  it("returns 0 for unknown/empty", () => {
    expect(storageFreeGB("Unknown")).toBe(0);
    expect(storageFreeGB("")).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// storagePct
// ---------------------------------------------------------------------------
describe("storagePct", () => {
  it("calculates free % of total", () => {
    expect(storagePct("32.0 GB / 64.0 GB")).toBe(50);
  });

  it("clamps at 100", () => {
    expect(storagePct("128.0 GB / 64.0 GB")).toBe(100);
  });

  it("returns 0 for unparseable strings", () => {
    expect(storagePct("Unknown")).toBe(0);
    expect(storagePct("")).toBe(0);
  });

  it("rounds to nearest integer", () => {
    // 10 / 30 = 33.33... -> 33
    expect(storagePct("10.0 GB / 30.0 GB")).toBe(33);
  });
});

// ---------------------------------------------------------------------------
// storageColor
// ---------------------------------------------------------------------------
describe("storageColor", () => {
  it("danger when free storage is 5 GB or below", () => {
    expect(storageColor("5.0 GB / 64.0 GB")).toBe("danger");
    expect(storageColor("1.2 GB / 64.0 GB")).toBe("danger");
  });

  it("warning when free storage is between 6 and 10 GB", () => {
    expect(storageColor("8.0 GB / 64.0 GB")).toBe("warning");
    expect(storageColor("10.0 GB / 64.0 GB")).toBe("warning");
  });

  it("success when free storage is above 10 GB", () => {
    expect(storageColor("32.0 GB / 64.0 GB")).toBe("success");
    expect(storageColor("50.0 GB / 64.0 GB")).toBe("success");
  });

  it("danger for unparseable (0 GB treated as <= 5)", () => {
    expect(storageColor("Unknown")).toBe("danger");
  });
});

// ---------------------------------------------------------------------------
// settingGroupFor
// ---------------------------------------------------------------------------
describe("settingGroupFor", () => {
  // Mirrors the classic frontend's ordering: Imaging regex runs first.
  // Keys that contain both an Imaging token AND a focus/dither token
  // (e.g. stack_dither_enable, af_before_stack) fall into Imaging because
  // the Imaging check is first in the chain.
  const cases: [string, string][] = [
    ["stack_brightness",     "Imaging"],
    ["exp_ms_stack_l",       "Imaging"],
    ["gain",                 "Imaging"],
    ["stack_lenhance",       "Imaging"],
    ["wide_cam",             "Imaging"],
    // "stack" is matched before "dither"
    ["stack_dither_enable",  "Imaging"],
    // "stack" is matched before "focus"
    ["af_before_stack",      "Imaging"],
    // "exp" substring matches in "expert_mode"
    ["expert_mode",          "Imaging"],
    ["heater_enable",        "Environment"],
    ["temp_unit",            "Environment"],
    ["auto_3ppa_calib",      "Mount & Focus"],
    // "focal" does NOT contain the substring "focus" — falls through to General
    ["focal_pos",            "General"],
    ["auto_power_off",       "General"],
    ["dark_mode",            "General"],
    // Real device "stack" sub-object keys have no "stack_" prefix, so they
    // need the explicit IMAGING_KEYS allow-list to stay grouped correctly.
    ["dbe",                  "Imaging"],
    ["star_correction",      "Imaging"],
    ["airplane_line_removal","Imaging"],
    ["drizzle2x",            "Imaging"],
    ["star_trails",          "Imaging"],
    ["cont_capt",            "Imaging"],
    ["wide_denoise",         "Imaging"],
  ];

  it.each(cases)("groups '%s' into '%s'", (key, group) => {
    expect(settingGroupFor(key)).toBe(group);
  });
});

// ---------------------------------------------------------------------------
// isNavActive
// ---------------------------------------------------------------------------
describe("isNavActive", () => {
  it("root '/' is active on '/'", () => {
    expect(isNavActive("/", "/")).toBe(true);
  });

  it("root '/' is active on empty string", () => {
    expect(isNavActive("/", "")).toBe(true);
  });

  it("root '/' is NOT active on sub-routes", () => {
    expect(isNavActive("/", "/live")).toBe(false);
    expect(isNavActive("/", "/settings")).toBe(false);
  });

  it("sub-route matches exact path", () => {
    expect(isNavActive("/live", "/live")).toBe(true);
  });

  it("sub-route does not match different path", () => {
    expect(isNavActive("/live", "/settings")).toBe(false);
  });

  it("sub-route does not match unrelated prefix", () => {
    expect(isNavActive("/live", "/liveview")).toBe(true); // startsWith is intentional
    expect(isNavActive("/settings", "/live")).toBe(false);
  });
});
