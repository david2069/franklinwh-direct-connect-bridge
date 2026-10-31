"""MQTT publishing + Home Assistant discovery."""


def handle_command(key: str, payload: str, *, settings, client, store=None,
                   host: str | None = None, gateway=None) -> str:
    """Route one HA control message to a write that takes effect.

    Smart-circuit schedules are NOT exposed: the gateway accepts and discards them. A
    reserve SoC goes through the cloud (C2), never the local API, which discards it; it
    is written to ``gateway``'s own serial, with the same checks as the REST route.
    """
    from .entities import MODE_ALIAS

    if key == "operating_mode":
        alias = MODE_ALIAS.get(payload)
        if not alias:
            return f"unknown mode '{payload}'"
        out = client.set_mode(settings, alias, host=host)
        return f"mode -> {payload}: {'ok' if out.get('ok', True) else out}"

    if key.startswith("smart_circuit_"):
        try:
            circuit = int(key.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            return f"bad control key '{key}'"
        on = payload.upper() == "ON"
        out = client.set_smart_circuit(settings, circuit, on, host=host)
        # result:0 only means the frame parsed; the read-back is what proves it.
        return (f"circuit {circuit} -> {'on' if on else 'off'}: "
                f"{'confirmed' if out.get('confirmed') else 'NOT confirmed'}")

    if key.startswith("reserve_soc_"):
        from .. import providers
        mode = key.removeprefix("reserve_soc_")
        if mode not in ("tou", "self"):
            # Emergency Backup's reserve is fixed at 100 %; nothing else is a mode.
            return f"unknown control '{key}'"
        if gateway is None:
            return "reserve: no gateway"
        refused = providers.cloud_target_refusal(
            settings, serial=gateway.serial,
            serial_locked=bool(getattr(gateway, "serial_locked", False)),
            is_mock=bool(getattr(gateway, "is_mock", False)))
        if refused:
            return f"reserve {mode}: {refused}"
        try:
            soc = int(round(float(payload)))
        except ValueError:
            return f"reserve {mode}: not a number: {payload!r}"
        try:
            out = providers.set_reserve(settings, mode, soc, serial=gateway.serial.upper())
        except Exception as e:  # noqa: BLE001 — the result IS the answer, logged by the caller
            return f"reserve {mode} -> {soc}%: failed: {type(e).__name__}: {e}"
        ok = out.get("ok", True) if isinstance(out, dict) else True
        return f"reserve {mode} -> {soc}%: {'applied via cloud' if ok else out}"

    return f"unknown control '{key}'"
