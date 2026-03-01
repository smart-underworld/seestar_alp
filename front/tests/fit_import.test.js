import fs from "node:fs";
import path from "node:path";

function loadScript(relPath) {
  const scriptPath = path.resolve(process.cwd(), relPath);
  const source = fs.readFileSync(scriptPath, "utf8");
  window.eval(source);
}

function fitsCard(keyword, value = "") {
  const left = `${keyword.padEnd(8, " ")}= ${value}`;
  return left.padEnd(80, " ");
}

describe("fit_import.js", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button id="getHeaders"></button>
      <input id="fileInput" />
      <input id="ra" />
      <input id="dec" />
      <input id="targetName" />
      <input id="useLpFilter" type="checkbox" />
    `;
  });

  it("parses FITS cards and fills form fields", () => {
    const cards = [
      fitsCard("RA", "'12h34m56.7s'"),
      fitsCard("DEC", "'+12d34m56s'"),
      fitsCard("OBJECT", "'M42'"),
      fitsCard("FILTER", "'LP'"),
      fitsCard("END"),
    ].join("");
    const bytes = new TextEncoder().encode(cards).buffer;

    globalThis.FileReader = class {
      readAsArrayBuffer() {
        this.onload({ target: { result: bytes } });
      }
    };

    loadScript("public/fit_import.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));

    const input = document.getElementById("fileInput");
    Object.defineProperty(input, "files", {
      value: [{}],
      configurable: true,
    });
    input.dispatchEvent(new Event("change"));

    expect(document.getElementById("ra").value).toBe("12h34m56.7s");
    expect(document.getElementById("dec").value).toBe("+12d34m56s");
    expect(document.getElementById("targetName").value).toBe("M42");
    expect(document.getElementById("useLpFilter").checked).toBe(true);
  });
});
