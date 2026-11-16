import fs from "node:fs";
import path from "node:path";

function loadScript(relPath) {
  const scriptPath = path.resolve(process.cwd(), relPath);
  const source = fs.readFileSync(scriptPath, "utf8");
  window.eval(source);
}

// Any property, any call: enough to stand in for Aladin and the chart classes.
const stub = new Proxy(function () {}, {
  get: (target, prop) => (prop === Symbol.toPrimitive ? () => 0 : stub),
  apply: () => stub,
});

function stubGoogleCharts(tables) {
  class DataTable {
    constructor() {
      this.columns = [];
      this.rows = [];
      tables.push(this);
    }
    addColumn(type, label) {
      this.columns.push(typeof type === "object" ? type.label : label);
    }
    addRow(row) {
      this.rows.push(row);
    }
    addRows(rows) {
      if (Array.isArray(rows)) this.rows.push(...rows);
    }
    getNumberOfRows() {
      return this.rows.length;
    }
  }
  window.google = {
    charts: { load() {}, setOnLoadCallback: (callback) => callback() },
    visualization: new Proxy(
      { DataTable },
      { get: (target, prop) => (prop in target ? target[prop] : stub) },
    ),
  };
}

// Day-chart rows for a target, with the engine called the way the planner
// card (partials/astro_mosaic.html) calls it.
function dayRows(target, horizonHard, horizonSoft = null) {
  const tables = [];
  stubGoogleCharts(tables);
  window.A = stub;
  const ids = [
    "aladin-div",
    "radec-div",
    "day-div",
    "dayvisibility-panel-text",
    "year-div",
    "yearvisibility-panel-text",
    "status-text",
    "error-text",
  ];
  document.body.innerHTML = ids.map((id) => `<div id="${id}"></div>`).join("");
  const params = {
    fov_x: 43.8,
    fov_y: 77.4,
    am_fov_x: 0.73,
    am_fov_y: 1.29,
    grid_type: "fov",
    grid_size_x: 1,
    grid_size_y: 1,
    grid_overlap: 100,
    location_lat: 44.06,
    location_lng: 0.65,
    horizonSoft,
    horizonHard,
    meridian_transit: null,
    UTCdate_ms: Date.UTC(2026, 9, 24, 0, 0, 0, 0),
    timezoneOffset: 2,
    isCustomMode: true,
    isRepositionModeFunc: () => false,
    repositionTargetFunc: () => {},
  };
  const panels = {
    aladin_panel: "aladin-div",
    aladin_panel_text: "radec-div",
    dayvisibility_panel: "day-div",
    dayvisibility_panel_text: "dayvisibility-panel-text",
    yearvisibility_panel: "year-div",
    yearvisibility_panel_text: "yearvisibility-panel-text",
    status_text: "status-text",
    error_text: "error-text",
    panel_view_x: null,
    panel_view_y: null,
    panel_view_div: null,
    panel_view_text: null,
  };
  window.StartAstroMosaicViewerEngine("all", target, params, panels, null, 100, {});
  const day = tables.find((table) => table.columns.includes("Not visible"));
  if (!day) {
    // The stubs can swallow an exception thrown inside the engine: fail here
    // with the reason rather than on an undefined table below.
    const error = document.getElementById("error-text").innerHTML;
    throw new Error(`no day-visibility table was built (engine error: ${error || "none"})`);
  }
  const visible = day.columns.indexOf("Visible");
  const hidden = day.columns.indexOf("Not visible");
  const value = (cell) => (cell && typeof cell === "object" ? cell.v : cell);
  return day.rows.map((row) => ({
    visible: value(row[visible]),
    hidden: value(row[hidden]),
  }));
}

