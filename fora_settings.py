"""
fora_settings.py - Impostazioni System / Layout della MV-1610HS.

I formati vengono dall'analisi del software originale (vedi PROTOCOLLO_MV1600HS.md)
e sono stati verificati sulle risposte reali della matrice.

Regola del protocollo: la lettura  Rxx<parametri>  risponde  Axx<parametri><campi>
e l'impostazione corrispondente e'  Sxx<parametri><campi>  con gli stessi campi.
Per scrivere si rilegge il valore attuale, si sostituiscono SOLO i caratteri dei
campi modificati e si rimanda il resto identico (campi riservati compresi).
"""

import re

COLORS9 = ["WHITE", "YELLOW", "GREEN", "CYAN", "RED", "MAGENTA", "BLUE", "GRAY", "BLACK"]
RESOLUTIONS8 = ["1280x1024", "1360x768", "1600x1200", "1920x1200", "1440x900", "1680x1050",
                "1920x1080", "1280x720"]


def E(*options):
    return {"type": "enum", "options": list(options)}


def I(lo, hi):
    return {"type": "int", "min": lo, "max": hi}


B = {"type": "bool"}
RGB = {"type": "rgb"}
TEXT16 = {"type": "text", "max": 16}

GLOBAL = E("Impostazioni del layout", "Globali")  # 0 = Individual, 1 = Global

