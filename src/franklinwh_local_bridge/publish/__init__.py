"""MQTT publishing + Home Assistant discovery."""


def handle_command(key: str, payload: str, *, settings, client, store=None,
                   host: str | None = None) -> str:
    """Route one HA control message to a hardware-verified write.

    Only the writes proven on hardware are reachable here. Reserve SoC and
    smart-circuit schedules are NOT exposed as controls: the gateway accepts and
    discards both, so an HA entity for them would appear to work and would not.
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

    return f"unknown control '{key}'"
