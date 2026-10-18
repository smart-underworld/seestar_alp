// Field of view (arcmin) per Seestar model/camera, shared by the planning
// cards. fov_x is the short sensor axis and fov_y the long one.
// S50 Pro telephoto: 3840x2160 px at 2.9 um on a 260 mm lens (ZWO lists the
// 2.8 deg diagonal); worked out per axis here.
// S50 Pro wide: ZWO lists 63 deg (portrait); the short axis is estimated from
// the 9:16 sensor aspect, so treat it as approximate.
// "base" names the telephoto entry for features that only use that camera.
window.SEESTAR_MODELS = {
  "S50": { fov_x: 43.8, fov_y: 77.4 },
  "S50 Pro": { fov_x: 82.8, fov_y: 147.3 },
  "S50 Pro Wide": { fov_x: 2126.0, fov_y: 3780.0, base: "S50 Pro" },
  "S30": { fov_x: 73.2, fov_y: 130.2 },
  "S30 Pro": { fov_x: 144.4, fov_y: 256.7 },
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
