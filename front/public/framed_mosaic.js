// Live preview of a Framed Mosaic (scale + rotation) over an Aladin sky view.
// Base FOV matches the Seestar S50's telephoto camera (43.8 x 77.4 arcmin);
// this is a visual planning aid only — it does not compute device commands.
(function () {
  const BASE_FOV_X_DEG = 43.8 / 60.0;
  const BASE_FOV_Y_DEG = 77.4 / 60.0;

  let aladin = null;
  let overlay = null;
  let aladinDiv = null;
  let currentRaDeg = 10.68;
  let currentDecDeg = 41.27;
  let isDragging = false;

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

  // Inverse of rectangleCorners' rotation: is (raDeg, decDeg) inside the
  // current frame's (possibly rotated) rectangle?
  function isInsideFrame(raDeg, decDeg) {
    const scale = parseFloat(document.getElementById("framed_mosaic_scale").value);
    const angle = parseFloat(document.getElementById("framed_mosaic_angle").value);
    const cosDec = Math.cos((currentDecDeg * Math.PI) / 180.0) || 1e-6;
    const dRa = (raDeg - currentRaDeg) * cosDec;
    const dDec = decDeg - currentDecDeg;
    const angleRad = (angle * Math.PI) / 180.0;
    const cosA = Math.cos(angleRad);
    const sinA = Math.sin(angleRad);
    const localX = dRa * cosA + dDec * sinA;
    const localY = -dRa * sinA + dDec * cosA;
    const halfW = (BASE_FOV_X_DEG * scale) / 2.0;
    const halfH = (BASE_FOV_Y_DEG * scale) / 2.0;
    return Math.abs(localX) <= halfW && Math.abs(localY) <= halfH;
  }

  // Mouse event -> [ra, dec] in degrees at that screen position, using the
  // aladin container's own bounding box rather than event.offsetX/offsetY
  // (which is relative to whatever inner canvas layer received the event).
  function eventToRaDec(evt) {
    const rect = aladinDiv.getBoundingClientRect();
    return aladin.pix2world(evt.clientX - rect.left, evt.clientY - rect.top);
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
    aladinDiv = document.getElementById("framed-mosaic-aladin-div");
    overlay = A.graphicOverlay({ color: "#f59e0b", lineWidth: 2 });
    aladin.addOverlay(overlay);
    update_framed_mosaic();
    setUpFrameDrag();
  };

  // Click-and-drag the rectangle itself to move its center, independent of
  // panning the sky view. Registered in the capture phase so we can
  // stopPropagation before Aladin's own view-pan handler (bound directly on
  // its canvas, in the bubble phase) ever sees the mousedown -- otherwise
  // both a frame-drag and a view-pan would start from the same click.
  function setUpFrameDrag() {
    aladinDiv.addEventListener(
      "mousedown",
      function (evt) {
        const [ra, dec] = eventToRaDec(evt);
        if (!isInsideFrame(ra, dec)) return;
        isDragging = true;
        evt.stopPropagation();
        evt.preventDefault();
        currentRaDeg = ra;
        currentDecDeg = dec;
        update_framed_mosaic();
      },
      true
    );

    aladinDiv.addEventListener("mousemove", function (evt) {
      if (isDragging) return;
      const [ra, dec] = eventToRaDec(evt);
      aladinDiv.style.cursor = isInsideFrame(ra, dec) ? "move" : "";
    });

    document.addEventListener("mousemove", function (evt) {
      if (!isDragging) return;
      const [ra, dec] = eventToRaDec(evt);
      currentRaDeg = ra;
      currentDecDeg = dec;
      update_framed_mosaic();
    });

    document.addEventListener("mouseup", function () {
      isDragging = false;
    });
  }

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
          // Submit the frame's own center (currentRaDeg/currentDecDeg), not
          // the view's center (aladin.getRaDec()) -- once the frame can be
          // dragged independently of the view, those two can differ, and
          // it's the frame's position the user actually wants scheduled.
          // Aladin Lite returns RA in degrees, but the schedule form (and the
          // device layer's Util.parse_coordinate for numeric RA) expects RA
          // in hours. Dec is already in degrees, which is what's expected.
          document.getElementById("fm_ra").value = (currentRaDeg / 15).toFixed(6);
          // dec is already in degrees (no unit conversion needed), but fix
          // its precision too: raw JS floats very close to 0 stringify in
          // exponential notation (e.g. "1e-7"), which fails the server's
          // check_dec_value() regexes and would wrongly reject the target.
          document.getElementById("fm_dec").value = currentDecDeg.toFixed(6);
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
