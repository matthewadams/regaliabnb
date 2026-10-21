#!/usr/bin/env python3
"""Sensi thermostat access: sign in, read every thermostat, set mode/temperature.

Talks to Sensi's own cloud through the same unofficial endpoints the Sensi app,
manager.sensicomfort.com and the iprak/sensi Home Assistant integration use.
No paid API, and no browser is driven either -- but none of this is a supported
Sensi API, so it can break whenever Sensi changes its app. Used directly (CLI
below) and imported by sensi_hvac.py.

Refresh token (the 10-year JWT stored as localStorage "refreshToken" at
manager.sensicomfort.com): --token, else env SENSI_REFRESH_TOKEN, else the last one
given on this machine (~/.config/sensi). Access tokens (~4h) are cached there too.

Usage:
  status [--match TEXT] [--raw]          every thermostat on the account (JSON)
  set --thermostat NAME_OR_ID --mode heat|cool|off|auto [--temp N]
                                         heat/cool need --temp; off/auto keep setpoints
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# --- Sensi endpoints (from iprak/sensi auth.py / client.py, v2.2.3) ----------
OAUTH_URL = "https://oauth.sensiapi.io/token"
OAUTH_CLIENT_ID = "fleet"
OAUTH_CLIENT_SECRET = "JLFjJmketRhj>M9uoDhusYKyi?zUyNqhGB)H2XiwLEF#KcGKrRD2JZsDQ7ufNven"
SOCKET_URL = "https://rt.sensiapi.io"
SOCKET_QUERY = (
    "?capabilities=display_humidity,operating_mode_settings,fan_mode_settings,"
    "indoor_equipment,outdoor_equipment,indoor_stages,outdoor_stages,"
    "continuous_backlight,degrees_fc,display_time,keypad_lockout,temp_offset,"
    "compressor_lockout,boost,min_heat_setpoint,max_heat_setpoint,"
    "min_cool_setpoint,max_cool_setpoint,lowest_heat_setpoint_ceiling,"
    "heat_setpoint_ceiling,highest_cool_setpoint_floor,cool_setpoint_floor"
)
UA = "regalia-hvac-automation (matthew@matthewadams.me)"


class AuthError(Exception):
    pass


# ============================================================================
# Sensi auth: the refresh token from manager.sensicomfort.com (localStorage
# "refreshToken") is a 10-year JWT that Sensi does not rotate; it is traded for a
# ~4-hour access token, which is cached and reused until it nears expiry.
# ============================================================================
CACHE_DIR = os.path.expanduser(os.environ.get("SENSI_CACHE_DIR", "~/.config/sensi"))


def _cache(name: str, value: str | None = None) -> str | None:
    """Tiny file cache in ~/.config/sensi (mode 600). Read when value is None."""
    path = os.path.join(CACHE_DIR, name)
    if value is None:
        try:
            with open(path) as f:
                return f.read().strip() or None
        except OSError:
            return None
    try:
        os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(value)
    except OSError:
        pass
    return value


def resolve_refresh_token(given: str | None) -> str | None:
    """Token passed in (and remembered), else the last one remembered on this machine."""
    if given:
        _cache("refresh_token", given)
        return given
    return _cache("refresh_token")


def get_access_token(refresh_token: str | None) -> str:
    """Access token for Sensi's realtime API. Reuses a cached one (they last ~4h) for the
    same refresh token; otherwise trades the refresh token for a new one and caches it."""
    refresh_token = resolve_refresh_token(refresh_token)
    if not refresh_token:
        raise AuthError("No Sensi refresh token supplied or remembered")
    try:
        cached = json.loads(_cache("access.json") or "{}")
    except ValueError:
        cached = {}
    import time
    if cached.get("for") == refresh_token[-16:] and cached.get("expires_at", 0) - time.time() > 600:
        return cached["access_token"]
    body = urllib.parse.urlencode({
        "client_id": OAUTH_CLIENT_ID,
        "client_secret": OAUTH_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode()
    req = urllib.request.Request(OAUTH_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "accept": "*/*", "accept-language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            js = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            raise AuthError(f"Sensi rejected the refresh token (HTTP {e.code}). Log in at "
                            "manager.sensicomfort.com and copy localStorage 'refreshToken' "
                            "into the scheduled task.") from e
        raise
    if js.get("refresh_token") and js["refresh_token"] != refresh_token:
        _cache("refresh_token", js["refresh_token"])       # remember a rotated token, if Sensi ever rotates
    _cache("access.json", json.dumps({"for": (js.get("refresh_token") or refresh_token)[-16:],
                                      "access_token": js["access_token"],
                                      "expires_at": time.time() + int(js.get("expires_in") or 3600)}))
    return js["access_token"]



# ============================================================================
# Sensi realtime (socket.io) client
# ============================================================================
class Sensi:
    def __init__(self, access_token: str):
        try:
            import socketio  # python-socketio[asyncio_client]
        except ImportError:  # installed lazily: only runs that must reach Sensi pay for it
            import subprocess
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages",
                            "python-socketio[asyncio_client]==5.16.3"], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import socketio
        self.sio = socketio.AsyncClient(reconnection=False)
        self.token = access_token
        self.devices: dict[str, dict] = {}
        self.connect_error = None
        self._got_state = asyncio.Event()

        @self.sio.on("state")
        async def _state(data):
            for item in data or []:
                icd = item.get("icd_id")
                if not icd:
                    continue
                d = self.devices.setdefault(icd, {})
                for k in ("registration", "capabilities", "state", "thermostat_info"):
                    if item.get(k):
                        if isinstance(item[k], dict) and isinstance(d.get(k), dict):
                            d[k].update(item[k])
                        else:
                            d[k] = item[k]
            if self.devices and all("state" in d and d["state"].get("operating_mode")
                                    for d in self.devices.values()):
                self._got_state.set()

        @self.sio.on("connect_error")
        async def _err(data):
            self.connect_error = data

    async def __aenter__(self):
        await self.sio.connect(SOCKET_URL + SOCKET_QUERY,
                               headers={"Authorization": "bearer " + self.token},
                               socketio_path="/thermostat", transports=["websocket"],
                               wait_timeout=20)
        try:
            await asyncio.wait_for(self._got_state.wait(), 25)
        except asyncio.TimeoutError:
            pass  # partial data; callers see missing state as offline
        return self

    async def __aexit__(self, *a):
        try:
            await asyncio.wait_for(self.sio.disconnect(), 10)
        except Exception:
            pass

    async def _call(self, event: str, payload: dict, timeout: float = 15):
        fut = asyncio.get_running_loop().create_future()

        def cb(*args):
            if fut.done():
                return
            if not args:
                fut.set_result((None, {}))
            elif len(args) >= 2:
                fut.set_result((args[0], args[1]))
            elif isinstance(args[0], dict) and "error" in args[0]:
                fut.set_result((args[0], None))
            else:
                fut.set_result((None, args[0]))

        await self.sio.emit(event, payload, callback=cb)
        try:
            err, data = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return f"timeout waiting for {event}", None
        if err:
            desc = err.get("error", {}).get("description") if isinstance(err, dict) else str(err)
            return desc or str(err), None
        return None, data

    async def set_mode(self, icd: str, mode: str):
        err, data = await self._call("set_operating_mode", {"icd_id": icd, "value": mode})
        if err is None and isinstance(data, str) and data != "accepted":
            err = data
        return err

    async def set_temp(self, icd: str, mode: str, temp: int, scale: str = "f"):
        err, _ = await self._call("set_temperature", {"icd_id": icd, "scale": scale,
                                                      "mode": mode, "target_temp": temp})
        return err


def summarize_device(icd: str, d: dict) -> dict:
    st, cap, reg = d.get("state", {}), d.get("capabilities", {}), d.get("registration", {})

    def num(x):
        try:
            return float(x) if x is not None else None
        except (TypeError, ValueError):
            return None
    return {
        "icd_id": icd,
        "name": reg.get("name") or icd,
        "product_type": reg.get("product_type"),
        "address": " ".join(str(reg.get(k) or "") for k in ("address1", "address2", "city")).strip(),
        "online": str(st.get("status", "")).lower() == "online",
        "mode": st.get("operating_mode"),
        "indoor_temp": num(st.get("display_temp")),
        "humidity": num(st.get("humidity")),
        "heat_setpoint": num(st.get("current_heat_temp")),
        "cool_setpoint": num(st.get("current_cool_temp")),
        "heat_ceiling": num(st.get("heat_max_temp")),   # guest can't heat above this
        "cool_floor": num(st.get("cool_min_temp")),     # guest can't cool below this
        "scale": (st.get("display_scale") or "f").lower(),
        "hw_heat_range": [cap.get("min_heat_setpoint"), cap.get("max_heat_setpoint")],
        "hw_cool_range": [cap.get("min_cool_setpoint"), cap.get("max_cool_setpoint")],
        "modes_supported": [k for k, v in (cap.get("operating_mode_settings") or {}).items() if v == "yes"],
        "keypad_lockout": st.get("partial_keypad_lockout") or st.get("keypad_lockout"),
        "scheduling": st.get("scheduling"),
    }


async def sensi_status(access_token: str, raw: bool = False) -> list[dict]:
    async with Sensi(access_token) as c:
        devs = c.devices
    out = [summarize_device(i, d) for i, d in devs.items()]
    if raw:
        for o in out:
            o["raw"] = devs[o["icd_id"]]
    return out


async def _write(conn, t_id: str, cur_mode: str, mode: str, sp: int, scale: str):
    err = None
    if cur_mode != mode:
        err = await conn.set_mode(t_id, mode)
        await asyncio.sleep(1.5)
    if not err:
        err = await conn.set_temp(t_id, mode, int(sp), scale)
    return err


def _pick(devices: list[dict], ref: str) -> dict:
    exact = [d for d in devices if d["icd_id"] == ref or d["name"].lower() == ref.lower()]
    if exact:
        return exact[0]
    loose = [d for d in devices if ref.lower() in d["name"].lower()]
    if len(loose) == 1:
        return loose[0]
    names = ", ".join(d["name"] for d in devices)
    raise SystemExit(f"thermostat '{ref}' is {'ambiguous' if loose else 'not found'}; choose one of: {names}")


async def set_one(access_token: str, ref: str, mode: str, temp: int | None) -> dict:
    async with Sensi(access_token) as c:
        devices = [summarize_device(i, d) for i, d in c.devices.items()]
        t = _pick(devices, ref)
        if not t["online"]:
            return {"thermostat": t["name"], "ok": False, "error": "thermostat offline"}
        before = {k: t[k] for k in ("mode", "heat_setpoint", "cool_setpoint", "indoor_temp")}
        if mode in ("heat", "cool"):
            if temp is None:
                raise SystemExit("--temp is required for heat/cool")
            err = await _write(c, t["icd_id"], t["mode"], mode, temp, t["scale"])
        else:
            err = None if t["mode"] == mode else await c.set_mode(t["icd_id"], mode)
    return {"thermostat": t["name"], "before": before, "set": {"mode": mode, "temp": temp},
            "ok": err is None, "error": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default=os.environ.get("SENSI_REFRESH_TOKEN"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--match"); s.add_argument("--raw", action="store_true")
    w = sub.add_parser("set")
    w.add_argument("--thermostat", required=True)
    w.add_argument("--mode", required=True, choices=["heat", "cool", "off", "auto"])
    w.add_argument("--temp", type=int)
    a = ap.parse_args()
    try:
        tok = get_access_token(a.token)
        if a.cmd == "status":
            out = asyncio.run(sensi_status(tok, a.raw))
            if a.match:
                out = [d for d in out if a.match.lower() in d["name"].lower()]
        else:
            out = asyncio.run(set_one(tok, a.thermostat, a.mode, a.temp))
    except AuthError as e:
        out = {"fatal": True, "alerts": [f"SENSI AUTH: {e}"]}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
