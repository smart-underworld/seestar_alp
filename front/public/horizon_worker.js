// Horizon page worker: the MMhorizon core (WebAssembly) and the open panorama.
// Opening a 35-megapixel photo takes seconds; here it does not freeze the page.
//
// Messages: {id, op, args} in, {id, result} or {id, error} out.

import init, { Releve } from "./mmhorizon/mmhorizon_wasm.js";
import { horizonLineFromSun } from "./horizon_panorama_core.js";

const ready = init();
let releve = null;

function state() {
  const north = releve.nord;
  return {
    infos: JSON.parse(releve.infos()),
    horizon: releve.horizon,
    north: north ?? null,
    turn: releve.tour,
    limit: releve.limite(),
    // Columns of north, east, south and west, once north is set.
    cardinals: north === undefined ? null : [0, 90, 180, 270].map((a) => releve.colonneDAzimut(a)),
  };
}

const operations = {
  open({ bytes, name }) {
    if (releve) {
      releve.free();
      releve = null;
    }
    releve = new Releve(new Uint8Array(bytes), name);
    return {
      ...state(),
      width: releve.largeur,
      height: releve.hauteur,
      previewWidth: releve.apercuLargeur,
      previewHeight: releve.apercuHauteur,
      preview: releve.apercu(),
    };
  },
  setNorth({ column }) {
    releve.fixerNord(column);
    return state();
  },
  setHorizon({ row }) {
    releve.fixerHorizon(row);
    return state();
  },
  // The same point seen at columns a and b, at both ends of a panorama that
  // runs past a full turn: one turn is the distance between them.
  setTurn({ a, b }) {
    releve.fixerTour(a, b);
    return state();
  },
  // The Sun at (column, row) stands at (azimuth, altitude): it sets both
  // north and the horizon line.
  orientOnSun({ column, row, azimuth, altitude }) {
    releve.fixerHorizon(horizonLineFromSun(row, releve.ligneDeHauteur(altitude), releve.horizon));
    releve.fixerReference(column, azimuth);
    return state();
  },
  direction({ column, row }) {
    return { azimuth: releve.azimutDeColonne(column), altitude: releve.hauteurDeLigne(row) };
  },
  files({ site }) {
    return {
      hrz: new TextDecoder().decode(releve.exporter("nina", site)),
      horizonJson: releve.fichierHorizon(site),
    };
  },
};

self.onmessage = async ({ data: { id, op, args } }) => {
  try {
    await ready;
    const result = operations[op](args);
    self.postMessage({ id, result }, result.preview ? [result.preview.buffer] : []);
  } catch (e) {
    self.postMessage({ id, error: String((e && e.message) || e) });
  }
};
