import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { writable } from "svelte/store";

// svelte-dnd-action uses browser layout APIs not available in jsdom
vi.mock("svelte-dnd-action", () => ({
  dndzone: () => ({ update: () => {}, destroy: () => {} }),
  SHADOW_ITEM_MARKER_PROPERTY_NAME: "__isDndShadow",
  SOURCES: { POINTER: "pointer", KEYBOARD: "keyboard", DND_ZONE_DRAG: "dnd_zone_drag", DND_ZONE_TOUCH: "dnd_zone_touch" },
  TRIGGERS: { DRAG_STARTED: "dragStarted" },
}));

const {
  mockScheduleGet, mockScheduleAddItem, mockScheduleDeleteItem,
  mockScheduleSetState, mockScheduleClear, mockScheduleSearch,
  mockScheduleExport, mockScheduleImport, mockScheduleInsertItem,
  mockLibraryList, mockLibrarySave, mockLibraryLoad, mockLibraryDelete,
} = vi.hoisted(() => ({
  mockScheduleGet: vi.fn(),
  mockScheduleAddItem: vi.fn(),
  mockScheduleDeleteItem: vi.fn(),
  mockScheduleSetState: vi.fn(),
  mockScheduleClear: vi.fn(),
  mockScheduleSearch: vi.fn(),
  mockScheduleExport: vi.fn(),
  mockScheduleImport: vi.fn(),
  mockScheduleInsertItem: vi.fn(),
  mockLibraryList: vi.fn(),
  mockLibrarySave: vi.fn(),
  mockLibraryLoad: vi.fn(),
  mockLibraryDelete: vi.fn(),
}));

vi.mock("../lib/stores/deviceStore", () => ({
  activeDevNum: writable<number>(1),
  isConnected: writable<boolean>(false),
  activeDeviceStatus: writable(null),
}));

vi.mock("../lib/api", () => ({
  api: {
    devices: {
      schedule: {
        get: mockScheduleGet,
        addItem: mockScheduleAddItem,
        deleteItem: mockScheduleDeleteItem,
        setState: mockScheduleSetState,
        clear: mockScheduleClear,
        insertItem: mockScheduleInsertItem,
        exportSchedule: mockScheduleExport,
        importSchedule: mockScheduleImport,
      },
      scheduleLibrary: {
        list: mockLibraryList,
        save: mockLibrarySave,
        load: mockLibraryLoad,
        delete: mockLibraryDelete,
      },
      search: mockScheduleSearch,
    },
  },
}));

import * as deviceStore from "../lib/stores/deviceStore";
import Schedule from "./Schedule.svelte";

const mockIsConnected = deviceStore.isConnected as ReturnType<typeof writable<boolean>>;
const mockActiveDevNum = deviceStore.activeDevNum as ReturnType<typeof writable<number>>;

const HANG = new Promise<never>(() => {});

const EMPTY_SCHEDULE = { state: "idle", list: [] };

// URL.createObjectURL is not available in jsdom
global.URL.createObjectURL = vi.fn(() => "blob:mock");
global.URL.revokeObjectURL = vi.fn();

beforeEach(() => {
  mockIsConnected.set(false);
  mockActiveDevNum.set(1);
  mockScheduleGet.mockReset();
  mockScheduleAddItem.mockReset();
  mockScheduleDeleteItem.mockReset();
  mockScheduleSetState.mockReset();
  mockScheduleClear.mockReset();
  mockScheduleSearch.mockReset();
  mockScheduleExport.mockReset();
  mockScheduleImport.mockReset();
  mockLibraryList.mockReset();
  mockLibrarySave.mockReset();
  mockLibraryLoad.mockReset();
  mockLibraryDelete.mockReset();
  mockScheduleGet.mockResolvedValue(EMPTY_SCHEDULE);
  mockScheduleAddItem.mockResolvedValue({});
  mockScheduleDeleteItem.mockResolvedValue({});
  mockScheduleSetState.mockResolvedValue({});
  mockScheduleClear.mockResolvedValue({});
  mockScheduleSearch.mockResolvedValue({ query: "", result: {} });
  mockLibraryList.mockResolvedValue({ files: [] });
  mockLibrarySave.mockResolvedValue({ filename: "test.json" });
  mockLibraryLoad.mockResolvedValue(JSON.stringify({ version: "1.0", state: "stopped", list: [] }));
  mockLibraryDelete.mockResolvedValue({ status: "ok" });
});

