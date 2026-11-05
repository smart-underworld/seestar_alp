// Horizon page: a 360-degree panorama analysed in the browser by the MMhorizon
// core (horizon_worker.js), oriented on north or on the Sun, its turn set when
// it runs past 360 degrees, then saved as the local horizon profile (.hrz) of
// this ALP.

import {
  MARK_COLORS,
  extent,
  hasUtcOffset,
  photoPoint,
  photoTimeUtc,
  profilePoints,
  summary,
  turnBetween,
} from "./horizon_panorama_core.js";

const page = document.getElementById("hz-page");
const $ = (id) => document.getElementById(id);
const configLat = Number(page.dataset.lat);
const configLon = Number(page.dataset.lon);

const HINTS = {
  north: "Click the point of the panorama that faces true north.",
  sun:
    "Click the centre of the Sun: its position at the time of the photo sets both north and the horizon line. " +
    "If the Sun shows at both ends of the panorama, click it at both: the distance between the two is one full turn.",
  horizon: "Click a point at altitude 0°, the true horizon (for instance a distant sea or plain), to set the horizon line.",
  turn:
    "When the panorama runs past a full turn, its start shows again at its end. Click a point near the start, " +
    "then the same point near the end: the distance between them is one full turn (360°).",
};

// --- Worker ---------------------------------------------------------------

const worker = new Worker("/public/horizon_worker.js", { type: "module" });
const pending = new Map();
let lastId = 0;

worker.onmessage = ({ data }) => {
  const call = pending.get(data.id);
  pending.delete(data.id);
  if (data.error) {
    call.reject(new Error(data.error));
  } else {
    call.resolve(data.result);
  }
};
worker.onerror = (e) => setStatus(`The panorama analysis could not start: ${e.message || "worker error"}`, "danger");

function call(op, args, transfer = []) {
  return new Promise((resolve, reject) => {
    const id = ++lastId;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, op, args }, transfer);
  });
}

// --- Page state -----------------------------------------------------------

let photo = null; // {name, width, height, previewWidth, previewHeight}
let current = null; // worker state(): infos, horizon, north, turn, limit, cardinals
let files = null; // {hrz, horizonJson} once north is set
let base = null; // canvas holding the preview image
let firstPoint = null; // {column, row}: first click of the "One turn" mode
let lastSun = null; // {column, row}: the Sun click north and horizon come from
// Points clicked, kept on the panorama in the colour of their mode.
let sunMarks = []; // the Sun, once or at both ends
let turnMarks = []; // the same point at both ends, in "One turn" mode

function setStatus(text, kind = "secondary") {
  const status = $("hz-status");
  status.className = `mt-2 small text-${kind}`;
  status.textContent = text;
}

function mode() {
  return document.querySelector('input[name="hz-mode"]:checked').value;
}

function site() {
  const exif = current.infos.photo;
  // The photo's own location first; the ALP's when the photo has none.
  return JSON.stringify({
    latitude: exif.latitude ?? configLat,
    longitude: exif.longitude ?? configLon,
  });
}

// --- Drawing --------------------------------------------------------------

