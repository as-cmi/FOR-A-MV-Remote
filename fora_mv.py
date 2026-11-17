#!/usr/bin/env python3
"""
fora_mv.py - Client minimale per multiviewer FOR-A MV-410HS / MV-1600HS.

Protocollo (dal manuale "RS-232C/422/485/LAN COMMAND MV-410HS v2.0"):
  - ASCII, comando = codice 3 lettere + parametri + CR (+LF)
  - LAN: TCP porta 2010, una sola connessione, il socket viene chiuso
    dall'apparato dopo 5 s di inattivita' (MV-1610HS misurata: ~15 s)
  - Risposte: "OK", "ERRnnn", oppure "Axx..." per le richieste di stato "Rxx"
  - Non inviare il comando successivo prima di aver ricevuto la risposta

Uso:
  python3 fora_mv.py --host 192.168.0.1              # console interattiva
  python3 fora_mv.py --host 192.168.0.1 -c RVS        # singolo comando
  python3 fora_mv.py --host 192.168.0.1 --probe       # legge tutti gli stati
  python3 fora_mv.py --host 192.168.0.1 --discover    # quali comandi esistono?
  python3 fora_mv.py --host 192.168.0.1 --brute R     # prova tutti i codici R??
  python3 fora_mv.py --host 192.168.0.1 --snapshot prima.json   # fotografa tutti gli stati
  python3 fora_mv.py --diff prima.json dopo.json      # cosa e' cambiato tra due fotografie
  python3 fora_mv.py --serial /dev/ttyUSB0 --baud 38400   # RS-232C (richiede pyserial)
"""

import argparse
import json
import select
import socket
import sys
import threading
import time

EOLS = {"crlf": b"\r\n", "cr": b"\r", "lf": b"\n"}

ERRORS = {
    "001": "Command error",
    "002": "Command length error",
    "003": "Parameter range error",
    "004": "Apparato in modalita' MENU",
    "005": "Funzione non installata",
}

RESOLUTIONS = {
    "00": "1280x1024", "01": "1360x768", "02": "1600x1200", "03": "1920x1200",
    "04": "1440x900", "05": "1680x1050", "06": "1920x1080", "07": "1280x720",
}
# Tabella ricavata dal software di gestione originale; il manuale MV-410HS
# documenta solo 00-31 e 80. 40-43 e 50-59: segnali PC sulle schede d'ingresso 5-10.
INPUT_FORMATS = {
    "00": "1080/59.94i", "01": "1080/50i", "02": "1080/23.98PsF",
    "10": "720/59.94p", "11": "720/50p", "20": "525/60", "21": "625/50",
    "30": "NTSC", "31": "PAL",
    "40": "640x480", "41": "1024x768", "42": "1280x1024", "43": "1360x768",
    "50": "640x480", "51": "1024x768", "52": "1280x1024", "53": "1360x768", "54": "1600x1200",
    "55": "1920x1200", "56": "1440x900", "57": "1680x1050", "58": "1920x1080", "59": "1280x720",
    "80": "LOSS",
}
FRAME_RATES = {"0": "0fps (off)", "1": "1fps", "2": "5/4fps", "3": "10/8fps",
               "4": "15/12fps", "5": "30/25fps", "6": "60/50fps"}
JPEG_Q = {"0": "Low", "1": "Normal", "2": "Fine", "3": "Superfine"}
FREQS = {"0": "60Hz", "1": "59.94Hz", "2": "50Hz"}
COLORS = {"00": "WHITE", "01": "YELLOW", "02": "GREEN", "03": "CYAN", "04": "RED",
          "05": "MAGENTA", "06": "BLUE", "07": "GRAY", "08": "BLACK"}
ONOFF = {"0": "OFF", "1": "ON"}


def _ch(c):
    return "CLOCK" if c == "80" else f"CH{int(c)}" if c.isdigit() else c


def _scr(s):
    return "FULL" if s == "00" else f"LAYOUT{int(s)}" if s.isdigit() else s


# ---------------------------------------------------------------------------
# Decodifica risposte
# ---------------------------------------------------------------------------

