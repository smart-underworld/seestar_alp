import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const URLS = {
  stsci: "https://stpubdata.s3.us-east-1.amazonaws.com/mast/skybackgrounds/DSSColor",
  cds: "https://alasky.cds.unistra.fr/DSS/DSSColor",
  cdsbis: "https://alaskybis.cds.unistra.fr/DSS/DSSColor",
  csiro: "https://casda.csiro.au/hips/DSS2/color",
  chinavo: "https://hips.china-vo.org/m/CDS_P_DSS2_color",
  esa: "https://skies.esac.esa.int/DSSColor",
  irsa: "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color",
};
const HOST_MARKERS = {
  stsci: "stpubdata.s3",
  cds: "//alasky.cds.unistra.fr",
  cdsbis: "alaskybis.cds",
  csiro: "casda.csiro.au",
  chinavo: "hips.china-vo.org",
  esa: "skies.esac.esa.int",
  irsa: "irsa.ipac.caltech.edu",
};

// Loads a fresh copy of the script, which probes once at load.
function loadSurveyScript() {
  const scriptPath = path.resolve(process.cwd(), "public/dss_survey.js");
  window.eval(fs.readFileSync(scriptPath, "utf8"));
  return window.SSCDssSurvey;
}

const hostOf = (url) => Object.keys(HOST_MARKERS).find((k) => url.includes(HOST_MARKERS[k]));

// Each host either answers ("up"), fails fast ("down"), hangs until the probe
// aborts it ("hang"), answers properties but no tiles ("tiles-down"), or lacks
// only the second tile ("tile2-down"). Hosts not named are down.
function mockFetch(states) {
  window.fetch = vi.fn((url, options) => {
    let state = states[hostOf(url)] || "down";
    if (state === "tiles-down") state = url.endsWith("/properties") ? "up" : "down";
    if (state === "tile2-down") state = url.endsWith("Npix350.jpg") ? "down" : "up";
    if (state === "hang") {
      return new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    }
    return state === "up"
      ? Promise.resolve({ ok: true })
      : Promise.reject(new TypeError("Failed to fetch"));
  });
}

const calledHosts = () => [...new Set(window.fetch.mock.calls.map(([url]) => hostOf(url)))];
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("DSS survey selection", () => {
  beforeEach(() => {
    delete window.SSCDssSurvey;
  });

  afterEach(() => {
    vi.useRealTimers();
    delete window.fetch;
  });

  it("uses the first host when it answers, and probes no other", async () => {
    mockFetch({ stsci: "up", cds: "up" });
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    expect(await survey.refresh()).toBe(URLS.stsci);
    expect(seen).toEqual([]);
    expect(calledHosts()).toEqual(["stsci"]);
  });

  it("moves to CDS, once, when the first host is down", async () => {
    mockFetch({ stsci: "down", cds: "up" });
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    await survey.refresh();
    await tick();
    expect(survey.current()).toBe(URLS.cds);
    expect(seen).toEqual([URLS.cds]);
  });

  it("takes the first answering host in list order", async () => {
    mockFetch({ csiro: "up", chinavo: "up", esa: "up", irsa: "up" });
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.csiro);
  });

  it("falls back when the first host hangs past the timeout", async () => {
    vi.useFakeTimers();
    mockFetch({ stsci: "hang", cds: "up" });
    const survey = loadSurveyScript();
    expect(survey.current()).toBe(URLS.stsci);
    await vi.advanceTimersByTimeAsync(3100);
    expect(survey.current()).toBe(URLS.cds);
  });

  it("skips a host that answers properties but not tiles", async () => {
    mockFetch({ stsci: "tiles-down", cds: "up" });
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.cds);
  });

  it("requires both order-3 tiles from a full-sky host", async () => {
    mockFetch({ stsci: "tile2-down", cds: "up" });
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.cds);
  });

  it("uses the partial IRSA host only when no other answers, without the second tile", async () => {
    mockFetch({ irsa: "tile2-down" });
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.irsa);
    const irsaPaths = window.fetch.mock.calls
      .map(([url]) => url)
      .filter((url) => hostOf(url) === "irsa");
    expect(irsaPaths.some((url) => url.includes("Npix350"))).toBe(false);
  });

  it("prefers a full-sky host to IRSA", async () => {
    mockFetch({ esa: "up", irsa: "up" });
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.esa);
  });

  it("stays on the first host when no host answers", async () => {
    mockFetch({});
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    expect(await survey.refresh()).toBe(URLS.stsci);
    expect(seen).toEqual([]);
  });

  it("stays on the first host when fetch is unavailable", async () => {
    delete window.fetch;
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(URLS.stsci);
  });

  it("never hands Aladin the P/DSS2/color id", () => {
    mockFetch({ stsci: "up" });
    const survey = loadSurveyScript();
    expect(survey.current()).not.toContain("P/DSS2/color");
    expect(survey.current()).toMatch(/^https:\/\//);
  });

  it("does not let a throwing listener stop the others", async () => {
    mockFetch({ cds: "up" });
    const survey = loadSurveyScript();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const seen = [];
    survey.onChange(() => {
      throw new Error("boom");
    });
    survey.onChange((s) => seen.push(s));
    await survey.refresh();
    await tick();
    expect(seen).toEqual([URLS.cds]);
    warn.mockRestore();
  });

  it("ignores a second load of the script", async () => {
    mockFetch({ stsci: "up" });
    const first = loadSurveyScript();
    await tick();
    const probes = window.fetch.mock.calls.length;
    const second = loadSurveyScript();
    await tick();
    expect(second).toBe(first);
    expect(window.fetch.mock.calls.length).toBe(probes);
  });
});

describe("DSS survey periodic check", () => {
  const FIVE_MINUTES = 5 * 60 * 1000;

  beforeEach(() => {
    delete window.SSCDssSurvey;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete window.fetch;
  });

  it("leaves a working survey alone and probes only that host", async () => {
    mockFetch({ stsci: "up", cds: "up" });
    const survey = loadSurveyScript();
    await vi.advanceTimersByTimeAsync(10);
    window.fetch.mockClear();
    await vi.advanceTimersByTimeAsync(FIVE_MINUTES);
    expect(survey.current()).toBe(URLS.stsci);
    expect(calledHosts()).toEqual(["stsci"]);
  });

  it("does not switch on one failed check", async () => {
    mockFetch({ stsci: "up", cds: "up" });
    const survey = loadSurveyScript();
    await vi.advanceTimersByTimeAsync(10);
    const good = window.fetch.getMockImplementation();
    let failedOnce = false;
    window.fetch.mockImplementation((url, options) => {
      if (!failedOnce && hostOf(url) === "stsci") {
        failedOnce = true;
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return good(url, options);
    });
    await vi.advanceTimersByTimeAsync(FIVE_MINUTES);
    expect(survey.current()).toBe(URLS.stsci);
  });

  it("switches when the host in use keeps failing", async () => {
    mockFetch({ stsci: "up", cds: "up" });
    const survey = loadSurveyScript();
    await vi.advanceTimersByTimeAsync(10);
    const seen = [];
    survey.onChange((s) => seen.push(s));
    mockFetch({ stsci: "down", cds: "up" });
    await vi.advanceTimersByTimeAsync(FIVE_MINUTES);
    expect(survey.current()).toBe(URLS.cds);
    expect(seen).toEqual([URLS.cds]);
  });
});
