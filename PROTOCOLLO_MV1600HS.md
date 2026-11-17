# Protocollo MV-1600HS – note da verifiche sul campo

> Progetto indipendente, **non affiliato né approvato da FOR-A**. FOR-A, MV-410HS,
> MV-1600HS e MV-1610HS sono marchi dei rispettivi proprietari. Le informazioni sul
> protocollo sono raccolte per l'interoperabilità con apparati in proprio possesso;
> il manuale e il software originali non sono inclusi.

Riferimento: manuale `MV410HS_Command-E-V2.0.pdf`. L'MV-1600HS usa lo stesso
protocollo, con le differenze sotto. Verificato il 2026-11-16 su una MV-1610HS.

## Connessione
- TCP porta 2010, ASCII, terminatore CR LF.
- **Password LAN attiva**: ogni comando va preceduto da
  `<lunghezza ID><ID><password 5 cifre>`. La password può contenere 0
  (il manuale dice 1-9). Senza prefisso tutti i comandi rispondono `ERR001`.
- Risposte `OK` / `ERRnnn` / `Axx...` come da manuale.
- Il modello reale è **MV-1610HS** (realm della pagina web su porta 80, che
  richiede login).
- **Una sola connessione**: se un altro client è collegato la porta 2010 rifiuta
  (`ECONNREFUSED`, errno 111). Misurato il 2026-11-16:
  - porta di nuovo libera ~1 s dopo la chiusura dal PC, subito dopo la chiusura
    dalla matrice (il manuale parlava di ~10 s);
  - la matrice chiude la connessione dopo **~15 s** di silenzio (manuale: 5 s).
- **Nessun comando di chiusura** nel protocollo: a fine sessione basta chiudere
  il socket TCP.
- Il client deve tenere viva la connessione (un comando ogni pochi secondi) e,
  se la porta è occupata, restare in attesa e riprovare.
- Rifiuto di oltre 2 minuti osservato senza nessun nostro client collegato:
  la porta era tenuta da qualcun altro (altro PC o forse la pagina web della
  matrice, da verificare).
- Le modifiche `SLD` sono applicate subito all'uscita (verificato).

## Differenze rispetto all'MV-410HS
| Comando | MV-410HS | MV-1600HS |
|---|---|---|
| `RVS` | senza parametri, risposta 4×4 cifre | vuole 3 cifre (`RVS000`); risposta = eco `000` + 5×4 cifre (`AVS000` `0501` `0000`×4 → SW 05.01) |
| Ingressi | 01-04 | 01-10 (`RIF11` → `ERR003`) |
| `RBD` | schermo 01-04 | accetta anche `00` (full screen); il riservato finale è di 5 cifre |

## Comandi verificati (lettura)
Tutti i 21 comandi `R` del manuale rispondono con formato e lunghezza del manuale
(eccetto `RVS`, sopra). Esempi reali:

```
RIF01     -> AIF0101            CH1 1080/50i   (80 = LOSS)
RDP0      -> ADP00101           split, layout 1
ROF0      -> AOF02              50Hz
RLO001    -> ALO00106           layout 1 = 1920x1080 (layout 2-4: 03 = 1920x1200)
RLD00101  -> ALD001011020000000012800720124805360020056012220560101
RRG01     -> ARG010000000000000000
RAC00001  -> AAC000011200000    full, CH1, meter ON, 8CH
RTT00001  -> ATT000011200CHANNEL 1
RBD00000  -> ABD000000010101010000000
RNR       -> ANR63              60/50fps, Superfine
RAD       -> AAD20100100000
```

## Comandi di impostazione (S)
Tutti i 21 comandi `S` del manuale (escluso `SVR`, mai inviato) sono riconosciuti
(`ERR002` senza parametri). Non sono ancora stati provati con parametri.

## Da verificare
- Significato del parametro di `RVS` (provare `RVS001`, `RVS002`… per altre schede).
- Canali ammessi in `RLD`/`SLD` (01-10? 80 = CLOCK).
- `SDF`/`SDS` con canali 05-10.
- Flusso JPEG sulla porta 2000 (formato non documentato).

## 16 layout (MV-1610HS)
`RLO001`…`RLO016` rispondono (`RLO017` → `ERR003`): la macchina ha **16 layout**,
ognuno con la propria risoluzione (es. L1 1920x1080, L2-8 1920x1200, L9 1280x1024,
L16 1280x720). Il manuale MV-410HS ne prevede 4.

## Comandi non documentati (dal software originale, 2026-11-17)
Fonte: analisi, ai soli fini di interoperabilità, del software di gestione originale
(non più reperibile): formato dei comandi, voci dei menu che li usano e valori ammessi.
Il formato di ogni risposta `Axx` è stato
confrontato con `snapshots/base_20261117.json`: tutte le lunghezze coincidono.
Regola generale: `Rxx` + parametri → `Axx` + parametri + gli stessi campi di `Sxx`.

Notazione: `LL` layout 01-16, `CC` canale 01-10 (80 = CLOCK), `II` ingresso 01-10,
`O` uscita (0/1, opzione dual output), campi `0`/`00000` finali = riservati.

