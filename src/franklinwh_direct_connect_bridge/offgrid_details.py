"""The off-grid Details (owner 2026-11-13): what the site is doing when it goes off-grid or
back on. One list of rows for the OFF-GRID dialog and one line for the control log, so
both say the same thing.

From the cached summary: mode, SoC, battery, grid, solar, home and the smart circuits'
on/off. A live read (the dialog's Details only, never before a write) adds circuit watts,
the generator and V2L. The generator and V2L appear only when installed."""
from __future__ import annotations

from typing import Any


def _kw(w) -> str:
    return f"{(w or 0) / 1000:.1f} kW"


def _num(v) -> bool:
    return isinstance(v, (int, float))


def rows(summ: dict, *, circuits: dict | None = None, generator: dict | None = None,
         v2l_installed: bool = False) -> list[dict[str, Any]]:
    p = (summ or {}).get("power") or {}
    out: list[dict[str, Any]] = []

    def add(key, label, value):
        if value is not None:
            out.append({"key": key, "label": label, "value": value})

    add("mode", "Mode", p.get("mode") or None)
    add("soc", "SoC", f"{round(p['soc'])}%" if _num(p.get("soc")) else None)
    b = p.get("battery_w")    # positive = discharging
    add("battery", "Battery", None if not _num(b) else
        f"discharging {_kw(b)}" if b > 0 else f"charging {_kw(-b)}" if b < 0 else "idle")
    g = p.get("grid_w")       # positive = import
    add("grid", "Grid", None if not _num(g) else
        f"importing {_kw(g)}" if g > 0 else f"exporting {_kw(-g)}" if g < 0 else _kw(0))
    add("solar", "Solar", _kw(p["solar_w"]) if _num(p.get("solar_w")) else None)
    add("home", "Home", _kw(p["load_w"]) if _num(p.get("load_w")) else None)

    if circuits and circuits.get("circuits"):
        cs = [f"{c['name']} on {_kw(c['watts'])}" if c.get("on") and _num(c.get("watts"))
              else f"{c['name']} {'on' if c.get('on') else 'off'}"
              for c in circuits["circuits"] if c.get("present")]
    else:
        names = (summ or {}).get("circuit_names") or {}
        cs = [f"{names.get(n) or f'Circuit {n}'} {'on' if on else 'off'}"
              for n, on in sorted(((summ or {}).get("circuits_on") or {}).items())]
    add("circuits", "Smart circuits", ", ".join(cs) or None)

    if generator and generator.get("installed"):
        today = p.get("kwh_gen")
        add("generator", "Generator", ", ".join(x for x in (
            generator.get("state_name"),
            _kw(generator["power_w"]) if _num(generator.get("power_w")) else None,
            f"{today:.1f} kWh today" if _num(today) else None) if x))
    if v2l_installed:
        car = (circuits or {}).get("carsw") or {}
        add("v2l", "V2L", ", ".join(x for x in (
            "on" if car.get("enabled") else "off" if car else "not read",
            _kw(car["watts"]) if _num(car.get("watts")) else None) if x))
    return out


def line(rs: list[dict]) -> str:
    """The rows as one line, for the control log."""
    return "; ".join(f"{r['label']} {r['value']}" for r in rs)