def decode(resp: str) -> str:
    """Traduce una risposta grezza in testo leggibile (best effort)."""
    if resp == "OK":
        return "OK"
    if resp.startswith("ERR"):
        return f"ERRORE {resp[3:]}: {ERRORS.get(resp[3:6], 'sconosciuto')}"
    code, p = resp[:3], resp[3:]
    try:
        if code == "AVS":
            # MV-410HS: 4 campi da 4 cifre. MV-1600HS: eco del parametro (3) + 5 campi.
            head, body = ("", p) if len(p) == 16 else (p[:3], p[3:])
            v = [f"{body[i:i + 2]}.{body[i + 2:i + 4]}" for i in range(0, len(body) - 3, 4)]
            names = ["SW"] + [f"HW{i}" for i in range(1, len(v))]
            txt = "  ".join(f"{n} {x}" for n, x in zip(names, v))
            return f"Versione [{head}] {txt}" if head else f"Versione {txt}"
        if code == "AIF":
            return f"Ingresso {_ch(p[0:2])}: {INPUT_FORMATS.get(p[2:4], '?' + p[2:4])}"
        if code == "ADP":
            mode = {"0": "VIDEO", "2": "MENU"}.get(p[1], p[1])
            scr = "Full screen" if p[2] == "0" else "Split (layout)"
            sel = f"CH{int(p[3:5])}" if p[2] == "0" else f"LAYOUT{int(p[3:5])}"
            return f"Display: {mode}, {scr}, selezionato {sel}"
        if code == "AFA":
            return "Fan: ALLARME!" if p[0] == "1" else "Fan: OK"
        if code == "ANR":
            return f"Trasmissione video: {FRAME_RATES.get(p[0], p[0])}, JPEG {JPEG_Q.get(p[1], p[1])}"
        if code == "AOF":
            return f"Frequenza uscita: {FREQS.get(p[1], p[1])}"
        if code == "AAM":
            return f"Display mode: Mode{int(p[2]) + 1}"
        if code == "ALO":
            return f"{_scr(p[1:3])} risoluzione {RESOLUTIONS.get(p[3:5], p[3:5])}"
        if code == "AFL":
            return f"Full screen risoluzione {RESOLUTIONS.get(p[1:3], p[1:3])}"
        if code == "ALD":
            n = lambda a, b: int(p[a - 4:b - 3])  # posizioni byte come da manuale
            return (f"{_scr(p[1:3])} {_ch(p[3:5])} {ONOFF.get(p[5], p[5])} layer {p[6:8]} "
                    f"win x={n(12, 15)} y={n(16, 19)} w={n(20, 23)} h={n(24, 27)} "
                    f"title x={n(28, 31)} y={n(32, 35)}")
        if code == "ARG":
            return (f"Crop {_ch(p[0:2])}: T={int(p[2:6])} B={int(p[6:10])} "
                    f"L={int(p[10:14])} R={int(p[14:18])}")
        if code == "AAC":
            nch = {"0": "2CH", "1": "4CH", "2": "8CH"}.get(p[6], p[6])
            return f"Audio meter {_scr(p[1:3])} {_ch(p[3:5])}: {ONOFF.get(p[5], p[5])} {nch}"
        if code == "AAD":
            hold = "OFF" if p[4:6] == "00" else f"{int(p[4:6])}s"
            return f"Audio meter: ref -{int(p[0:2])}dBFS, peak {-int(p[2:4])}dBFS, hold {hold}"
        if code == "ATT":
            size = {"0": "S", "1": "M", "2": "L"}.get(p[6], p[6])
            return (f"Titolo {_scr(p[1:3])} {_ch(p[3:5])}: {ONOFF.get(p[5], p[5])} size {size} "
                    f"{COLORS.get(p[7:9], p[7:9])} '{p[9:]}'")
        if code == "ABD":
            return (f"Bordo {_scr(p[1:3])}: {ONOFF.get(p[5], p[5])} T={p[6:8]} B={p[8:10]} "
                    f"L={p[10:12]} R={p[12:14]} {COLORS.get(p[14:16], p[14:16])}")
        if code == "ATL":
            return f"Tally: {ONOFF.get(p[2], p[2])}, simultanei {'RED' if p[3] == '0' else 'AMBER'}"
        if code == "AVO":
            return f"Video loss {_ch(p[0:2])}: {ONOFF.get(p[2], p[2])}"
        if code == "AVL":
            t = int(p[0:3])
            return "Video loss display: fino a reset" if t == 0 else f"Video loss display: {t}s"
        if code == "ADC":
            return f"Clock ref: {'LTC' if p[0] == '1' else 'Interno'}"
        if code == "ADD":
            return f"Orologio: {'Digitale' if p[1] == '1' else 'Analogico'}, tipo {p[2:4]}"
        if code == "ADT":
            return f"Data/ora: 20{p[0:2]}-{p[2:4]}-{p[4:6]} {p[6:8]}:{p[8:10]}:{p[10:12]}"
    except (ValueError, IndexError):
        return f"(risposta non decodificabile) {resp}"
    return resp