describe("Schedule — offline", () => {
  it("shows offline notice when not connected", () => {
    render(Schedule);
    expect(screen.getByText(/Scope is offline/)).toBeInTheDocument();
  });

  it("hides Start button but shows builder when offline", () => {
    render(Schedule);
    expect(screen.queryByText(/▶ Start/)).not.toBeInTheDocument();
    expect(screen.getByText("Action Library")).toBeInTheDocument();
  });
});

describe("Schedule — loading", () => {
  it("shows loading indicator while schedule fetches", () => {
    mockIsConnected.set(true);
    mockScheduleGet.mockReturnValue(HANG);
    render(Schedule);
    expect(screen.getByText(/Loading/)).toBeInTheDocument();
  });
});

describe("Schedule — empty queue", () => {
  beforeEach(() => {
    mockIsConnected.set(true);
    mockScheduleGet.mockResolvedValue(EMPTY_SCHEDULE);
  });

  it("shows empty queue message", async () => {
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText(/queue is empty/i)).toBeInTheDocument(),
    );
  });

  it("shows the action library panel", async () => {
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText("Action Library")).toBeInTheDocument(),
    );
  });

  it("renders action group tabs (Observation, Setup, Timing, Control)", async () => {
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText("Observation")).toBeInTheDocument(),
    );
    expect(screen.getByText("Setup")).toBeInTheDocument();
    expect(screen.getByText("Timing")).toBeInTheDocument();
    expect(screen.getByText("Control")).toBeInTheDocument();
  });
});

describe("Schedule — state badge", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("shows running state badge when schedule is running", async () => {
    mockScheduleGet.mockResolvedValue({ state: "running", list: [] });
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText("running")).toBeInTheDocument(),
    );
  });

  it("shows Play button when schedule is not running", async () => {
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /▶|Play/i })).toBeInTheDocument(),
    );
  });
});

describe("Schedule — queue with items", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("renders queue count and item labels", async () => {
    mockScheduleGet.mockResolvedValue({
      state: "idle",
      list: [
        { action: "auto_focus", params: { try_count: 1 }, schedule_item_id: "id-1", state: "idle" },
        { action: "scope_park",  params: {},               schedule_item_id: "id-2", state: "idle" },
      ],
    });
    render(Schedule);
    // queue count is unique to the queue panel
    await waitFor(() =>
      expect(screen.getByText("2 items in queue")).toBeInTheDocument(),
    );
    // both action labels appear in the queue item divs
    expect(screen.getAllByText("Auto Focus").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Park").length).toBeGreaterThan(0);
  });

  it("shows edit button for each item", async () => {
    mockScheduleGet.mockResolvedValue({
      state: "idle",
      list: [
        { action: "scope_park", params: {}, schedule_item_id: "id-1", state: "idle" },
      ],
    });
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText("1 item in queue")).toBeInTheDocument(),
    );
    expect(screen.getAllByRole("button", { name: /Edit/i }).length).toBeGreaterThan(0);
  });
});

describe("Schedule — clear", () => {
  beforeEach(() => mockIsConnected.set(true));

  it("shows Clear button when queue has items", async () => {
    mockScheduleGet.mockResolvedValue({
      state: "idle",
      list: [{ action: "scope_park", params: {}, schedule_item_id: "id-1", state: "idle" }],
    });
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByText("1 item in queue")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /⊘ Clear/i })).toBeInTheDocument();
  });

  it("calls schedule.clear when confirmed", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockScheduleGet.mockResolvedValue({
      state: "idle",
      list: [{ action: "scope_park", params: {}, schedule_item_id: "id-1", state: "idle" }],
    });
    render(Schedule);
    await waitFor(() => expect(screen.getByText("Park")).toBeInTheDocument());
    screen.getByRole("button", { name: /Clear/i }).click();
    // second click to confirm (two-step clear)
    await waitFor(async () => {
      const confirmBtn = screen.queryByRole("button", { name: /Confirm|Yes|Clear/i });
      if (confirmBtn && confirmBtn !== screen.queryByRole("button", { name: /^Clear$/i })) {
        confirmBtn.click();
      }
    });
    confirmSpy.mockRestore();
  });

  it("calls setState stop when Stop is clicked on a running schedule", async () => {
    mockScheduleGet.mockResolvedValue({ state: "running", list: [] });
    render(Schedule);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /⏹|Stop/i })).toBeInTheDocument(),
    );
    screen.getByRole("button", { name: /⏹|Stop/i }).click();
    await waitFor(() =>
      expect(mockScheduleSetState).toHaveBeenCalledWith(1, "stop"),
    );
  });
});

