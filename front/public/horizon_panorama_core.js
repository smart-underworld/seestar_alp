// Horizon page: helpers without DOM or WebAssembly, shared by the page and its
// worker (and tested in front/tests/horizon_panorama.test.js).

/*
 * Colour of each mode button and of the marks it leaves on the panorama, in
 * the order of the steps: the two points of one turn, the Sun clicked, north
 * and the cardinal points, the horizon line.
 */
export const MARK_COLORS = {
  turn: "rgb(255, 0, 255)",
  sun: "rgb(255, 140, 0)",
  north: "rgb(255, 220, 0)",
  horizon: "rgb(0, 230, 230)",
};

/*
 * Horizon line (row at altitude 0) once the Sun, seen at row sunRow, is known
 * to stand at sunAltitude. rowOfSunAltitude is the row of that altitude under
 * the current horizon line: both projections MMhorizon handles move every
 * altitude by the same number of rows when the horizon line moves.
 */
export function horizonLineFromSun(sunRow, rowOfSunAltitude, currentHorizon) {
  return sunRow + (currentHorizon - rowOfSunAltitude);
}

/*
 * Photo date (ISO 8601, or EXIF's own "2026:10:23 15:59:17") as the `when` of
 * /horizon/sun; null when it cannot be read. A date with its UTC offset
 * (MMhorizon adds EXIF's OffsetTimeOriginal when the photo has one) goes as
 * UTC. One without goes as written, a local time that the server reads in
 * the site's time zone: this browser's may be another.
 */
export function photoTime(exifDate) {
  if (!exifDate) {
    return null;
  }
  const iso = String(exifDate).replace(/^(\d{4}):(\d\d):(\d\d)[ T]/, "$1-$2-$3T");
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  if (hasUtcOffset(iso)) {
    return date.toISOString();
  }
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d(\.\d+)?)?$/.test(iso) ? iso : null;
}

/*
 * Why the Sun cannot orient this photo, or null when it can. Its position
 * needs the time of the photo, and the place: the photo's GPS position, or
 * else the ALP's Latitude and Longitude, where 0, 0 stands for "not set".
 */
export function sunUnavailable(exif, siteLat, siteLon) {
  if (photoTime(exif.date) === null) {
    return exif.date ? `the photo's date (${exif.date}) cannot be read` : "the photo has no date";
  }
  const photoPlace = exif.latitude != null && exif.longitude != null;
  const sitePlace = knownPlace(siteLat, siteLon);
  if (!photoPlace && !sitePlace) {
    return "the photo has no GPS position and this ALP's Latitude and Longitude are not set (Settings)";
  }
  return null;
}

export function hasUtcOffset(exifDate) {
  return /([+-]\d\d:?\d\d|Z)$/.test(exifDate || "");
}

/* Whether lat, lon are a place: in Settings, 0, 0 stands for "not set". */
function knownPlace(lat, lon) {
  return Number.isFinite(lat) && Number.isFinite(lon) && !(lat === 0 && lon === 0);
}

/*
 * Site of the saved .horizon.json record, as the JSON MMhorizon's files()
 * takes: the photo's GPS position, else the ALP's Latitude and Longitude.
 * null when neither is known, rather than 0 N 0 E: MMhorizon then leaves the
 * place blank.
 */
export function siteOfRecord(exif, siteLat, siteLon) {
  if (exif.latitude != null && exif.longitude != null) {
    return JSON.stringify({ latitude: exif.latitude, longitude: exif.longitude });
  }
  if (knownPlace(siteLat, siteLon)) {
    return JSON.stringify({ latitude: siteLat, longitude: siteLon });
  }
  return null;
}

// More than the turns a photo can hold: MMhorizon keeps a turn between half
// and all of the photo width.
const MAX_TURNS = 8;

/*
 * Columns where a mark at `column`, in the first turn, shows on a panorama
 * `width` px wide: once on every turn the photo covers. A turn that is not a
 * positive number gives the mark once, and the count is bounded whatever the
 * turn, so a degenerate one cannot hang the page.
 */