# ---------------------------------------------------------------------------
# Trasporti
# ---------------------------------------------------------------------------

class TcpTransport:
    def __init__(self, host, port=2010, timeout=3.0, retry_for=20.0, on_retry=None):
        self.host, self.port, self.timeout = host, port, timeout
        # La matrice accetta una sola connessione: se un altro client e' collegato
        # rifiuta (ECONNREFUSED). In quel caso si riprova per retry_for secondi.
        self.retry_for = retry_for
        self.on_retry = on_retry or (lambda msg: print(f"[{msg}]"))
        self.sock = None

    def name(self):
        return f"tcp://{self.host}:{self.port}"

    def connect(self, retry_for=None):
        self.close()
        deadline = time.monotonic() + (self.retry_for if retry_for is None else retry_for)
        while True:
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                break
            except ConnectionRefusedError:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise ConnectionRefusedError(
                        111, "Connection refused: porta occupata (un altro client e' "
                             "connesso o la matrice non l'ha ancora liberata)")
                self.on_retry(f"porta occupata, riprovo (ancora {left:.0f} s)")
                time.sleep(min(1.0, left))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def is_alive(self):
        """Rileva se l'apparato ha chiuso il socket (timeout inattivita' 5 s)."""
        if self.sock is None:
            return False
        try:
            r, _, _ = select.select([self.sock], [], [], 0)
            if r:
                data = self.sock.recv(1, socket.MSG_PEEK)
                return len(data) > 0
            return True
        except OSError:
            return False

    def write(self, data: bytes):
        self.sock.sendall(data)

    def read_line(self) -> bytes:
        buf = b""
        deadline = time.monotonic() + self.timeout
        while not buf.endswith(b"\r") and not buf.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout, ricevuto finora: {buf!r}")
            self.sock.settimeout(remaining)
            b = self.sock.recv(1)
            if not b:
                raise ConnectionError("connessione chiusa dall'apparato")
            buf += b
        # consuma l'eventuale LF dopo il CR
        if buf.endswith(b"\r"):
            self.sock.settimeout(0.05)
            try:
                nxt = self.sock.recv(1, socket.MSG_PEEK)
                if nxt == b"\n":
                    self.sock.recv(1)
            except (socket.timeout, BlockingIOError):
                pass
        return buf.strip(b"\r\n")

    def close(self, wait=1.5):
        """Chiusura ordinata: invia FIN, attende la chiusura dalla matrice (porta
        rilasciata) per al massimo `wait` secondi, poi chiude il socket.
        Ritorna True se la matrice ha confermato la chiusura."""
        sock, self.sock = self.sock, None
        if not sock:
            return False
        released = False
        try:
            sock.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                sock.settimeout(max(0.05, deadline - time.monotonic()))
                if sock.recv(256) == b"":
                    released = True
                    break
        except OSError:
            # reset dalla matrice o socket gia' chiuso: la connessione non c'e' piu'
            released = True
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return released


