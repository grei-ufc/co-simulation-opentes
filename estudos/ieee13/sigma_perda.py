"""Reducao do desvio-padrao medio das 5 barras PV por nivel de perda.

Media entre sementes, sobre as saidas do `./run.sh loss-multiseed`. Roda fora do
container (pandas e numpy).

Uso, a partir da raiz do repositorio:

    python3 estudos/ieee13/sigma_perda.py output/sensibilidade_perda_multiseed
"""
import re, sys, glob
from pathlib import Path
import numpy as np, pandas as pd
D = Path(sys.argv[1]); BUSES = ["646", "632", "634", "645", "652"]
def sig(f):
    df = pd.read_csv(f); out = []
    for b in BUSES:
        cs = [c for c in df.columns if f"Bus-{b}-" in c and "_pu" in c]
        out.append(df[cs].where(df[cs] > 0.5).mean(axis=1).std())
    return float(np.mean(out))
base = sig(D / "result_baseline.csv")
niveis = {}
for f in sorted(D.glob("result_loss*.csv")):
    m = re.match(r"result_loss(\d+)(?:_s\d+)?\.csv", f.name)
    niveis.setdefault(int(m.group(1)), []).append(sig(f))
print(f"baseline sigma medio {base:.4f}")
reds = {}
for k in sorted(niveis):
    v = np.array(niveis[k]); r = 100 * (1 - v / base); reds[k] = r.mean()
    print(f"  perda {k:3d}%  n={len(v):2d}  sigma {v.mean():.4f}  reducao {r.mean():5.1f}% (+-{r.std():.1f})")
est = [reds[k] for k in reds if 0 < k < 100]
print(f"niveis 5-95%: reducao de {min(est):.1f} a {max(est):.1f}%; 0%: {reds.get(0,float('nan')):.1f}%; 100%: {reds.get(100,float('nan')):.1f}%")
