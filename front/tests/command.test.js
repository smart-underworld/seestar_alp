import fs from "node:fs";
import path from "node:path";
import { vi } from "vitest";

function loadScript(relPath) {
  const scriptPath = path.resolve(process.cwd(), relPath);
  const source = fs.readFileSync(scriptPath, "utf8");
  window.eval(source);
}

describe("command.js", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="eventStatusDiv"></div>
      <div id="eventStatusContent"></div>
    `;
    globalThis.htmx = { trigger: vi.fn() };
    loadScript("public/command.js");
    document.dispatchEvent(new Event("DOMContentLoaded"));
  });

  it("adds hx-disable when accordion collapses", () => {
    const eventStatusDiv = document.getElementById("eventStatusDiv");
    const content = document.getElementById("eventStatusContent");

    eventStatusDiv.dispatchEvent(new Event("hide.bs.collapse"));
    expect(content.hasAttribute("hx-disable")).toBe(true);
  });

  it("removes hx-disable and triggers reload when accordion expands", () => {
    const eventStatusDiv = document.getElementById("eventStatusDiv");
    const content = document.getElementById("eventStatusContent");
    content.setAttribute("hx-disable", "");

    eventStatusDiv.dispatchEvent(new Event("show.bs.collapse"));
    expect(content.hasAttribute("hx-disable")).toBe(false);
    expect(globalThis.htmx.trigger).toHaveBeenCalledWith(
      content,
      "htmx:load",
    );
  });
});
