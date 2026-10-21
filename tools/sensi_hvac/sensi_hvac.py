#!/usr/bin/env python3
"""Guest HVAC mode automation for Sensi thermostats in short-term rentals.

Rental policy on top of sensi_unofficial.py (Sensi access, which must sit next to this
file). Reads the hourly forecast from the National Weather Service (free, no key).

Handles every situation for each thermostat independently (no averaging):
  - guest stays: HEAT/COOL chosen from that thermostat's indoor reading and the
    forecast; guest told; first check of a stay always sets guest mode.
  - check-out: setback (heat 60 / cool 82 by season), except same-day turnovers,
    which are left to the cleaner until the next guest's pre-arrival.
  - vacant days: a manual (cleaner/host) change is held 4h, then the setback returns.
Each `run` does the cheapest work first and stops at the first gate that fails:
  1-2. reservations + this task's own note tags + the clock (offline)
  3.   forecast (one NWS fetch, only if a guest-mode change looks possible)
  4.   Sensi, last: ONE connection reads live state, decides, writes, closes.
History lives in Hospitable reservation notes as [HVAC_...] tags; the caller
appends the tags this script returns.

Usage (Sensi refresh token via --token or env SENSI_REFRESH_TOKEN)
  run --occupancy O --config C [--dry-run] [--now ISO]
  precheck --occupancy O --config C [--now ISO]    offline gates only: would Sensi be needed?
  apply --config C --change <apply_spec> ...       do approved shadow-run changes
  status [--raw]                                   list thermostats (JSON)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sensi_unofficial import (AuthError, Sensi, UA, _write, get_access_token,
                               sensi_status, summarize_device)

# ============================================================================
# Weather (NWS)
# ============================================================================
def nws_hourly(lat: float, lon: float) -> list[dict]:
    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    pts = get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    fc = get(pts["properties"]["forecastHourly"])
    out = []
    for p in fc["properties"]["periods"]:
        t = p["temperature"]
        if p.get("temperatureUnit") == "C":
            t = t * 9 / 5 + 32
        out.append({"start": p["startTime"], "temp_f": float(t)})
    return out


# ============================================================================
# Decision logic (pure)
# ============================================================================
DEFAULTS = {
    "timezone": "America/Chicago",
    "pre_arrival_hours": 3,
    "quiet_hours": [22, 7],            # local [start, end): no messages, no non-emergency switches
    "min_dwell_hours": 6,              # don't flip-flop modes
    "heat_default": 68, "cool_default": 74,
    "cool_trigger_indoor": 75,         # in HEAT mode: switch to COOL when indoor >= this ...
    "cool_margin_over_heat_sp": 2,     # ... and indoor >= heat setpoint + this ...
    "cool_needs_outdoor_max": 72,      # ... and forecast max over next 6h >= this
    "heat_trigger_indoor": 67,         # in COOL mode: switch to HEAT when indoor <= this ...
    "heat_margin_under_cool_sp": 2,    # ... and indoor <= cool setpoint - this ...
    "heat_needs_outdoor_min": 60,      # ... and forecast min over next 6h <= this
    "emergency_hot": 80, "emergency_cold": 63,   # override dwell + quiet hours
    "balance_outdoor": 68,             # auto/off/mixed: pick by 12h mean outdoor vs this (if indoor neutral)
    "max_messages_per_day": 2,
    # --- vacancy (no guest) ---
    "vacancy_heat": 60, "vacancy_cool": 82,   # setback: heat to 60 / cool to 82, chosen by season
    "vacancy_flip_hot": 80,            # vacancy HEAT -> vacancy COOL when indoor >= this
    "vacancy_flip_cold": 62,           # vacancy COOL -> vacancy HEAT when indoor <= this
    "manual_hold_hours": 4,            # cleaner/host manual setting on a vacant day is respected this long
    "vacant_check_hours": [9, 13, 17, 21],   # local hours at which a settled vacant unit is read
    "same_day_turnover_hours": 12,     # next check-in this soon after check-out: no setback; cleaner's until pre-arrival
}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def forecast_window(fc: list[dict], now: datetime, hours: int) -> list[float]:
    end = now + timedelta(hours=hours)
    vals = [p["temp_f"] for p in fc
            if now - timedelta(hours=1) < _parse(p["start"]) <= end]
    return vals




# ----------------------------------------------------------------------------
# History lives in Hospitable reservation notes as tags, one per thermostat.
# During a stay (in that stay's reservation):
#   [HVAC_SWITCH <iso> <key> <mode> sp=<n> lim=<n>]  guest mode set by this task
#   [HVAC_MSG <iso> <key>,<key>]                      guest told about it
# While vacant (in the most recently departed reservation):
#   [HVAC_VACANT <iso> <key> <mode> sp=<n>]           setback set (or confirmed) by this task
#   [HVAC_MANUAL <iso> <key> <mode> sp=<n>]           someone changed it by hand; held for a while
# ----------------------------------------------------------------------------
SWITCH_RE = re.compile(r"\[HVAC_SWITCH (\S+) ([A-Za-z0-9_-]+) (heat|cool)(?: sp=(\d+))?(?: lim=(\d+))?\]")
MSG_RE = re.compile(r"\[HVAC_MSG (\S+) ([A-Za-z0-9_,-]+)\]")
VAC_RE = re.compile(r"\[HVAC_(VACANT|MANUAL) (\S+) ([A-Za-z0-9_-]+) ([a-z]+)(?: sp=(\d+))?\]")


def _ts(when: datetime) -> str:
    return when.isoformat(timespec="minutes")


def switch_tag(when: datetime, key: str, mode: str, sp=None, lim=None) -> str:
    extra = (f" sp={int(sp)}" if sp is not None else "") + (f" lim={int(lim)}" if lim is not None else "")
    return f"[HVAC_SWITCH {_ts(when)} {key} {mode}{extra}]"


def msg_tag(when: datetime, keys: list[str]) -> str:
    return f"[HVAC_MSG {_ts(when)} {','.join(keys)}]"


def vac_tag(kind: str, when: datetime, key: str, mode: str, sp=None) -> str:
    return f"[HVAC_{kind} {_ts(when)} {key} {mode}{f' sp={int(sp)}' if sp is not None else ''}]"


def parse_history(notes: str | None):
    switches, msgs = [], []
    for ts, key, mode, sp, lim in SWITCH_RE.findall(notes or ""):
        try:
            switches.append({"at": _parse(ts), "key": key, "mode": mode,
                             "sp": int(sp) if sp else None, "lim": int(lim) if lim else None})
        except ValueError:
            pass
    for ts, keys in MSG_RE.findall(notes or ""):
        try:
            msgs.append({"at": _parse(ts), "keys": keys.split(",")})
        except ValueError:
            pass
    return sorted(switches, key=lambda x: x["at"]), sorted(msgs, key=lambda x: x["at"])


def parse_vacancy(notes: str | None, since: datetime) -> list[dict]:
    out = []
    for kind, ts, key, mode, sp in VAC_RE.findall(notes or ""):
        try:
            at = _parse(ts)
        except ValueError:
            continue
        if at >= since:
            out.append({"kind": kind, "at": at, "key": key, "mode": mode, "sp": int(sp) if sp else None})
    return sorted(out, key=lambda x: x["at"])


def last_for(items: list[dict], key: str):
    s = [x for x in items if x["key"] == key]
    return s[-1] if s else None


def _ctx(cfg: dict, now: datetime):
    c = {**DEFAULTS, **cfg.get("rules", {})}
    tz = ZoneInfo(c["timezone"])
    local = now.astimezone(tz)
    qs, qe = c["quiet_hours"]
    quiet = (local.hour >= qs or local.hour < qe) if qs > qe else (qs <= local.hour < qe)
    return c, tz, local, quiet


def unit_reservations(c: dict, uid: str, occ: list[dict], now: datetime):
    """(current, departed, next) for one unit. `current` = stay in progress or in its
    pre-arrival window; `departed` = most recent stay already checked out."""
    rs = {r["reservation_id"]: r for r in occ
          if r.get("property_id") == uid and r.get("status") == "accepted"}.values()
    current = departed = nxt = None
    for r in rs:
        ci, co = _parse(r["check_in"]), _parse(r["check_out"])
        if ci - timedelta(hours=c["pre_arrival_hours"]) <= now < co:
            current = r
        elif co <= now and (departed is None or co > _parse(departed["check_out"])):
            departed = r
        elif ci > now and (nxt is None or ci < _parse(nxt["check_in"])):
            nxt = r
    return current, departed, nxt


def occupied_units(cfg: dict, occ: list[dict], now: datetime) -> set[str]:
    c = {**DEFAULTS, **cfg.get("rules", {})}
    return {u["property_id"] for u in cfg["units"] if unit_reservations(c, u["property_id"], occ, now)[0]}


def vacancy_skip_reason(c: dict, departed, nxt) -> str | None:
    if departed is None:
        return "vacant, but no recent reservation to keep records in; not managed"
    if nxt and _parse(nxt["check_in"]) - _parse(departed["check_out"]) < timedelta(hours=c["same_day_turnover_hours"]):
        return "turnover day: left as the guest/cleaner left it until the next guest's pre-arrival"
    return None


# ----------------------------------------------------------------------------
# Gates 2-3: per THERMOSTAT, without contacting Sensi, is there anything that
# could need doing? Free checks (tags, dwell, quiet hours, clock) come before
# the forecast, which is fetched lazily and only if needed.
# ----------------------------------------------------------------------------
def gate(cfg: dict, now: datetime, occ: list[dict], forecasts) -> list[dict]:
    c, tz, local, quiet = _ctx(cfg, now)
    get_fc = forecasts if callable(forecasts) else (lambda unit: forecasts.get(unit["property_id"]) or [])
    out = []
    for unit in cfg["units"]:
        g = {"unit": unit["name"], "property_id": unit["property_id"], "contact_sensi": False, "thermostats": []}
        out.append(g)
        cur, departed, nxt = unit_reservations(c, unit["property_id"], occ, now)
        g["reservation"], g["departed"], g["next"] = cur, departed, nxt
        if cur:
            g["state"] = "guest"
            switches, _ = parse_history(cur.get("notes"))
            for t in unit["thermostats"]:
                tg = {"key": t["key"], "label": t["label"], "contact_sensi": False}
                g["thermostats"].append(tg)
                last = last_for(switches, t["key"])
                if not last:
                    tg["contact_sensi"], tg["why"] = True, "first check this stay: set guest mode"
                    continue
                tg["last_set"] = f"{last['mode']} at {_ts(last['at'])}"
                if now < _parse(cur["check_in"]):
                    tg["contact_sensi"], tg["why"] = True, "before check-in: confirm guest setting (cleaner may have changed it)"
                    continue
                if now - last["at"] < timedelta(hours=c["min_dwell_hours"]):
                    tg["why"] = "within dwell period"
                    continue
                if quiet:
                    tg["why"] = "quiet hours"
                    continue
                w6 = forecast_window(get_fc(unit), now, 6)
                if not w6:
                    tg["why"] = "no forecast; holding last mode"
                    continue
                fmin6, fmax6 = min(w6), max(w6)
                if last["mode"] == "heat" and fmax6 >= c["cool_needs_outdoor_max"]:
                    tg["contact_sensi"], tg["why"] = True, f"in heat; outdoor reaches {fmax6:.0f}° in next 6h"
                elif last["mode"] == "cool" and fmin6 <= c["heat_needs_outdoor_min"]:
                    tg["contact_sensi"], tg["why"] = True, f"in cool; outdoor drops to {fmin6:.0f}° in next 6h"
                else:
                    tg["why"] = f"forecast ({fmin6:.0f}–{fmax6:.0f}°) doesn't call for leaving {last['mode']}"
        else:
            g["state"] = "vacant"
            skip = vacancy_skip_reason(c, departed, nxt)
            if skip:
                g["why"] = skip
                continue
            vt = parse_vacancy(departed.get("notes"), _parse(departed["check_out"]))
            for t in unit["thermostats"]:
                tg = {"key": t["key"], "label": t["label"], "contact_sensi": False}
                g["thermostats"].append(tg)
                last = last_for(vt, t["key"])
                if not last:
                    tg["contact_sensi"], tg["why"] = True, "checked out: set vacancy setback"
                elif last["kind"] == "MANUAL":
                    until = last["at"] + timedelta(hours=c["manual_hold_hours"])
                    if now < until:
                        tg["why"] = f"manual setting held until {until.astimezone(tz):%H:%M}"
                    else:
                        tg["contact_sensi"], tg["why"] = True, "manual hold expired: restore setback"
                elif local.hour in c["vacant_check_hours"]:
                    tg["contact_sensi"], tg["why"] = True, "scheduled vacancy check"
                else:
                    tg["why"] = f"setback ({last['mode']} to {last['sp']}°) in place; next check at a vacancy-check hour"
        g["contact_sensi"] = any(tg["contact_sensi"] for tg in g["thermostats"])
    return out


# ----------------------------------------------------------------------------
# Gate 4: with live readings, decide each thermostat on its own numbers.
# ----------------------------------------------------------------------------
def decide_thermostat(c: dict, t: dict, fmin6, fmax6, fmean12, first_check: bool = False):
    """Guest-mode decision. Returns (desired_mode or None, why, emergency_flag).
    On the first check of a stay the current mode is ignored (it may be a setback, a
    cleaner's setting, Auto or Off) and a guest mode is always chosen."""
    indoor, cur = t["indoor_temp"], t["mode"]
    if not first_check:
        if indoor >= c["emergency_hot"] and cur != "cool":
            return "cool", f"EMERGENCY: indoor {indoor:.0f}°", True
        if indoor <= c["emergency_cold"] and cur != "heat":
            return "heat", f"EMERGENCY: indoor {indoor:.0f}°", True
        if cur == "heat":
            hsp = t["heat_setpoint"] or 0
            if (indoor >= c["cool_trigger_indoor"] and indoor >= hsp + c["cool_margin_over_heat_sp"]
                    and fmax6 is not None and fmax6 >= c["cool_needs_outdoor_max"]):
                return "cool", f"indoor {indoor:.0f}° (heat to {hsp:.0f}°), outdoor rising to {fmax6:.0f}°", False
            return None, f"stay in heat (indoor {indoor:.0f}°, heat to {hsp:.0f}°)", False
        if cur == "cool":
            csp = t["cool_setpoint"] or 99
            if (indoor <= c["heat_trigger_indoor"] and indoor <= csp - c["heat_margin_under_cool_sp"]
                    and fmin6 is not None and fmin6 <= c["heat_needs_outdoor_min"]):
                return "heat", f"indoor {indoor:.0f}° (cool to {csp:.0f}°), outdoor falling to {fmin6:.0f}°", False
            return None, f"stay in cool (indoor {indoor:.0f}°, cool to {csp:.0f}°)", False
    pre = "first check of stay" if first_check else f"was {cur}"
    if indoor >= c["cool_trigger_indoor"] - 1:
        return "cool", f"{pre}; indoor {indoor:.0f}° is warm", False
    if indoor <= c["heat_trigger_indoor"] + 1:
        return "heat", f"{pre}; indoor {indoor:.0f}° is cool", False
    if fmean12 is not None:
        m = "cool" if fmean12 >= c["balance_outdoor"] else "heat"
        return m, f"{pre}; next-12h outdoor average {fmean12:.0f}°", False
    return None, f"{pre}; no forecast to choose by", False


def target_setpoint(c: dict, t: dict, mode: str) -> int:
    if mode == "heat":
        sp, lim, (lo, hi) = c["heat_default"], t["heat_ceiling"], t["hw_heat_range"]
        sp = min(sp, lim) if lim else sp
    else:
        sp, lim, (lo, hi) = c["cool_default"], t["cool_floor"], t["hw_cool_range"]
        sp = max(sp, lim) if lim else sp
    sp = max(sp, lo) if lo is not None else sp
    sp = min(sp, hi) if hi is not None else sp
    return int(round(sp))


def vacancy_target(c: dict, t: dict, fmean12) -> tuple[str, int]:
    indoor = t["indoor_temp"]
    if indoor >= c["vacancy_flip_hot"]:
        mode = "cool"
    elif indoor <= c["vacancy_flip_cold"]:
        mode = "heat"
    elif fmean12 is not None:
        mode = "cool" if fmean12 >= c["balance_outdoor"] else "heat"
    else:
        mode = "cool" if indoor >= 72 else "heat"
    return mode, c["vacancy_heat"] if mode == "heat" else c["vacancy_cool"]


def current_sp(t: dict):
    return {"heat": t["heat_setpoint"], "cool": t["cool_setpoint"]}.get(t["mode"])


def is_setback(c: dict, t: dict) -> bool:
    sp = current_sp(t)
    return ((t["mode"] == "heat" and sp == c["vacancy_heat"]) or
            (t["mode"] == "cool" and sp == c["vacancy_cool"]))


def _action(unit, res_id, t, key, label, mode, sp, kind, lim=None):
    return {"unit": unit["name"], "reservation_id": res_id, "icd_id": t["icd_id"], "key": key,
            "thermostat": label, "kind": kind, "from_mode": t["mode"], "set_mode": mode, "temp_mode": mode,
            "set_temp": sp, "scale": t["scale"], "limit": lim,
            "apply_spec": f"{key}:{mode}:{sp}:{t['mode']}:{kind}:{res_id}"}


def decide(cfg: dict, now: datetime, devices: list[dict], occupancy: list[dict],
           forecasts: dict[str, list[dict]], dry_run: bool) -> dict:
    c, tz, local, quiet = _ctx(cfg, now)
    by_icd = {d["icd_id"]: d for d in devices}
    report = {"units": [], "actions": [], "note_tags": [], "messages": [], "alerts": []}

    for unit in cfg["units"]:
        uid = unit["property_id"]
        u = {"unit": unit["name"], "thermostats": []}
        report["units"].append(u)
        cur, departed, nxt = unit_reservations(c, uid, occupancy, now)
        fc = forecasts.get(uid) or []
        w6, w12 = forecast_window(fc, now, 6), forecast_window(fc, now, 12)
        fmin6, fmax6 = (min(w6), max(w6)) if w6 else (None, None)
        fmean12 = sum(w12) / len(w12) if w12 else None
        u["forecast"] = {"next6h_min": fmin6, "next6h_max": fmax6,
                         "next12h_avg": round(fmean12, 1) if fmean12 is not None else None}

        if not cur:
            skip = vacancy_skip_reason(c, departed, nxt)
            if skip:
                u["decision"] = skip
                continue
            u["state"] = "vacant"
            u["records_in"] = departed.get("code") or departed["reservation_id"]
            decide_vacant(c, local, now, unit, departed, by_icd, fmean12, report, u, dry_run)
            continue

        u["state"] = "guest"
        u["reservation"] = cur.get("code") or cur["reservation_id"]
        switches, msgs = parse_history(cur.get("notes"))
        if not w6:
            report["alerts"].append(f"{unit['name']}: no forecast data")
        switched_now = []
        for cfg_t in unit["thermostats"]:
            key, label = cfg_t["key"], cfg_t["label"]
            t = by_icd.get(cfg_t["id"])
            tr = {"thermostat": label}
            u["thermostats"].append(tr)
            if not t or not t["online"] or t["indoor_temp"] is None:
                report["alerts"].append(f"{unit['name']}: {label} unreachable")
                tr["decision"] = "unreachable"
                continue
            if t.get("scheduling") == "on":
                tr["warning"] = "Sensi schedule is ON; a schedule step can override the setpoint this task sets"
            tr.update(mode=t["mode"], indoor=t["indoor_temp"], heat_to=t["heat_setpoint"], cool_to=t["cool_setpoint"])
            last = last_for(switches, key)
            first = last is None
            if not first and now < _parse(cur["check_in"]) and last.get("sp") is not None:
                # Before check-in, the cleaner may still be working: put back exactly the guest
                # setting chosen earlier (indoor readings mid-cleaning aren't a basis to re-decide).
                desired, sp = last["mode"], last["sp"]
                if t["mode"] == desired and current_sp(t) == sp:
                    tr["decision"] = f"before check-in: guest setting ({desired} to {sp}°) still in place"
                    continue
                lim = t["heat_ceiling"] if desired == "heat" else t["cool_floor"]
                was = f"{t['mode']}" + (f" to {current_sp(t):.0f}°" if current_sp(t) is not None else "")
                tr["decision"] = f"before check-in: restore {desired} to {sp}° (someone changed it to {was})"
                report["actions"].append(_action(unit, cur["reservation_id"], t, key, label, desired, sp, "guest", lim))
                if not dry_run:
                    report["note_tags"].append({"reservation_id": cur["reservation_id"], "unit": unit["name"],
                                                "key": key, "tag": switch_tag(local, key, desired, sp, lim)})
                continue
            desired, why, emergency = decide_thermostat(c, t, fmin6, fmax6, fmean12, first_check=first)
            if desired is None:
                tr["decision"] = why
                continue
            if not first and t["mode"] in ("heat", "cool") and not emergency:
                if now - last["at"] < timedelta(hours=c["min_dwell_hours"]):
                    tr["decision"] = f"would switch to {desired} but held (switched {last['at'].astimezone(tz):%H:%M}); {why}"
                    continue
                if quiet:
                    tr["decision"] = f"would switch to {desired} but held (quiet hours); {why}"
                    continue
            sp = target_setpoint(c, t, desired)
            lim = t["heat_ceiling"] if desired == "heat" else t["cool_floor"]
            if first and t["mode"] == desired and current_sp(t) == sp:
                tr["decision"] = f"already {desired} to {sp}° ({why}); recorded"
                if not dry_run:
                    report["note_tags"].append({"reservation_id": cur["reservation_id"], "unit": unit["name"],
                                                "key": key, "tag": switch_tag(local, key, desired, sp, lim)})
                continue
            tr["decision"] = f"switch to {desired}, {desired} to {sp}°: {why}"
            report["actions"].append(_action(unit, cur["reservation_id"], t, key, label, desired, sp, "guest", lim))
            if not dry_run:
                report["note_tags"].append({"reservation_id": cur["reservation_id"], "unit": unit["name"],
                                            "key": key, "tag": switch_tag(local, key, desired, sp, lim)})
            switched_now.append({"key": key, "label": label, "mode": desired, "sp": sp,
                                 "lim": int(lim) if lim is not None else None})

        live_modes = {cfg_t["key"]: (by_icd.get(cfg_t["id"]) or {}).get("mode") for cfg_t in unit["thermostats"]}
        msg, note = owed_message(c, tz, local, quiet, unit, cur, switches, msgs, now, dry_run,
                                 switched_now, live_modes)
        if msg:
            report["messages"].append(msg)
        elif note:
            u["message"] = note
    return report


def decide_vacant(c, local, now, unit, departed, by_icd, fmean12, report, u, dry_run):
    """Vacancy: set the setback after check-out, respect a manual (cleaner/host) change
    for manual_hold_hours, then restore the setback; flip setback mode by season."""
    rid = departed["reservation_id"]
    vt = parse_vacancy(departed.get("notes"), _parse(departed["check_out"]))
    guest_sw, _ = parse_history(departed.get("notes"))

    def tag(kind, key, mode, sp):
        if not dry_run:
            report["note_tags"].append({"reservation_id": rid, "unit": unit["name"], "key": key,
                                        "tag": vac_tag(kind, local, key, mode, sp)})

    for cfg_t in unit["thermostats"]:
        key, label = cfg_t["key"], cfg_t["label"]
        t = by_icd.get(cfg_t["id"])
        tr = {"thermostat": label}
        u["thermostats"].append(tr)
        if not t or not t["online"] or t["indoor_temp"] is None:
            report["alerts"].append(f"{unit['name']}: {label} unreachable")
            tr["decision"] = "unreachable"
            continue
        if t.get("scheduling") == "on":
            tr["warning"] = "Sensi schedule is ON; it may override the setback"
        tr.update(mode=t["mode"], indoor=t["indoor_temp"], heat_to=t["heat_setpoint"], cool_to=t["cool_setpoint"])
        last = last_for(vt, key)
        vmode, vsp = vacancy_target(c, t, fmean12)
        setback_now = is_setback(c, t)

        def set_setback(why):
            tr["decision"] = f"set setback: {vmode} to {vsp}° ({why})"
            report["actions"].append(_action(unit, rid, t, key, label, vmode, vsp, "vacant"))
            # the VACANT tag is returned with the action and written only if the change succeeds
            if not dry_run:
                report["note_tags"].append({"reservation_id": rid, "unit": unit["name"], "key": key,
                                            "tag": vac_tag("VACANT", local, key, vmode, vsp)})

        if last is None:                                   # first look after check-out
            gs = last_for(guest_sw, key)
            if setback_now:
                tr["decision"] = f"already at setback ({t['mode']} to {current_sp(t):.0f}°); recorded"
                tag("VACANT", key, t["mode"], current_sp(t))
            elif gs is None or t["mode"] == gs["mode"]:
                set_setback("guest checked out" + ("" if gs else "; no guest-mode record, assuming guest's setting"))
            else:
                tr["decision"] = (f"manual change since check-out ({t['mode']}"
                                  f"{'' if current_sp(t) is None else f' to {current_sp(t):.0f}°'}); "
                                  f"holding {c['manual_hold_hours']}h")
                tag("MANUAL", key, t["mode"], current_sp(t))
        elif last["kind"] == "MANUAL":
            if now - last["at"] < timedelta(hours=c["manual_hold_hours"]):
                tr["decision"] = "manual setting still within its hold"
            elif setback_now:
                tr["decision"] = "manual hold over; already back at setback; recorded"
                tag("VACANT", key, t["mode"], current_sp(t))
            else:
                set_setback(f"manual hold of {c['manual_hold_hours']}h is over")
        else:                                              # last == VACANT
            same = t["mode"] == last["mode"] and (last["sp"] is None or current_sp(t) == last["sp"])
            if not same:
                tr["decision"] = (f"manual change detected ({t['mode']}"
                                  f"{'' if current_sp(t) is None else f' to {current_sp(t):.0f}°'}); "
                                  f"holding {c['manual_hold_hours']}h")
                tag("MANUAL", key, t["mode"], current_sp(t))
            elif last["mode"] == "heat" and t["indoor_temp"] >= c["vacancy_flip_hot"]:
                vmode, vsp = "cool", c["vacancy_cool"]
                set_setback(f"indoor {t['indoor_temp']:.0f}° while at heat setback")
            elif last["mode"] == "cool" and t["indoor_temp"] <= c["vacancy_flip_cold"]:
                vmode, vsp = "heat", c["vacancy_heat"]
                set_setback(f"indoor {t['indoor_temp']:.0f}° while at cool setback")
            else:
                tr["decision"] = f"setback in place ({last['mode']} to {last['sp']}°, indoor {t['indoor_temp']:.0f}°)"


def owed_message(c, tz, local, quiet, unit, res, switches, msgs, now, dry_run,
                 switched_now=(), live_modes=None):
    """One message per unit update, covering every thermostat switched after check-in
    that the guest hasn't been told about yet."""
    check_in = _parse(res["check_in"])
    if now < check_in:
        return None, None
    labels = {t["key"]: t["label"] for t in unit["thermostats"]}
    items = {s["key"]: s for s in switched_now}
    for t in unit["thermostats"]:
        k = t["key"]
        if k in items:
            continue
        last = last_for(switches, k)
        if not last or last["at"] < check_in:
            continue
        if any(m["at"] >= last["at"] and k in m["keys"] for m in msgs):
            continue
        if live_modes and live_modes.get(k) not in (None, last["mode"]):
            continue    # changed again since; don't announce a stale mode
        items[k] = {"key": k, "label": labels[k], "mode": last["mode"], "sp": last["sp"], "lim": last["lim"]}
    if not items:
        return None, None
    if quiet:
        return None, "deferred until after quiet hours"
    if sum(1 for m in msgs if m["at"].astimezone(tz).date() == local.date()) >= c["max_messages_per_day"]:
        return None, "suppressed: daily message cap reached"
    ordered = [items[t["key"]] for t in unit["thermostats"] if t["key"] in items]
    return {"unit": unit["name"], "reservation_id": res["reservation_id"],
            "thermostats": [i["label"] for i in ordered],
            "guest_first_name": res.get("guest_first_name"), "language": res.get("language") or "en",
            "text_en": message_text(ordered, len(unit["thermostats"]), res.get("guest_first_name")),
            "note_tag_after_send": None if dry_run else msg_tag(local, [i["key"] for i in ordered])}, None


def _limit_phrase(mode: str, lim) -> str:
    if lim is None:
        return ""
    return f" (you can go as low as {lim}°)" if mode == "cool" else f" (you can go as high as {lim}°)"


def _names(labels: list[str]) -> str:
    if len(labels) == 1:
        return f"the {labels[0]}"
    if all(lb.endswith(" thermostat") for lb in labels):
        stems = [lb[: -len(" thermostat")] for lb in labels]
        return "the " + ", ".join(stems[:-1]) + " and " + stems[-1] + " thermostats"
    return "the " + ", ".join(labels[:-1]) + " and the " + labels[-1]


def message_text(items: list[dict], n_in_unit: int, first_name: str | None) -> str:
    hi = f"Hi {first_name}" if first_name else "Hi"
    modes = {i["mode"] for i in items}
    why = ("with the weather warming up" if modes == {"cool"} else
           "with the weather cooling off" if modes == {"heat"} else "to keep every part of the house comfortable")
    same = len({(i["mode"], i.get("sp"), i.get("lim")) for i in items}) == 1
    if same:
        i = items[0]
        sp = f", set to {i['mode']} to {i['sp']}°" if i.get("sp") is not None else ""
        body = (f"{why}, we've switched {_names([x['label'] for x in items])} to {i['mode'].upper()} mode{sp}. "
                f"You can raise or lower the setting right on the thermostat{'s' if len(items) > 1 else ''}"
                f"{_limit_phrase(i['mode'], i.get('lim'))}.")
    else:
        lines = []
        for i in items:
            sp = f", set to {i['mode']} to {i['sp']}°" if i.get("sp") is not None else ""
            lines.append(f"The {i['label']} is now in {i['mode'].upper()} mode{sp}"
                         f"{_limit_phrase(i['mode'], i.get('lim'))}.")
        body = (f"{why}, we've adjusted the thermostats. " + " ".join(lines) +
                " You can raise or lower each setting right on that thermostat.")
    return (f"{hi}, quick heads-up: {body} If you'd prefer a different mode, just message us here "
            "and we'll switch it for you. Enjoy your stay!")


# ============================================================================
# CLI
# ============================================================================
def load(p):
    with open(p) as f:
        return json.load(f)


async def sensi_session(token: str, cfg, now, occ, forecasts, dry_run):
    """ONE Sensi connection, opened last: read live state, decide, write, close."""
    async with Sensi(token) as c:
        devices = [summarize_device(i, d) for i, d in c.devices.items()]
        rep = decide(cfg, now, devices, occ, forecasts, dry_run)
        if rep["actions"] and not dry_run:
            rep["results"] = []
            for a in rep["actions"]:
                err = await _write(c, a["icd_id"], a["from_mode"], a["set_mode"], a["set_temp"], a["scale"])
                rep["results"].append({**a, "ok": err is None, "error": err})
    return rep


async def apply_changes(token: str, cfg: dict, changes: list[dict], now: datetime) -> dict:
    """Carry out changes a shadow run proposed and the host approved ("do it").
    Each change is refused if the thermostat no longer shows the mode the shadow run saw."""
    c, tz, local, quiet = _ctx(cfg, now)
    ids = {t["key"]: (u, t) for u in cfg["units"] for t in u["thermostats"]}
    out = {"results": [], "note_tags": [], "msg_tags": {}}
    async with Sensi(token) as conn:
        live = {i: summarize_device(i, d) for i, d in conn.devices.items()}
        for ch in changes:
            unit, t = ids[ch["key"]]
            dev = live.get(t["id"])
            r = {**ch, "unit": unit["name"], "thermostat": t["label"]}
            if not dev or not dev["online"]:
                r.update(ok=False, error="thermostat unreachable")
            elif ch.get("from") and dev["mode"] != ch["from"]:
                r.update(ok=False, error=f"stale: thermostat is now in {dev['mode']}, not {ch['from']}; not changed")
            else:
                err = await _write(conn, t["id"], dev["mode"], ch["mode"], ch["sp"], dev["scale"])
                r.update(ok=err is None, error=err)
                if err is None:
                    if ch.get("kind") == "vacant":
                        tg = vac_tag("VACANT", local, ch["key"], ch["mode"], ch["sp"])
                    else:
                        lim = dev["heat_ceiling"] if ch["mode"] == "heat" else dev["cool_floor"]
                        tg = switch_tag(local, ch["key"], ch["mode"], ch["sp"], lim)
                    out["note_tags"].append({"unit": unit["name"], "key": ch["key"],
                                             "reservation_id": ch.get("reservation_id"), "tag": tg})
            out["results"].append(r)
    for u in cfg["units"]:
        keys = [t["key"] for t in u["thermostats"]
                if any(n["key"] == t["key"] and n["tag"].startswith("[HVAC_SWITCH") for n in out["note_tags"])]
        if keys:
            out["msg_tags"][u["name"]] = msg_tag(local, keys)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("SENSI_REFRESH_TOKEN"),
                    help="Sensi refresh token (or env SENSI_REFRESH_TOKEN)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--raw", action="store_true")
    for name in ("precheck", "run"):
        r = sub.add_parser(name)
        r.add_argument("--occupancy", required=True); r.add_argument("--config", required=True)
        r.add_argument("--dry-run", action="store_true"); r.add_argument("--now")
    p = sub.add_parser("apply", help="carry out approved changes from a shadow run")
    p.add_argument("--config", required=True)
    p.add_argument("--change", action="append", required=True,
                   help="KEY:MODE:SETPOINT:FROM_MODE:KIND:RESERVATION_ID (the report's apply spec)")
    a = ap.parse_args()

    if a.cmd == "apply":
        changes = []
        for spec in a.change:
            key, mode, sp, *rest = spec.split(":")
            assert mode in ("heat", "cool"), spec
            changes.append({"key": key, "mode": mode, "sp": int(sp),
                            "from": rest[0] if len(rest) > 0 else None,
                            "kind": rest[1] if len(rest) > 1 else "guest",
                            "reservation_id": rest[2] if len(rest) > 2 else None})
        try:
            res = asyncio.run(apply_changes(get_access_token(a.token), load(a.config), changes,
                                            datetime.now(timezone.utc)))
        except AuthError as e:
            res = {"fatal": True, "alerts": [f"SENSI AUTH: {e}"]}
        except Exception as e:
            res = {"fatal": True, "alerts": [f"SENSI UNREACHABLE: {type(e).__name__}: {e}"]}
        print(json.dumps(res, indent=2))
        return

    if a.cmd == "status":
        print(json.dumps(asyncio.run(sensi_status(get_access_token(a.token), a.raw)), indent=2))
        return

    cfg, occ = load(a.config), load(a.occupancy)
    now = _parse(a.now) if a.now else datetime.now(timezone.utc)
    c, tz, local, quiet = _ctx(cfg, now)
    out = {"now": now.isoformat(), "local": local.strftime("%a %Y-%m-%d %H:%M %Z"), "dry_run": a.dry_run,
           "sensi_contacted": False, "units": [], "actions": [], "note_tags": [], "messages": [], "alerts": []}

    # Gates 1-2 (offline): reservations + this task's own tags + the clock.
    cache: dict[tuple, list] = {}

    def get_fc(unit):
        key = (round(unit["lat"], 2), round(unit["lon"], 2))
        if key not in cache:
            try:
                cache[key] = nws_hourly(unit["lat"], unit["lon"])
            except Exception as e:  # weather down: guest modes held; first checks still proceed
                cache[key] = []
                out["alerts"].append(f"forecast unavailable for {unit['name']}: {e}")
        return cache[key]

    gates = gate(cfg, now, occ, get_fc)        # gate 3 (forecast) is fetched lazily inside, if needed
    if a.cmd == "precheck":
        out["proceed"] = any(g["contact_sensi"] for g in gates)
        out["units"] = [{"unit": g["unit"], "why": g.get("why"),
                         "thermostats": [{k: t[k] for k in ("label", "why") if k in t} for t in g["thermostats"]]}
                        for g in gates]
        print(json.dumps(out, indent=2))
        return

    need = any(g["contact_sensi"] for g in gates)
    if not need:
        for g in gates:
            entry = {"unit": g["unit"], "state": g.get("state"), "decision": g.get("why") or "no Sensi contact",
                     "thermostats": [{"thermostat": t["label"], "last_set": t.get("last_set"), "why": t.get("why")}
                                     for t in g["thermostats"]]}
            if g["state"] == "guest":
                res = g["reservation"]
                unit = next(x for x in cfg["units"] if x["property_id"] == g["property_id"])
                switches, msgs = parse_history(res.get("notes"))
                msg, note = owed_message(c, tz, local, quiet, unit, res, switches, msgs, now, a.dry_run)
                if msg:
                    out["messages"].append(msg)
                elif note:
                    entry["message"] = note
            out["units"].append(entry)
        out["summary"] = "Nothing needs Sensi this run."
        print(json.dumps(out, indent=2))
        return

    # Gate 4: Sensi, last -- one connection: read all, decide each thermostat, write, close.
    try:
        token = get_access_token(a.token)
        forecasts = {u["property_id"]: get_fc(u) for u in cfg["units"]}
        rep = asyncio.run(sensi_session(token, cfg, now, occ, forecasts, a.dry_run))
    except AuthError as e:
        out["alerts"].append(f"SENSI AUTH: {e}")
        out["fatal"] = True
        print(json.dumps(out, indent=2))
        return
    except Exception as e:  # Sensi unreachable or protocol changed: change nothing, tell the host
        out["alerts"].append(f"SENSI UNREACHABLE: {type(e).__name__}: {e}")
        out["fatal"] = True
        print(json.dumps(out, indent=2))
        return
    out["sensi_contacted"] = True
    for k in ("units", "alerts", "actions", "note_tags", "messages"):
        out[k] += rep[k]
    if "results" in rep:
        out["results"] = rep["results"]
        failed = {x["key"] for x in rep["results"] if not x["ok"]}
        for x in rep["results"]:
            if not x["ok"]:
                out["alerts"].append(f"{x['unit']}/{x['thermostat']}: set failed: {x['error']}")
        if failed:   # never record, or tell a guest about, a change that didn't happen
            out["note_tags"] = [t for t in out["note_tags"] if t["key"] not in failed]
            bad_units = {x["unit"] for x in rep["results"] if not x["ok"] and x["kind"] == "guest"}
            out["messages"] = [m for m in out["messages"] if m["unit"] not in bad_units]
            if bad_units:
                out["alerts"].append(f"guest message withheld for: {', '.join(sorted(bad_units))}; "
                                     "successful changes there will be announced next run")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
