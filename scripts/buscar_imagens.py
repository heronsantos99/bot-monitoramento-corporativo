#!/usr/bin/env python3
"""
REAVI — coletor de imagens (roda no GitHub Actions, que tem internet liberada).
Baixa 1 foto livre de direitos por categoria para imagens/<categoria>.jpg,
renovando a cada execução (variedade semanal), e grava os créditos.
NUNCA quebra o coletor: se a chave faltar ou uma busca falhar, segue em frente.
"""
import os, json, pathlib, random, urllib.request, urllib.parse, unicodedata, re, sys

# categoria (slug) -> termo de busca genérico em inglês (cenário/objeto, nunca pessoa/logo)
CATEGORIAS = {
    "bancario":     "bank building facade",
    "tributario":   "tax documents calculator",
    "stf":          "supreme court building",
    "judiciario":   "courthouse columns",
    "previdencia":  "elderly hands documents",
    "fintech":      "mobile payment phone",
    "credito":      "credit card finance",
    "m-a":          "corporate handshake skyscraper",
    "mercado":      "stock market screen",
    "balancos":     "financial charts office",
    "telecom":      "telecom tower antenna",
    "energia":      "power lines electricity",
    "cambio":       "currency exchange money",
    "antifraude":   "cyber security lock",
    "farmaceutico": "pharmaceutical laboratory",
    "congresso":    "parliament building brasilia",
}

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

def baixar(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()

def main():
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        print("PEXELS_API_KEY ausente — pulando busca de imagens (posts usarão fundo gráfico).")
        return 0

    out = pathlib.Path("imagens"); out.mkdir(exist_ok=True)
    creditos = {}
    if (out / "_creditos.json").exists():
        try: creditos = json.loads((out / "_creditos.json").read_text(encoding="utf-8"))
        except Exception: creditos = {}

    ok = 0
    for cat, termo in CATEGORIAS.items():
        try:
            q = urllib.parse.quote(termo)
            page = random.randint(1, 5)  # varia a foto a cada execução
            data = json.loads(baixar(
                f"https://api.pexels.com/v1/search?query={q}&per_page=10&orientation=portrait&page={page}",
                {"Authorization": key}))
            fotos = data.get("photos", [])
            if not fotos:
                print(f"  {cat}: nenhum resultado para '{termo}'"); continue
            ph = random.choice(fotos)
            img = baixar(ph["src"]["large"])
            (out / f"{cat}.jpg").write_bytes(img)
            creditos[cat] = f"Foto: {ph.get('photographer','')} / Pexels"
            ok += 1
            print(f"  ✓ {cat}.jpg  ({creditos[cat]})")
        except Exception as e:
            print(f"  {cat}: falhou ({e}) — mantém a foto anterior, se houver")

    (out / "_creditos.json").write_text(json.dumps(creditos, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Concluído: {ok}/{len(CATEGORIAS)} categorias atualizadas.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Erro geral (ignorado para não quebrar o coletor): {e}")
        sys.exit(0)