class SerialTransport:
    def __init__(self, port, baud=9600, parity="N", timeout=3.0):
        try:
            import serial  # pyserial
        except ImportError:
            sys.exit("Per la seriale serve pyserial:  pip install pyserial")
        self._serial = serial
        self.port, self.baud, self.parity, self.timeout = port, baud, parity, timeout
        self.ser = None

    def name(self):
        return f"serial://{self.port}@{self.baud},8{self.parity}1"

    def connect(self):
        self.close()
        self.ser = self._serial.Serial(self.port, self.baud, bytesize=8, parity=self.parity,
                                       stopbits=1, timeout=self.timeout, xonxoff=False,
                                       rtscts=False)

    def is_alive(self):
        return self.ser is not None and self.ser.is_open

    def write(self, data: bytes):
        self.ser.reset_input_buffer()
        self.ser.write(data)

    def read_line(self) -> bytes:
        line = self.ser.read_until(b"\r")
        if not line.endswith(b"\r"):
            raise TimeoutError(f"timeout, ricevuto finora: {line!r}")
        self.ser.timeout = 0.05
        if self.ser.read(1) not in (b"\n", b""):
            pass  # byte inatteso, ignorato
        self.ser.timeout = self.timeout
        return line.strip(b"\r\n")

    def close(self):
        if self.ser:
            self.ser.close()
        self.ser = None


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MvClient:
    def __init__(self, transport, rs485_id=None, lan_id=None, lan_password=None,
                 verbose=True, eol="crlf"):
        self.t = transport
        self.closed = False
        self.verbose = verbose
        self.eol = EOLS[eol]
        self.lock = threading.Lock()
        self.prefix = ""
        if rs485_id is not None:
            self.prefix = f"I{int(rs485_id):02d}"
        elif lan_id is not None:
            if not (1 <= len(lan_id) <= 8):
                raise ValueError("ID LAN: 1-8 caratteri")
            if not (lan_password and len(lan_password) == 5
                    and lan_password.isdigit()):
                raise ValueError("Password LAN: 5 cifre 0-9")
            self.prefix = f"{len(lan_id)}{lan_id}{lan_password}"
        self._ka_stop = None

    def connect(self):
        self.t.connect()
        if self.verbose:
            print(f"[connesso a {self.t.name()}]")

    def send(self, cmd: str, quiet=False) -> str:
        """Invia un comando (senza CR/LF) e ritorna la risposta grezza."""
        verbose = self.verbose and not quiet
        frame = (self.prefix + cmd).encode("ascii") + self.eol
        with self.lock:
            if self.closed:
                raise ConnectionError("client chiuso")
            for attempt in (1, 2):
                if not self.t.is_alive():
                    if verbose:
                        print("[socket chiuso, riconnessione...]")
                    self.t.connect()
                try:
                    if verbose:
                        print(f"  >> {frame!r}")
                    self.t.write(frame)
                    resp = self.t.read_line().decode("ascii", errors="replace")
                    if verbose:
                        print(f"  << {resp!r}")
                    return resp
                except (ConnectionError, BrokenPipeError, ConnectionResetError):
                    if attempt == 2:
                        raise
                    self.t.close()

    def start_keepalive(self, interval=3.0):
        """Tiene aperto il socket TCP inviando RFA prima dei 5 s di timeout."""
        self.stop_keepalive()
        stop = threading.Event()

        def loop():
            while not stop.wait(interval):
                try:
                    self.send("RFA", quiet=True)
                except Exception as e:
                    print(f"\n[keepalive errore: {e}]")

        threading.Thread(target=loop, daemon=True).start()
        self._ka_stop = stop

    def stop_keepalive(self):
        if self._ka_stop:
            self._ka_stop.set()
            self._ka_stop = None

    def close(self):
        """Chiude definitivamente: niente piu' riconnessioni automatiche.
        Ritorna True se la matrice ha confermato il rilascio della porta."""
        self.closed = True
        self.stop_keepalive()
        return self.t.close()


# ---------------------------------------------------------------------------
# Operazioni di test
# ---------------------------------------------------------------------------

STATUS_CMDS = ["RDP0", "RFA", "RNR", "ROF0", "RAM00", "RFL0", "RAD",
               "RTL00", "RVL", "RDC", "RDD0", "RDT"]


def run(client, cmd):
    try:
        resp = client.send(cmd)
        print(f"  => {decode(resp)}")
        return resp
    except Exception as e:
        print(f"  !! {type(e).__name__}: {e}")
        return None


# Codici documentati nel manuale MV-410HS. SVR (reset allarme video loss) e'
# escluso perche' non ha parametri e verrebbe eseguito davvero.
KNOWN_READ = ["RVS", "RIF", "RDP", "RFA", "RNR", "ROF", "RAM", "RLO", "RLD", "RRG",
              "RAC", "RAD", "RTT", "RBD", "RFL", "RTL", "RVO", "RVL", "RDC", "RDD", "RDT"]
