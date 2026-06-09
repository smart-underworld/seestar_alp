import { writable } from "svelte/store";

/** Set to a non-null string to block SPA navigation with a confirm() prompt. */
export const navGuardMessage = writable<string | null>(null);
