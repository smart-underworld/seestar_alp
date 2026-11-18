"""Confirmation gate for physical or destructive telescope actions."""

PHYSICAL_ACTIONS: frozenset[str] = frozenset(
    {"scope_park", "scope_move_to_horizon", "reboot", "shutdown"}
)


def gate(action: str, confirm: bool) -> dict | None:
    """Return a refusal dict if a physical action lacks confirmation, else None."""
    if action in PHYSICAL_ACTIONS and not confirm:
        return require_confirm(action, confirm)
    return None


def require_confirm(
    action: str, confirm: bool, reason: str | None = None
) -> dict | None:
    """Require confirmation for ``action`` regardless of ``PHYSICAL_ACTIONS``.

    Used by tool-level gates for actions that always need confirmation
    (start_scheduler, start_mosaic, startup_sequence) without adding them to
    ``PHYSICAL_ACTIONS`` — those names must stay un-gated as schedule items.
    Returns a refusal dict when ``confirm`` is falsy, else ``None``.
    """
    if confirm:
        return None
    return {
        "ok": False,
        "error": reason or f"{action} requires confirm=true",
        "requires_confirmation": True,
    }