KNOWN_SET = ["SDF", "SDS", "SNF", "SNJ", "SOF", "SAM", "SLO", "SLD", "SRG", "SLS",
             "SAC", "SAD", "STT", "SBD", "SFL", "STL", "SVO", "SVL", "SDC", "SDD", "SDT"]


def _classify(resp):
    if resp is None:
        return "nessuna risposta"
    if resp.startswith("ERR001"):
        return None  # comando sconosciuto
    if resp.startswith("ERR002"):
        return "ESISTE (parametri mancanti)"
    if resp.startswith("ERR"):
        return f"ESISTE ({decode(resp)})"
    return f"ESISTE -> {resp!r}"


def _try(client, cmd):
    try:
        return client.send(cmd, quiet=True)
    except (TimeoutError, OSError):
        return None


def _save_report(client, title, rows):
    fn = time.strftime(f"{title.replace(' ', '_')}_%Y%m%d_%H%M%S.txt")
    with open(fn, "w") as f:
        f.write(f"# {title} - {client.t.name()} - eol={client.eol!r} prefix={client.prefix!r}\n")
        for cmd, resp, note in rows:
            f.write(f"{cmd}\t{resp!r}\t{note}\n")
    print(f"[report salvato in {fn}]")


def discover(client):
    """Prova i codici del manuale senza parametri: ERR001 = sconosciuto,
    ERR002 = il comando esiste ma vuole parametri."""
    rows = []
    print("== Codici del manuale MV-410HS (inviati senza parametri) ==")
    for cmd in KNOWN_READ + KNOWN_SET:
        resp = _try(client, cmd)
        note = _classify(resp)
        rows.append((cmd, resp, note or "sconosciuto"))
        print(f"  {cmd}  {resp!r:14}  {note or '-'}")
    found = [r[0] for r in rows if r[2] != "sconosciuto"]
    print(f"== Riconosciuti: {', '.join(found) or 'nessuno'} ==")
    # le sole letture (R) sono sicure da provare con parametri di riempimento
    need = [r[0] for r in rows if r[0][0] == "R" and r[1] and r[1].startswith("ERR002")]
    if need:
        print("== Lunghezza parametri delle letture ==")
        for code in need:
            n, cmd, resp = param_len(client, code)
            rows.append((cmd or code, resp, f"param {n} car." if n else "lunghezza ?"))
    if not found:
        print("  Nessun codice riconosciuto. Prova: 'eol cr', poi verifica nel menu LAN\n"
              "  se e' attiva la password (--lan-id / --lan-password), poi 'brute R'.")
    _save_report(client, "discover", rows)
    return found


def _fillers(n):
    """Parametri di prova di lunghezza n: tutti zeri, '..01', '0' + '01'*k."""
    c = ["0" * n, "0" * (n - 1) + "1", ("0" + "01" * n)[:n], ("01" * n)[:n]]
    return list(dict.fromkeys(c))


def param_len(client, code, max_len=16, quiet=False):
    """Trova quanti caratteri di parametro vuole un comando:
    ERR002 = lunghezza sbagliata, ERR003 = lunghezza giusta ma valori fuori range."""
    for n in range(1, max_len + 1):
        right_len = None
        for f in _fillers(n):
            resp = _try(client, code + f)
            if resp is None or resp.startswith("ERR002"):
                break
            if resp.startswith("ERR003"):
                right_len = (code + f, resp)
                continue
            if not quiet:
                print(f"  {code}: {n} car. -> {code + f!r} = {resp!r}  {decode(resp)}")
            return n, code + f, resp
        if right_len:
            if not quiet:
                print(f"  {code}: {n} car. (valori da capire, {right_len[0]!r} = ERR003)")
            return n, right_len[0], right_len[1]
    if not quiet:
        print(f"  {code}: lunghezza non trovata (1..{max_len})")
    return None, None, None


def brute(client, letter="R", timeout=1.0):
    """Prova tutti i codici <letter>AA..<letter>ZZ senza parametri."""
    rows, old = [], client.t.timeout
    client.t.timeout = timeout
    print(f"== Scansione {letter}AA..{letter}ZZ (676 codici) ==")
    try:
        for a in range(65, 91):
            for b in range(65, 91):
                cmd = f"{letter}{chr(a)}{chr(b)}"
                resp = _try(client, cmd)
                note = _classify(resp)
                if note:
                    rows.append((cmd, resp, note))
                    print(f"  {cmd}  {resp!r:14}  {note}")
            print(f"  ...{letter}{chr(a)}Z", end="\r", flush=True)
    finally:
        client.t.timeout = old
    print(f"\n== Trovati {len(rows)} codici ==")
    _save_report(client, f"brute {letter}", rows)
    return rows


