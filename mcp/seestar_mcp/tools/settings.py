"""Settings tools: read via both firmware paths, write via any of the three save variants."""

from typing import Any

from seestar_mcp.tools._util import call

VARIANTS = ("auto", "set_setting", "set_stack_setting", "set_stack_settings")


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and result.get("ok") is False and "error" in result


async def read_settings_tool(telescope_id: int = 1) -> dict[str, Any]:
    """Read settings from both get_setting and get_stack_setting (older firmware may
    only support one; whichever succeeds is returned, failures listed under "errors")."""
    out: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    for key, factory in (
        ("setting", lambda c: c.get_setting()),
        ("stack_setting", lambda c: c.get_stack_setting()),
    ):
        result = await call(telescope_id, factory)
        if _is_error(result):
            errors[key] = result["error"]
        else:
            out[key] = result
    if errors:
        out["errors"] = errors
    return out


async def write_setting_tool(
    values: dict[str, Any], variant: str = "auto", telescope_id: int = 1
) -> Any:
    """Save stack settings. variant: auto | set_setting | set_stack_setting |
    set_stack_settings. auto uses set_stack_settings for several keys, else
    set_stack_setting. A variant the firmware rejects returns {"ok": false, ...}."""
    if variant not in VARIANTS:
        return {
            "ok": False,
            "error": f"unknown variant {variant!r}; use one of {VARIANTS}",
        }
    if not values:
        return {"ok": False, "error": "values must not be empty"}
    if variant == "auto":
        variant = "set_stack_settings" if len(values) > 1 else "set_stack_setting"
    return await call(telescope_id, lambda c: getattr(c, variant)(**values))


def register(mcp: Any) -> None:
    for fn in (read_settings_tool, write_setting_tool):
        mcp.tool(name=fn.__name__.removesuffix("_tool"))(fn)
