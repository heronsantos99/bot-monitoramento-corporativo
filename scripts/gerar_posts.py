#!/usr/bin/env python3
# REAVI · gerador de artes — JSON da LLM  ->  PNGs prontos pra postar
# uso: python3 gerar_posts.py leva.json ./saida

import json, sys, base64, pathlib, re, unicodedata
from playwright.sync_api import sync_playwright

W, H = 1080, 1350        # post 4:5
RW, RH = 1080, 1920      # reels/story 9:16
# procura as fontes na pasta "fontes/" do repo; se não achar, usa node_modules
_LOCAL = pathlib.Path(__file__).parent.parent / "fontes"
FONTS = _LOCAL if _LOCAL.exists() else pathlib.Path("node_modules/@fontsource")
_FLAT = _LOCAL.exists()

def font_face(fam, file, weight):
    p = (FONTS / pathlib.Path(file).name) if _FLAT else (FONTS / file)
    b64 = base64.b64encode(p.read_bytes()).decode()
    return (f"@font-face{{font-family:'{fam}';font-weight:{weight};font-style:normal;"
            f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}")

def build_fonts():
    css = []
    for w in (500, 700, 800, 900):
        css.append(font_face("Tektur", f"tektur/files/tektur-latin-{w}-normal.woff2", w))
    for w in (400, 500, 700):
        css.append(font_face("JetBrains Mono", f"jetbrains-mono/files/jetbrains-mono-latin-{w}-normal.woff2", w))
    for w in (400, 500, 600, 700):
        css.append(font_face("Space Grotesk", f"space-grotesk/files/space-grotesk-latin-{w}-normal.woff2", w))
    return "".join(css)

FUNDOS = {
 "pinho": dict(bg="#0F3D2C", fg="#EEF3E3", muted="#a9c1b4", ac="#C6F03A", acfg="#04140E",
               photo="linear-gradient(180deg,#134c35,#061c13)"),
 "bruma": dict(bg="#E7EEE4", fg="#0F3D2C", muted="#5b7365", ac="#0F8A55", acfg="#EEF3E3",
               photo="linear-gradient(180deg,#cfe0d5,#a8bfaf)"),
 "limao": dict(bg="#C6F03A", fg="#04140E", muted="#3d6a22", ac="#0F3D2C", acfg="#C6F03A",
               photo="linear-gradient(180deg,#bce62f,#8fbf1f)"),
}

ARROW = ('<svg class="ar" viewBox="0 0 24 24" fill="none" stroke="var(--ac)" stroke-width="2.4">'
         '<path d="M6 18 L18 6 M9 6 h9 v9"/></svg>')

def esc(s): return (s or "").replace("&", "&amp;").replace("<", "&lt;")

def titulo_html(p):
    t = esc(p.get("titulo", ""))
    d = esc(p.get("destaque", "")).strip()
    if not d:
        return t
    i = t.lower().find(d.lower())
    if i > -1:
        return t[:i] + f'<span class="hl">{t[i:i+len(d)]}</span>' + t[i+len(d):]
    return t + f' <span class="hl">{d}</span>'

def shell(fundo, inner, w=W, h=H, extra=""):
    f = FUNDOS[fundo]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{build_fonts()}
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{w}px;height:{h}px;overflow:hidden}}
body{{background:{f['bg']};color:{f['fg']};font-family:'Space Grotesk',sans-serif;
  --bg:{f['bg']};--fg:{f['fg']};--muted:{f['muted']};--ac:{f['ac']};--acfg:{f['acfg']};--photo:{f['photo']};
  display:flex;flex-direction:column;padding:76px 68px;position:relative}}
.kick{{font-family:'JetBrains Mono',monospace;font-size:30px;letter-spacing:.16em;text-transform:uppercase;
  background:var(--ac);color:var(--acfg);align-self:flex-start;padding:16px 32px;border-radius:999px;font-weight:700;z-index:3}}
