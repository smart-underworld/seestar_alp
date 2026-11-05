// @vitest-environment node
// The bundled MMhorizon module loads and runs: its self-check analyses a
// synthetic panorama whose profile is known.
import fs from "node:fs";
import path from "node:path";

import { controle, initSync, Releve, version } from "../public/mmhorizon/mmhorizon_wasm.js";

describe("mmhorizon_wasm.js", () => {
  beforeAll(() => {
    initSync({ module: fs.readFileSync(path.resolve(process.cwd(), "public/mmhorizon/mmhorizon_wasm_bg.wasm")) });
  });

  it("passes its self-check", () => {
    expect(version()).toBe("0.1.3");
    expect(controle()).toMatch(/^contrôle : tour 1800\.0 px/);
  });

  it("has what the Horizon page calls", () => {
    for (const method of ["fixerNord", "fixerReference", "fixerHorizon", "fixerTour", "exporter", "fichierHorizon"]) {
      expect(typeof Releve.prototype[method]).toBe("function");
    }
  });

  it("reports an unreadable photo as an exception", () => {
    expect(() => new Releve(new Uint8Array([1, 2, 3]), "nothing.jpg")).toThrow(/photo illisible/);
  });
});
