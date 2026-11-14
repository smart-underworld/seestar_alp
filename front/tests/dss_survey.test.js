import fs from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const CDS_ID = "P/DSS2/color";
const ESA_URL = "https://skies.esac.esa.int/DSSColor";

// Loads a fresh copy of the script, which probes once at load.
function loadSurveyScript() {
  const scriptPath = path.resolve(process.cwd(), "public/dss_survey.js");
  window.eval(fs.readFileSync(scriptPath, "utf8"));
  return window.SSCDssSurvey;
}

const reply = (ok) =>
  ok ? Promise.resolve({ ok: true }) : Promise.reject(new TypeError("Failed to fetch"));

// Each host either answers, fails fast, or hangs until the probe aborts it.
function mockFetch({ cds, esa }) {
  window.fetch = vi.fn((url, options) => {
    const state = url.includes("alasky.cds.unistra.fr") ? cds : esa;
    if (state === "hang") {
      return new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    }
    return reply(state === "up");
  });
}

describe("DSS survey selection", () => {
  beforeEach(() => {
    delete window.SSCDssSurvey;
  });

  afterEach(() => {
    vi.useRealTimers();
    delete window.fetch;
  });

  it("keeps the CDS id when CDS answers", async () => {
    mockFetch({ cds: "up", esa: "up" });
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    expect(await survey.refresh()).toBe(CDS_ID);
    expect(survey.current()).toBe(CDS_ID);
    expect(seen).toEqual([]);
  });

  it("switches to the ESA mirror once, when CDS is down", async () => {
    mockFetch({ cds: "down", esa: "up" });
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    await survey.refresh();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(survey.current()).toBe(ESA_URL);
    expect(seen).toEqual([ESA_URL]);
  });

  it("falls back to the ESA mirror when CDS hangs past the timeout", async () => {
    vi.useFakeTimers();
    mockFetch({ cds: "hang", esa: "up" });
    const survey = loadSurveyScript();
    expect(survey.current()).toBe(CDS_ID);
    await vi.advanceTimersByTimeAsync(3100);
    expect(survey.current()).toBe(ESA_URL);
  });

  it("stays on the CDS id when neither host answers", async () => {
    mockFetch({ cds: "down", esa: "down" });
    const survey = loadSurveyScript();
    const seen = [];
    survey.onChange((s) => seen.push(s));
    expect(await survey.refresh()).toBe(CDS_ID);
    expect(seen).toEqual([]);
  });

  it("stays on the CDS id when fetch is unavailable", async () => {
    delete window.fetch;
    const survey = loadSurveyScript();
    expect(await survey.refresh()).toBe(CDS_ID);
  });

  it("does not let a throwing listener stop the others", async () => {
    mockFetch({ cds: "down", esa: "up" });
    const survey = loadSurveyScript();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const seen = [];
    survey.onChange(() => {
      throw new Error("boom");
    });
    survey.onChange((s) => seen.push(s));
    await survey.refresh();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(seen).toEqual([ESA_URL]);
    warn.mockRestore();
  });
});