# Ogni gruppo = un comando R/S. "read" puo' contenere {ch} (ingresso), {L} (layout).
# fields: (nome, etichetta, inizio, larghezza, tipo); larghezza None = fino a fine risposta.
GROUPS = [
    # ------------------------------------------------------------------ System
    dict(id="sys_umd_proto", sec="system", title="Protocollo UMD / tally", read="RSC",
         fields=[("proto", "Protocollo", 0, 1, E("MV-1610HS", "TSL Ver.3.1", "TSL Ver.4.0"))]),
    dict(id="sys_tally", sec="system", title="Tally", read="RTL00",
         fields=[("det", "Rilevamento tally", 0, 1, B),
                 ("sim", "Tally simultanei", 1, 1, E("RED", "AMBER")),
                 ("src", "Sorgente", 2, 1, E("TALLY IN/REMOTE", "Command", "TSL")),
                 ("disp", "Visualizzazione", 3, 1, E("Frame", "Indicator")),
                 ("info", "Lato informazioni", 4, 1, E("Left", "Right"))]),
    dict(id="sys_tally_in", sec="system", title="Ingresso tally", read="RRT",
         fields=[("sel", "Ingresso", 0, 1, E("TALLY IN", "REMOTE"))]),
    dict(id="sys_umd", sec="system", title="UMD · indirizzo per ingresso", read="RUD0{ch}", per="input",
         fields=[("addr", "Indirizzo", 0, 3, I(0, 999))]),
    dict(id="sys_meter", sec="system", title="Level meter audio", read="RAD",
         fields=[("ref", "Livello riferimento (-dBFS)", 0, 2, I(1, 60)),
                 ("peak", "Livello picco (-dBFS)", 2, 2, I(0, 30)),
                 ("hold", "Tenuta picco (s, 0 = off)", 4, 2, I(0, 10))]),
    dict(id="sys_alarm_over", sec="system", title="Allarme audio · OVER", read="RAA0",
         fields=[("level", "Livello", 0, 2, I(0, 99)),
                 ("disp", "Tempo visualizzazione", 2, 3, I(0, 999)),
                 ("detect", "Tempo rilevazione", 5, 3, I(0, 999))]),
    dict(id="sys_alarm_silence", sec="system", title="Allarme audio · SILENCE", read="RAA1",
         fields=[("level", "Livello", 0, 2, I(0, 99)),
                 ("disp", "Tempo visualizzazione", 2, 3, I(0, 999)),
                 ("detect", "Tempo rilevazione", 5, 3, I(0, 999))]),
    dict(id="sys_alarm_in", sec="system", title="Allarmi audio per ingresso", read="RAO{ch}", per="input",
         fields=[("over", "Over", 0, 1, B), ("silence", "Silence", 1, 1, B)]),
    dict(id="sys_vloss", sec="system", title="Video loss · durata allarme", read="RVL",
         fields=[("time", "Secondi (0 = fino a reset)", 0, 3, I(0, 100))]),
    dict(id="sys_vloss_in", sec="system", title="Video loss per ingresso", read="RVO{ch}", per="input",
         fields=[("det", "Rilevamento", 0, 1, B)]),
    dict(id="sys_freeze", sec="system", title="Freeze video", read="RVF",
         fields=[("disp", "Tempo visualizzazione", 0, 3, I(0, 999)),
                 ("detect", "Tempo rilevazione", 3, 3, I(0, 999))]),
    dict(id="sys_freeze_in", sec="system", title="Freeze per ingresso", read="RFO{ch}", per="input",
         fields=[("det", "Rilevamento", 0, 1, B)]),
    dict(id="sys_clockref", sec="system", title="Orologio · riferimento", read="RDC",
         fields=[("ref", "Riferimento", 0, 1, E("INTERNAL", "LTC"))]),
    dict(id="sys_clock", sec="system", title="Orologio / logo", read="RDD0",
         fields=[("what", "Mostra", 0, 1, E("CLOCK", "LOGO")),
                 ("clock", "Tipo orologio", 1, 2, E("ANALOG 1", "ANALOG 2", "DIGITAL 1", "DIGITAL 2")),
                 ("logo", "Logo", 3, 2, E("LOGO 1", "LOGO 2"))]),
    dict(id="sys_clockcolor", sec="system", title="Orologio digitale · colore", read="RDI0",
         fields=[("rgb", "Colore", 0, 9, RGB)]),
    dict(id="sys_ltc", sec="system", title="LTC", read="RLF0",
         fields=[("fps", "Frame rate", 0, 1, E("30FPS", "25FPS")),
                 ("offset", "Offset", 1, 2, I(0, 99))]),
    dict(id="sys_timecorr", sec="system", title="Correzione orologio", read="RAJ",
         fields=[("corr", "Frequenza", 0, 1, E("1/MINUTE", "1/HOUR", "1/DAY"))]),
    dict(id="sys_titletype", sec="system", title="Titoli di sistema", read="RST000",
         fields=[("type", "Tipo", 0, 1, E("STATIC", "DYNAMIC"))]),
    dict(id="sys_outfreq", sec="system", title="Uscita · frequenza", read="ROF0", danger=True,
         fields=[("freq", "Frequenza", 0, 1, E("60Hz", "59.94Hz", "50Hz"))]),
    dict(id="sys_fullres", sec="system", title="Uscita · risoluzione schermo intero", read="RFL0", danger=True,
         fields=[("res", "Risoluzione", 0, 2, E(*RESOLUTIONS8))]),

    # ------------------------------------------------------------------ Layout
    dict(id="lay_switch", sec="layout", title="Impostazioni usate da questo layout", read=None,
         multi=[("RAS0{L}", "Modo di visualizzazione"), ("RBC0{L}", "Bordi"), ("RAE0{L}", "Audio"),
                ("RTC0{L}", "Titoli"), ("RRE0{L}", "Crop"), ("RTG0{L}", "Timecode")],
         fields=[("g", "", 0, 1, GLOBAL)]),
    dict(id="lay_border", sec="layout", title="Bordi", read="RBD0{L}00",
         fields=[("on", "Bordo", 0, 1, B), ("t", "Sopra", 1, 2, I(0, 50)), ("b", "Sotto", 3, 2, I(0, 50)),
                 ("l", "Sinistra", 5, 2, I(0, 50)), ("r", "Destra", 7, 2, I(0, 50)),
                 ("color", "Colore", 9, 2, E(*COLORS9))]),
    dict(id="lay_meter", sec="layout", title="Level meter per finestra", read="RAC0{L}{ch}", per="input",
         fields=[("on", "Meter", 0, 1, B), ("n", "Canali", 1, 1, E("2CH", "4CH", "8CH"))]),
    dict(id="lay_tc", sec="layout", title="Timecode per finestra", read="RTH0{L}{ch}", per="input",
         fields=[("on", "Timecode", 0, 1, B), ("size", "Dimensione", 1, 1, E("SMALL", "MEDIUM", "LARGE"))]),
    dict(id="lay_title", sec="layout", title="Titoli per finestra", read="RTT0{L}{ch}", per="input",
         fields=[("on", "Titolo", 0, 1, B), ("size", "Dim.", 1, 1, E("SMALL", "MEDIUM", "LARGE")),
                 ("color", "Colore", 2, 2, E(*COLORS9)), ("text", "Testo", 4, None, TEXT16)]),
]
BY_ID = {g["id"]: g for g in GROUPS}