def version(client):
    """RVS: sull'MV-1600HS vuole 3 cifre (RVS000), sull'MV-410HS nessun parametro."""
    for cmd in (getattr(client, "rvs_cmd", "RVS000"), "RVS"):
        resp = run(client, cmd)
        if resp and not resp.startswith("ERR002"):
            client.rvs_cmd = cmd
            return resp
    return resp


def inputs(client, max_ch=16):
    """Legge formato e video-loss di ogni ingresso; si ferma al primo ERR003
    (l'MV-1600HS di prova ne ha 10)."""
    n = 0
    for ch in range(1, max_ch + 1):
        resp = run(client, f"RIF{ch:02d}")
        if resp is None or resp.startswith("ERR"):
            break
        run(client, f"RVO{ch:02d}")
        n = ch
    print(f"  [{n} ingressi]")
    client.channels = n
    return n


def layout_info(client, layout):
    """Risoluzione e finestre di un layout (RLO + RLD per ogni canale e CLOCK)."""
    run(client, f"RLO0{layout:02d}")
    for ch in list(range(1, getattr(client, "channels", 10) + 1)) + [80]:
        run(client, f"RLD0{layout:02d}{ch:02d}")


def probe(client, channels):
    print("== Stato generale ==")
    version(client)
    for c in STATUS_CMDS:
        run(client, c)
    print("== Ingressi ==")
    inputs(client, channels)
    print("== Layout ==")
    for lay in range(1, 5):
        run(client, f"RLO0{lay:02d}")


def scan(client, max_ch=32):
    """Scopre quanti ingressi accetta l'apparato (si ferma al primo ERR)."""
    found = 0
    for ch in range(1, max_ch + 1):
        resp = run(client, f"RIF{ch:02d}")
        if resp is None or resp.startswith("ERR"):
            break
        found = ch
    print(f"== Ingressi rilevati: {found} ==")
    return found


# Lunghezza dei parametri dei 54 comandi R trovati sulla MV-1610HS (brute R + plen,
# 2026-11-17). Quelli senza commento non sono nel manuale MV-410HS.
R_PARAM_LEN = {
    # documentati
    "RVS": 3, "RIF": 2, "RDP": 1, "RFA": 0, "RNR": 0, "ROF": 1, "RAM": 2, "RLO": 3,
    "RLD": 5, "RRG": 2, "RAC": 5, "RAD": 0, "RTT": 5, "RBD": 5, "RFL": 1, "RTL": 2,
    "RVO": 2, "RVL": 0, "RDC": 0, "RDD": 1, "RDT": 0,
    # non documentati
    "RAA": 1, "RAE": 3, "RAJ": 0, "RAO": 2, "RAS": 3, "RBC": 3, "RCD": 0, "RCR": 5,
    "RDI": 1, "RED": 1, "RFO": 2, "RID": 2, "RIO": 2, "RIP": 2, "RIS": 2, "RIT": 2,
    "RLF": 1, "RMP": 4, "RNM": 1, "ROS": 1, "RRE": 3, "RRS": 2, "RRT": 0, "RSC": 0,
    "RST": 3, "RTC": 3, "RTD": 1, "RTG": 3, "RTH": 5, "RTP": 4, "RUD": 3, "RVF": 0,
    "RWP": 5,
}
VOLATILE = {"RDT"}  # cambiano da soli (orologio): esclusi dal confronto


def _param_candidates(n):
    """Valori plausibili per n cifre: canali/layout 00-16, 80 = CLOCK."""
    ids = [f"{i:02d}" for i in range(0, 17)] + ["80"]
    if n == 0:
        return [""]
    if n == 1:
        return [str(i) for i in range(10)]
    if n == 2:
        return ids
    if n == 3:
        return ["0" + i for i in ids]
    if n == 4:
        return [a + b for a in ids for b in ids]
    if n == 5:
        return ["0" + a + b for a in ids for b in ids]
    return ["0" * n]


