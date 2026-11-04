import {
  MARK_COLORS,
  extent,
  hasUtcOffset,
  horizonLineFromSun,
  photoPoint,
  photoTimeUtc,
  profilePoints,
  summary,
  turnBetween,
} from "../public/horizon_panorama_core.js";

describe("horizon_panorama_core.js", () => {
  it("moves the horizon line so that the Sun's row has the Sun's altitude", () => {
    // Under a horizon at row 1400, altitude 26.3 falls on row 404; the Sun is
    // seen on row 433: the horizon is 29 rows lower.
    expect(horizonLineFromSun(433, 404, 1400)).toBe(1429);
  });

  it("reads the photo date as UTC, with or without offset", () => {
    expect(photoTimeUtc("2026-10-23T15:59:17+02:00")).toBe("2026-10-23T13:59:17.000Z");
    expect(photoTimeUtc("2026-10-23T15:59:17")).toBe(new Date(2026, 9, 23, 15, 59, 17).toISOString());
    expect(photoTimeUtc(null)).toBeNull();
    expect(photoTimeUtc("not a date")).toBeNull();
    expect(hasUtcOffset("2026-10-23T15:59:17+02:00")).toBe(true);
    expect(hasUtcOffset("2026-10-23T15:59:17Z")).toBe(true);
    expect(hasUtcOffset("2026-10-23T15:59:17")).toBe(false);
  });

  it("maps a click on the scaled canvas to photo pixels", () => {
    // 3600 x 795 preview of a 12672 x 2800 photo, drawn 1200 px wide at (10, 50).
    const rect = { left: 10, top: 50, width: 1200, height: 265 };
    const point = photoPoint(610, 182.5, rect, 3600, 795, 12672, 2800);
    expect(point.column).toBeCloseTo(6336, 6);
    expect(point.row).toBeCloseTo(1400, 6);
  });

  it("gives each mode button and its marks a colour of their own", () => {
    expect(Object.keys(MARK_COLORS)).toEqual(["turn", "sun", "north", "horizon"]);
    expect(new Set(Object.values(MARK_COLORS)).size).toBe(4);
    // Not the red of the detected limit.
    expect(Object.values(MARK_COLORS)).not.toContain("rgb(255, 40, 40)");
  });

  it("takes two clicks for one turn only between half and all of the photo width", () => {
    // The Sun of the 2026-10-23 panorama, at both ends of a 12672 px photo.
    expect(turnBetween(1710, 12177, 12672)).toBe(10467);
    expect(turnBetween(12177, 1710, 12672)).toBe(10467);
    expect(turnBetween(1710, 1790, 12672)).toBeNull(); // the same Sun, clicked again
    expect(turnBetween(0, 12673, 12672)).toBeNull();
    expect(turnBetween(0, 6336, 12672)).toBe(6336);
    expect(extent(12672, 10467)).toBeCloseTo(435.8, 1);
  });

  it("draws the profile like the Planning page's Horizon card", () => {
    const altitudes = Array.from({ length: 360 }, (_, azimuth) => (azimuth === 90 ? 25.5 : 10));
    altitudes[200] = null; // outside the panorama
    altitudes[300] = 95; // clamped to the 0-90 scale
    const points = profilePoints(altitudes).split(" ");
    expect(points[0]).toBe("0,90");
    expect(points[1]).toBe("0,80");
    expect(points[91]).toBe("90,64.5");
    expect(points[201]).toBe("200,90");
    expect(points[301]).toBe("300,0");
    expect(points.slice(-2)).toEqual(["360,80", "360,90"]);
  });

  it("summarises the panorama in English", () => {
    const text = summary({
      largeur: 12672,
      hauteur: 2800,
      projection: "cylindrique",
      couverture_deg: 360,
      couverture_methode: "supposee",
      champ_vertical_deg: [-34.207, 35.319],
      orientation: "paysage",
      objectif: "ultra-grand-angle",
      au_dela_du_champ: 3,
      gpano_ecarte: "GPano écarté : …",
    });
    expect(text).toBe(
      "12672 × 2800 px · cylindrical · 360° of azimuth (assumed full turn) · " +
        "altitude -34.2° to +35.3° · landscape, ultra-wide lens · " +
        "obstacles above the top of the photo over 3° · GPano metadata ignored: inconsistent with the lens",
    );
  });

  it("says how far a panorama runs past a full turn", () => {
    const infos = {
      largeur: 12672,
      hauteur: 2800,
      projection: "cylindrique",
      couverture_deg: 360,
      couverture_methode: "designation",
      tour_px: 10467,
      champ_vertical_deg: [-42.86, 36.97],
      orientation: "paysage",
      objectif: "ultra-grand-angle",
      au_dela_du_champ: 0,
      gpano_ecarte: null,
    };
    expect(summary(infos)).toBe(
      "12672 × 2800 px · cylindrical · 436° of azimuth, one turn in 10467 px (same point marked at both ends) · " +
        "altitude -42.9° to +37.0° · landscape, ultra-wide lens",
    );
    expect(summary({ ...infos, tour_px: 12672, couverture_methode: "supposee" })).toContain(
      "· 360° of azimuth (assumed full turn) ·",
    );
  });
});
