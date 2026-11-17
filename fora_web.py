#!/usr/bin/env python3
"""
fora_web.py - Interfaccia web locale per multiviewer FOR-A MV-1600HS.

Avvia un piccolo server HTTP (solo libreria standard) che parla con la matrice
via TCP (fora_mv.py) e serve la pagina fora_web.html.

  python3 fora_web.py                      # poi apri http://127.0.0.1:8080
  python3 fora_web.py --mv <IP> --lan-id <ID> --lan-password <PASSWORD>
  python3 fora_web.py --bind 0.0.0.0       # raggiungibile da altri PC della rete

I parametri di connessione usati con successo vengono salvati in fora_web.json
(password compresa, in chiaro).
"""

import argparse
import json
import signal
import os
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # il Python "embeddable" di Windows non aggiunge la cartella dello script

from fora_mv import MvClient, TcpTransport, decode, RESOLUTIONS, INPUT_FORMATS  # noqa: E402
import fora_settings  # noqa: E402
CONFIG = os.path.join(HERE, "fora_web.json")
PAGE = os.path.join(HERE, "fora_web.html")

CLOCK = 80
KEEPALIVE = 4.0     # s di silenzio prima di un RFA (MV-1610HS misurata: chiude dopo ~15 s)
PAGE_IDLE = 180.0   # s senza pagine aperte: la porta viene rilasciata (server dimenticato acceso)
POS = ["x", "y", "w", "h", "tx", "ty", "mlx", "mly", "mrx", "mry"]


# ---------------------------------------------------------------------------
# Formato finestre (SLD / ALD)
# ---------------------------------------------------------------------------

def parse_ald(resp):
    """'ALD0LLCC' + on(1) layer(2) 10x4 cifre meterW(1) meterH(2)."""
    p = resp[3:]
    d = p[5:]
    win = {"ch": int(p[3:5]), "on": d[0] == "1", "layer": int(d[1:3])}
    for i, k in enumerate(POS):
        win[k] = int(d[3 + i * 4:7 + i * 4])
    win["mw"], win["mh"] = int(d[43]), int(d[44:46])
    return win


def validate(win, res_w, res_h):
    """Stessi vincoli del manuale (sez. 3-8). Ritorna la lista degli errori."""
    if not win["on"]:
        return []
    e = []
    x, y, w, h = (win[k] for k in ("x", "y", "w", "h"))
    if not 1 <= win["layer"] <= 5:
        e.append("layer 1-5")
    if x % 2 or y % 2:
        e.append("posizione multipla di 2")
    if w % 8 or h % 8:
        e.append("dimensione multipla di 8")
    if not 120 <= w <= 1920 or not 80 <= h <= 1200:
        e.append("dimensione minima 120x80")
    if x > 1800 or y > 1120:
        e.append("posizione massima 1800,1120")
    if x < 0 or y < 0 or x + w > res_w or y + h > res_h:
        e.append(f"la finestra esce dallo schermo {res_w}x{res_h}")
    for k in POS[4:]:
        if win[k] % 2 or win[k] < 0:
            e.append(f"{k} pari e >= 0")
    if win["tx"] > res_w or win["ty"] > res_h:
        e.append("titolo fuori schermo")
    if win["ch"] != CLOCK:
        if not 1 <= win["mw"] <= 3 or not 1 <= win["mh"] <= 10:
            e.append("meter: larghezza 1-3, altezza 1-10")
        if max(win["mlx"], win["mrx"]) > res_w or max(win["mly"], win["mry"]) > res_h:
            e.append("meter fuori schermo")
    return e


def build_sld(layout, win):
    head = f"SLD0{layout:02d}{win['ch']:02d}"
    if not win["on"]:
        return head + "0" * 46  # (*1)(*2): tutto a zero quando OFF
    vals = [win[k] for k in POS]
    mw, mh = win["mw"], win["mh"]
    if win["ch"] == CLOCK:  # (*2): niente meter per l'orologio
        vals[6:10] = [0, 0, 0, 0]
        mw = mh = 0
    return head + "1" + f"{win['layer']:02d}" + "".join(f"{v:04d}" for v in vals) + f"{mw}{mh:02d}"


# ---------------------------------------------------------------------------
# Dispositivo
# ---------------------------------------------------------------------------

