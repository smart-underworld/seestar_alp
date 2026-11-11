import {
  MARK_COLORS,
  columnsEveryTurn,
  extent,
  hasUtcOffset,
  horizonLineFromSun,
  photoPoint,
  photoTime,
  profilePoints,
  siteOfRecord,
  summary,
  sunUnavailable,
  turnBetween,
} from "../public/horizon_panorama_core.js";

describe("horizon_panorama_core.js", () => {
  it("moves the horizon line so that the Sun's row has the Sun's altitude", () => {
    // Under a horizon at row 1400, altitude 26.3 falls on row 404; the Sun is
    // seen on row 433: the horizon is 29 rows lower.
    expect(horizonLineFromSun(433, 404, 1400)).toBe(1429);
  });

  it("sends a photo date with offset as UTC, and one without as written", () => {
    expect(photoTime("2026-10-23T15:59:17+02:00")).toBe("2026-10-23T13:59:17.000Z");
    // Local time of the site, read by the server: not this browser's zone.
    expect(photoTime("2026-10-23T15:59:17")).toBe("2026-10-23T15:59:17");
    expect(photoTime(null)).toBeNull();
    expect(photoTime("not a date")).toBeNull();
    expect(hasUtcOffset("2026-10-23T15:59:17+02:00")).toBe(true);
    expect(hasUtcOffset("2026-10-23T15:59:17Z")).toBe(true);
    expect(hasUtcOffset("2026-10-23T15:59:17")).toBe(false);
  });

  it("reads EXIF's own date form, which Date does not", () => {
    expect(photoTime("2026:10:23 15:59:17")).toBe("2026-10-23T15:59:17");
    expect(photoTime("2026:10:23 15:59:17+02:00")).toBe("2026-10-23T13:59:17.000Z");
    expect(hasUtcOffset("2026:10:23 15:59:17")).toBe(false);
  });

  it("offers Sun mode only with a readable date and a known place", () => {
    const located = { date: "2026-10-23T15:59:17+02:00", latitude: 44.06, longitude: 0.65 };
    expect(sunUnavailable(located, 0, 0)).toBeNull();
    // No GPS in the photo: the ALP's location, unless it is unset (0, 0).
    const unplaced = { date: "2026-10-23T15:59:17+02:00", latitude: null, longitude: null };
    expect(sunUnavailable(unplaced, 44.06, 0.65)).toBeNull();
    expect(sunUnavailable(unplaced, 0, 0)).toMatch(/Latitude and Longitude are not set/);
    expect(sunUnavailable({ ...unplaced, latitude: undefined, longitude: undefined }, 0, 0)).not.toBeNull();
    // A date the browser cannot read, or none.
    expect(sunUnavailable({ ...located, date: "23/10/2026 15h59" }, 44.06, 0.65)).toMatch(/cannot be read/);
    expect(sunUnavailable({ ...located, date: null }, 44.06, 0.65)).toBe("the photo has no date");
  });

  it("records the photo's place, else the ALP's, and no place rather than 0 N 0 E", () => {
    const located = { latitude: 44.06, longitude: 0.65 };
    const unplaced = { latitude: null, longitude: null };
    expect(JSON.parse(siteOfRecord(located, 45, 1))).toEqual({ latitude: 44.06, longitude: 0.65 });
    expect(JSON.parse(siteOfRecord(unplaced, 45, 1))).toEqual({ latitude: 45, longitude: 1 });
    expect(siteOfRecord(unplaced, 0, 0)).toBeNull();
    expect(siteOfRecord({}, NaN, NaN)).toBeNull();
  });

  it("repeats a cardinal mark on every turn, and stops whatever the turn", () => {
    expect(columnsEveryTurn(1000, 10467, 12672)).toEqual([1000, 11467]);
    expect(columnsEveryTurn(3000, 10467, 12672)).toEqual([3000]);
    // A turn of 0, or not a number: the mark once, never an endless loop.
    expect(columnsEveryTurn(1000, 0, 12672)).toEqual([1000]);
    expect(columnsEveryTurn(1000, NaN, 12672)).toEqual([1000]);
    expect(columnsEveryTurn(1000, 1e-9, 12672).length).toBe(8);
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
