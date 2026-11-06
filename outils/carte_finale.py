#!/usr/bin/env python3
"""Fond de la carte finale (1080x1920) : logo DKG réel en haut + « Réserve ton séjour sur ».

Le reste du texte (dkgguesthouse.com en grand, « À suivre… », « Personnages générés par IA »)
est posé par video4k.py monter, en postproduction. Le logo n'est jamais recréé : on recadre le
fichier fourni par DKG (fond #191919 identique au fond de la carte, donc raccord invisible).

  python3 outils/carte_finale.py [--logo assets/logo/dkg-guest-house.png] [-o assets/graphiques/carte-finale.png]
"""
import argparse, os
from PIL import Image, ImageDraw, ImageFont

W, H, FOND = 1080, 1920, (25, 25, 25)
POLICES = ["/usr/share/fonts/truetype/higgsfield/Montserrat-SemiBold.ttf",
           os.path.join(os.path.dirname(__file__), "..", "assets", "polices", "Montserrat-SemiBold.ttf")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logo", default="assets/logo/dkg-guest-house.png")
    ap.add_argument("--texte", default="Réserve ton séjour sur")
    ap.add_argument("--site", default="", help="ex. dkgguesthouse.com : dessiné en grand sous le texte")
    ap.add_argument("--suite", default="", help="ex. À suivre… : dessiné en couleur d'accent")
    ap.add_argument("--accent", default="#FF3130")
    ap.add_argument("-o", default="assets/graphiques/carte-finale.png")
    a = ap.parse_args()
    logo = Image.open(a.logo).convert("RGBA")
    lw, lh = logo.size
    sans_fond = logo.getextrema()[3][0] < 255  # version transparente : on garde tout le logo
    if not sans_fond:  # logo carré sur fond sombre : on garde la bande utile (pictogramme + nom)
        logo = logo.crop((0, int(lh * 0.33), lw, int(lh * 0.80)))
    cible = 980
    logo = logo.resize((cible, int(logo.size[1] * cible / logo.size[0])), Image.LANCZOS)
    carte = Image.new("RGBA", (W, H), FOND + (255,))
    y_logo = int(H * 0.14)
    carte.alpha_composite(logo, ((W - cible) // 2, y_logo))
    d = ImageDraw.Draw(carte)
    fp = next((p for p in POLICES if os.path.exists(p)), None)
    f = ImageFont.truetype(fp, 50) if fp else ImageFont.load_default()
    tw = d.textlength(a.texte, font=f)
    d.text(((W - tw) / 2, int(H * 0.435)), a.texte, font=f, fill=(255, 255, 255))
    fb = [p.replace("SemiBold", "ExtraBold") for p in POLICES]
    fpb = next((p for p in fb if os.path.exists(p)), fp)
    if a.site:
        fs = ImageFont.truetype(fpb, 84) if fpb else ImageFont.load_default()
        while fs.size > 40 and d.textlength(a.site, font=fs) > W - 120:
            fs = ImageFont.truetype(fpb, fs.size - 4)
        d.text(((W - d.textlength(a.site, font=fs)) / 2, int(H * 0.475)), a.site, font=fs, fill=(255, 255, 255))
    if a.suite:
        acc = tuple(int(a.accent.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        fa = ImageFont.truetype(fp, 54) if fp else ImageFont.load_default()
        d.text(((W - d.textlength(a.suite, font=fa)) / 2, int(H * 0.585)), a.suite, font=fa, fill=acc)
    os.makedirs(os.path.dirname(a.o) or ".", exist_ok=True)
    carte.convert("RGB").save(a.o)
    print(f"Carte finale (fond) : {a.o} — logo {'sans fond' if sans_fond else 'recadré'}")


if __name__ == "__main__":
    main()
