#!/usr/bin/env python3
"""
mv_sim.py - Simulatore di multiviewer FOR-A (protocollo MV-410HS / MV-1600HS).

Serve a provare fora_mv.py senza l'apparato:
  python3 mv_sim.py --port 2010 --lan-id ADMIN --lan-password 12345
  python3 fora_mv.py --host 127.0.0.1

Comportamento riprodotto dal manuale:
  - una sola connessione TCP alla volta (le altre: connection refused)
  - socket chiuso dopo 15 s di inattivita' (misurato; il manuale dice 5 s)
  - porta rifiutata per ~1 s dopo ogni chiusura
  - OK / ERRnnn / risposte Axx
"""

import argparse
import socket
import time

IDLE_TIMEOUT = 15.0  # misurato sull MV-1610HS (il manuale dice 5 s)


class State:
    def __init__(self, channels):
        self.channels = channels
        self.full = False
        self.selected = 1
        self.fr, self.jpeg = "0", "1"
        self.freq = "0"
        self.mode = "0"
        # risoluzioni lette dalla MV-1610HS di prova (16 layout)
        self.layout_res = dict(zip(range(1, 17), ["06", "03", "03", "03", "03", "03", "03", "03",
                                                  "00", "01", "02", "03", "04", "05", "06", "07"]))
        self.video_loss = {c: "1" for c in range(1, channels + 1)}
        self.clock_offset = 0.0
        self.titles = {c: f"CHANNEL {c}" for c in range(1, channels + 1)}
        self.titles[80] = "CLOCK"
        # finestre: layout -> canale -> stringa di 46 cifre (formato SLD/ALD da "on" in poi)
        self.windows = {n: self._grid(channels, n, *RES[self.layout_res[n]]) for n in range(1, 17)}

    @staticmethod
    def _grid(channels, layout, rw, rh):
        """Layout iniziale: griglia di finestre 16:9 (4 colonne, 3 righe), clock spento."""
        res = {}
        cols = 4 if layout != 2 else 3
        w = rw // cols // 8 * 8
        h = min(w * 9 // 16, rh // 3) // 8 * 8
        for c in range(1, channels + 1):
            x, y = (c - 1) % cols * w, (c - 1) // cols * h
            on = "1" if (layout != 3 or c <= 4) else "0"
            res[c] = (on + "01" + f"{x:04d}{y:04d}{w:04d}{h:04d}" + f"{x + 8:04d}{y + h - 40:04d}"
                      + f"{x + 8:04d}{y + 8:04d}{x + w - 24:04d}{y + 8:04d}" + "101")
            if on == "0":
                res[c] = "0" * 46
        res[80] = "0" * 46
        return res


# lunghezza parametri delle letture (manuale MV-410HS; RVS a 3 cifre come sull'MV-1600HS)
R_LEN = {"RVS": 3, "RIF": 2, "RDP": 1, "RFA": 0, "RNR": 0, "ROF": 1, "RAM": 2, "RLO": 3,
         "RLD": 5, "RRG": 2, "RAC": 5, "RAD": 0, "RTT": 5, "RBD": 5, "RFL": 1, "RTL": 2,
         "RVO": 2, "RVL": 0, "RDC": 0, "RDD": 1, "RDT": 0}


RES = {"00": (1280, 1024), "01": (1360, 768), "02": (1600, 1200), "03": (1920, 1200),
       "04": (1440, 900), "05": (1680, 1050), "06": (1920, 1080), "07": (1280, 720)}


def _check_sld(st, lay, ch, d):
    """Validazione SLD come da manuale (ERR003 se fuori range)."""
    on, layer = d[0], int(d[1:3])
    v = [int(d[3 + i * 4:7 + i * 4]) for i in range(10)]
    mw, mh = int(d[43]), int(d[44:46])
    if on == "0":
        return d == "0" * 46
    x, y, w, h = v[0:4]
    rw, rh = RES[st.layout_res[lay]]
    if not 1 <= layer <= 5 or x > 1800 or y > 1120 or not 120 <= w <= 1920 or not 80 <= h <= 1200:
        return False
    if any(n % 2 for n in v[0:2] + v[4:10]) or w % 8 or h % 8:
        return False
    if x + w > rw or y + h > rh:
        return False
    if ch == 80:
        return v[6:10] == [0, 0, 0, 0] and mw == 0 and mh == 0
    return 1 <= mw <= 3 and 1 <= mh <= 10


REPLAY = {}           # risposte reali caricate da uno snapshot (--replay)
REPLAY_SKIP = {"RLD", "SLD", "RDP", "SDS", "SDF", "SLS"}  # gestiti dallo stato del simulatore


def replay(cmd):
    """Con --replay: R?? risponde come la matrice reale, S?? aggiorna la risposta del
    corrispondente R?? (stessi parametri, stessa lunghezza)."""
    code = cmd[:3]
    if code in REPLAY_SKIP or not REPLAY:
        return None
    if code[0] == "R":
        return REPLAY.get(cmd)
    if code[0] == "S":
        from fora_mv import R_PARAM_LEN
        rc = "R" + code[1:]
        n = R_PARAM_LEN.get(rc)
        if n is None:
            return None
        key = rc + cmd[3:3 + n]
        old = REPLAY.get(key)
        if old is None:
            return None
        new = "A" + cmd[1:]
        if len(new) != len(old) and rc != "RTT":
            return "ERR002"
        REPLAY[key] = new
        return "OK"
    return None


def handle(st: State, cmd: str) -> str:
    r = replay(cmd)
    if r is not None:
        return r
    code, p = cmd[:3], cmd[3:]
    if code in R_LEN and len(p) != R_LEN[code]:
        return "ERR002"
    if code in ("RLD", "SLD", "RTT", "STT"):
        if len(p) < 5 or p[0] != "0" or not p[1:5].isdigit():
            return "ERR003"
        lay, ch = int(p[1:3]), int(p[3:5])
        if not (1 <= lay <= 16 or (code in ("RTT", "STT") and lay == 0)):
            return "ERR003"
        if ch != 80 and not 1 <= ch <= st.channels:
            return "ERR003"
        if code == "RLD":
            return f"ALD{p}{st.windows[lay][ch]}"
        if code == "SLD":
            d = p[5:]
            if len(d) != 46:
                return "ERR002"
            if not d.isdigit() or not _check_sld(st, lay, ch, d):
                return "ERR003"
            st.windows[lay][ch] = d
            return "OK"
        if code == "RTT":
            return f"ATT{p}1200{st.titles[ch]}"
        if code == "STT":
            st.titles[ch] = p[9:]
            return "OK"
    if code == "SLS":
        return "OK" if len(p) == 3 else "ERR002"
    if code in ("RAC", "RBD"):
        if p[0] != "0" or not p[1:3].isdigit() or not 0 <= int(p[1:3]) <= 16:
            return "ERR003"
        return "OK"  # risposta reale non simulata

    def ch_ok(s):
        return s.isdigit() and 1 <= int(s) <= st.channels

    def lay_ok(s):
        return s.isdigit() and 1 <= int(s) <= 16

    # --- controllo ---
    if code == "SDF":
        if len(p) != 3:
            return "ERR002"
        if not ch_ok(p[1:3]):
            return "ERR003"
        st.full, st.selected = True, int(p[1:3])
        return "OK"
    if code == "SDS":
        if len(p) != 3:
            return "ERR002"
        if not lay_ok(p[1:3]):
            return "ERR003"
        st.full, st.selected = False, int(p[1:3])
        return "OK"
    if code == "SNF":
        if len(p) != 1:
            return "ERR002"
        if p not in "0123456":
            return "ERR003"
        st.fr = p
        return "OK"
    if code == "SNJ":
        if len(p) != 1:
            return "ERR002"
        if p not in "0123":
            return "ERR003"
        st.jpeg = p
        return "OK"
    if code == "SOF":
        if len(p) != 2:
            return "ERR002"
        st.freq = p[1]
        return "OK"
    if code == "SAM":
        if len(p) != 3:
            return "ERR002"
        st.mode = p[2]
        return "OK"
    if code == "SVO":
        if len(p) != 3:
            return "ERR002"
        if not ch_ok(p[0:2]):
            return "ERR003"
        st.video_loss[int(p[0:2])] = p[2]
        return "OK"
    if code == "SDT":
        if len(p) != 12:
            return "ERR002"
        t = time.mktime(time.strptime(p, "%y%m%d%H%M%S"))
        st.clock_offset = t - time.time()
        return "OK"
    if code in ("SLO", "SLD", "SRG", "SLS", "SAC", "SAD", "STT", "SBD", "SFL",
                "STL", "SVL", "SVR", "SDC", "SDD"):
        return "OK"  # accettati senza simulare lo stato

    # --- richieste di stato ---
    if code == "RVS":
        return "AVS" + p + "0501" + "0000" * 4  # formato MV-1600HS
    if code == "RIF":
        if not ch_ok(p):
            return "ERR003"
        fmt = "01" if int(p) <= 4 else "80"  # come la macchina di prova
        return f"AIF{p}{fmt}"
    if code == "RDP":
        return f"ADP00{'0' if st.full else '1'}{st.selected:02d}"
    if code == "RFA":
        return "AFA0"
    if code == "RNR":
        return f"ANR{st.fr}{st.jpeg}"
    if code == "ROF":
        return f"AOF0{st.freq}"
    if code == "RAM":
        return f"AAM00{st.mode}"
    if code == "RLO":
        if len(p) != 3 or not lay_ok(p[1:3]):
            return "ERR003"
        return f"ALO0{p[1:3]}{st.layout_res[int(p[1:3])]}"
    if code == "RFL":
        return "AFL006"
    if code == "RAD":
        return "AAD200003" + "00000"
    if code == "RTL":
        return "ATL0010" + "00000"
    if code == "RVO":
        if not ch_ok(p):
            return "ERR003"
        return f"AVO{p}{st.video_loss[int(p)]}"
    if code == "RVL":
        return "AVL010" + "00000"
    if code == "RDC":
        return "ADC0"
    if code == "RDD":
        return "ADD0000" + "00000"
    if code == "RDT":
        return "ADT" + time.strftime("%y%m%d%H%M%S", time.localtime(time.time() + st.clock_offset))
    return "ERR001"


def _listen(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(1)
    return srv


def serve(port, channels, prefix="", release_delay=10.0):
    st = State(channels)
    print(f"[sim] in ascolto su :{port}, {channels} ingressi")
    while True:
        srv = _listen(port)
        conn, addr = srv.accept()
        # come la matrice: una sola connessione, le altre vengono rifiutate
        srv.close()
        print(f"[sim] connesso {addr}")
        conn.settimeout(IDLE_TIMEOUT)
        buf = b""
        try:
            while True:
                data = conn.recv(256)
                if not data:
                    break
                buf += data
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    buf = buf.lstrip(b"\n")
                    cmd = line.decode("ascii", errors="replace")
                    if prefix and not cmd.startswith(prefix):
                        resp = "ERR001"
                    else:
                        resp = handle(st, cmd[len(prefix):])
                    print(f"[sim] {cmd!r} -> {resp!r}")
                    conn.sendall(resp.encode("ascii") + b"\r\n")
        except socket.timeout:
            print("[sim] 5 s di inattivita', chiudo il socket")
        except OSError as e:
            print(f"[sim] errore: {e}")
        finally:
            conn.close()
        # come la matrice: la porta resta occupata per un po' (connection refused)
        print(f"[sim] porta occupata per {release_delay:g} s")
        time.sleep(release_delay)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=2010)
    ap.add_argument("--channels", type=int, default=10)
    ap.add_argument("--release-delay", type=float, default=1.0,
                    help="secondi di connection refused dopo ogni chiusura (MV-1610HS: ~1 s)")
    ap.add_argument("--replay", metavar="SNAPSHOT", help="risponde con i valori reali di uno snapshot")
    ap.add_argument("--lan-id", help="simula la password LAN (es. ADMIN)")
    ap.add_argument("--lan-password", default="00000")
    a = ap.parse_args()
    prefix = f"{len(a.lan_id)}{a.lan_id}{a.lan_password}" if a.lan_id else ""
    if a.replay:
        import json
        import os
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        REPLAY.update(json.load(open(a.replay))["responses"])
        print(f"[sim] {len(REPLAY)} risposte reali da {a.replay}")
    try:
        serve(a.port, a.channels, prefix, a.release_delay)
    except KeyboardInterrupt:
        pass