class Device:
    def __init__(self):
        self.client = None
        self.cfg = {"host": "", "port": 2010, "lan_id": "", "lan_password": ""}
        self.info = {}
        self.log = deque(maxlen=500)
        self.log_id = 0
        self.log_lock = threading.Lock()
        self.status_cache = (0.0, None)
        self.link = "down"        # "up" | "waiting" | "reconnecting" | "down"
        self.last_page = 0.0
        self.idle_cfg = None
        self.pending_cfg = {}
        self.link_err = ""
        self.last_cmd = 0.0
        threading.Thread(target=self._watchdog, daemon=True).start()
        if os.path.exists(CONFIG):
            try:
                self.cfg.update(json.load(open(CONFIG)))
            except (OSError, ValueError):
                pass

    # -- log ----------------------------------------------------------------
    def _log(self, kind, text):
        with self.log_lock:
            self.log_id += 1
            self.log.append({"id": self.log_id, "t": time.strftime("%H:%M:%S"),
                             "kind": kind, "text": text})

    def log_since(self, since):
        with self.log_lock:
            return [e for e in self.log if e["id"] > since]

    # -- connessione ----------------------------------------------------------
    @property
    def connected(self):
        return self.client is not None

    def connect(self, host, port=2010, lan_id="", lan_password=""):
        """Si connette. Se la porta e' occupata da un altro client non fallisce:
        resta in attesa (link "waiting") e _watchdog la prende appena si libera."""
        self.disconnect()
        # retry_for=0: un socket caduto fa fallire subito il comando;
        # i nuovi tentativi li fa _watchdog, senza bloccare le richieste HTTP
        t = TcpTransport(host, int(port), timeout=3.0, retry_for=0)
        c = MvClient(t, lan_id=lan_id or None, lan_password=lan_password or None, verbose=False)
        self.info = {}
        self.pending_cfg = {"host": host, "port": int(port), "lan_id": lan_id,
                            "lan_password": lan_password}
        try:
            t.connect()
        except ConnectionRefusedError:
            self.client = c
            self.last_page = time.monotonic()
            self.link = "waiting"
            self.link_err = "porta 2010 occupata da un altro client"
            self._log("info", f"{host}:{port} occupata da un altro client: attendo che si liberi")
            print(f"[{host}:{port} occupata da un altro client: attendo che si liberi]")
            return self.info
        self.client = c
        self.link, self.link_err = "up", ""
        self.last_page = time.monotonic()
        self._log("info", f"connesso a {host}:{port}")
        try:
            return self._init()
        except RuntimeError as e:
            if "timed out" not in str(e):
                raise
            # Con un altro client attivo la matrice puo' accettare la connessione TCP
            # senza mai rispondere: equivale a "porta occupata", si resta in attesa.
            with c.lock:
                c.t.close(wait=0.2)
            self.link = "waiting"
            self.link_err = "la matrice non risponde: porta occupata da un altro client?"
            self._log("info", self.link_err)
            return self.info

    def _init(self):
        """Prima lettura dopo la connessione: versione, ingressi, titoli."""
        resp = self.cmd("RVS000")
        if resp.startswith("ERR001"):
            self.disconnect()
            raise RuntimeError("la matrice non riconosce i comandi: ID o password LAN errati?")
        if resp.startswith("ERR002"):
            resp = self.cmd("RVS")
        n = 0
        for ch in range(1, 17):
            r = self.cmd(f"RIF{ch:02d}")
            if r.startswith("ERR"):
                break
            n = ch
        titles = {}
        for ch in range(1, n + 1):
            r = self.cmd(f"RTT000{ch:02d}")
            titles[ch] = r[12:] if r.startswith("ATT") else ""
        layouts = 0  # MV-410HS: 4, MV-1610HS: 16
        for lay in range(1, 33):
            if not self.cmd(f"RLO0{lay:02d}").startswith("ALO"):
                break
            layouts = lay
        self.info = {"version": decode(resp), "channels": n, "layouts": layouts or 4, "titles": titles}
        self.cfg = self.pending_cfg
        try:
            json.dump(self.cfg, open(CONFIG, "w"), indent=2)
        except OSError:
            pass
        return self.info

    def disconnect(self, reason=""):
        """Chiude la connessione e rilascia la porta della matrice.
        Ritorna True se la matrice ha confermato la chiusura."""
        c, self.client = self.client, None
        self.link = "down"
        self.status_cache = (0.0, None)
        if not c:
            return None
        c.closed = True  # da qui nessun comando in coda puo' riaprire la connessione
        got = c.lock.acquire(timeout=5)  # aspetta l'eventuale comando in corso
        try:
            released = c.close()
        finally:
            if got:
                c.lock.release()
        msg = "disconnesso: porta rilasciata" if released else "disconnesso (chiusura non confermata dalla matrice)"
        self._log("info", f"{msg}{' - ' + reason if reason else ''}")
        print(f"[{msg}{' - ' + reason if reason else ''}]", flush=True)
        return released

    def page_seen(self):
        """Chiamata a ogni interrogazione della pagina."""
        self.last_page = time.monotonic()
        cfg, self.idle_cfg = self.idle_cfg, None
        if cfg and not self.client:  # porta rilasciata per inattivita': la pagina e' tornata
            self._log("info", "pagina di nuovo aperta: riconnessione")
            threading.Thread(target=self._reconnect_idle, args=(cfg,), daemon=True).start()

    def _reconnect_idle(self, cfg):
        try:
            self.connect(cfg["host"], cfg["port"], cfg["lan_id"], cfg["lan_password"])
        except Exception as e:
            self._log("err", f"riconnessione fallita: {e}")

    def cmd(self, c, log=True):
        client = self.client
        if not client:
            raise RuntimeError("non connesso")
        if self.link != "up":
            raise RuntimeError(f"matrice non disponibile: {self.link_err}")
        try:
            resp = client.send(c, quiet=True)
        except Exception as e:
            if self.client is client:
                self.link, self.link_err = "reconnecting", str(e)
            self._log("err", f"{c} -> {type(e).__name__}: {e}")
            raise RuntimeError(f"{c}: {e}")
        self.last_cmd = time.monotonic()
        if log or resp.startswith("ERR"):
            self._log("err" if resp.startswith("ERR") else "io", f"{c} -> {resp}")
        return resp

    def _watchdog(self):
        """Tiene viva la connessione (la matrice chiude dopo ~15 s di silenzio) e,
        se cade o la porta e' occupata da un altro client, riprova finche' serve."""
        while True:
            time.sleep(0.5)
            c = self.client
            if not c:
                continue
            if time.monotonic() - self.last_page > PAGE_IDLE:
                self.idle_cfg = self.pending_cfg
                self.disconnect(f"nessuna pagina aperta da {PAGE_IDLE / 60:.0f} minuti")
                continue
            if self.link in ("reconnecting", "waiting"):
                try:
                    with c.lock:
                        if self.client is not c:
                            continue
                        c.t.connect(retry_for=0)
                    self.link, self.link_err = "up", ""
                    self.status_cache = (0.0, None)
                    self._log("info", "connesso" if not self.info else "riconnesso")
                    if not self.info:
                        try:
                            self._init()
                        except RuntimeError as e:
                            if "timed out" not in str(e):
                                raise
                            with c.lock:
                                c.t.close(wait=0.2)
                            self.link = "waiting"
                            self.link_err = "la matrice non risponde: porta occupata da un altro client?"
                            time.sleep(3)
                except ConnectionRefusedError:
                    self.link_err = "porta 2010 occupata da un altro client"
                    time.sleep(1.5)
                except OSError as e:
                    self.link_err = str(e)
                    time.sleep(1.5)
                except RuntimeError as e:   # es. password errata: _init ha gia' disconnesso
                    self._log("err", str(e))
            elif time.monotonic() - self.last_cmd > KEEPALIVE:
                try:
                    self.cmd("RFA", log=False)
                except RuntimeError:
                    pass

    # -- operazioni ------------------------------------------------------------
    def status(self):
        """Stato uscita e ingressi; in cache 1 s (la pagina interroga ogni 2 s,
        il che fa anche da keepalive per il timeout di 5 s della matrice)."""
        t, cached = self.status_cache
        if cached and time.monotonic() - t < 1.0:
            return cached
        r = self.cmd("RDP0")
        out = {"menu": r[4] == "2", "full": r[5] == "0", "sel": int(r[6:8])} if r.startswith("ADP") else None
        inputs = []
        for ch in range(1, self.info.get("channels", 0) + 1):
            r = self.cmd(f"RIF{ch:02d}")
            code = r[5:7] if r.startswith("AIF") else "??"
            inputs.append({"ch": ch, "code": code, "fmt": INPUT_FORMATS.get(code, r),
                           "loss": code == "80", "title": self.info["titles"].get(ch, "")})
        st = {"output": out, "inputs": inputs}
        self.status_cache = (time.monotonic(), st)
        return st

    def layout(self, n):
        r = self.cmd(f"RLO0{n:02d}")
        code = r[6:8] if r.startswith("ALO") else "06"  # ALO + 0 + layout(2) + risoluzione(2)
        w, h = (int(v) for v in RESOLUTIONS.get(code, "1920x1080").split("x"))
        modes = self.display_modes(n)
        wins = []
        for ch in list(range(1, self.info["channels"] + 1)) + [CLOCK]:
            r = self.cmd(f"RLD0{n:02d}{ch:02d}")
            if not r.startswith("ALD"):
                continue
            win = parse_ald(r)
            t = self.cmd(f"RTT0{n:02d}{ch:02d}")
            win["title"] = t[12:] if t.startswith("ATT") else ""
            win["mode"] = modes(ch)
            wins.append(win)
        return {"layout": n, "res": {"code": code, "w": w, "h": h}, "windows": wins}

    def display_modes(self, n):
        """Modo di visualizzazione per finestra (0 Mode1, 1 Mode2: proporzioni mantenute;
        2 Mode3: immagine stirata). Il layout usa il modo globale (RAM00) o, se
        l'interruttore SAS e' su Individual, quello per finestra (RAM0LLCC, formato
        del software originale: se la matrice non lo accetta si usa il globale)."""
        r = self.cmd("RAM00")
        glob = int(r[5]) if r.startswith("AAM") and r[5:6].isdigit() else 0
        sw = self.cmd(f"RAS0{n:02d}")
        if not sw.startswith("AAS") or sw[6:7] != "0":   # 1 = Global
            return lambda ch: glob

        def per_window(ch):
            q = f"RAM0{n:02d}{ch:02d}"
            a = self.cmd(q)
            return int(a[len(q)]) if a.startswith("AAM") and a[len(q):len(q) + 1].isdigit() else glob
        return per_window

    def set_window(self, n, win, res_w, res_h):
        errs = validate(win, res_w, res_h)
        if errs:
            return {"ok": False, "error": "; ".join(errs)}
        resp = self.cmd(build_sld(n, win))
        if resp != "OK":
            return {"ok": False, "error": decode(resp)}
        back = parse_ald(self.cmd(f"RLD0{n:02d}{win['ch']:02d}"))
        back["title"] = win.get("title", "")
        return {"ok": True, "window": back}