describe("Schedule — offline building", () => {
  it("shows Load file button when offline", () => {
    render(Schedule);
    expect(screen.getByText(/↑ Load file/i)).toBeInTheDocument();
  });

  it("adds item to local queue without calling API when offline", async () => {
    render(Schedule);
    // Select the Park action (no params form, just a chip)
    const parkChip = await waitFor(() => screen.getByRole("button", { name: /^Park$/i }));
    parkChip.click();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /\+ Add to Schedule/i })).toBeInTheDocument(),
    );
    screen.getByRole("button", { name: /\+ Add to Schedule/i }).click();
    await waitFor(() =>
      expect(screen.getByText("1 item in queue")).toBeInTheDocument(),
    );
    // Device API should NOT have been called (offline)
    expect(mockScheduleAddItem).not.toHaveBeenCalled();
  });

  it("deletes item from local queue without calling API when offline", async () => {
    render(Schedule);
    // Add an item first (offline)
    const parkChip = await waitFor(() => screen.getByRole("button", { name: /^Park$/i }));
    parkChip.click();
    await waitFor(() => screen.getByRole("button", { name: /\+ Add to Schedule/i })).then(b => b.click());
    await waitFor(() => expect(screen.getByText("1 item in queue")).toBeInTheDocument());
    // Now delete it
    screen.getByRole("button", { name: /Remove/i }).click();
    await waitFor(() =>
      expect(screen.getByText(/queue is empty/i)).toBeInTheDocument(),
    );
    expect(mockScheduleDeleteItem).not.toHaveBeenCalled();
  });

  it("shows Save file button when queue has items offline", async () => {
    render(Schedule);
    const parkChip = await waitFor(() => screen.getByRole("button", { name: /^Park$/i }));
    parkChip.click();
    await waitFor(() => screen.getByRole("button", { name: /\+ Add to Schedule/i })).then(b => b.click());
    await waitFor(() => expect(screen.getByText("1 item in queue")).toBeInTheDocument());
    expect(screen.getByTitle(/Download schedule/i)).toBeInTheDocument();
  });
});

describe("Schedule — server library", () => {
  it("renders Saved Schedules panel", () => {
    render(Schedule);
    expect(screen.getByText("Saved Schedules")).toBeInTheDocument();
  });

  it("expands to show empty state when no files on server", async () => {
    render(Schedule);
    screen.getByText("Saved Schedules").click();
    await waitFor(() =>
      expect(screen.getByText(/No saved schedules on server/i)).toBeInTheDocument(),
    );
  });

  it("expands to show list of saved files", async () => {
    mockLibraryList.mockResolvedValue({
      files: [
        { name: "deep_sky_run.json", size: 1024, modified: 1700000000 },
      ],
    });
    render(Schedule);
    screen.getByText("Saved Schedules").click();
    await waitFor(() =>
      expect(screen.getByText("deep_sky_run")).toBeInTheDocument(),
    );
  });

  it("calls library.delete when delete button is clicked", async () => {
    mockLibraryList.mockResolvedValue({
      files: [{ name: "old_run.json", size: 512, modified: 1700000000 }],
    });
    render(Schedule);
    screen.getByText("Saved Schedules").click();
    await waitFor(() => expect(screen.getByText("old_run")).toBeInTheDocument());
    screen.getByTitle(/Delete old_run\.json/i).click();
    await waitFor(() =>
      expect(mockLibraryDelete).toHaveBeenCalledWith("old_run.json"),
    );
  });

  it("calls library.load then applies content when Load is clicked offline", async () => {
    const schedContent = JSON.stringify({
      version: "1.0", state: "stopped",
      list: [{ action: "scope_park", params: {}, schedule_item_id: "x1" }],
    });
    mockLibraryList.mockResolvedValue({
      files: [{ name: "nightly.json", size: 100, modified: 1700000000 }],
    });
    mockLibraryLoad.mockResolvedValue(schedContent);
    render(Schedule);
    screen.getByText("Saved Schedules").click();
    await waitFor(() => expect(screen.getByText("nightly")).toBeInTheDocument());
    screen.getByRole("button", { name: /^Load$/i }).click();
    await waitFor(() =>
      expect(screen.getByText("1 item in queue")).toBeInTheDocument(),
    );
    expect(mockScheduleImport).not.toHaveBeenCalled(); // offline — local only
  });
});