export function columnsEveryTurn(column, turn, width) {
  if (!(turn > 0)) {
    return column < width ? [column] : [];
  }
  const columns = [];
  for (let x = column; x < width && columns.length < MAX_TURNS; x += turn) {
    columns.push(x);
  }
  return columns;
}

/*
 * Position in the photo, in pixels, of a pointer event on a canvas that shows
 * the photo scaled to canvasWidth x canvasHeight and is drawn in rect.
 */
export function photoPoint(clientX, clientY, rect, canvasWidth, canvasHeight, photoWidth, photoHeight) {
  const x = ((clientX - rect.left) / rect.width) * canvasWidth;
  const y = ((clientY - rect.top) / rect.height) * canvasHeight;
  return {
    column: (x * photoWidth) / canvasWidth,
    row: (y * photoHeight) / canvasHeight,
  };
}

/*
 * Width of one full turn, in photo pixels, if columns a and b can show the
 * same point at the start and at the end of a panorama that runs past a full
 * turn: between half and all of the photo width, the bounds MMhorizon's
 * fixerTour accepts. null otherwise.
 */
export function turnBetween(a, b, photoWidth) {
  const turn = Math.abs(b - a);
  return turn >= photoWidth / 2 && turn <= photoWidth ? turn : null;
}

/* Azimuth, in degrees, that a panorama photoWidth wide covers with this turn. */
export function extent(photoWidth, turn) {
  return (photoWidth * 360) / turn;
}

/*
 * SVG points of a profile of 360 altitudes (null where the panorama gave
 * none), for a viewBox where x is the azimuth and y = 90 - altitude, clamped
 * to 0-90 degrees as on the Planning page's Horizon card.
 */
export function profilePoints(altitudes) {
  const points = ["0,90"];
  altitudes.forEach((altitude, azimuth) => {
    const value = Math.min(Math.max(altitude ?? 0, 0), 90);
    points.push(`${azimuth},${round(90 - value, 2)}`);
  });
  const first = Math.min(Math.max(altitudes[0] ?? 0, 0), 90);
  points.push(`360,${round(90 - first, 2)}`, "360,90");
  return points.join(" ");
}

const WORDS = {
  cylindrique: "cylindrical",
  equirectangulaire: "equirectangular",
  gpano: "GPano metadata",
  chevauchement: "overlap",
  designation: "same point marked at both ends",
  supposee: "assumed full turn",
  paysage: "landscape",
  portrait: "portrait",
  inconnue: "unknown",
  inconnu: "unknown",
  principal: "main lens",
  "ultra-grand-angle": "ultra-wide lens",
  teleobjectif: "telephoto lens",
};

function word(value) {
  return WORDS[value] ?? value;
}

/* One-line summary of an MMhorizon infos() object. */
export function summary(infos) {
  const [low, high] = infos.champ_vertical_deg;
  const parts = [
    `${infos.largeur} × ${infos.hauteur} px`,
    word(infos.projection),
    coverage(infos),
    `altitude ${signed(low)}° to ${signed(high)}°`,
    `${word(infos.orientation)}, ${word(infos.objectif)}`,
  ];
  if (infos.au_dela_du_champ > 0) {
    parts.push(`obstacles above the top of the photo over ${infos.au_dela_du_champ}°`);
  }
  if (infos.gpano_ecarte) {
    parts.push("GPano metadata ignored: inconsistent with the lens");
  }
  return parts.join(" · ");
}

function coverage(infos) {
  const method = word(infos.couverture_methode);
  // couverture_deg stops at 360: past a full turn, say how far it runs.
  const degrees = infos.tour_px ? extent(infos.largeur, infos.tour_px) : infos.couverture_deg;
  if (degrees >= 360.5) {
    return `${Math.round(degrees)}° of azimuth, one turn in ${Math.round(infos.tour_px)} px (${method})`;
  }
  return `${Math.round(infos.couverture_deg)}° of azimuth (${method})`;
}

function signed(value) {
  const text = round(value, 1).toFixed(1);
  return value >= 0 ? `+${text}` : text;
}

function round(value, decimals) {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}
