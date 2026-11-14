// DSS2 colour sky background for the Aladin Lite views.
//
// The survey is normally requested by its CDS id ("P/DSS2/color"), which
// Aladin Lite serves from CDS Strasbourg (alasky.cds.unistra.fr). When that
// host is unreachable the sky map is blank. ESA hosts a copy of the same HiPS
// (same order, tile size, tile format and frame), so fall back to it.
//
// CDS stays the first choice whenever it answers. The choice is made once at
// page load. A view created before the probe finishes starts on the CDS id and
// is switched over through onChange().
(function () {
  const CDS_ID = "P/DSS2/color";
  const CDS_PROPERTIES = "https://alasky.cds.unistra.fr/DSS/DSSColor/properties";
  // No trailing slash: Aladin Lite appends "/" itself and would otherwise
  // request ".../DSSColor//Norder3/...".
  const ESA_URL = "https://skies.esac.esa.int/DSSColor";
  const ESA_PROPERTIES = ESA_URL + "/properties";
  const PROBE_TIMEOUT_MS = 3000;

  let current = CDS_ID;
  const listeners = [];

  // True when `url` answers with a 2xx status this page is allowed to read
  // (CORS), which is also what Aladin Lite needs in order to load a survey.
  function reachable(url) {
    if (typeof window.fetch !== "function") return Promise.resolve(false);
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    const timer = controller ? setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS) : null;
    return window
      .fetch(url, {
        mode: "cors",
        cache: "no-store",
        signal: controller ? controller.signal : undefined,
      })
      .then((response) => response.ok)
      .catch(() => false)
      .then((ok) => {
        if (timer) clearTimeout(timer);
        return ok;
      });
  }

  function choose() {
    return Promise.all([reachable(CDS_PROPERTIES), reachable(ESA_PROPERTIES)]).then(
      ([cds, esa]) => (!cds && esa ? ESA_URL : CDS_ID),
    );
  }

  function refresh() {
    return choose().then((survey) => {
      if (survey !== current) {
        current = survey;
        listeners.forEach((listener) => {
          try {
            listener(survey);
          } catch (error) {
            console.warn("DSS survey listener failed", error);
          }
        });
      }
      return current;
    });
  }

  window.SSCDssSurvey = {
    current: () => current,
    onChange: (listener) => {
      listeners.push(listener);
    },
    refresh,
  };

  refresh();
})();