DEV = Device()


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _route(self, method):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        q = parse_qs(url.query)
        try:
            if method == "GET" and url.path in ("/", "/index.html"):
                body = open(PAGE, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parts[:1] != ["api"]:
                return self._json({"error": "not found"}, 404)
            api = parts[1:]
            since = int(q.get("since", ["0"])[0])

            if method == "GET" and api == ["state"]:
                DEV.page_seen()
                st = {"connected": DEV.connected, "link": DEV.link, "link_err": DEV.link_err,
                      "cfg": DEV.cfg, "info": DEV.info}
                if DEV.connected:
                    try:
                        st.update(DEV.status())
                    except RuntimeError as e:
                        st["error"] = str(e)
                st["log"] = DEV.log_since(since)
                return self._json(st)
            if method == "POST" and api == ["connect"]:
                b = self._body()
                info = DEV.connect(b["host"], b.get("port", 2010), b.get("lan_id", ""),
                                   b.get("lan_password", ""))
                return self._json({"ok": True, "info": info})
            if method == "POST" and api == ["disconnect"]:
                DEV.idle_cfg = None
                return self._json({"ok": True, "released": DEV.disconnect("richiesta dalla pagina")})
            if not DEV.connected:
                return self._json({"error": "non connesso"}, 409)
            if method == "GET" and len(api) == 2 and api[0] == "layout":
                return self._json(DEV.layout(int(api[1])))
            if method == "POST" and len(api) == 3 and api[0] == "layout" and api[2] == "window":
                b = self._body()
                return self._json(DEV.set_window(int(api[1]), b["window"], b["res_w"], b["res_h"]))
            if method == "POST" and len(api) == 3 and api[0] == "layout" and api[2] == "save":
                r = DEV.cmd(f"SLS0{int(api[1]):02d}")
                return self._json({"ok": r == "OK", "error": decode(r)})
            if method == "POST" and api == ["show"]:
                b = self._body()
                c = "SDF" if b["kind"] == "full" else "SDS"
                r = DEV.cmd(f"{c}0{int(b['n']):02d}")
                DEV.status_cache = (0.0, None)
                return self._json({"ok": r == "OK", "error": decode(r)})
            if method == "GET" and api == ["settings", "schema"]:
                return self._json(fora_settings.schema())
            if method == "GET" and api[:2] == ["settings", "system"]:
                return self._json(fora_settings.read_section(DEV.cmd, "system", DEV.info["channels"]))
            if method == "GET" and len(api) == 3 and api[:2] == ["settings", "layout"]:
                return self._json(fora_settings.read_section(DEV.cmd, "layout", DEV.info["channels"],
                                                             int(api[2])))
            if method == "POST" and api == ["settings"]:
                b = self._body()
                return self._json(fora_settings.write(DEV.cmd, b["group"], b["read"], b["changes"]))
            if method == "POST" and api == ["raw"]:
                c = self._body()["cmd"].strip()
                r = DEV.cmd(c[:3].upper() + c[3:])
                return self._json({"ok": True, "resp": r, "decoded": decode(r)})
            return self._json({"error": "not found"}, 404)
        except (RuntimeError, OSError, ValueError, KeyError) as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")


_win_handler = None  # riferimento da tenere vivo (ctypes)


def install_windows_close_handler():
    """Windows: chiudendo la finestra della console (X), disconnettendosi o spegnendo,
    il processo viene terminato senza passare da KeyboardInterrupt. Questo gestore
    rilascia prima la porta della matrice."""
    global _win_handler
    import ctypes
    proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

    def on_event(event):  # 0 Ctrl+C, 1 Ctrl+Break, 2 chiusura, 5 logoff, 6 spegnimento
        if event in (2, 5, 6):
            DEV.disconnect("chiusura della finestra")
        return 0  # prosegue con il comportamento normale

    _win_handler = proto(on_event)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_handler, True)


