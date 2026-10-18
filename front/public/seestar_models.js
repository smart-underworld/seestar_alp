// Field of view (arcmin) per Seestar model/camera, shared by the planning
// cards. fov_x is the short sensor axis and fov_y the long one.
// S50 Pro telephoto: 3840x2160 px at 2.9 um on a 260 mm lens (ZWO lists the
// 2.8 deg diagonal); worked out per axis here.
// S30 Pro telephoto: same sensor on a 160 mm lens; ZWO lists 4.6 deg, which
// matches the 4.58 deg diagonal worked out here.
// S50 Pro / S30 Pro wide: ZWO lists 63 deg (portrait); the short axis is
// estimated from the 9:16 sensor aspect, so treat it as approximate.
// S30: ZWO publishes its spec table only as an image; the value matches
// AstroMosaic's. All four telephoto entries agree with AstroMosaic's Seestar
// table (https://ruuth.xyz/AstroMosaic.html), which has no wide entries.
// "base" names the telephoto entry for features that only use that camera.
window.SEESTAR_MODELS = {
  "S50": { fov_x: 43.8, fov_y: 77.4 },
  "S50 Pro": { fov_x: 82.8, fov_y: 147.2 },
  "S50 Pro Wide": { fov_x: 2126.0, fov_y: 3780.0, base: "S50 Pro" },
  "S30": { fov_x: 73.2, fov_y: 130.2 },
  "S30 Pro": { fov_x: 134.6, fov_y: 239.2 },
  "S30 Pro Wide": { fov_x: 2126.0, fov_y: 3780.0, base: "S30 Pro" },
};

// FOV of the currently selected model. With telephoto=true a wide angle
// selection resolves to its telephoto camera.
window.seestarFov = function seestarFov(telephoto) {
  const select = document.getElementById("seestar");
  let entry = window.SEESTAR_MODELS[select ? select.value : "S50"] || window.SEESTAR_MODELS["S50"];
  if (telephoto && entry.base) {
    entry = window.SEESTAR_MODELS[entry.base];
  }
  return entry;
};
