"""Confirmation gate for physical or destructive telescope actions."""

PHYSICAL_ACTIONS: frozenset[str] = frozenset(
    {"scope_park", "scope_move_to_horizon", "reboot", "shutdown"}
)


def gate(action: str, confirm: bool) -> dict | None:
    """Return a refusal dict if a physical action lacks confirmation, else None."""
    if action in PHYSICAL_ACTIONS and not confirm:
        return {
            "ok": False,
            "error": f"{action} requires confirm=true",
            "requires_confirmation": True,
        }
    return None