h1{{font-family:'Tektur',sans-serif;font-weight:800;line-height:1.02;letter-spacing:-.01em}}
.hl{{background:var(--ac);color:var(--acfg);padding:0 16px;border-radius:14px;display:inline-block;transform:rotate(-1.6deg)}}
.foot{{display:flex;justify-content:space-between;align-items:center;margin-top:38px;z-index:3}}
.handle{{font-family:'JetBrains Mono',monospace;font-size:26px;letter-spacing:.06em;color:var(--ac)}}
.ar{{width:52px;height:52px}}
.photo{{position:absolute;inset:0;background:var(--photo);z-index:0}}
.photo::after{{content:"SUBSTITUA POR FOTO DA NOTICIA";position:absolute;top:44%;left:50%;
  transform:translate(-50%,-50%);font-family:'JetBrains Mono',monospace;font-size:24px;letter-spacing:.14em;
  color:rgba(238,243,227,.34);border:3px dashed rgba(238,243,227,.24);padding:24px 36px;border-radius:16px;white-space:nowrap}}
.body{{margin-top:auto;z-index:3}}
.sub{{font-size:34px;line-height:1.35;color:var(--muted);margin-top:24px;max-width:850px}}
{extra}
</style></head><body>{inner}</body></html>"""

def art_A(p):  # foto + manchete
    return shell(p["fundo"], f"""<div class="photo"></div>
<span class="kick">{esc(p['categoria'])}</span>
<div class="body"><h1 style="font-size:96px">{titulo_html(p)}</h1>
{f'<div class="sub">{esc(p["sub"])}</div>' if p.get("sub") else ""}
<div class="foot"><span class="handle">@reavi.br</span>{ARROW}</div></div>""")

def art_B(p):  # manchete gráfica
    return shell(p["fundo"], f"""
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:auto">
<span class="kick">{esc(p['categoria'])}</span>{ARROW}</div>
<h1 style="font-size:112px;margin-bottom:auto">{titulo_html(p)}</h1>
{f'<div class="sub">{esc(p["sub"])}</div>' if p.get("sub") else ""}
<div class="foot"><span class="handle">@reavi.br</span><span class="handle" style="opacity:.65">reavi.com.br</span></div>""")

def art_C(p):  # número
    return shell(p["fundo"], f"""
<div style="display:flex;justify-content:space-between;align-items:center">
<span class="kick">{esc(p['categoria'])}</span>{ARROW}</div>
<div style="font-family:'Tektur';font-weight:900;font-size:340px;line-height:.82;color:var(--ac);
  margin:auto 0 12px;letter-spacing:-.035em">{esc(p.get('big',''))}</div>
<div style="font-size:48px;line-height:1.28;max-width:840px">{esc(p.get('titulo',''))}</div>
{f'<div class="sub">{esc(p["sub"])}</div>' if p.get("sub") else ""}
<div class="foot"><span class="handle">@reavi.br</span><span class="handle" style="opacity:.65">reavi.com.br</span></div>""")

def art_D(p):  # contraponto
    return shell(p["fundo"], f"""
<span class="kick" style="margin-bottom:44px">{esc(p['categoria'])}</span>
<div style="padding-bottom:38px;border-bottom:4px solid color-mix(in srgb,var(--ac) 45%,transparent)">
  <div style="font-family:'JetBrains Mono';font-size:24px;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);margin-bottom:20px">A notícia</div>
  <div style="font-size:44px;line-height:1.25;color:var(--muted);font-weight:500">{esc(p.get('fato',''))}</div></div>
<div style="margin-top:44px;display:flex;flex-direction:column;flex:1">
  <div style="font-family:'JetBrains Mono';font-size:24px;letter-spacing:.16em;text-transform:uppercase;color:var(--ac);margin-bottom:22px">O que ninguém disse</div>
  <h1 style="font-size:82px">{titulo_html(p)}</h1>
  <div class="foot" style="margin-top:auto"><span class="handle">@reavi.br</span>{ARROW}</div></div>""")

def art_reels(p):
    return shell(p["fundo"], f"""<div class="photo"></div>
<span class="kick">{esc(p['categoria'])}</span>
<div class="body">
<span style="font-family:'JetBrains Mono';font-size:22px;letter-spacing:.2em;color:var(--ac);display:block;margin-bottom:20px">REELS</span>
<h1 style="font-size:100px">{titulo_html(p)}</h1>
<div class="foot"><span class="handle">@reavi.br</span>{ARROW}</div></div>""", w=RW, h=RH)

def art_slide(p, s, i, n):
    capa = (i == 0)
    fundo = p["fundo"] if capa else ("bruma" if i % 2 else "pinho")
    top = f"""<div style="display:flex;justify-content:space-between;align-items:center">
