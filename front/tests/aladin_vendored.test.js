import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { describe, expect, it, vi } from "vitest";

const bundlePath = path.resolve(process.cwd(), "public/vendor/aladin-lite/aladin.js");

// The planner templates load aladin.js with a plain <script src>. An ES module
// build (the raw npm dist file) is a SyntaxError there, window.A never exists,
// and the sky map stays blank.
describe("vendored Aladin Lite bundle", () => {
  const source = fs.readFileSync(bundlePath, "utf8");

  it("parses as a classic script, not an ES module", () => {
    expect(() => new vm.Script(source, { filename: "aladin.js" })).not.toThrow();
  });

  it("does not end in an ES export", () => {
    expect(source.trimEnd().slice(-300)).not.toMatch(/export\s*\{/);
  });

  it("defines window.A with the Aladin API when run in a browser-like window", async () => {
    const win = window;
    delete win.A;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    // WebGL2 is not available in jsdom, so the library's async init rejects.
    // That is expected here; only the synchronous global matters.
    win.eval(source);
    expect(typeof win.A).toBe("object");
    expect(typeof win.A.aladin).toBe("function");
    expect(typeof win.A.polyline).toBe("function");
    if (win.A.init && win.A.init.catch) await win.A.init.catch(() => {});
  });
});
