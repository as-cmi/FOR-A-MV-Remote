#!/usr/bin/env python3
"""
build_windows.py - Crea il pacchetto portatile per Windows 10/11 (64 bit).

  python3 build_windows.py
  python3 build_windows.py --python-zip /percorso/python-3.12.10-embed-amd64.zip

Risultato: dist/FORA-MV-Remote-win64.zip, da estrarre sul PC Windows e avviare
con "FORA MV Remote.bat". Contiene il Python "embeddable" ufficiale: sui PC non
serve installare nulla.
"""

import argparse
import hashlib
import os
import shutil
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY_VER = "3.12.10"
PY_ZIP = f"python-{PY_VER}-embed-amd64.zip"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/{PY_ZIP}"
PY_MD5 = "fe8ef205f2e9c3ba44d0cf9954e1abd3"  # pubblicato su python.org/downloads/release/python-31210/
APP_FILES = ["fora_mv.py", "fora_web.py", "fora_settings.py", "fora_web.html", "PROTOCOLLO_MV1600HS.md",
             "README.md", "LICENSE"]
NAME = "FORA-MV-Remote"


def crlf(text):
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


LAUNCHER = r"""@echo off
title FORA MV Remote
cd /d "%~dp0"
"%~dp0python\python.exe" "%~dp0app\fora_web.py" --open %*
if errorlevel 1 pause
"""

CONSOLE = r"""@echo off
title FORA MV - console diagnostica
cd /d "%~dp0"
echo Console comandi per FOR-A MV - digita help per l'elenco, quit per uscire
echo.
set "MVIP="
set "MVID="
set "MVPW="
set /p MVIP=IP della matrice: 
if "%MVIP%"=="" goto end
set /p MVID=ID LAN, Invio se la password non e' attiva: 
if "%MVID%"=="" goto nopw
set /p MVPW=Password LAN, 5 cifre: 
"%~dp0python\python.exe" "%~dp0app\fora_mv.py" --host %MVIP% --lan-id %MVID% --lan-password %MVPW%
goto end
:nopw
"%~dp0python\python.exe" "%~dp0app\fora_mv.py" --host %MVIP%
:end
pause
"""

README = """FORA MV Remote - controllo multiviewer FOR-A MV-1600HS / MV-1610HS
=====================================================================

REQUISITI
  Windows 10 o 11 a 64 bit. Non serve installare nulla: Python e' incluso
  nella cartella "python".

INSTALLAZIONE
  1. Estrai lo zip in una cartella scrivibile (es. Documenti o Desktop),
     NON in "Programmi".
  2. Se Windows segnala il file come scaricato da Internet: tasto destro
     sullo zip > Proprieta' > "Sblocca", prima di estrarre.

AVVIO
  Doppio clic su "FORA MV Remote.bat".
  Si apre una finestra nera (il server) e il browser con l'interfaccia.
  Inserisci IP della matrice, porta 2010, ID e password LAN, poi Connetti.
  I parametri vengono ricordati (file app\\fora_web.json, password in chiaro).

  Per chiudere: chiudi la finestra nera (o Ctrl+C dentro di essa).
  La connessione con la matrice viene chiusa e la porta si libera.

USO
  - Sinistra: uscita su layout 1-4 o ingresso a schermo intero.
  - Centro: editor del layout. Trascina per spostare, maniglie per
    ridimensionare, frecce/Shift+frecce da tastiera.
    Con "Invio immediato" ogni modifica va subito a monitor.
  - "Salva in memoria" salva il layout nella matrice (chiede conferma).

NOTE IMPORTANTI
  - La matrice accetta UNA sola connessione di controllo. Se un altro PC o
    programma e' collegato, l'interfaccia mostra "in attesa" (pallino
    arancione) e si collega da sola appena la porta si libera.
  - Non aprire due copie del programma sulla stessa matrice.
  - L'interfaccia e' raggiungibile solo da questo PC (127.0.0.1).
    Per usarla da altri PC: "FORA MV Remote.bat" --bind 0.0.0.0
    (attenzione: la pagina non ha login).

DIAGNOSTICA
  "Console diagnostica.bat" apre la console a riga di comando (fora_mv.py)
  per inviare comandi diretti (es. RVS000, RIF01, probe, discover).
  Non usarla mentre l'interfaccia e' connessa alla stessa matrice.

CONTENUTO
  FORA MV Remote.bat       avvio interfaccia
  Console diagnostica.bat  console comandi
  app\\                     programma (fora_web.py, fora_web.html, fora_mv.py)
  app\\PROTOCOLLO_MV1600HS.md  note sul protocollo
  python\\                  Python {ver} embeddable (python.org)
"""


def get_python_zip(path):
    if not path:
        path = os.path.join(HERE, "build", PY_ZIP)
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            print(f"Scarico {PY_URL}")
            urllib.request.urlretrieve(PY_URL, path)
    md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
    if md5 != PY_MD5:
        raise SystemExit(f"{path}: MD5 {md5} diverso da quello pubblicato ({PY_MD5})")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python-zip", help=f"{PY_ZIP} gia' scaricato (altrimenti lo scarica)")
    ap.add_argument("--out", default=os.path.join(HERE, "dist"))
    a = ap.parse_args()

    py_zip = get_python_zip(a.python_zip)
    root = os.path.join(a.out, NAME)
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(os.path.join(root, "app"))

    with zipfile.ZipFile(py_zip) as z:
        z.extractall(os.path.join(root, "python"))
    for f in APP_FILES:
        shutil.copy2(os.path.join(HERE, f), os.path.join(root, "app", f))
    for name, text in [("FORA MV Remote.bat", LAUNCHER), ("Console diagnostica.bat", CONSOLE),
                       ("LEGGIMI.txt", README.format(ver=PY_VER))]:
        with open(os.path.join(root, name), "w", newline="") as fh:
            fh.write(crlf(text))

    out_zip = os.path.join(a.out, f"{NAME}-win64.zip")
    if os.path.exists(out_zip):
        os.remove(out_zip)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dirpath, _, files in os.walk(root):
            for f in sorted(files):
                full = os.path.join(dirpath, f)
                z.write(full, os.path.relpath(full, a.out))
    print(f"Creato {out_zip} ({os.path.getsize(out_zip) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