<span class="kick">{esc(p['categoria']) if capa else esc(s['tag'])}</span>
<span style="font-family:'JetBrains Mono';font-size:26px;color:var(--ac);opacity:.85">{i+1} / {n}</span></div>"""
    if capa:
        mid = (f'<h1 style="font-size:104px;margin-top:auto">{titulo_html(p)}</h1>'
               '<div style="font-family:\'JetBrains Mono\';font-size:26px;color:var(--ac);letter-spacing:.12em;margin-top:34px">arrasta →</div>')
    else:
        mid = (f'<div style="flex:1;display:flex;align-items:center">'
               f'<div style="font-size:58px;line-height:1.30;font-weight:500">{esc(s["texto"])}</div></div>')
    return shell(fundo, top + mid + f"""
<div class="foot" style="margin-top:auto"><span class="handle">@reavi.br</span>{ARROW}</div>""")

def regra_de_ouro(posts):
    """nunca dois 'limao' colados"""
    r = list(posts)
    for k in range(1, len(r)):
        if r[k]["fundo"] == "limao" and r[k-1]["fundo"] == "limao":
            for m in range(k+1, len(r)):
                if r[m]["fundo"] != "limao":
                    r[k], r[m] = r[m], r[k]
                    break
    return r

def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:28] or "post"

def launch_chromium(pw):
    """Abre o Chromium. Se o Playwright não achar o dele (download bloqueado em
    alguns ambientes), procura um Chromium já instalado na máquina."""
    try:
        return pw.chromium.launch()
    except Exception as e:
        import glob, shutil
        candidatos = []
        for padrao in ("/opt/pw-browsers/chromium*/chrome-linux/chrome",
                       "/root/.cache/ms-playwright/chromium*/chrome-linux/chrome",
                       "/ms-playwright/chromium*/chrome-linux/chrome"):
            candidatos += glob.glob(padrao)
        for nome in ("chromium", "chromium-browser", "google-chrome", "chrome"):
            achado = shutil.which(nome)
            if achado:
                candidatos.append(achado)
        for c in candidatos:
            try:
                print(f"  (usando Chromium do sistema: {c})")
                return pw.chromium.launch(executable_path=c)
            except Exception:
                continue
        raise RuntimeError(
            "Não encontrei um Chromium utilizável. Rode: playwright install chromium\n"
            f"Erro original: {e}")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "leva.json"
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "saida"); out.mkdir(parents=True, exist_ok=True)
    posts = regra_de_ouro(json.load(open(src, encoding="utf-8")))
    jobs = []
    for idx, p in enumerate(posts, 1):
        a = p.get("arquetipo")
        base = f"{idx:02d}_{slug(p['categoria'])}"
        if a == "CARROSSEL":
            n = len(p.get("carrossel", []))
            for i, s in enumerate(p["carrossel"]):
                jobs.append((f"{base}_slide{i+1}", art_slide(p, s, i, n), W, H))
        elif a == "REELS":
            jobs.append((f"{base}_reels_capa_PRECISA-FOTO", art_reels(p), RW, RH))
        else:
            nm = base + ("_PRECISA-FOTO" if a == "A" else "")
            jobs.append((nm, {"A": art_A, "B": art_B, "C": art_C, "D": art_D}[a](p), W, H))

    with sync_playwright() as pw:
        b = launch_chromium(pw)
        for name, html, w, h in jobs:
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            pg.set_content(html, wait_until="load")
            pg.wait_for_timeout(260)
            pg.screenshot(path=str(out / f"{name}.png"))
            pg.close()
            print("✓", name, f"{w}x{h}")
        b.close()

    # legendas em texto
    with open(out / "legendas.txt", "w", encoding="utf-8") as f:
        for idx, p in enumerate(posts, 1):
            f.write(f"{'='*60}\n#{idx:02d} · {p['categoria']} · {p.get('formato','')}\n{'='*60}\n")
            f.write((p.get("legenda") or "") + "\n\n")
            if p.get("hashtags"): f.write(" ".join(p["hashtags"]) + "\n")
            if p.get("reels_roteiro"): f.write("\n[ROTEIRO REELS]\n" + p["reels_roteiro"] + "\n")
            f.write("\n")
    print("✓ legendas.txt")

if __name__ == "__main__":
    main()
