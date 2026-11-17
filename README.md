# FOR-A MV Remote

Software di controllo per i multiviewer **FOR-A MV-1600HS / MV-1610HS** (protocollo
compatibile con la serie MV-410HS), nato per sostituire il software di gestione
originale, ormai obsoleto e non più reperibile.

Funziona con la sola libreria standard di Python e si usa dal browser.

> Progetto indipendente, **non affiliato né approvato da FOR-A**. I marchi citati
> appartengono ai rispettivi proprietari. Manuali e software originali non sono inclusi.

## Funzionalità

- **Editor dei layout** (16 layout sulla MV-1610HS): finestre da trascinare e
  ridimensionare con aggancio a griglia e ai bordi, layer, titoli, posizioni di
  titolo e level meter, invio immediato alla matrice.
- **Riquadro della proporzione reale** dentro ogni finestra: 16:9, 4:3 o
  risoluzione PC secondo il segnale in ingresso, "stirato" in Mode3.
- **Uscita**: selezione del layout o di un ingresso a schermo intero, stato degli
  ingressi in tempo reale.
- **Impostazioni System e Layout**: UMD (indirizzi, protocollo TSL 3.1/4.0),
  tally, level meter, allarmi audio, video loss, freeze, orologio/LTC, bordi,
  timecode, titoli, interruttori Global/Individual per layout.
- **Connessione robusta**: password LAN, keepalive, attesa se la porta è occupata
  da un altro client, rilascio garantito della porta alla disconnessione.
- **Strumenti di diagnostica**: console a riga di comando, scansione dei comandi,
  fotografia completa degli stati e confronto tra due fotografie.

## Requisiti

- Python 3 recente (testato con 3.12 e 3.14), nessun pacchetto esterno.
- Per la seriale RS-232C/422/485: `pip install pyserial`.
- Multiviewer raggiungibile in rete sulla porta comandi TCP 2010.

## Avvio rapido

```bash
python3 fora_web.py --open
```

Si apre il browser su `http://127.0.0.1:8080`: inserisci IP della matrice, porta
2010 e, se la password LAN è attiva, ID e password, poi **Connetti**.

Opzioni utili:

```bash
python3 fora_web.py --mv <IP> --lan-id <ID> --lan-password <PASSWORD>   # connessione all'avvio
python3 fora_web.py --bind 0.0.0.0                                      # accesso da altri PC (senza login!)
```

I parametri di connessione vengono salvati in `fora_web.json` (password in chiaro,
escluso da git).

### Windows

`build_windows.py` crea un pacchetto portatile (Python "embeddable" incluso, niente
da installare):

```bash
python3 build_windows.py
```

Il risultato è `dist/FORA-MV-Remote-win64.zip`: si estrae e si avvia con
`FORA MV Remote.bat`.

## Note importanti

- La matrice accetta **una sola connessione di controllo**. Finché il server è
  acceso e connesso, nessun altro client può collegarsi: usa **Disconnetti** o
  chiudi il server quando hai finito. Se nessuna pagina è aperta da 3 minuti, il
  server rilascia comunque la porta.
- "Salva in memoria" scrive il layout nella memoria permanente della matrice.
- Le impostazioni d'uscita (frequenza, risoluzione) cambiano il segnale in onda:
  la pagina chiede conferma.

## Console e diagnostica

```bash
python3 fora_mv.py --host <IP> --lan-id <ID> --lan-password <PASSWORD>        # console interattiva
python3 fora_mv.py --host <IP> ... -c RVS000 -c RIF01                         # singoli comandi
python3 fora_mv.py --host <IP> ... --probe                                    # stato generale
python3 fora_mv.py --host <IP> ... --brute R                                  # scopre i comandi di lettura
python3 fora_mv.py --host <IP> ... --snapshot prima.json                      # fotografia degli stati
python3 fora_mv.py --diff prima.json dopo.json                                # cosa è cambiato
```

## Simulatore

`mv_sim.py` imita la matrice (una sola connessione, timeout, password, layout e
finestre) per sviluppare e provare senza l'apparato:

```bash
python3 mv_sim.py --port 2010 --replay snapshots/base_20261117.json
python3 fora_web.py --mv 127.0.0.1
```

Con `--replay` risponde con i valori reali di una fotografia e i comandi di
impostazione aggiornano le risposte.

## Struttura

| File | Contenuto |
|---|---|
| `fora_mv.py` | client del protocollo (TCP/seriale), decodifica, console, strumenti |
| `fora_web.py`, `fora_web.html` | server HTTP locale e interfaccia web |
| `fora_settings.py` | impostazioni System/Layout |
| `mv_sim.py` | simulatore |
| `build_windows.py` | pacchetto portatile per Windows |
| `PROTOCOLLO_MV1600HS.md` | note sul protocollo, inclusi i comandi non documentati |
| `snapshots/` | fotografie degli stati di una MV-1610HS reale |
| `tools/` | test dei comandi di impostazione, strumenti di analisi .NET |

## Licenza

[MIT](LICENSE)