def instances(group, channels, layout=None):
    """Elenco delle letture (comando, etichetta) di un gruppo."""
    fmt = lambda t, ch=None: t.format(ch=f"{ch:02d}" if ch else "", L=f"{layout:02d}" if layout else "")
    if group.get("multi"):
        return [(fmt(t), label) for t, label in group["multi"]]
    if group.get("per") == "input":
        return [(fmt(group["read"], ch), f"CH{ch}") for ch in range(1, channels + 1)]
    return [(fmt(group["read"]), "")]


def decode_body(group, body):
    vals = {}
    for name, _label, start, width, spec in group["fields"]:
        raw = body[start:] if width is None else body[start:start + width]
        t = spec["type"]
        if t == "bool":
            vals[name] = raw == "1"
        elif t == "enum":
            vals[name] = int(raw) if raw.isdigit() else None
        elif t == "int":
            vals[name] = int(raw) if raw.isdigit() else None
        elif t == "rgb":
            vals[name] = "#%02x%02x%02x" % (int(raw[0:3]), int(raw[3:6]), int(raw[6:9])) if raw.isdigit() else None
        else:
            vals[name] = raw
    return vals


def encode_field(spec, width, value):
    t = spec["type"]
    if t == "bool":
        return "1" if value else "0"
    if t == "enum":
        v = int(value)
        if not 0 <= v < len(spec["options"]):
            raise ValueError("valore non ammesso")
        return f"{v:0{width}d}"
    if t == "int":
        v = int(value)
        if not spec["min"] <= v <= spec["max"]:
            raise ValueError(f"valore fuori range {spec['min']}-{spec['max']}")
        return f"{v:0{width}d}"
    if t == "rgb":
        h = str(value).lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return f"{r:03d}{g:03d}{b:03d}"
    if t == "text":
        s = str(value)
        if len(s) > spec["max"] or not s.isascii():
            raise ValueError(f"massimo {spec['max']} caratteri ASCII")
        return s
    raise ValueError(t)


def apply_changes(group, body, changes):
    """Nuovo corpo: sostituisce solo i campi modificati."""
    out = body
    for name, _label, start, width, spec in group["fields"]:
        if name not in changes:
            continue
        enc = encode_field(spec, width, changes[name])
        if width is None:
            out = out[:start] + enc
        else:
            if len(enc) != width:
                raise ValueError(f"{name}: larghezza errata")
            out = out[:start] + enc + out[start + width:]
    return out


def schema():
    """Schema per la pagina (senza i comandi)."""
    return [{"id": g["id"], "sec": g["sec"], "title": g["title"], "per": g.get("per"),
             "multi": bool(g.get("multi")), "danger": g.get("danger", False),
             "fields": [{"name": n, "label": lb, "spec": sp} for n, lb, _s, _w, sp in g["fields"]]}
            for g in GROUPS]


def read_section(cmd, sec, channels, layout=None):
    """Legge tutti i gruppi di una sezione. cmd(c) -> risposta."""
    out = []
    for g in GROUPS:
        if g["sec"] != sec:
            continue
        rows = []
        for read, label in instances(g, channels, layout):
            try:
                resp = cmd(read)
            except RuntimeError as e:
                rows.append({"read": read, "label": label, "error": str(e)})
                continue
            if not resp.startswith("A" + read[1:3]):
                rows.append({"read": read, "label": label, "error": resp})
                continue
            body = resp[len(read):]
            rows.append({"read": read, "label": label, "values": decode_body(g, body)})
        out.append({"id": g["id"], "rows": rows})
    return out


def write(cmd, group_id, read, changes):
    """Rilegge, applica le modifiche, invia Sxx, rilegge per conferma."""
    g = BY_ID[group_id]
    templates = [t for t, _ in g["multi"]] if g.get("multi") else [g["read"]]
    pats = [re.escape(t).replace(r"\{ch\}", r"\d\d").replace(r"\{L\}", r"\d\d") for t in templates]
    if not any(re.fullmatch(p, read) for p in pats):
        raise ValueError("lettura non valida per il gruppo")
    resp = cmd(read)
    if not resp.startswith("A" + read[1:3]):
        raise RuntimeError(f"lettura fallita: {resp}")
    body = resp[len(read):]
    new_body = apply_changes(g, body, changes)
    s_cmd = "S" + read[1:] + new_body
    r = cmd(s_cmd)
    if r != "OK":
        return {"ok": False, "error": r, "sent": s_cmd}
    back = cmd(read)
    return {"ok": True, "values": decode_body(g, back[len(read):]), "sent": s_cmd}
