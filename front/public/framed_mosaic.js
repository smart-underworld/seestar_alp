// Live preview of a Framed Mosaic (scale + rotation) over an Aladin sky view.
// Base FOV matches the Seestar S50's telephoto camera (43.8 x 77.4 arcmin);
// this is a visual planning aid only — it does not compute device commands.
(function () {
  const BASE_FOV_X_DEG = 43.8 / 60.0;
  const BASE_FOV_Y_DEG = 77.4 / 60.0;

  let aladin = null;
  let overlay = null;
  let currentRaDeg = 10.68;
  let currentDecDeg = 41.27;

  function rectangleCorners(raDeg, decDeg, scale, angleDeg) {
    const halfW = (BASE_FOV_X_DEG * scale) / 2.0;
    const halfH = (BASE_FOV_Y_DEG * scale) / 2.0;
    const angleRad = (angleDeg * Math.PI) / 180.0;
    const cosA = Math.cos(angleRad);
    const sinA = Math.sin(angleRad);
    const cosDec = Math.cos((decDeg * Math.PI) / 180.0) || 1e-6;

    const localCorners = [
      [-halfW, -halfH],
      [halfW, -halfH],
      [halfW, halfH],
      [-halfW, halfH],
    ];

    return localCorners.map(([x, y]) => {
      const rotatedX = x * cosA - y * sinA;
      const rotatedY = x * sinA + y * cosA;
      return [raDeg + rotatedX / cosDec, decDeg + rotatedY];
    });
  }

  window.update_framed_mosaic = function update_framed_mosaic() {
    const scale = parseFloat(document.getElementById("framed_mosaic_scale").value);
    const angle = parseFloat(document.getElementById("framed_mosaic_angle").value);
    document.getElementById("framed_mosaic_scale_display").textContent = scale.toFixed(1);
    document.getElementById("framed_mosaic_angle_display").textContent = angle;

    // Keep the hidden form inputs (actually submitted to the schedule form)
    // in sync with the sliders unconditionally, even if the Aladin preview
    // itself failed to load or hasn't initialized yet.
    document.getElementById("fm_mosaicScale").value = scale.toFixed(1);
    document.getElementById("fm_mosaicAngle").value = angle;

    if (!aladin) return;

    overlay.removeAll();
    const corners = rectangleCorners(currentRaDeg, currentDecDeg, scale, angle);
    overlay.add(A.polygon(corners, { color: "#f59e0b", lineWidth: 2 }));
  };

  window.init_framed_mosaic_aladin = function init_framed_mosaic_aladin() {
    aladin = A.aladin("#framed-mosaic-aladin-div", {
      survey: "P/DSS2/color",
      fov: 2,
      target: document.getElementById("framed_mosaic_search_text").value,
    });
    overlay = A.graphicOverlay({ color: "#f59e0b", lineWidth: 2 });
    aladin.addOverlay(overlay);
    update_framed_mosaic();
  };

  document.addEventListener("DOMContentLoaded", function () {
    if (typeof A !== "undefined" && A.init) {
      A.init.then(init_framed_mosaic_aladin);
    }

    const searchBtn = document.getElementById("framed_mosaic_search_button");
    if (searchBtn) {
      searchBtn.addEventListener("click", function () {
        if (!aladin) return;
        // Aladin Lite v3's gotoObject takes an options object with
        // success/error callbacks, not a bare callback function -- passing
        // a bare function silently registers nothing, so the view pans but
        // our overlay never redraws at the new position.
        aladin.gotoObject(
          document.getElementById("framed_mosaic_search_text").value,
          {
            success: function () {
              const [ra, dec] = aladin.getRaDec();
              currentRaDeg = ra;
              currentDecDeg = dec;
              update_framed_mosaic();
            },
            error: function () {
              // Object not found -- leave the overlay at its last position.
            },
          }
        );
      });
    }

    const openBtn = document.getElementById("open_framed_mosaic_schedule_modal_btn");
    const modal = document.getElementById("framed_mosaic_schedule_modal");
    const closeBtn = document.getElementById("close_framed_mosaic_schedule_modal_btn");
    if (openBtn && modal) {
      openBtn.addEventListener("click", function () {
        document.getElementById("fm_targetName").value =
          document.getElementById("framed_mosaic_search_text").value;
        if (aladin) {
          const [ra, dec] = aladin.getRaDec();
          // Aladin Lite returns RA in degrees, but the schedule form (and the
          // device layer's Util.parse_coordinate for numeric RA) expects RA
          // in hours. Dec is already in degrees, which is what's expected.
          document.getElementById("fm_ra").value = (ra / 15).toFixed(6);
          // dec is already in degrees (no unit conversion needed), but fix
          // its precision too: raw JS floats very close to 0 stringify in
          // exponential notation (e.g. "1e-7"), which fails the server's
          // check_dec_value() regexes and would wrongly reject the target.
          document.getElementById("fm_dec").value = dec.toFixed(6);
        }
        modal.showModal();
      });
    }
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", function () {
        modal.close();
      });
    }
  });
})();
