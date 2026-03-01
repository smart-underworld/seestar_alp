import fs from "node:fs";
import path from "node:path";

function loadScript(relPath) {
  const scriptPath = path.resolve(process.cwd(), relPath);
  const source = fs.readFileSync(scriptPath, "utf8");
  window.eval(source);
}

describe("liveview.js", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("updateModeButtons toggles active button classes", () => {
    document.body.innerHTML = `
      <button id="star" class="mode-button btn-secondary"></button>
      <button id="moon" class="mode-button btn-secondary"></button>
    `;
    loadScript("public/liveview.js");

    window.updateModeButtons("moon");

    const star = document.getElementById("star");
    const moon = document.getElementById("moon");
    expect(moon.classList.contains("btn-primary")).toBe(true);
    expect(moon.classList.contains("btn-secondary")).toBe(false);
    expect(star.classList.contains("btn-primary")).toBe(false);
    expect(star.classList.contains("btn-secondary")).toBe(true);
  });

  it("updateMovementControls hides controls during stack stage", () => {
    document.body.innerHTML = `
      <div id="movement-controls"></div>
      <div id="focus-controls"></div>
      <div id="exposure-controls"></div>
    `;
    loadScript("public/liveview.js");

    window.updateMovementControls("Stack");
    expect(
      document
        .getElementById("movement-controls")
        .classList.contains("visually-hidden"),
    ).toBe(true);
    expect(
      document
        .getElementById("focus-controls")
        .classList.contains("visually-hidden"),
    ).toBe(true);
    expect(
      document
        .getElementById("exposure-controls")
        .classList.contains("visually-hidden"),
    ).toBe(true);
  });

  it("updateMovementControls shows controls outside stack stage", () => {
    document.body.innerHTML = `
      <div id="movement-controls" class="visually-hidden"></div>
      <div id="focus-controls" class="visually-hidden"></div>
      <div id="exposure-controls" class="visually-hidden"></div>
    `;
    loadScript("public/liveview.js");

    window.updateMovementControls("Preview");
    expect(
      document
        .getElementById("movement-controls")
        .classList.contains("visually-hidden"),
    ).toBe(false);
    expect(
      document
        .getElementById("focus-controls")
        .classList.contains("visually-hidden"),
    ).toBe(false);
    expect(
      document
        .getElementById("exposure-controls")
        .classList.contains("visually-hidden"),
    ).toBe(false);
  });
});