def snapshot(client, path, codes=None):
    """Legge tutti i comandi R con tutte le combinazioni plausibili di parametri e
    salva le risposte valide (ERR esclusi). Solo letture: non modifica nulla."""
    codes = codes or sorted(R_PARAM_LEN)
    snap, total = {}, sum(len(_param_candidates(R_PARAM_LEN[c])) for c in codes)
    done, t0 = 0, time.monotonic()
    for code in codes:
        for p in _param_candidates(R_PARAM_LEN[code]):
            resp = _try(client, code + p)
            done += 1
            if resp and not resp.startswith("ERR"):
                snap[code + p] = resp
            if done % 50 == 0:
                print(f"  {done}/{total} comandi, {len(snap)} risposte valide", end="\r", flush=True)
    with open(path, "w") as f:
        json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "target": client.t.name(),
                   "responses": snap}, f, indent=1, sort_keys=True)
    print(f"\n[{len(snap)} risposte in {time.monotonic() - t0:.0f} s salvate in {path}]")
    return snap


def _mark(a, b):
    """Sottolinea con ^ i caratteri diversi tra due risposte."""
    return "".join("^" if i >= len(a) or i >= len(b) or a[i] != b[i] else " "
                   for i in range(max(len(a), len(b))))


def diff(path_a, path_b):
    a = json.load(open(path_a))["responses"]
    b = json.load(open(path_b))["responses"]
    changed = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k) and k[:3] not in VOLATILE]
    print(f"== {len(changed)} differenze tra {path_a} e {path_b} ==")
    for k in changed:
        ra, rb = a.get(k, "(assente)"), b.get(k, "(assente)")
        print(f"  {k:9} prima: {ra}")
        print(f"  {'':9} dopo:  {rb}")
        if k in a and k in b:
            print(f"  {'':9}        {_mark(ra, rb)}")
    return changed


HELP = """
Comandi console:
  <RAW>            invia il comando cosi' com'e' (es. RVS, SDF001, RIF03)
  ver              versione (RVS)
  status           stato display (RDP)
  full <ch>        full screen del canale (SDF0cc)
  layout <n>       mostra layout n (SDS0nn)
  input <ch>       formato ingresso (RIFcc)
  probe [n]        legge tutti gli stati (n = numero ingressi, default --channels)
  scan             scopre il numero di ingressi
  inputs           formato e video-loss di ogni ingresso
  linfo <n>        dettaglio finestre del layout n (RLO + RLD)
  time             legge orologio interno (RDT)
  synctime         imposta l'orologio interno con l'ora del PC (SDT)
  discover         prova i codici del manuale e dice quali esistono
  brute [L]        prova tutti i codici L?? (default R = richieste di stato)
  plen <COD>       trova la lunghezza dei parametri di un comando R (es. plen RVS)
  eol crlf|cr|lf   cambia il terminatore di riga
  ka on|off        keepalive TCP (evita la chiusura dopo 5 s)
  v                attiva/disattiva output byte grezzi
  quit / exit
"""


