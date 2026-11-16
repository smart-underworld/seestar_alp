// DSS2 colour sky background for the Aladin Lite views.
//
// The survey is published on several hosts. When the one in use is unreachable
// the sky map is blank (or sits on "loading..."), so the page probes the hosts
// and uses the first one in SURVEYS order that answers.
//
// STScI MAST (an S3 bucket) is first, then CDS Strasbourg and its backup
// server, then full-sky mirrors, and Caltech IRSA last because it only holds a
// partial cutout. STScI's HiPS is MAST's own DSS colour build, not a copy of
// CDS's: colours differ a little and 11 mostly galactic-plane blue plates are
// missing (https://dc.g-vo.org/rr/q/lp/custom/archive.stsci.edu/HiPS/DSSColor).
// The CDS-registered hosts are listed at
// https://dc.g-vo.org/rr/q/lp/custom/CDS/P/DSS2/color
//
// Only the first host is probed when it answers (3 requests). The rest are
// probed, all at once, only if it fails. A view created before the probe
// finishes starts on the first host and is switched over through onChange().
//
// Aladin Lite is given each host's URL, never the id "P/DSS2/color": an id is
// resolved through CDS's MocServer and then loaded from whatever mirror that
// names, which can be down while the probed host is up.
(function () {
  // The page loads this script from two planner cards. Keep the first copy so
  // the listeners registered on it are not lost.
  if (window.SSCDssSurvey) return;

  // No trailing slash: Aladin Lite appends "/" itself and would otherwise
  // request ".../DSSColor//Norder3/...".
  const SURVEYS = [
    { url: "https://stpubdata.s3.us-east-1.amazonaws.com/mast/skybackgrounds/DSSColor" },
    { url: "https://alasky.cds.unistra.fr/DSS/DSSColor" },
    { url: "https://alaskybis.cds.unistra.fr/DSS/DSSColor" },
    { url: "https://casda.csiro.au/hips/DSS2/color" },
    { url: "https://hips.china-vo.org/m/CDS_P_DSS2_color" },
    { url: "https://skies.esac.esa.int/DSSColor" },
    // About 0.5% of the sky (Orion, M31, M33, M45): last resort only.
    { url: "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color", partial: true },
  ];

  // Every host gets the same check: the properties file and two order-3 tiles
  // on opposite sides of the sky. A host can answer the small properties file
  // and still stall on tiles, so a tile must come back too. A partial host
  // cannot be expected to have the second tile.
  const PROBE_PATHS = ["/properties", "/Norder3/Dir0/Npix0.jpg", "/Norder3/Dir0/Npix350.jpg"];
  const PROBE_TIMEOUT_MS = 3000;
  const RECHECK_INTERVAL_MS = 5 * 60 * 1000;

  const FIRST = SURVEYS[0].url;
  let current = FIRST;
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

  // True when the host serves every probe path that applies to it.
  function serves(survey) {
    const paths = survey.partial ? PROBE_PATHS.slice(0, 2) : PROBE_PATHS;
    return Promise.all(paths.map((path) => reachable(survey.url + path))).then((all) =>
      all.every(Boolean),
    );
  }

  // The first host that serves; the first host in the list if none does
  // (nothing better is known, and it may come back).
  function choose() {
    // Without fetch nothing can be probed, so keep the default.
    if (typeof window.fetch !== "function") return Promise.resolve(FIRST);
    return serves(SURVEYS[0]).then((ok) => {
      if (ok) return FIRST;
      const rest = SURVEYS.slice(1);
      return Promise.all(rest.map(serves)).then((up) => {
        const index = up.indexOf(true);
        return index === -1 ? FIRST : rest[index].url;
      });
    });
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

  // Periodic check while the tab is open. The survey is left alone as long as
  // the host in use still serves, so the map does not change under someone who
  // is planning just because a better host came back. A failure has to repeat
  // before the page moves on, so one slow answer does not switch it.
  function recheck() {
    if (typeof window.fetch !== "function") return Promise.resolve(current);
    const survey = SURVEYS.find((s) => s.url === current);
    return serves(survey)
      .then((ok) => ok || serves(survey))
      .then((ok) => (ok ? current : refresh()));
  }

  window.SSCDssSurvey = {
    current: () => current,
    onChange: (listener) => {
      listeners.push(listener);
    },
    refresh,
  };

  if (typeof setInterval === "function") {
    setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState !== "hidden") recheck();
    }, RECHECK_INTERVAL_MS);
  }

  refresh();
})();