function draw() {
  const canvas = $("hz-canvas");
  const ctx = canvas.getContext("2d");
  const kx = photo.previewWidth / photo.width;
  const ky = photo.previewHeight / photo.height;
  // Keep lines visible whatever the zoom: about 2 screen pixels.
  const px = canvas.width / canvas.getBoundingClientRect().width || 1;
  ctx.drawImage(base, 0, 0);

  ctx.lineWidth = 2 * px;
  ctx.strokeStyle = "rgb(255, 40, 40)";
  ctx.beginPath();
  for (let i = 0; i < current.limit.length; i += 2) {
    const x = current.limit[i] * kx;
    const y = current.limit[i + 1] * ky;
    if (i === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();

  ctx.strokeStyle = MARK_COLORS.horizon;
  ctx.setLineDash([8 * px, 6 * px]);
  ctx.beginPath();
  ctx.moveTo(0, current.horizon * ky);
  ctx.lineTo(canvas.width, current.horizon * ky);
  ctx.stroke();
  ctx.setLineDash([]);

  if (current.cardinals) {
    ctx.font = `bold ${14 * px}px sans-serif`;
    ctx.textAlign = "center";
    ["N", "E", "S", "W"].forEach((name, i) => {
      // Repeat the mark on every turn the photo shows.
      for (let x = current.cardinals[i]; x < photo.width; x += current.turn) {
        ctx.strokeStyle = ctx.fillStyle = MARK_COLORS.north;
        ctx.globalAlpha = i === 0 ? 1 : 0.6;
        ctx.lineWidth = (i === 0 ? 2 : 1) * px;
        ctx.beginPath();
        ctx.moveTo(x * kx, 18 * px);
        ctx.lineTo(x * kx, canvas.height);
        ctx.stroke();
        ctx.fillText(name, x * kx, 15 * px);
      }
    });
    ctx.globalAlpha = 1;
  }

  // A clicked point: a line down the panorama, a ring where the click fell.
  const mark = (point, color) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2 * px;
    ctx.setLineDash([4 * px, 4 * px]);
    ctx.beginPath();
    ctx.moveTo(point.column * kx, 0);
    ctx.lineTo(point.column * kx, canvas.height);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(point.column * kx, point.row * ky, 8 * px, 0, 2 * Math.PI);
    ctx.stroke();
  };
  sunMarks.forEach((point) => mark(point, MARK_COLORS.sun));
  [...turnMarks, ...(firstPoint ? [firstPoint] : [])].forEach((point) => mark(point, MARK_COLORS.turn));
}

function drawProfile() {
  // An SVG element has no `hidden` property: set the attribute itself.
  const svg = $("hz-profile");
  svg.toggleAttribute("hidden", !files);
  if (files) {
    const altitudes = JSON.parse(files.horizonJson).hauteur_min_deg;
    $("hz-profile-shape").setAttribute("points", profilePoints(altitudes));
  }
}

// --- State updates --------------------------------------------------------

async function apply(state) {
  current = state;
  $("hz-summary").textContent = summary(current.infos);
  files = current.north === null ? null : await call("files", { site: site() });
  $("hz-north").textContent =
    current.north === null
      ? "North is not set yet: azimuths are relative to the left edge of the photo."
      : `North at column ${Math.round(current.north)} · horizon line at row ${Math.round(current.horizon)} · ` +
        `one turn in ${Math.round(current.turn)} px.`;
  for (const id of ["hz-save", "hz-download-hrz", "hz-download-json"]) {
    $(id).disabled = files === null;
  }
  draw();
  drawProfile();
}

async function openPhoto(file) {
  setStatus(`Analysing ${file.name}… a few seconds, longer on a phone.`);
  $("hz-work").hidden = true;
  $("hz-result").textContent = "";
  try {
    const bytes = await file.arrayBuffer();
    const state = await call("open", { bytes, name: file.name }, [bytes]);
    photo = {
      name: file.name,
      width: state.width,
      height: state.height,
      previewWidth: state.previewWidth,
      previewHeight: state.previewHeight,
    };
    firstPoint = null;
    lastSun = null;
    sunMarks = [];
    turnMarks = [];
    base = document.createElement("canvas");
    base.width = photo.previewWidth;
    base.height = photo.previewHeight;
    const pixels = new Uint8ClampedArray(state.preview.buffer);
    base.getContext("2d").putImageData(new ImageData(pixels, photo.previewWidth, photo.previewHeight), 0, 0);
    const canvas = $("hz-canvas");
    canvas.width = photo.previewWidth;
    canvas.height = photo.previewHeight;
    $("hz-work").hidden = false;
    const exif = state.infos.photo;
    $("hz-mode-sun").disabled = !exif.date;
    if (!exif.date && mode() === "sun") {
      $("hz-mode-north").checked = true;
    }
    updateHint();
    await apply(state);
    setStatus(`${file.name} analysed.`, "success");
  } catch (e) {
    setStatus(`This photo could not be analysed: ${e.message}`, "danger");
  }
}

async function onClick(event) {
  if (!photo) {
    return;
  }
  const canvas = $("hz-canvas");
  const { column, row } = photoPoint(
    event.clientX,
    event.clientY,
    canvas.getBoundingClientRect(),
    canvas.width,
    canvas.height,
    photo.width,
    photo.height,
  );
  try {
    if (mode() === "north") {
      lastSun = null;
      await apply(await call("setNorth", { column }));
    } else if (mode() === "horizon") {
      lastSun = null;
      await apply(await call("setHorizon", { row }));
    } else if (mode() === "turn") {
      await markTurn(column, row);
    } else {
      await clickSun(column, row);
    }
  } catch (e) {
    setStatus(e.message, "danger");
  }
}

async function markTurn(column, row) {
  if (!firstPoint) {
    firstPoint = { column, row };
    draw();
    setStatus(`First point at column ${Math.round(column)}: now click the same point at the other end of the panorama.`);
    return;
  }
  const first = firstPoint;
  const a = first.column;
  firstPoint = null;
  const turn = turnBetween(a, column, photo.width);
  if (turn === null) {
    draw();
    throw new Error(
      `The two points are ${Math.round(Math.abs(column - a))} px apart: one turn spans between half and all of ` +
        `the photo width (${Math.round(photo.width / 2)} to ${photo.width} px). Click the first point again.`,
    );
  }
  turnMarks = [first, { column, row }];
  await apply(await call("setTurn", { a, b: column }));
  const turnText = `One turn in ${Math.round(turn)} px: the photo covers ${Math.round(extent(photo.width, turn))}°.`;
  if (lastSun) {
    // North and the horizon line came from the Sun under the former turn.
    await orientOnSun(lastSun.column, lastSun.row, `${turnText} North and horizon line set again from the Sun. `);
  } else {
    setStatus(turnText, "success");
  }
}

async function clickSun(column, row) {
  // The Sun clicked again, at the other end of a panorama that runs past a
  // full turn: the two clicks also set the turn.
  const turn = lastSun && turnBetween(lastSun.column, column, photo.width);
  if (!turn) {
    lastSun = { column, row };
    sunMarks = [{ column, row }];
    await orientOnSun(column, row);
    return;
  }
  sunMarks = [sunMarks[0] ?? lastSun, { column, row }];
  turnMarks = [];
  await apply(await call("setTurn", { a: lastSun.column, b: column }));
  lastSun = { column: lastSun.column, row: (lastSun.row + row) / 2 };
  await orientOnSun(
    lastSun.column,
    lastSun.row,
    `Sun marked at both ends: one turn in ${Math.round(turn)} px, the photo covers ` +
      `${Math.round(extent(photo.width, turn))}°. `,
  );
}

async function orientOnSun(column, row, prefix = "") {
  const exif = current.infos.photo;
  const when = photoTimeUtc(exif.date);
  const lat = exif.latitude ?? configLat;
  const lon = exif.longitude ?? configLon;
  const response = await fetch(`/horizon/sun?when=${encodeURIComponent(when)}&lat=${lat}&lon=${lon}`);
  if (!response.ok) {
    throw new Error(`Sun position: ${response.status} ${await response.text()}`);
  }
  const sun = await response.json();
  await apply(await call("orientOnSun", { column, row, ...sun }));
  const where = exif.latitude != null ? "the photo's location" : "the ALP's location";
  const zone = hasUtcOffset(exif.date) ? "" : ", photo time taken as this browser's local time";
  setStatus(
    `${prefix}Sun at azimuth ${sun.azimuth.toFixed(1)}°, altitude ${sun.altitude.toFixed(1)}° on ${exif.date} ` +
      `(${where}${zone}).`,
    "success",
  );
}

let pointerFrame = 0;
function onMove(event) {
  if (!photo || pointerFrame) {
    return;
  }
  pointerFrame = requestAnimationFrame(async () => {
    pointerFrame = 0;
    const canvas = $("hz-canvas");
    const point = photoPoint(
      event.clientX,
      event.clientY,
      canvas.getBoundingClientRect(),
      canvas.width,
      canvas.height,
      photo.width,
      photo.height,
    );
    const { azimuth, altitude } = await call("direction", point);
    const relative = current.north === null ? " (relative)" : "";
    $("hz-pointer").textContent = `Azimuth ${azimuth.toFixed(1)}°${relative} · altitude ${altitude.toFixed(1)}°`;
  });
}

function updateHint() {
  $("hz-hint").textContent = HINTS[mode()];
  if (firstPoint) {
    firstPoint = null;
    draw();
  }
}

function setZoom() {
  $("hz-canvas").style.width = `${Number($("hz-zoom").value) * 100}%`;
  if (photo) {
    draw();
  }
}

function download(text, name, type) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([text], { type }));
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function stem() {
  return photo.name.replace(/\.[^.]*$/, "");
}