describe("AstroMosaicEngine.js horizon", () => {
  beforeAll(() => {
    window.console.log = () => {};
    loadScript("public/AstroMosaicEngine.js");
  });

  it("pads horizon limits to one value every 5 degrees, 0 to 355", () => {
    const limits = window.fillHorizonLimits([30]);
    expect(limits).toHaveLength(72);
    expect(limits.every((limit) => limit === 30)).toBe(true);
    expect(window.fillHorizonLimits(null)).toHaveLength(72);
  });

  it("leaves the caller's horizon array as it was", () => {
    const horizon = [30];
    const limits = window.fillHorizonLimits(horizon);
    expect(limits).toHaveLength(72);
    expect(horizon).toEqual([30]);
  });

  it("uses a soft-only horizon as the hard one, as the wrapper does", () => {
    const params = { horizonSoft: [20], horizonHard: null };
    window.normalizeHorizonLimits(params);
    expect(params.horizonSoft).toBeNull();
    expect(params.horizonHard).toHaveLength(72);
    expect(params.horizonHard.every((limit) => limit === 20)).toBe(true);
  });

  it("draws a flat 0 degree horizon when none is given", () => {
    const params = { horizonSoft: null, horizonHard: null };
    window.normalizeHorizonLimits(params);
    expect(params.horizonHard).toHaveLength(72);
    expect(params.horizonHard.every((limit) => limit === 0)).toBe(true);
  });

  it("maps azimuths of 357.5 degrees and more to the limit at 0", () => {
    expect(window.horizonLimitIndex(0)).toBe(0);
    expect(window.horizonLimitIndex(352.4)).toBe(70);
    expect(window.horizonLimitIndex(355)).toBe(71);
    expect(window.horizonLimitIndex(357.5)).toBe(0);
    expect(window.horizonLimitIndex(359.8)).toBe(0);
    const limits = window.fillHorizonLimits([30]);
    for (let az = 0; az < 360; az += 0.5) {
      expect(limits[window.horizonLimitIndex(az)]).toBe(30);
    }
  });

  it("draws a target high above a flat horizon as visible", () => {
    // M31 culminates at about 84 degrees from 44 N: above 30 degrees for most of the night.
    const rows = dayRows("00:42:44 +41:16:09", [30]);
    const visible = rows.filter((row) => row.visible != null);
    const hidden = rows.filter((row) => row.hidden != null);
    expect(visible.length).toBeGreaterThan(rows.length / 2);
    expect(visible.every((row) => row.visible > 30)).toBe(true);
    expect(hidden.every((row) => row.hidden <= 30)).toBe(true);
  });

  it("draws Polaris as visible all night, across azimuth 360", () => {
    const rows = dayRows("02:31:49 +89:15:51", [30]);
    expect(rows.every((row) => row.visible != null)).toBe(true);
  });

  it("draws a soft-only horizon like a hard one", () => {
    const rows = dayRows("00:42:44 +41:16:09", null, [30]);
    const visible = rows.filter((row) => row.visible != null);
    expect(visible.length).toBeGreaterThan(rows.length / 2);
    expect(visible.every((row) => row.visible > 30)).toBe(true);
  });
});

