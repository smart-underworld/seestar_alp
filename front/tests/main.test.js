import fs from "node:fs";
import path from "node:path";
import { vi } from "vitest";

function loadScript(relPath) {
  const scriptPath = path.resolve(process.cwd(), relPath);
  const source = fs.readFileSync(scriptPath, "utf8");
  window.eval(source);
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("main.js", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <select id="searchFor"><option value="DS">DS</option></select>
      <input id="targetName" />
      <input id="ra" />
      <input id="dec" />
      <input id="useJ2000" type="checkbox" />
      <input id="useLpFilter" type="checkbox" />
    `;
    globalThis.alert = vi.fn();
    globalThis.fetch = vi.fn();
    globalThis.bootstrap = { Modal: class {} };
    loadScript("public/main.js");
  });

  it("fetchCoordinates in DS mode fills RA/DEC and flags", async () => {
    document.getElementById("searchFor").value = "DS";
    document.getElementById("targetName").value = "M42";
    globalThis.fetch.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("01h00m00s +02d00m00s on"),
    });

    await window.fetchCoordinates();
    await flush();

    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(document.getElementById("ra").value).toBe("01h00m00s");
    expect(document.getElementById("dec").value).toBe("+02d00m00s");
    expect(document.getElementById("useJ2000").checked).toBe(true);
    expect(document.getElementById("useLpFilter").checked).toBe(true);
  });

  it("fetchCoordinates in DS mode alerts when target is missing", async () => {
    document.getElementById("searchFor").value = "DS";
    document.getElementById("targetName").value = "";

    await window.fetchCoordinates();
    await flush();

    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(globalThis.alert).toHaveBeenCalledTimes(1);
  });

  it("fetchClipboard parses six-part coordinates into RA/DEC", async () => {
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue("12 34 56 +12 34 56"),
      },
      configurable: true,
    });

    await window.fetchClipboard();
    await flush();

    expect(document.getElementById("ra").value).toBe("12h34m56s");
    expect(document.getElementById("dec").value).toBe("12d34m56s");
  });

  it("fetchClipboard parses two-part format into RA/DEC", async () => {
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue("DE:01h02m03s +10°20'30\""),
      },
      configurable: true,
    });

    await window.fetchClipboard();
    await flush();

    expect(document.getElementById("ra").value).toBe("DE:01h02m03s");
    expect(document.getElementById("dec").value).toBe("+10d20m30s");
  });

  it("fetchClipboard alerts on unsupported clipboard format", async () => {
    Object.defineProperty(globalThis.navigator, "clipboard", {
      value: {
        readText: vi.fn().mockResolvedValue("bad format value"),
      },
      configurable: true,
    });

    await window.fetchClipboard();
    await flush();

    expect(globalThis.alert).toHaveBeenCalledTimes(1);
  });

  it("fetchStellarium fills target coordinates", async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            name: "M31",
            ra: "00h42m44s",
            dec: "+41d16m09s",
            lp: false,
          }),
        ),
    });

    await window.fetchStellarium();
    await flush();

    expect(document.getElementById("targetName").value).toBe("M31");
    expect(document.getElementById("ra").value).toBe("00h42m44s");
    expect(document.getElementById("dec").value).toBe("+41d16m09s");
    expect(document.getElementById("useJ2000").checked).toBe(true);
    expect(document.getElementById("useLpFilter").checked).toBe(false);
  });

  it("toggleuitheme flips HTML theme and calls backend endpoint", async () => {
    document.documentElement.setAttribute("data-bs-theme", "dark");
    globalThis.fetch.mockResolvedValue({ ok: true });

    await window.toggleuitheme();
    await flush();

    expect(document.documentElement.getAttribute("data-bs-theme")).toBe("light");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch.mock.calls[0][0]).toContain("/toggleuitheme");
  });
});