async function save() {
  $("hz-save").disabled = true;
  try {
    const response = await fetch("/horizon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hrz: files.hrz, horizon_json: files.horizonJson }),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.description || body.title || response.status);
    }
    const previous = body.previous_file && body.previous_file !== body.file ? ` It replaces ${body.previous_file}, left in place.` : "";
    $("hz-result").className = "alert alert-success mt-3";
    $("hz-result").textContent =
      `Saved to ${body.file} (${body.points} points): the planner and the scheduler use it from now on.${previous}`;
    const shown = $("hz-current");
    if (shown) {
      shown.textContent = `${body.file} · ${body.points} points`;
    }
  } catch (e) {
    $("hz-result").className = "alert alert-danger mt-3";
    $("hz-result").textContent = `Not saved: ${e.message}`;
  } finally {
    $("hz-save").disabled = false;
  }
}

// Each mode button in the colour of the marks it leaves.
for (const [name, color] of Object.entries(MARK_COLORS)) {
  const label = document.querySelector(`label[for="hz-mode-${name}"]`);
  for (const property of ["color", "border-color", "hover-bg", "hover-border-color", "active-bg", "active-border-color"]) {
    label.style.setProperty(`--bs-btn-${property}`, color);
  }
  label.style.setProperty("--bs-btn-hover-color", "#000");
  label.style.setProperty("--bs-btn-active-color", "#000");
}
for (const swatch of document.querySelectorAll("[data-mark]")) {
  swatch.style.color = MARK_COLORS[swatch.dataset.mark];
}

$("hz-photo").addEventListener("change", (e) => e.target.files[0] && openPhoto(e.target.files[0]));
$("hz-canvas").addEventListener("click", onClick);
$("hz-canvas").addEventListener("mousemove", onMove);
for (const input of document.querySelectorAll('input[name="hz-mode"]')) {
  input.addEventListener("change", updateHint);
}
$("hz-zoom").addEventListener("change", setZoom);
$("hz-save").addEventListener("click", save);
$("hz-download-hrz").addEventListener("click", () => download(files.hrz, `${stem()}.hrz`, "text/plain"));
$("hz-download-json").addEventListener("click", () =>
  download(files.horizonJson, `${stem()}.horizon.json`, "application/json"),
);
updateHint();