describe("AstroMosaicEngine.js name resolution without CDS", () => {
  const ids = ["aladin-div", "radec-div", "day-div", "dayvisibility-panel-text", "year-div", "yearvisibility-panel-text", "status-text", "error-text"];
  const panels = {
    aladin_panel: "aladin-div", aladin_panel_text: "radec-div",
    dayvisibility_panel: "day-div", dayvisibility_panel_text: "dayvisibility-panel-text",
    yearvisibility_panel: "year-div", yearvisibility_panel_text: "yearvisibility-panel-text",
    status_text: "status-text", error_text: "error-text",
    panel_view_x: null, panel_view_y: null, panel_view_div: null, panel_view_text: null,
  };
  const params = {
    fov_x: 43.8, fov_y: 77.4, am_fov_x: 0.73, am_fov_y: 1.29, grid_type: "fov",
    grid_size_x: 1, grid_size_y: 1, grid_overlap: 100, location_lat: 44.06, location_lng: 0.65,
    horizonSoft: null, horizonHard: [0], meridian_transit: null,
    UTCdate_ms: Date.UTC(2026, 9, 24), timezoneOffset: 2, isCustomMode: true,
    isRepositionModeFunc: () => false, repositionTargetFunc: () => {},
  };

  // Sesame (CDS) refuses; /localsearch answers with `hits`. Returns the day
  // charts built, so a test can tell the engine got as far as drawing.
  async function run(target, hits, localOk = true) {
    const tables = [];
    stubGoogleCharts(tables);
    window.A = stub;
    window.alert = vi.fn();
    document.body.innerHTML = ids.map((id) => `<div id="${id}"></div>`).join("");
    const urls = [];
    window.fetch = vi.fn((url) => {
      urls.push(url);
      if (url.includes("nph-sesame")) return Promise.reject(new TypeError("NetworkError"));
      if (!localOk) return Promise.resolve({ ok: false, status: 404, text: () => Promise.resolve("") });
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(JSON.stringify(hits)) });
    });
    window.StartAstroMosaicViewerEngine("all", target, params, panels, null, 100, {});
    await new Promise((resolve) => setTimeout(resolve, 20));
    return { tables, urls, error: document.getElementById("error-text").innerHTML };
  }

  beforeAll(() => {
    window.console.log = () => {};
    loadScript("public/AstroMosaicEngine.js");
  });

  it("uses the local object database when Sesame is unreachable and no catalogs are loaded", async () => {
    const m33 = { ra: "01h33m50.89s", dec: "+30d39m36.8s", lp: "false", objectName: "Triangulum Galaxy", identifiers: "M33" };
    const m30 = { ra: "21h40m22.02s", dec: "-23d10m44.7s", lp: "false", objectName: "M30", identifiers: "M30" };
    const out = await run("M33", [m30, m33]);
    expect(out.urls.some((u) => u.endsWith("/localsearch?target=M33"))).toBe(true);
    expect(out.error).toBe("");
    expect(out.tables.some((t) => t.columns.includes("Not visible"))).toBe(true);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("asks the Harvard Sesame mirror before the local database when CDS is down", async () => {
    const tables = [];
    stubGoogleCharts(tables);
    window.A = stub;
    document.body.innerHTML = ids.map((id) => `<div id="${id}"></div>`).join("");
    const urls = [];
    window.fetch = vi.fn((url) => {
      urls.push(url);
      if (url.includes("u-strasbg")) return Promise.reject(new TypeError("NetworkError"));
      const xml = "<Sesame><jpos>01:33:50.9 +30:39:37</jpos></Sesame>";
      return Promise.resolve({ status: 200, ok: true, text: () => Promise.resolve(xml) });
    });
    window.StartAstroMosaicViewerEngine("all", "M33", params, panels, null, 100, {});
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(urls).toHaveLength(2);
    expect(urls[1]).toContain("vizier.cfa.harvard.edu");
    expect(urls.some((u) => u.includes("localsearch"))).toBe(false);
    expect(tables.some((t) => t.columns.includes("Not visible"))).toBe(true);
  });

  it("finds an object that has several catalogue ids among substring hits", async () => {
    // alp.dat stores "IC11 NGC281"; NGC2810.. also match a LIKE '%NGC281%'
    const hits = [
      { ra: "00h52m59.3s", dec: "+56d37m19s", lp: "true", objectName: "IC11 NGC281", identifiers: "IC11 NGC281" },
      { ra: "09h13m00s", dec: "-23d00m00s", lp: "false", objectName: "NGC2810", identifiers: "NGC2810" },
      { ra: "09h14m00s", dec: "-24d00m00s", lp: "false", objectName: "NGC2811", identifiers: "NGC2811" },
    ];
    const out = await run("NGC281", hits);
    expect(out.error).toBe("");
    expect(out.tables.some((t) => t.columns.includes("Not visible"))).toBe(true);
  });

  it("matches a full common name with spaces", async () => {
    const hits = [
      { ra: "00h42m44.35s", dec: "+41d16m08.6s", lp: "false", objectName: "Andromeda Galaxy", identifiers: "NGC224 M31" },
      { ra: "00h40m00s", dec: "+41d00m00s", lp: "false", objectName: "Andromeda II", identifiers: "A2" },
    ];
    const out = await run("Andromeda Galaxy", hits);
    expect(out.error).toBe("");
    expect(out.tables.some((t) => t.columns.includes("Not visible"))).toBe(true);
  });

  it("does not take a substring hit for another object", async () => {
    const m30 = { ra: "21h40m22.02s", dec: "-23d10m44.7s", lp: "false", objectName: "M30", identifiers: "M30" };
    const m35 = { ra: "06h09m05.06s", dec: "+24d20m19.1s", lp: "false", objectName: "M35", identifiers: "M35" };
    const out = await run("M3", [m30, m35]);
    expect(out.tables).toHaveLength(0);
    expect(out.error).toContain("Failed to resolve name M3");
  });

  it("shows an error, not an exception, when the local search finds nothing", async () => {
    const out = await run("Nosuchthing", [], false);
    expect(out.tables).toHaveLength(0);
    expect(out.error).toContain("Failed to resolve name Nosuchthing");
    expect(window.alert).not.toHaveBeenCalled();
  });
});