def repl(client, channels):
    print(HELP)
    while True:
        try:
            line = input("mv> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd in ("help", "?"):
                print(HELP)
            elif cmd == "ver":
                version(client)
            elif cmd == "status":
                run(client, "RDP0")
            elif cmd == "full":
                run(client, f"SDF0{int(args[0]):02d}")
            elif cmd == "layout":
                run(client, f"SDS0{int(args[0]):02d}")
            elif cmd == "input":
                run(client, f"RIF{int(args[0]):02d}")
            elif cmd == "probe":
                probe(client, int(args[0]) if args else channels)
            elif cmd == "scan":
                scan(client)
            elif cmd == "inputs":
                inputs(client)
            elif cmd == "linfo":
                layout_info(client, int(args[0]))
            elif cmd == "discover":
                discover(client)
            elif cmd == "brute":
                letter = (args[0] if args else "R").upper()
                if letter != "R" and "force" not in args:
                    print("  ATTENZIONE: codici diversi da R?? potrebbero eseguire azioni\n"
                          "  (es. salvataggi/reset senza parametri). Usa 'brute X force'.")
                else:
                    brute(client, letter[0])
            elif cmd == "plen":
                code = args[0].upper()
                if code[0] != "R" and "force" not in args:
                    print("  Solo comandi R: con un comando S i valori di prova (es. 0)\n"
                          "  verrebbero applicati davvero. Usa 'plen XXX force'.")
                else:
                    param_len(client, code)
            elif cmd == "eol":
                client.eol = EOLS[args[0].lower()]
                print(f"[terminatore {client.eol!r}]")
            elif cmd == "time":
                run(client, "RDT")
            elif cmd == "synctime":
                run(client, "SDT" + time.strftime("%y%m%d%H%M%S"))
            elif cmd == "ka":
                if args and args[0] == "on":
                    client.start_keepalive()
                    print("[keepalive attivo]")
                else:
                    client.stop_keepalive()
                    print("[keepalive disattivato]")
            elif cmd == "v":
                client.verbose = not client.verbose
                print(f"[verbose {'on' if client.verbose else 'off'}]")
            else:
                # maiuscolo solo sul codice: il testo dei titoli (STT) resta com'e'
                run(client, line[:3].upper() + line[3:])
        except (IndexError, ValueError):
            print("  argomento mancante o non valido (vedi 'help')")


def main():
    ap = argparse.ArgumentParser(description="Client di test per multiviewer FOR-A MV-series")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--host", help="IP dell'apparato (default di fabbrica 192.168.0.1)")
    g.add_argument("--serial", help="porta seriale, es. /dev/ttyUSB0 o COM3")
    ap.add_argument("--port", type=int, default=2010, help="porta TCP comandi (default 2010)")
    ap.add_argument("--baud", type=int, default=9600, choices=[9600, 19200, 38400])
    ap.add_argument("--parity", default="N", choices=["N", "O", "E"])
    ap.add_argument("--timeout", type=float, default=3.0)
    ap.add_argument("--rs485-id", type=int, help="ID RS-485 (00-31), aggiunge prefisso 'Inn'")
    ap.add_argument("--lan-id", help="ID LAN (se l'apparato ha la password attiva)")
    ap.add_argument("--lan-password", help="password LAN, 5 cifre 0-9")
    ap.add_argument("--eol", default="crlf", choices=list(EOLS), help="terminatore di riga")
    ap.add_argument("--discover", action="store_true", help="prova i codici del manuale ed esce")
    ap.add_argument("--brute", metavar="LETTERA", help="prova tutti i codici LETTERA?? ed esce (solo R consigliato)")
    ap.add_argument("--plen", metavar="COD", help="trova la lunghezza parametri di un comando R ed esce")
    ap.add_argument("--channels", type=int, default=16, help="numero massimo di ingressi da provare")
    ap.add_argument("-c", "--command", action="append", help="esegue comando/i ed esce")
    ap.add_argument("--probe", action="store_true", help="legge tutti gli stati ed esce")
    ap.add_argument("-q", "--quiet", action="store_true", help="non mostra i byte grezzi")
    ap.add_argument("--snapshot", metavar="FILE", help="salva le risposte di tutti i comandi R (solo letture)")
    ap.add_argument("--diff", nargs=2, metavar=("PRIMA", "DOPO"), help="confronta due snapshot (non serve la matrice)")
    a = ap.parse_args()
    if a.diff:
        diff(*a.diff)
        return
    if not (a.host or a.serial):
        ap.error("serve --host oppure --serial")

    if a.host:
        t = TcpTransport(a.host, a.port, a.timeout)
    else:
        t = SerialTransport(a.serial, a.baud, a.parity, a.timeout)

    client = MvClient(t, rs485_id=a.rs485_id, lan_id=a.lan_id,
                      lan_password=a.lan_password, verbose=not a.quiet, eol=a.eol)
    try:
        client.connect()
    except OSError as e:
        sys.exit(f"Connessione fallita verso {t.name()}: {e}")

    try:
        if a.command:
            for c in a.command:
                run(client, c[:3].upper() + c[3:])
        elif a.snapshot:
            snapshot(client, a.snapshot)
        elif a.discover:
            discover(client)
        elif a.plen:
            if a.plen.upper()[0] != "R":
                sys.exit("--plen e' consentito solo per comandi R")
            param_len(client, a.plen.upper())
        elif a.brute:
            brute(client, a.brute[0].upper())
        elif a.probe:
            probe(client, a.channels)
        else:
            repl(client, a.channels)
    finally:
        client.close()


if __name__ == "__main__":
    main()
