"""Test sicuro dei comandi S: per ogni comando legge il valore attuale (Rxx) e lo
riscrive identico (Sxx = 'S' + risposta[1:]). Prima e dopo: snapshot completo.

  python3 tools/echo_test.py --host <IP> --lan-id <ID> --lan-password <PASSWORD>
poi:
  python3 fora_mv.py --diff snapshots/echo_before.json snapshots/echo_after.json
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fora_mv import MvClient, TcpTransport, snapshot  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--host", required=True)
ap.add_argument("--port", type=int, default=2010)
ap.add_argument("--lan-id")
ap.add_argument("--lan-password")
a = ap.parse_args()
OUT = os.path.join(ROOT, "snapshots")
READS = [
    "RUD001", "RSC", "RTL00", "RRT", "RAA0", "RAA1", "RAO01", "RVF", "RFO01",
    "RAC00101", "RTH00101", "RMP0101", "RTP0101", "RWP00101", "RDI0", "RLF0", "RAJ",
    "RST000", "RAS001", "RBC001", "RAE001", "RTC001", "RRE001", "RTG001", "RDD0",
]
EXTENDED = ["RAC10101", "RTT10101", "RTT10001", "RBD10100", "RBD00100", "RLD10101", "RDC0", "RDC1",
            "RTD0", "RCD"]

c = MvClient(TcpTransport(a.host, a.port, timeout=3.0), lan_id=a.lan_id,
             lan_password=a.lan_password, verbose=False)
t0 = time.time()
while True:
    try:
        c.connect()
        break
    except OSError as e:
        if time.time() - t0 > 600:
            raise SystemExit(f"porta ancora occupata dopo 10 minuti: {e}")
        time.sleep(5)
print(f"connesso dopo {time.time() - t0:.0f} s di attesa", flush=True)
snapshot(c, f"{OUT}/echo_before.json")

results = []
for r in READS:
    resp = c.send(r, quiet=True)
    if not resp.startswith("A"):
        results.append((r, resp, None, "lettura fallita"))
        continue
    s_cmd = "S" + resp[1:]
    s_resp = c.send(s_cmd, quiet=True)
    back = c.send(r, quiet=True)
    results.append((r, resp, s_cmd, s_resp, "uguale" if back == resp else f"DIVERSO: {back}"))
    print(f"{s_cmd:32} -> {s_resp:8} rilettura {'uguale' if back == resp else 'DIVERSA ' + back}", flush=True)

print("\n== letture estese (formato '1') ==")
for r in EXTENDED:
    print(f"{r:10} -> {c.send(r, quiet=True)}", flush=True)

time.sleep(1)
snapshot(c, f"{OUT}/echo_after.json")
c.close()
json.dump(results, open(f"{OUT}/echo_results.json", "w"), indent=1)