**Verifica sulla matrice (2026-11-17, `tools/echo_test.py`)**: 25 comandi S
riscritti con il valore letto (`SUD SSC STL SRT SAA SAO SVF SFO SAC STH SMP STP SWP SDI
SLF SAJ SST SAS SBC SAE STC SRE STG SDD`) → tutti `OK`, rilettura identica, 0 differenze
tra snapshot prima/dopo. Letture estese funzionanti: `RAC1LLCC`, `RTT1LLCC`, `RBD1LL00`,
`RDC0` (`ADC00`, con uscita). Interruttori Global/Individual: **1 = Global**,
0 = Individual (dal software originale).

### Menu System
| Comando | Campi | Significato |
|---|---|---|
| `SUD0` `II` `aaa` `00000` | aaa = indirizzo UMD 000-… | **UMD**: indirizzo per ingresso (oggi = ingresso-1) |
| `SSC` `p` `x` `0000` | p: 0 MV-1610HS, 1 TSL 3.1, 2 TSL 4.0 | **Protocollo UMD/tally** |
| `STL00` `d` `s` `i` `v` `f` `00` | d rilevazione on/off; s simultanei 0 RED 1 AMBER; i sorgente 0 TALLY IN/REMOTE, 1 Command, 2 TSL; v visualizzazione 0 Frame, 1 Indicator; f info 0 Left, 1 Right | **Tally** (estende il formato del manuale) |
| `SRT` `r` `00000` | 0 TALLY IN, 1 REMOTE | ingresso tally |
| `SAA` `t` `ll` `ddd` `eee` `00000` | t 0 = over, 1 = silence; ll livello; ddd tempo display; eee tempo rilevazione | **Allarmi audio** |
| `SAO` `II` `o` `s` `00000` | allarme over / silence per ingresso | allarmi audio per ingresso |
| `SVF` `ddd` `eee` `00` | tempo display, tempo rilevazione | **Freeze video** |
| `SFO` `II` `f` | rilevazione freeze per ingresso | |
| `SDC` `O` `r` | r 0 INTERNAL, 1 LTC | riferimento orologio (manuale: `SDC r`) |
| `SLF` `O` `f` `oo` `00000` | f 0 30FPS, 1 25FPS; oo offset | **LTC** |
| `SAJ` `c` `00000` | 0 1/MINUTE, 1 1/HOUR, 2 1/DAY | correzione orologio |
| `SDI` `O` `rrr` `ggg` `bbb` | colore RGB | colore font orologio digitale |
| `STD` … | | differenza oraria (time difference), formato da completare |
| `SST0` `00` `t` `00000` | 0 STATIC, 1 DYNAMIC | tipo titolo di sistema |
| `SAD`, `SVO`, `SVL`, `SOF0`, `SFL0` | come manuale | |
| `STT1`… | come `STT` + bordo (0 OFF, 1 EDGE, 2 MAT), RGB testo, RGB bordo, trasparenze | titoli estesi |

### Menu Layout — interruttori Global / Individual per layout
`SAS` (display mode), `SBC` (bordi), `SAE` (audio), `STC` (titoli), `SRE` (crop),
`STG` (timecode): formato `Sxx0` `LL` `g` `00000`, g = impostazioni globali o
del layout: **1 = Global, 0 = Individual** (es. `RAS001` = 1, `RAS002` = 0).

| Comando | Campi | Significato |
|---|---|---|
| `SAC1` `LL` `CC` `d` `n` `g1` `g2` `000` | d on/off; n 0 2CH, 1 4CH, 2 8CH; g1/g2 gruppo audio 1-4 | **level meter** esteso (2 gruppi audio) |
| `STH0` `LL` `CC` `d` `s` `00000` | d on/off; s 0 SMALL 1 MEDIUM 2 LARGE | **timecode** per finestra |
| `SDD` `O` `t` `cc` `ll` `000` | t 0 CLOCK 1 LOGO; cc 0 ANALOG1 1 ANALOG2 2 DIGITAL1 3 DIGITAL2; ll LOGO 1/2 | **orologio/logo** (estende il manuale) |
| `SBD1`… | come `SBD` + colore RGB | bordi estesi |

### Editor layout, per finestra
| Comando | Campi | Significato |
|---|---|---|
| `SLD0`/`SLD1` | come manuale; posizioni titolo e meter **assolute** | |
| `SWP0` `LL` `CC` `a` `t` `p` `0000` | a aspect; t posizione titolo (preset); p posizione tally L | proprietà finestra |
| `SMP` `LL` `CC` `xxxx yyyy xxxx yyyy` `s` | **indicatori tally** L e R (assoluti) + dimensione | |
| `STP` `LL` `CC` `xxxx` `yyyy` | posizione **timecode** (assoluta) | |

### Solo lettura / altro
- `RCD`: dati delle schede (slot); l'originale lo usa all'avvio.
- `RIS` `RID` `RIO` `RIP` `RIT` `RRS`: informazioni sulle schede d'ingresso 05-10.
- `RED`, `RNM`, `ROS`, `RCR`: non usati da questa versione del software.

### Connessione nel software originale
`TcpClient`: connessione, invio dei comandi, `Close`. Nessun comando di chiusura.
Testi codificati in Shift-JIS. `ERR004` → messaggio "menu aperto sulla matrice".

### Verificare un comando con snapshot/diff
1. `python3 fora_mv.py --host … --snapshot prima.json`
2. cambiare **una sola** impostazione
3. `python3 fora_mv.py --host … --snapshot dopo.json`
4. `python3 fora_mv.py --diff prima.json dopo.json`