def main():
    ap = argparse.ArgumentParser(description="Interfaccia web per FOR-A MV-1600HS")
    ap.add_argument("--bind", default="127.0.0.1", help="indirizzo di ascolto (default solo locale)")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--open", action="store_true", help="apre il browser all'avvio")
    ap.add_argument("--mv", help="IP della matrice: si connette all'avvio")
    ap.add_argument("--port", type=int, default=2010)
    ap.add_argument("--lan-id", default="")
    ap.add_argument("--lan-password", default="")
    a = ap.parse_args()
    if a.mv:
        try:
            info = DEV.connect(a.mv, a.port, a.lan_id, a.lan_password)
            if info:
                print(f"Connesso a {a.mv}: {info['version']}, {info['channels']} ingressi")
        except Exception as e:
            print(f"Connessione a {a.mv} fallita: {e}")
    def stop(signum, frame):
        raise KeyboardInterrupt
    for sig in (signal.SIGTERM, getattr(signal, "SIGHUP", None), getattr(signal, "SIGBREAK", None)):
        if sig:
            signal.signal(sig, stop)
    if os.name == "nt":
        install_windows_close_handler()
    # se la porta HTTP e' gia' in uso (es. seconda copia aperta) prova le successive
    for port in range(a.http_port, a.http_port + 10):
        try:
            srv = ThreadingHTTPServer((a.bind, port), Handler)
            break
        except OSError:
            continue
    else:
        sys.exit(f"Nessuna porta HTTP libera tra {a.http_port} e {a.http_port + 9}")
    url = f"http://{'127.0.0.1' if a.bind == '0.0.0.0' else a.bind}:{port}"
    print(f"Interfaccia su {url}")
    print("Per chiudere: Ctrl+C oppure chiudi questa finestra.")
    if a.open:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        DEV.disconnect()


if __name__ == "__main__":
    main()
