#!/usr/bin/env python3
"""Vidéo 4K 2.0 — moteur de préparation, de montage, d'export et de contrôle.

Le moteur ne génère aucune image par IA : la génération passe par l'outil relié (ex. Higgsfield),
avec accord sur le coût. Il prépare, assemble, exporte et contrôle — en local, sans frais.

Commandes
  audit                                   outils locaux disponibles (FFmpeg, encodeurs, filtres, polices)
  valider     projet.json                 contrôle le projet (stratégie, scènes, faits, droits, formats)
  dossier     projet.json [-o dossier.md] dossier de production complet en Markdown
  srt         projet.json [-o fichier]    sous-titres de la voix off (.srt ; .vtt si l'extension l'indique)
  animatique  projet.json [-o out.mp4] [--format NOM] [--voix fichier]
                                          animatique réelle (storyboard animé, filigrane « ANIMATIQUE »)
  monter      projet.json --plans DOSSIER [-o master.mp4] [--format NOM] [--voix F] [--musique F]
              [--logo F] [--sous-titres] [--brouillon]
                                          assemble les plans réels (S1.mp4 / S1.png…) en master
  exporter    master.mp4 --preset P [-o DOSSIER] [--projet projet.json]
              presets : master-4k, archive-h265, web-hero, web-presentation, social-916, social-45, social-11
  controler   fichier.mp4 [--ratio 16:9] [--resolution 3840x2160] [--duree S] [--budget-mo N]
              [--sans-son] [--lufs -16] [--json]

Codes de sortie : 0 = conforme, 1 = erreurs, 2 = outil manquant ou entrée invalide.
"""
import argparse, json, math, os, re, shutil, subprocess, sys, tempfile, textwrap, unicodedata
from datetime import date

VERSION = "1.0 (2026-10-13)"
STRATEGIES = {"conversion", "presentation", "storytelling", "service", "premium", "educative", "reciblage"}
CANAUX = {  # (duree min, duree max, son autorise, cta dans la video attendu)
    "site-hero": (5, 15, False, False),
    "site-presentation": (20, 120, True, True),
    "page-service": (15, 90, True, True),
    "pres-cta": (10, 45, True, True),
    "pub-sociale": (6, 45, True, True),
    "reciblage": (6, 20, True, True),
    "presentation-entreprise": (30, 180, True, True),
}
SOURCES = {"generation", "client", "banque", "graphique", "prise_de_vue"}
FONCTIONS = {"accroche", "probleme", "solution", "benefice", "demonstration", "preuve", "identite",
             "ambiance", "objection", "transition", "cta"}
RATIOS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5), "21:9": (21, 9)}
UHD = {"16:9": (3840, 2160), "9:16": (2160, 3840), "1:1": (2160, 2160), "4:5": (2160, 2700), "21:9": (3840, 1646)}
MUSIQUE_OK = {"fournie_client", "licenciee", "libre_verifiee", "aucune", "originale"}
AFFIRMATIONS = [  # motifs qui exigent un fait vérifié correspondant
    r"\bgaranti\w*", r"\bcertifi\w*", r"\bn[°o] ?1\b", r"\bnumero un\b", r"\ble meilleur\b", r"\bla meilleure\b",
    r"\bmeilleurs?\b", r"\d+ ?%", r"\bdepuis (19|20)\d\d\b", r"\b\d+ ?ans d'experience\b", r"\b\d+ ?(etoiles|avis)\b",
    r"\bprimee?\b", r"\baccredite\w*\b", r"\bagree\w*\b", r"\bplus rapide\b", r"\bmoins cher\b", r"\bprix\b",
    r"\$", r"\bgratuit\w*\b", r"\b24 ?h\b", r"\b24/7\b", r"\burgence\w*\b", r"\bsans engagement\b", r"\bsans frais\b",
    r"\ben \d+ (minutes|heures|jours)\b", r"\bsatisfaction\b", r"\bassure\w*\b", r"\bexpert\w*\b", r"\bspecialiste\w*\b",
]
ANIM_TAG = "ANIMATIQUE — prévisualisation, pas la vidéo finale"
LIBELLES = {"accroche": "Accroche", "probleme": "Problème", "solution": "Solution", "benefice": "Bénéfice",
            "demonstration": "Démonstration", "preuve": "Preuve", "identite": "Identité", "ambiance": "Ambiance",
            "objection": "Objection", "transition": "Transition", "cta": "Appel à l'action"}


# ---------------------------------------------------------------- utilitaires
def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower().replace("’", "'")


def die(msg, code=2):
    print(f"ERREUR : {msg}", file=sys.stderr)
    sys.exit(code)


def need(tool):
    if not shutil.which(tool):
        die(f"{tool} introuvable. Installer FFmpeg (Windows : winget install ffmpeg ; Mac : brew install ffmpeg).")


def run(cmd, quiet=True):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        die(f"commande échouée : {' '.join(cmd[:6])}…\n{tail}", 1)
    return p


def charger(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        die(f"fichier introuvable : {path}")
    except json.JSONDecodeError as e:
        die(f"JSON invalide dans {path} : {e}")


def scenes(p):
    return p.get("scenes", [])


def duree_totale(p):
    return round(sum(float(s.get("duree", 0)) for s in scenes(p)), 2)


def format_par_nom(p, nom=None):
    fmts = p.get("formats") or [{"nom": "principal", "ratio": "16:9", "resolution_cible": "3840x2160"}]
    if nom:
        for f in fmts:
            if f.get("nom") == nom or f.get("ratio") == nom:
                return f
        die(f"format « {nom} » absent du projet (disponibles : {', '.join(x.get('nom', '?') for x in fmts)})")
    return fmts[0]


def wh(fmt, defaut_ratio="16:9"):
    res = str(fmt.get("resolution_cible") or "")
    m = re.match(r"^(\d+)x(\d+)$", res)
    if m:
        return int(m.group(1)), int(m.group(2))
    return UHD.get(fmt.get("ratio", defaut_ratio), UHD["16:9"])


def ratio_de(w, h):
    g = math.gcd(w, h)
    r = f"{w // g}:{h // g}"
    for k, (a, b) in RATIOS.items():
        if abs(w / h - a / b) < 0.01:
            return k
    return r


def fr(x):
    """Nombre au format français (3,5)."""
    return f"{float(x):g}".replace(".", ",")


def maj(t):
    t = str(t or "").strip()
    return t[:1].upper() + t[1:]


ETATS = {"prepare": "préparé", "animatique": "animatique", "rendu": "rendu", "controle": "contrôlé"}
SOURCES_LIB = {"generation": "génération", "client": "médias du client", "prise_de_vue": "prise de vue", "banque": "banque d'images", "graphique": "graphique"}


def mots(t):
    return len(re.findall(r"[\wÀ-ÿ'’-]+", t or ""))


def tc(sec, sep=","):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def police(gras=True):
    cands = ["/usr/share/fonts/opentype/inter/Inter-Bold.otf" if gras else "/usr/share/fonts/opentype/inter/Inter-Medium.otf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if gras else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
             "/Library/Fonts/Arial Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf"]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def nom_police_ass():
    p = subprocess.run(["fc-list", ":family"], capture_output=True, text=True) if shutil.which("fc-list") else None
    fam = p.stdout if p else ""
    for f in ("Inter", "DejaVu Sans", "Arial"):
        if f in fam:
            return f
    return "Sans"


def ffprobe(path):
    need("ffprobe")
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    return json.loads(p.stdout)


# ---------------------------------------------------------------- audit
def cmd_audit(a):
    print(f"Vidéo 4K 2.0 — moteur {VERSION}\n")
    ok = True
    for t in ("ffmpeg", "ffprobe"):
        chemin = shutil.which(t)
        print(f"  {'✓' if chemin else '✗'} {t:<9} {chemin or 'absent — requis pour animatique, montage, export, contrôle'}")
        ok &= bool(chemin)
    if shutil.which("ffmpeg"):
        v = subprocess.run(["ffmpeg", "-hide_banner", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        fil = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        mux = subprocess.run(["ffmpeg", "-hide_banner", "-muxers"], capture_output=True, text=True).stdout
        print(f"    {v}")
        for e, role in [("libx264", "MP4 H.264 (master, web)"), ("libx265", "H.265 (archive)"), ("libvpx-vp9", "WebM VP9 (web)"),
                        ("libsvtav1", "AV1 (option web)"), ("aac", "audio AAC"), ("libopus", "audio Opus (WebM)"),
                        ("libwebp", "poster WebP")]:
            present = "✓" if re.search(r"\b" + re.escape(e) + r"\b", enc) else "✗"
            print(f"    {present} {e:<11} {role}")
        for f, role in [("subtitles", "textes et sous-titres incrustés (libass)"), ("xfade", "fondus entre plans"),
                        ("loudnorm", "normalisation du son"), ("sidechaincompress", "atténuation musique sous la voix"),
                        ("zscale", "mise à l'échelle haute qualité"), ("freezedetect", "contrôle des images figées"),
                        ("blackdetect", "contrôle des noirs")]:
            present = "✓" if re.search(r"\b" + f + r"\b", fil) else "✗"
            print(f"    {present} {f:<17} {role}")
        present = "✓" if re.search(r"\bavif\b", mux) else "✗"
        print(f"    {present} avif              poster AVIF")
    try:
        import PIL  # noqa
        print("  ✓ Pillow     images de l'animatique")
    except ImportError:
        print("  ✗ Pillow     requis pour l'animatique (pip install pillow)")
        ok = False
    print(f"  {'✓' if police() else '✗'} police      {police() or 'aucune police connue trouvée'}")
    print("\n  Génération IA (vidéo, image, voix) : non vérifiable par ce script.")
    print("  → Claude vérifie les outils reliés dans la session (ex. Higgsfield : balance, models_explore, get_cost).")
    return 0 if ok else 2


# ---------------------------------------------------------------- validation
def valider(p):
    E, A, I = [], [], []
    b = p.get("brief", {})
    for k in ("entreprise", "secteur", "objectif_commercial", "action_spectateur", "canal", "strategie", "cible", "promesse"):
        if not b.get(k):
            E.append(f"brief.{k} manquant")
    canal = b.get("canal", "")
    if canal and canal not in CANAUX:
        E.append(f"canal « {canal} » inconnu ({', '.join(sorted(CANAUX))})")
    strat = [s.strip() for s in str(b.get("strategie", "")).split("+") if s.strip()]
    for s in strat:
        if s not in STRATEGIES:
            E.append(f"stratégie « {s} » inconnue ({', '.join(sorted(STRATEGIES))})")
    if not b.get("kpi"):
        A.append("brief.kpi absent : préciser l'indicateur de performance (clic sur le CTA, demandes de soumission…)")
    if str(b.get("langue", p.get("projet", {}).get("langue", "fr"))).lower()[:2] != "fr":
        A.append("Langue autre que le français : au Québec, une version française est exigée pour la publicité commerciale")
    if b.get("public_moins_13_ans"):
        E.append("Publicité destinée aux moins de 13 ans : interdite au Québec (Loi sur la protection du consommateur)")

    faits = p.get("faits", [])
    verifies = [norm(f.get("texte", "")) for f in faits if f.get("statut") == "verifie"]
    statut_fait = {f.get("id"): f.get("statut") for f in faits if f.get("id")}
    R = []  # réserves qui empêchent la production finale (mais pas la préparation)
    for f in faits:
        if f.get("statut") not in {"verifie", "hypothese", "a_fournir"}:
            E.append(f"fait « {f.get('texte', '')[:40]} » : statut verifie / hypothese / a_fournir requis")
        if f.get("statut") == "verifie" and not f.get("source"):
            E.append(f"fait vérifié sans source : « {f.get('texte', '')[:50]} »")

    sc = scenes(p)
    if not sc:
        E.append("aucune scène")
    total = duree_totale(p)
    if canal in CANAUX:
        mn, mx, son_ok, cta_attendu = CANAUX[canal]
        if not (mn <= total <= mx):
            E.append(f"durée totale {total} s hors plage pour « {canal} » ({mn} à {mx} s)")
        if not son_ok and (p.get("voix_off", {}).get("active") or (p.get("direction_artistique", {}).get("musique", {}).get("statut") not in (None, "aucune"))):
            E.append("site-hero : vidéo muette en lecture automatique — pas de voix off ni de musique")
        if cta_attendu and sc and sc[-1].get("fonction") != "cta":
            E.append("la dernière scène doit porter l'appel à l'action (fonction « cta »)")
        if not cta_attendu and any(s.get("fonction") == "cta" for s in sc):
            A.append("site-hero : le CTA vit dans la page (bouton HTML), pas dans la vidéo")
    ids = set()
    for i, s in enumerate(sc, 1):
        sid = s.get("id", f"#{i}")
        if sid in ids:
            E.append(f"{sid} : identifiant en double")
        ids.add(sid)
        d = float(s.get("duree", 0) or 0)
        if d <= 0:
            E.append(f"{sid} : durée manquante")
        elif d < 1.2:
            A.append(f"{sid} : {d} s, très court — lisible ?")
        elif s.get("source") == "generation" and d > 10:
            E.append(f"{sid} : {d} s générés d'un bloc — découper en plans courts (≤ 10 s)")
        for k in ("fonction", "action", "plan", "source"):
            if not s.get(k):
                E.append(f"{sid} : champ « {k} » manquant")
        if s.get("fonction") and s["fonction"] not in FONCTIONS:
            A.append(f"{sid} : fonction « {s['fonction']} » non standard")
        if s.get("source") and s["source"] not in SOURCES:
            E.append(f"{sid} : source « {s['source']} » inconnue ({', '.join(sorted(SOURCES))})")
        if s.get("source") == "generation":
            pr = s.get("prompt") or {}
            manq = [k for k in ("sujet", "environnement", "action", "cadrage", "lumiere", "mouvement", "style", "eviter") if not pr.get(k)]
            if manq:
                E.append(f"{sid} : prompt incomplet ({', '.join(manq)})")
            ev = norm(" ".join(pr.get("eviter", [])) if isinstance(pr.get("eviter"), list) else pr.get("eviter", ""))
            if pr and not ("texte" in ev and "logo" in ev):
                E.append(f"{sid} : le prompt doit exclure texte et logos (ajoutés en postproduction)")
            if s.get("represente_entreprise_reelle"):
                E.append(f"{sid} : une image générée ne peut pas représenter les vrais locaux, l'équipe, les produits ou les réalisations du client — utiliser ses médias ou une prise de vue")
        te = s.get("texte_ecran", "")
        if te:
            limite = max(3, int(d * 2.2))
            if mots(te) > limite:
                E.append(f"{sid} : texte à l'écran trop long ({mots(te)} mots en {d} s, max {limite})")
        vo = s.get("voix_off", "")
        if vo and d:
            vitesse = mots(vo) / d
            if vitesse > 2.8:
                E.append(f"{sid} : voix off trop dense ({mots(vo)} mots en {d} s ; max ≈ 2,6 mots/s en français)")
            elif vitesse > 2.5:
                A.append(f"{sid} : voix off rapide ({vitesse:.1f} mots/s)")
        for champ in (te, vo):
            n = norm(champ)
            for motif in AFFIRMATIONS:
                for m in re.finditer(motif, n):
                    jeton = m.group(0).strip()
                    if not any(jeton in v for v in verifies):
                        E.append(f"{sid} : affirmation « {jeton} » sans fait vérifié correspondant (section faits)")
        for fid in s.get("faits_utilises", []):
            st = statut_fait.get(fid)
            if st is None:
                E.append(f"{sid} : fait « {fid} » référencé mais absent de la section faits")
            elif st != "verifie":
                R.append(f"{sid} s'appuie sur {fid} ({'hypothèse' if st == 'hypothese' else 'à fournir'})")
    cta = p.get("cta", {})
    if canal in CANAUX and CANAUX[canal][3]:
        if not cta.get("texte"):
            E.append("cta.texte manquant")
        if cta.get("statut") != "verifie":
            R.append("coordonnées du CTA non vérifiées")
    mus = p.get("direction_artistique", {}).get("musique", {})
    if mus and mus.get("statut") not in MUSIQUE_OK:
        R.append(f"musique « {mus.get('statut', 'non précisée')} » : licence à confirmer")
    if mus.get("statut") in {"licenciee", "libre_verifiee"} and not mus.get("licence"):
        E.append("musique déclarée licenciée sans référence de licence")
    logo = p.get("direction_artistique", {}).get("logo", {})
    if logo and logo.get("statut") not in {"fourni_client", "aucun"}:
        R.append("logo non fourni par le client (ne jamais le recréer ni le générer)")
    for s in sc:
        if s.get("source") in {"client", "prise_de_vue"} and s.get("statut_media") != "disponible":
            R.append(f"{s.get('id')} : média {s.get('source').replace('_', ' ')} à obtenir")
    prod = p.get("production", {})
    gen = str(prod.get("resolution_generation", "")).lower()
    for f in p.get("formats", []):
        w, h = wh(f)
        if f.get("ratio") and f["ratio"] in RATIOS and ratio_de(w, h) != f["ratio"]:
            E.append(f"format {f.get('nom')} : {w}x{h} ne correspond pas au ratio {f['ratio']}")
        if max(w, h) >= 3840 and gen and gen not in {"4k", "2160p"}:
            I.append(f"format {f.get('nom')} en {w}x{h} depuis une génération {gen} : mise à l'échelle, pas de 4K native — à annoncer comme tel")
    if any(s.get("source") == "generation" for s in sc) and not prod.get("outil_video"):
        A.append("production.outil_video non précisé (modèle et coût à confirmer avant génération)")
    I = R and [f"RÉSERVE — {r}" for r in R] + I or I
    return E, A, I


def pret(E, I):
    if E:
        return "À CORRIGER"
    if any(x.startswith("RÉSERVE") for x in I):
        return "PRÊT POUR LA PRÉPARATION (pas encore pour la production finale)"
    return "PRÊT À PRODUIRE"


def cmd_valider(a):
    p = charger(a.projet)
    E, A, I = valider(p)
    print(f"== {os.path.basename(a.projet)} — {len(scenes(p))} scènes, {duree_totale(p)} s, canal {p.get('brief', {}).get('canal', '?')}")
    for e in E:
        print(f"  ERREUR        {e}")
    for x in A:
        print(f"  AVERTISSEMENT {x}")
    for x in I:
        if x.startswith("RÉSERVE — "):
            print(f"  RÉSERVE       {x[10:]}")
        else:
            print(f"  INFO          {x}")
    print("  => " + (pret(E, I) if not E else f"À CORRIGER ({len(E)} erreur(s))"))
    return 1 if E else 0


# ---------------------------------------------------------------- sous-titres
def equilibrer(texte, largeur=42):
    """Coupe en deux lignes de longueurs proches (pas de mot orphelin)."""
    if len(texte) <= largeur:
        return [texte]
    espaces = [i for i, c in enumerate(texte) if c == " "]
    meilleur = min(espaces, key=lambda i: abs(len(texte) / 2 - i)) if espaces else len(texte) // 2
    return [texte[:meilleur].strip(), texte[meilleur:].strip()]


def couper(texte, largeur=42, lignes=2):
    """Blocs d'au plus deux lignes équilibrées de `largeur` caractères, coupés de préférence après une ponctuation."""
    if len(texte) <= largeur * lignes:
        l2 = equilibrer(texte, largeur)
        if all(len(x) <= largeur for x in l2):
            return [l2]
    phrases = [x.strip() for x in re.split(r"(?<=[.!?…;:])\s+", texte) if x.strip()]
    blocs, cour = [], ""
    for ph in phrases:
        essai = (cour + " " + ph).strip()
        if len(essai) <= largeur * lignes - 6:
            cour = essai
        else:
            if cour:
                blocs.append(cour)
            cour = ph
    if cour:
        blocs.append(cour)
    out = []
    for b in blocs:
        morceaux = textwrap.wrap(b, largeur)
        for i in range(0, len(morceaux), lignes):
            out.append(equilibrer(" ".join(morceaux[i:i + lignes]), largeur))
    return out


def cues(p):
    out, t = [], 0.0
    for s in scenes(p):
        d = float(s.get("duree", 0))
        vo = (s.get("voix_off") or "").strip()
        if vo:
            blocs = couper(vo)
            debut = t + min(0.15, d * 0.05)
            fin_dispo = t + d - 0.1
            part = (fin_dispo - debut) / len(blocs)
            for k, bl in enumerate(blocs):
                out.append((debut + k * part, debut + (k + 1) * part, "\n".join(bl)))
        t += d
    return out


def ecrire_srt(p, chemin):
    vtt = chemin.lower().endswith(".vtt")
    with open(chemin, "w", encoding="utf-8") as f:
        if vtt:
            f.write("WEBVTT\n\n")
        for i, (d, fn, txt) in enumerate(cues(p), 1):
            sep = "." if vtt else ","
            f.write(f"{i}\n{tc(d, sep)} --> {tc(fn, sep)}\n{txt}\n\n")
    return chemin


def cmd_srt(a):
    p = charger(a.projet)
    sortie = a.o or os.path.splitext(a.projet)[0] + ".srt"
    ecrire_srt(p, sortie)
    print(f"Sous-titres : {sortie} ({len(cues(p))} blocs)")
    return 0


# ---------------------------------------------------------------- dossier
def cmd_dossier(a):
    p = charger(a.projet)
    E, A, I = valider(p)
    b, da = p.get("brief", {}), p.get("direction_artistique", {})
    pr = p.get("projet", {})
    L = []
    w = L.append
    w(f"# Dossier de production — {b.get('entreprise', '?')}")
    w(f"\nProjet `{pr.get('id', '?')}` · version {pr.get('version', 1)} · généré le {date.today().isoformat()} par Vidéo 4K 2.0")
    statut = ETATS.get(p.get("production", {}).get("statut", "prepare"), p.get("production", {}).get("statut"))
    w(f"\n> **État réel : {statut}.** Ce dossier est une préparation de production. Il ne contient aucune vidéo rendue, "
      "sauf les fichiers listés dans la section « Fichiers réellement produits ».")
    if E:
        w("\n> ⚠️ Le projet comporte des erreurs à corriger avant production : " + " ; ".join(E))
    w("\n## 1. Brief")
    for k, lab in [("entreprise", "Entreprise"), ("secteur", "Secteur"), ("offre", "Offre"), ("cible", "Public cible"),
                   ("objectif_commercial", "Objectif commercial"), ("action_spectateur", "Action attendue du spectateur"),
                   ("canal", "Canal de diffusion"), ("placement", "Placement conseillé")]:
        if b.get(k):
            w(f"- **{lab}** : {b[k]}")
    w("\n## 2. Stratégie")
    for k, lab in [("strategie", "Stratégie"), ("justification", "Pourquoi"), ("promesse", "Promesse centrale"),
                   ("accroche", "Accroche"), ("benefice", "Bénéfice principal"), ("kpi", "Indicateur de performance"),
                   ("test_ab", "Test A/B proposé")]:
        if b.get(k):
            w(f"- **{lab}** : {b[k]}")
    if b.get("objections"):
        w("- **Objections traitées** : " + " ; ".join(b["objections"]))
    w("\n### Faits utilisés")
    w("| Fait | Statut | Source |\n|---|---|---|")
    for f in p.get("faits", []):
        lab = {"verifie": "vérifié", "hypothese": "hypothèse", "a_fournir": "à fournir"}.get(f.get("statut"), "?")
        w(f"| {f.get('texte', '')} | {lab} | {f.get('source', '—')} {f.get('date', '')} |")
    w("\n## 3. Concept et direction artistique")
    for k, lab in [("idee", "Idée créative"), ("style", "Style visuel"), ("emotion", "Ambiance et émotion"), ("lumiere", "Lumière"),
                   ("cameras", "Mouvements de caméra"), ("rythme", "Rythme du montage"), ("transitions", "Transitions"),
                   ("typo", "Typographie"), ("son", "Traitement sonore")]:
        v = da.get(k)
        if v:
            w(f"- **{lab}** : {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}")
    if da.get("palette"):
        w("- **Palette** : " + ", ".join(f"`{c}`" for c in da["palette"]))
    for alt in p.get("concepts_alternatifs", []):
        w(f"- **Concept alternatif** : {alt}")
    w("\n## 4. Scénario minuté")
    w("| # | Temps | Durée | Fonction | Action visible | Plan · mouvement | Texte à l'écran | Voix off | Son | Source |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    t = 0.0
    for s in scenes(p):
        d = float(s.get("duree", 0))
        w(f"| {s.get('id')} | {tc(t, '.')[3:8]} | {fr(d)} s | {LIBELLES.get(s.get('fonction', ''), s.get('fonction', ''))} | {s.get('action', '')} | "
          f"{s.get('plan', '')} · {s.get('mouvement', '')} | {s.get('texte_ecran', '') or '—'} | {s.get('voix_off', '') or '—'} | "
          f"{s.get('son', '') or '—'} | {SOURCES_LIB.get(s.get('source', ''), s.get('source', ''))} |")
        t += d
    w(f"\n**Durée totale : {fr(duree_totale(p))} s.**")
    w("\n## 5. Storyboard et prompts de génération (par scène)")
    for s in scenes(p):
        w(f"\n### {s.get('id')} — {LIBELLES.get(s.get('fonction', ''), s.get('fonction', ''))} ({fr(s.get('duree', 0))} s)")
        w(f"- **Ce qu'on voit** : {s.get('action', '')}")
        w(f"- **Cadrage** : {s.get('plan', '')} · **Mouvement** : {s.get('mouvement', '')} · **Transition sortante** : {s.get('transition', 'coupe')}")
        if s.get("source") == "generation":
            pr_ = s.get("prompt", {})
            ev = pr_.get("eviter", [])
            ev = ", ".join(ev) if isinstance(ev, list) else ev
            coh = pr_.get("coherence", [])
            coh = "; ".join(coh) if isinstance(coh, list) else coh
            txt = (f"{maj(pr_.get('sujet', ''))}. {maj(pr_.get('environnement', ''))}. {maj(pr_.get('action', ''))}. Cadrage : {pr_.get('cadrage', '')}. "
                   f"Lumière : {pr_.get('lumiere', '')}. Mouvement de caméra : {pr_.get('mouvement', '')}. Style : {pr_.get('style', '')}. "
                   f"Durée : {fr(s.get('duree', 0))} secondes, un seul plan continu, sans coupe."
                   + (f" Cohérence : {coh}." if coh else "") + f" À éviter : {ev}.")
            w(f"- **Prompt (génération)** :\n\n```\n{txt}\n```")
            if pr_.get("prompt_en"):
                w(f"- **Prompt (anglais, pour le modèle)** :\n\n```\n{pr_['prompt_en']}\n```")
        else:
            w(f"- **Source** : {SOURCES_LIB.get(s.get('source'), s.get('source'))} — {s.get('note_source', 'média à fournir ou à tourner')}")
    w("\n## 6. Voix off (texte intégral)")
    vo = p.get("voix_off", {})
    if vo.get("active"):
        w(f"Voix : {vo.get('voix', 'à choisir')} · outil : {vo.get('outil', 'à confirmer')} · statut : {vo.get('statut', 'à produire')}\n")
        for s in scenes(p):
            if s.get("voix_off"):
                w(f"> **{s.get('id')}** — {s['voix_off']}")
    else:
        w("Sans voix off.")
    w("\n## 7. Textes à l'écran et appel à l'action")
    for s in scenes(p):
        if s.get("texte_ecran"):
            w(f"- {s.get('id')} : « {s['texte_ecran']} »")
    cta = p.get("cta", {})
    if cta:
        w(f"- **CTA** : « {cta.get('texte', '')} » — coordonnées : {cta.get('coordonnees', '—')} ({cta.get('statut', 'à vérifier')})")
    w("\nLes textes, logos et coordonnées sont ajoutés **en postproduction**, jamais générés dans l'image.")
    w("\n## 8. Musique, son et ressources")
    mus = da.get("musique", {})
    w(f"- **Musique** : {mus.get('description', '—')} · source : {mus.get('source', '—')} · licence : {mus.get('licence', '—')} · statut : {mus.get('statut', 'à trouver')}")
    w("- Mixage : voix au premier plan, musique atténuée sous la voix (≈ −18 dB), normalisation −16 LUFS (web) ou −14 LUFS (réseaux sociaux).")
    w("\n| Ressource | Fournisseur | Droits connus | Statut |\n|---|---|---|---|")
    for r in p.get("ressources", []):
        w(f"| {r.get('nom', '')} | {r.get('source', '')} | {r.get('droits', '')} | {r.get('statut', '')} |")
    w("\n## 9. Formats, résolution et export")
    gen = p.get("production", {}).get("resolution_generation", "?")
    w("| Format | Ratio | Résolution cible | Usage | Origine des pixels |\n|---|---|---|---|---|")
    for f in p.get("formats", []):
        W, H = wh(f)
        native = "4K native" if str(gen).lower() in {"4k", "2160p"} else f"génération {gen} → mise à l'échelle"
        w(f"| {f.get('nom')} | {f.get('ratio')} | {W}×{H} | {f.get('usage', '')} | {native if max(W, H) >= 3840 else 'conforme'} |")
    w("\nExports prévus (moteur) : `exporter master.mp4 --preset master-4k | web-hero | web-presentation | social-916 | social-45 | social-11`.")
    w("\n## 10. Production et coûts")
    pd = p.get("production", {})
    for k, lab in [("outil_video", "Outil vidéo"), ("outil_image", "Outil image"), ("resolution_generation", "Résolution de génération"),
                   ("cout_estime_credits", "Coût estimé (crédits, mesuré par get_cost)"), ("mesure_le", "Coût mesuré le"),
                   ("statut", "Statut")]:
        if pd.get(k) not in (None, ""):
            w(f"- **{lab}** : {pd[k]}")
    w("- **Règle** : aucune génération payante sans accord explicite de Pavel sur le montant.")
    if p.get("integration_web"):
        iw = p["integration_web"]
        w("\n## 11. Intégration web")
        for k, v in iw.items():
            w(f"- **{k}** : {v}")
    w("\n## 12. Contrôle qualité")
    w(f"- Verdict du moteur : **{pret(E, I)}**" + (f" · {len(E)} erreur(s)" if E else "") + (f" · {len(A)} avertissement(s)" if A else ""))
    for x in E + A + I:
        w(f"  - {x}")
    w("\n## 13. Fichiers réellement produits")
    fichiers = pd.get("fichiers_produits", [])
    if fichiers:
        for f in fichiers:
            w(f"- `{f}`")
    else:
        w("Aucun fichier vidéo final produit à ce stade.")
    w("\n## 14. Reste à faire")
    for f in p.get("faits", []):
        if f.get("statut") == "a_fournir":
            w(f"- Obtenir : {f.get('texte')}")
    for x in p.get("reste_a_faire", []):
        w(f"- {x}")
    sortie = a.o or os.path.splitext(a.projet)[0] + "-dossier.md"
    with open(sortie, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"Dossier : {sortie}")
    return 1 if E else 0


# ---------------------------------------------------------------- animatique
def hex_rgb(h, defaut=(20, 24, 31)):
    m = re.match(r"^#?([0-9a-fA-F]{6})$", str(h or ""))
    return tuple(int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)) if m else defaut


def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def cadre_animatique(p, s, idx, total_t, debut, W, H, chemin):
    from PIL import Image, ImageDraw, ImageFont
    pal = p.get("direction_artistique", {}).get("palette") or ["#14181F", "#E9E4DA", "#C8A24A"]
    fond = hex_rgb(pal[0])
    texte = hex_rgb(pal[1] if len(pal) > 1 else "#FFFFFF", (240, 240, 240))
    accent = hex_rgb(pal[2] if len(pal) > 2 else "#C8A24A", (200, 160, 70))
    if abs(lum(fond) - lum(texte)) < 90:
        texte = (245, 245, 245) if lum(fond) < 128 else (20, 20, 20)
    im = Image.new("RGB", (W, H), fond)
    d = ImageDraw.Draw(im)
    u = min(W, H) / 1080
    fb, fr = police(True), police(False)

    def F(taille, gras=False):
        chem = fb if gras else fr
        return ImageFont.truetype(chem, int(taille * u)) if chem else ImageFont.load_default()

    marge = int(0.07 * W)
    y = int(0.08 * H)
    lib = LIBELLES.get(s.get("fonction", ""), s.get("fonction", "")).upper()
    d.text((marge, y), f"{s.get('id', '')} · {lib} · {float(s.get('duree', 0)):g} s · {s.get('source', '').replace('_', ' ')}", font=F(30, True), fill=accent)
    y += int(60 * u)
    largeur_car = max(18, int((W - 2 * marge) / (19 * u)))
    for ligne in textwrap.wrap(s.get("action", ""), largeur_car)[:5]:
        d.text((marge, y), ligne, font=F(38), fill=texte)
        y += int(52 * u)
    y += int(20 * u)
    d.text((marge, y), f"{s.get('plan', '')} — {s.get('mouvement', '')}", font=F(26), fill=accent)
    # texte à l'écran tel qu'il apparaîtra (zone de sécurité)
    if s.get("texte_ecran"):
        zone_y = int(H * (0.62 if H > W else 0.66))
        for ligne in textwrap.wrap(s["texte_ecran"], max(14, int(largeur_car * 0.8)))[:3]:
            d.text((marge, zone_y), ligne, font=F(56, True), fill=texte)
            zone_y += int(70 * u)
    if s.get("voix_off"):
        vy = H - int(0.19 * H)
        d.text((marge, vy), "Voix off : " + textwrap.shorten(s["voix_off"], width=largeur_car + 30, placeholder="…"), font=F(28), fill=texte)
    # zone de sécurité (titre 90 %, action 93 %) et filigrane
    sx, sy = int(W * 0.05), int(H * 0.05)
    d.rectangle([sx, sy, W - sx, H - sy], outline=tuple(int(c * 0.6 + f * 0.4) for c, f in zip(accent, fond)), width=max(1, int(2 * u)))
    d.text((marge, H - int(0.11 * H)), ANIM_TAG, font=F(22), fill=tuple(int(c * 0.55 + f * 0.45) for c, f in zip(texte, fond)))
    # barre de temps
    by = H - int(0.06 * H)
    d.rectangle([marge, by, W - marge, by + int(6 * u)], fill=tuple(int(c * 0.3 + f * 0.7) for c, f in zip(texte, fond)))
    x0 = marge + (W - 2 * marge) * debut / total_t
    x1 = marge + (W - 2 * marge) * (debut + float(s.get("duree", 0))) / total_t
    d.rectangle([x0, by, x1, by + int(6 * u)], fill=accent)
    im.save(chemin)


def cmd_animatique(a):
    need("ffmpeg")
    p = charger(a.projet)
    fmt = format_par_nom(p, a.format)
    W, H = wh(fmt)
    k = 1920 / max(W, H)  # l'animatique se rend en 1080p : c'est un outil de validation, pas un master
    W, H = int(W * k) // 2 * 2, int(H * k) // 2 * 2
    total = duree_totale(p)
    sortie = a.o or os.path.splitext(a.projet)[0] + f"-animatique-{fmt.get('ratio', '16:9').replace(':', 'x')}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        entrees, filtres, t = [], [], 0.0
        for i, s in enumerate(scenes(p)):
            img = os.path.join(tmp, f"s{i}.png")
            cadre_animatique(p, s, i, total, t, W, H, img)
            d = float(s.get("duree", 1))
            entrees += ["-loop", "1", "-t", f"{d:.3f}", "-i", img]
            n = max(2, int(d * 30))
            filtres.append(f"[{i}:v]scale={int(W * 1.06)}:-2,zoompan=z='min(zoom+0.0006,1.05)':d={n}:s={W}x{H}:fps=30,"
                           f"trim=duration={d:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
            t += d
        n = len(scenes(p))
        filtres.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + entrees
        if a.voix:
            cmd += ["-i", a.voix]
        cmd += ["-filter_complex", ";".join(filtres), "-map", "[v]"]
        if a.voix:
            cmd += ["-map", f"{n}:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-r", "30",
                "-metadata", f"comment=Vidéo 4K 2.0 | {ANIM_TAG}", "-movflags", "+faststart", sortie]
        run(cmd)
    print(f"Animatique : {sortie} ({W}x{H}, {total} s) — prévisualisation, pas la vidéo finale")
    return 0


# ---------------------------------------------------------------- montage
def esc_ass(t):
    return str(t).replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def ecrire_ass(p, chemin, W, H, sous_titres, fps=30):
    fam = nom_police_ass()
    pal = p.get("direction_artistique", {}).get("palette") or ["#14181F", "#FFFFFF", "#C8A24A"]

    def ass_col(h, alpha="00"):
        r, g, b = hex_rgb(h, (255, 255, 255))
        return f"&H{alpha}{b:02X}{g:02X}{r:02X}"
    clair = pal[1] if len(pal) > 1 else "#FFFFFF"
    accent = pal[2] if len(pal) > 2 else "#C8A24A"
    u = min(W, H) / 1080
    vertical = H > W
    # zones de sécurité : en vertical, l'interface des réseaux (légende, boutons) couvre le bas ~25 % et le haut ~12 %
    mv = int(H * (0.24 if vertical else 0.09))
    mh = int(W * 0.07)
    L = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
         "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
         "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
         f"Style: Titre,{fam},{int(64 * u)},{ass_col(clair)},{ass_col(clair)},&H64000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(1, int(1.5 * u))},{max(1, int(3 * u))},1,{mh},{mh},{int(H * (0.36 if vertical else 0.22))},1",
         f"Style: CTA,{fam},{int(78 * u)},{ass_col(clair)},{ass_col(clair)},&H64000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(1, int(1.5 * u))},{max(1, int(3 * u))},5,{mh},{mh},0,1",
         f"Style: CTA2,{fam},{int(40 * u)},{ass_col(accent)},{ass_col(accent)},&H64000000,&H96000000,0,0,0,0,100,100,0,0,1,{max(1, int(1 * u))},{max(1, int(2 * u))},5,{mh},{mh},0,1",
         f"Style: ST,{fam},{int(44 * u)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H7A000000,0,0,0,0,100,100,0,0,3,{max(1, int(8 * u))},0,2,{mh},{mh},{mv},1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]

    def t_ass(x):
        cs = int(round(x * 100))
        h, cs = divmod(cs, 360000)
        m, cs = divmod(cs, 6000)
        s, cs = divmod(cs, 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    t = 0.0
    sc = scenes(p)
    for i, s in enumerate(sc):
        d = float(s.get("duree", 0))
        if s.get("fonction") == "cta":
            cta = p.get("cta", {})
            L.append(f"Dialogue: 1,{t_ass(t + 0.2)},{t_ass(t + d)},CTA,,0,0,0,,{{\\fad(250,0)}}{esc_ass(cta.get('texte') or s.get('texte_ecran', ''))}")
            if cta.get("coordonnees"):
                L.append(f"Dialogue: 1,{t_ass(t + 0.5)},{t_ass(t + d)},CTA2,,0,0,0,,{{\\fad(250,0)\\pos({W // 2},{int(H * 0.60)})}}{esc_ass(cta['coordonnees'])}")
            if p.get("mention_images_illustratives"):
                L.append(f"Dialogue: 1,{t_ass(t + 0.5)},{t_ass(t + d)},CTA2,,0,0,0,,{{\\fs{int(26 * u)}\\pos({W // 2},{int(H * 0.69)})}}{esc_ass(p['mention_images_illustratives'])}")
        elif s.get("texte_ecran"):
            L.append(f"Dialogue: 1,{t_ass(t + 0.25)},{t_ass(t + d - 0.1)},Titre,,0,0,0,,{{\\fad(220,180)}}{esc_ass(s['texte_ecran'])}")
        t += d
    if sous_titres:
        cta_txt = norm(p.get("cta", {}).get("texte", "")).strip(" .!")
        for d0, d1, txt in cues(p):
            if cta_txt and norm(txt).replace("\n", " ").strip(" .!") == cta_txt:
                continue  # la réplique est déjà affichée en grand sur la carte finale
            L.append(f"Dialogue: 0,{t_ass(d0)},{t_ass(d1)},ST,,0,0,0,,{esc_ass(txt)}")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def fond_graphique(p, W, H, chemin):
    """Fond de carton (CTA, titre) : dégradé discret dans la couleur principale de la palette."""
    from PIL import Image
    pal = p.get("direction_artistique", {}).get("palette") or ["#14181F"]
    c = hex_rgb(pal[0])
    w2, h2 = max(2, W // 8), max(2, H // 8)
    im = Image.new("RGB", (w2, h2), c)
    px = im.load()
    for yy in range(h2):
        for xx in range(w2):
            dx, dy = (xx / w2 - 0.5), (yy / h2 - 0.45)
            k = 1.0 + 0.10 * (1 - min(1.0, (dx * dx + dy * dy) * 2.6)) - 0.05
            px[xx, yy] = tuple(max(0, min(255, int(v * k + (6 if lum(c) < 60 else 0) * (k - 0.95)))) for v in c)
    im.resize((W, H), Image.BICUBIC).save(chemin)
    return chemin


def trouver_plan(dossier, sid):
    for ext in (".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".webp"):
        c = os.path.join(dossier, sid + ext)
        if os.path.exists(c):
            return c
    return None


def cmd_monter(a):
    need("ffmpeg")
    p = charger(a.projet)
    E, _, _ = valider(p)
    if E and not a.brouillon:
        die("le projet comporte des erreurs (lancer « valider ») ; utiliser --brouillon pour un montage de travail", 1)
    fmt = format_par_nom(p, a.format)
    W, H = wh(fmt)
    if a.brouillon:
        k = 1920 / max(W, H)
        W, H = int(W * k) // 2 * 2, int(H * k) // 2 * 2
    fps = int(p.get("production", {}).get("fps", 30))
    sc = scenes(p)
    plans, manquants = [], []
    tmp_fonds = tempfile.mkdtemp()
    for s in sc:
        c = trouver_plan(a.plans, s.get("id"))
        if not c and s.get("source") == "graphique":
            c = fond_graphique(p, W, H, os.path.join(tmp_fonds, f"{s.get('id')}.png"))
        (plans if c else manquants).append(c or s.get("id"))
    if manquants:
        die(f"plans manquants dans {a.plans} : {', '.join(manquants)} (nommer les fichiers S1.mp4, S2.png…)", 1)
    sortie = a.o or os.path.splitext(a.projet)[0] + f"-master-{fmt.get('ratio', '16:9').replace(':', 'x')}.mp4"
    plus_petite_source = 99999
    for c in plans:
        if c.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            from PIL import Image
            with Image.open(c) as im:
                plus_petite_source = min(plus_petite_source, min(im.size))
        else:
            st = [x for x in ffprobe(c)["streams"] if x.get("codec_type") == "video"][0]
            plus_petite_source = min(plus_petite_source, min(int(st["width"]), int(st["height"])))
    natif = plus_petite_source >= min(W, H)
    with tempfile.TemporaryDirectory() as tmp:
        entrees, f, dur = [], [], []
        TR = {"fondu": "fade", "fondu_noir": "fadeblack", "fondu-noir": "fadeblack", "glissement": "smoothleft"}
        prevues = [float(x.get("duree", 1)) for x in sc]
        fondus = [0.0] * len(sc)  # durée du fondu ENTRANT de chaque scène (compensée pour garder la durée prévue)
        for i in range(1, len(sc)):
            if (sc[i - 1].get("transition") or "coupe").lower() in TR:
                fondus[i] = round(min(0.5, prevues[i] / 3, prevues[i - 1] / 3), 3)
        for i, (s, c) in enumerate(zip(sc, plans)):
            d = prevues[i] + fondus[i]
            dur.append(d)
            fx, fy = (s.get("cadrage_focus") or [0.5, 0.5])
            if c.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                entrees += ["-loop", "1", "-t", f"{d + 1:.3f}", "-i", c]
                n = int(d * fps) + 2
                f.append(f"[{i}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,"
                         f"crop={W * 2}:{H * 2}:(iw-ow)*{fx}:(ih-oh)*{fy},"
                         f"zoompan=z='min(zoom+0.0005,1.06)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={fps},"
                         f"trim=duration={d:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p,settb=1/{fps}[v{i}]")
            else:
                debut = float(s.get("debut_source", 0))
                dispo = float(ffprobe(c)["format"].get("duration", 0)) - debut
                if dispo + 0.05 < d:
                    print(f"  AVERTISSEMENT {s.get('id')} : plan de {dispo:.1f} s pour {d:.1f} s — dernière image prolongée de {d - dispo:.1f} s")
                entrees += ["-ss", f"{debut:.3f}", "-i", c]
                f.append(f"[{i}:v]fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
                         f"crop={W}:{H}:(iw-ow)*{fx}:(ih-oh)*{fy},tpad=stop_mode=clone:stop_duration={d:.3f},"
                         f"trim=duration={d:.3f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p,settb=1/{fps}[v{i}]")
        # enchaînement : coupe (concat) ou fondu (xfade) selon la transition sortante de la scène précédente
        cur, cur_len = "v0", dur[0]
        for i in range(1, len(sc)):
            tr = (sc[i - 1].get("transition") or "coupe").lower()
            out = f"x{i}"
            if fondus[i]:
                fd = fondus[i]
                tt = TR[tr]
                f.append(f"[{cur}][v{i}]xfade=transition={tt}:duration={fd:.3f}:offset={cur_len - fd:.3f},settb=1/{fps}[{out}]")
                cur_len += dur[i] - fd
            else:
                f.append(f"[{cur}][v{i}]concat=n=2:v=1:a=0,settb=1/{fps}[{out}]")
                cur_len += dur[i]
            cur = out
        # voile de lisibilité : dégradé sombre statique sous les titres, seulement pendant qu'ils sont affichés
        fenetres, t0 = [], 0.0
        for s_ in sc:
            d_ = float(s_.get("duree", 0))
            if s_.get("texte_ecran") and s_.get("fonction") != "cta" and s_.get("source") != "graphique":
                fenetres.append((t0 + 0.1, t0 + d_))
            t0 += d_
        if fenetres:
            from PIL import Image
            voile = os.path.join(tmp, "voile.png")
            g = Image.new("L", (1, 256))
            for yy in range(256):
                k = max(0.0, (yy / 255 - 0.45) / 0.55)
                g.putpixel((0, yy), int(150 * k ** 1.6))
            noir = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            noir.putalpha(g.resize((W, H)))
            noir.save(voile)
            entrees += ["-loop", "1", "-i", voile]
            expr = "+".join(f"between(t,{a_:.2f},{b_:.2f})" for a_, b_ in fenetres)
            f.append(f"[{len(sc)}:v]format=rgba[vo]")
            f.append(f"[{cur}][vo]overlay=0:0:shortest=1:enable='{expr}'[cs]")
            cur = "cs"
        ass = os.path.join(tmp, "textes.ass")
        ecrire_ass(p, ass, W, H, a.sous_titres)
        fontsdir = os.path.dirname(police() or "/usr/share/fonts")
        assx = ass.replace("\\", "/").replace(":", "\\:")
        f.append(f"[{cur}]subtitles='{assx}':fontsdir='{fontsdir}'[vt]")
        vlast = "vt"
        n_in = len(sc) + (1 if fenetres else 0)
        if a.logo:
            entrees += ["-i", a.logo]
            lw = int(min(W, H) * 0.16)
            t_cta = sum(dur[:-1]) if sc[-1].get("fonction") == "cta" else max(0, cur_len - 3)
            f.append(f"[{n_in}:v]scale={lw}:-1[lg]")
            f.append(f"[vt][lg]overlay=x=(W-w)/2:y=H*0.22:enable='gte(t,{t_cta:.2f})'[vl]")
            vlast = "vl"
            n_in += 1
        boucle = p.get("brief", {}).get("canal") == "site-hero"
        if boucle:  # boucle sans couture : la fin se fond dans le début (recette « seamless loop »)
            bd = 0.6
            f.append(f"[{vlast}]split=2[lb][lh]")
            f.append(f"[lb]trim=start={bd}:duration={cur_len - bd:.3f},setpts=PTS-STARTPTS,settb=1/{fps}[lbody]")
            f.append(f"[lh]trim=duration={bd},setpts=PTS-STARTPTS,settb=1/{fps}[lhead]")
            f.append(f"[lbody][lhead]xfade=transition=fade:duration={bd}:offset={cur_len - 2 * bd:.3f}[lp]")
            vlast = "lp"
            cur_len -= bd
        audio = []
        if a.voix:
            entrees += ["-i", a.voix]
            audio.append(("voix", n_in))
            n_in += 1
        if a.musique:
            entrees += ["-stream_loop", "-1", "-i", a.musique]
            audio.append(("musique", n_in))
            n_in += 1
        fin = cur_len
        amap = None
        if audio:
            d = dict(audio)
            if "voix" in d and "musique" in d:
                f.append(f"[{d['voix']}:a]aformat=channel_layouts=stereo,apad,atrim=0:{fin:.3f},asplit=2[vx][sc]")
                f.append(f"[{d['musique']}:a]aformat=channel_layouts=stereo,atrim=0:{fin:.3f},volume=0.5,"
                         f"afade=t=out:st={max(0, fin - 1.2):.3f}:d=1.2[mu]")
                f.append("[mu][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[mud]")
                f.append("[vx][mud]amix=inputs=2:duration=first:normalize=0[mx]")
            else:
                k_, idx = audio[0]
                f.append(f"[{idx}:a]aformat=channel_layouts=stereo,apad,atrim=0:{fin:.3f}"
                         + (f",afade=t=out:st={max(0, fin - 1.2):.3f}:d=1.2" if k_ == "musique" else "") + "[mx]")
            cible = float(a.lufs)
            f.append(f"[mx]loudnorm=I={cible}:TP=-1.5:LRA=11,aresample=48000[aout]")
            amap = "[aout]"
        meta = (f"Vidéo 4K 2.0 | {W}x{H} | plus petite source {plus_petite_source}px | "
                + ("pixels natifs" if natif else "MISE À L'ÉCHELLE depuis une source inférieure — pas de 4K native"))
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + entrees + ["-filter_complex", ";".join(f), "-map", f"[{vlast}]"]
        if amap:
            cmd += ["-map", amap, "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
        crf = "24" if a.brouillon else "16"
        cmd += ["-t", f"{fin:.3f}", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast" if a.brouillon else a.preset_x264, "-crf", crf,
                "-profile:v", "high", "-level", "5.2" if max(W, H) > 2000 else "4.2", "-pix_fmt", "yuv420p",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-metadata", f"comment={meta}", "-movflags", "+faststart", sortie]
        run(cmd)
    print(f"Master : {sortie} ({W}x{H}, {fin:.2f} s, {fps} i/s)")
    origine = "natifs" if natif else f"mise à l’échelle (plus petite source {plus_petite_source}px)"
    print(f"  Origine des pixels : {origine}")
    if a.brouillon:
        print("  Brouillon : résolution réduite, ne pas livrer.")
    return 0


# ---------------------------------------------------------------- export
def cmd_exporter(a):
    need("ffmpeg")
    info = ffprobe(a.master)
    v = [x for x in info["streams"] if x["codec_type"] == "video"][0]
    has_a = any(x["codec_type"] == "audio" for x in info["streams"])
    W, H = int(v["width"]), int(v["height"])
    duree = float(info["format"]["duration"])
    commentaire = info["format"].get("tags", {}).get("comment", "")
    os.makedirs(a.o, exist_ok=True)
    base = os.path.join(a.o, os.path.splitext(os.path.basename(a.master))[0])
    produits = []

    def enc(args, sortie):
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.master] + args + [sortie])
        produits.append(sortie)

    def cover(w, h):
        return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    P = a.preset

    def debit(audio_kbps):
        """Débit vidéo (kb/s) pour tenir dans --budget-mo, marge de 5 %."""
        if not a.budget_mo:
            return None
        k = float(a.budget_mo) * 8000 * 0.95 / duree - (audio_kbps if has_a else 0)
        if k < 150:
            die(f"budget de {a.budget_mo} Mo trop serré pour {duree:.1f} s (débit vidéo calculé {k:.0f} kb/s) : raccourcir ou réduire la résolution", 1)
        return int(k)

    def deux_passes(vf, kbps, audio_args, sortie, extra=()):
        logp = os.path.join(tempfile.gettempdir(), f"v4k2p-{os.getpid()}")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.master, "-vf", vf, "-c:v", "libx264", "-preset", "slow",
             "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k", "-pass", "1", "-passlogfile", logp,
             "-an", "-f", "mp4", os.devnull])
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", a.master, "-vf", vf, "-c:v", "libx264", "-preset", "slow",
             "-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.5)}k", "-bufsize", f"{kbps * 2}k", "-pass", "2", "-passlogfile", logp,
             "-pix_fmt", "yuv420p", "-profile:v", "high"] + list(extra) + audio_args + ["-movflags", "+faststart", sortie])
        for x in glob_logs(logp):
            os.remove(x)
        produits.append(sortie)
    if P == "master-4k":
        w, h = (3840, 2160) if W >= H else (2160, 3840)
        if W == H:
            w = h = 2160
        enc(["-vf", cover(w, h), "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high", "-level", "5.2",
             "-pix_fmt", "yuv420p", "-metadata", f"comment={commentaire}"] + (["-c:a", "aac", "-b:a", "320k"] if has_a else ["-an"])
            + ["-movflags", "+faststart"], f"{base}-4k.mp4")
    elif P == "archive-h265":
        enc(["-c:v", "libx265", "-preset", "slow", "-crf", "18", "-tag:v", "hvc1", "-pix_fmt", "yuv420p10le",
             "-metadata", f"comment={commentaire}"] + (["-c:a", "aac", "-b:a", "320k"] if has_a else ["-an"]) + ["-movflags", "+faststart"],
            f"{base}-archive-h265.mp4")
    elif P == "web-hero":
        # vidéo de fond : muette, légère, deux encodages + version téléphone + posters (budgets de 10k-websites / Moi 2.0)
        dw = 1600 if W >= H else 900
        dh = int(dw * H / W) // 2 * 2
        k = debit(0)
        if k:
            deux_passes(f"scale={dw}:{dh}:flags=lanczos", k, ["-an"], f"{base}-hero-desktop.mp4")
        else:
            enc(["-vf", f"scale={dw}:{dh}:flags=lanczos", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-profile:v", "high",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart"], f"{base}-hero-desktop.mp4")
        enc(["-vf", f"scale={dw}:{dh}:flags=lanczos", "-an", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "38", "-row-mt", "1",
             "-deadline", "good", "-cpu-used", "2"], f"{base}-hero-desktop.webm")
        vf_tel = cover(540, 960) if W >= H else "scale=540:-2:flags=lanczos"
        enc(["-vf", vf_tel, "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "30",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart"], f"{base}-hero-mobile.mp4")
        enc(["-vf", vf_tel, "-an", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "40", "-row-mt", "1", "-deadline", "good", "-cpu-used", "2"],
            f"{base}-hero-mobile.webm")
        premier = f"{base}-hero-desktop.mp4"
        for ext, args in ((".jpg", ["-q:v", "4"]), (".webp", ["-c:v", "libwebp", "-quality", "72"]), (".avif", ["-c:v", "libaom-av1", "-still-picture", "1", "-crf", "34"])):
            sortie = f"{base}-poster{ext}"
            run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", premier, "-frames:v", "1"] + args + [sortie])
            produits.append(sortie)
    elif P == "web-presentation":
        vf = "scale=-2:1080:flags=lanczos" if W >= H else "scale=1080:-2:flags=lanczos"
        aud = ["-c:a", "aac", "-b:a", "128k"] if has_a else ["-an"]
        k = debit(128)
        if k:
            deux_passes(vf, k, aud, f"{base}-1080p.mp4")
        else:
            enc(["-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-profile:v", "high", "-pix_fmt", "yuv420p"] + aud
                + ["-movflags", "+faststart"], f"{base}-1080p.mp4")
        enc(["-vf", "scale=-2:720:flags=lanczos" if W >= H else "scale=720:-2:flags=lanczos", "-c:v", "libx264", "-preset", "slow",
             "-crf", "25", "-pix_fmt", "yuv420p"] + (["-c:a", "aac", "-b:a", "96k"] if has_a else ["-an"]) + ["-movflags", "+faststart"],
            f"{base}-720p.mp4")
        sortie = f"{base}-poster.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{min(1.0, duree / 3):.2f}", "-i", f"{base}-1080p.mp4",
             "-frames:v", "1", "-q:v", "3", sortie])
        produits.append(sortie)
        if a.projet:
            produits.append(ecrire_srt(charger(a.projet), f"{base}.vtt"))
    elif P in {"social-916", "social-45", "social-11"}:
        w, h = {"social-916": (1080, 1920), "social-45": (1080, 1350), "social-11": (1080, 1080)}[P]
        if (W >= H) != (w >= h) and P == "social-916":
            print("  AVERTISSEMENT : recadrage d'un master horizontal en vertical — vérifier que le sujet et les textes restent dans le cadre ;"
                  " préférer un master vertical dédié (monter --format 9:16).")
        af = ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"] if has_a else ["-an"]
        enc(["-vf", cover(w, h), "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-r", "30"] + af + ["-movflags", "+faststart"], f"{base}-{P}.mp4")
    else:
        die(f"preset inconnu : {P}")
    for x in produits:
        print(f"  {x}  ({os.path.getsize(x) / 1e6:.2f} Mo)")
    return 0


# ---------------------------------------------------------------- contrôle
def glob_logs(prefix):
    d = os.path.dirname(prefix) or "."
    b = os.path.basename(prefix)
    return [os.path.join(d, x) for x in os.listdir(d) if x.startswith(b)]


def faststart(path):
    try:
        with open(path, "rb") as f:
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                size, typ = int.from_bytes(hdr[:4], "big"), hdr[4:8].decode("latin1")
                if typ == "moov":
                    return True
                if typ == "mdat":
                    return False
                if size == 1:
                    size = int.from_bytes(f.read(8), "big") - 8
                f.seek(size - 8, 1)
    except Exception:
        return None


def cmd_controler(a):
    need("ffmpeg")
    info = ffprobe(a.fichier)
    E, A, OK = [], [], []
    vs = [x for x in info["streams"] if x["codec_type"] == "video"]
    aus = [x for x in info["streams"] if x["codec_type"] == "audio"]
    if not vs:
        die("aucun flux vidéo", 1)
    v = vs[0]
    W, H = int(v["width"]), int(v["height"])
    num, den = (v.get("avg_frame_rate") or "0/1").split("/")
    fps = float(num) / float(den) if float(den) else 0
    duree = float(info["format"].get("duration", 0))
    taille = os.path.getsize(a.fichier) / 1e6
    comment = info["format"].get("tags", {}).get("comment", "")
    res = {"fichier": a.fichier, "largeur": W, "hauteur": H, "ratio": ratio_de(W, H), "fps": round(fps, 2), "duree": round(duree, 2),
           "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"), "taille_mo": round(taille, 2), "audio": bool(aus),
           "faststart": faststart(a.fichier) if a.fichier.lower().endswith((".mp4", ".mov", ".m4v")) else None, "metadonnees": comment}
    if a.ratio and res["ratio"] != a.ratio:
        E.append(f"ratio {res['ratio']} au lieu de {a.ratio}")
    if a.resolution:
        ew, eh = map(int, a.resolution.lower().split("x"))
        if (W, H) != (ew, eh):
            E.append(f"résolution {W}x{H} au lieu de {ew}x{eh}")
        else:
            OK.append(f"résolution {W}x{H}")
    if max(W, H) >= 3840:
        if "MISE À L'ÉCHELLE" in comment:
            A.append("4K obtenue par mise à l'échelle (pas de 4K native) : l'annoncer comme telle")
        elif "pixels natifs" in comment:
            OK.append("4K à partir de pixels natifs")
        else:
            A.append("origine des pixels 4K inconnue (fichier non produit par le moteur)")
    if a.duree and abs(duree - float(a.duree)) > 0.25:
        E.append(f"durée {duree:.2f} s au lieu de {a.duree} s")
    if v.get("pix_fmt") not in {"yuv420p", "yuv420p10le"}:
        A.append(f"format de pixels {v.get('pix_fmt')} : yuv420p conseillé pour la compatibilité")
    if res["faststart"] is False:
        E.append("MP4 sans « faststart » : la lecture web attendra le téléchargement complet")
    if a.sans_son and aus:
        E.append("piste audio présente alors qu'une vidéo muette est attendue (vidéo de fond)")
    if a.budget_mo and taille > float(a.budget_mo):
        E.append(f"poids {taille:.2f} Mo au-delà du budget de {a.budget_mo} Mo")
    # noirs et images figées
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.fichier, "-vf",
                        "blackdetect=d=0.4:pix_th=0.08,freezedetect=n=0.002:d=1.5", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    noirs = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)
    figes = re.findall(r"freeze_start: ([\d.]+)", p.stderr)
    if a.projet:  # les cartons graphiques (CTA, titres) sont fixes par construction : ne pas les signaler
        pj, t0, zones = charger(a.projet), 0.0, []
        for s_ in scenes(pj):
            d_ = float(s_.get("duree", 0))
            if s_.get("source") == "graphique":
                zones.append((t0 - 0.3, t0 + d_ + 0.3))
            t0 += d_
        figes = [x for x in figes if not any(z0 <= float(x) <= z1 for z0, z1 in zones)]
    noirs_int = [(s, e) for s, e in noirs if float(s) > 0.3 and float(e) < duree - 0.3]
    if noirs_int:
        A.append("passages noirs au milieu : " + ", ".join(f"{float(s):.1f}–{float(e):.1f} s" for s, e in noirs_int[:4]))
    if figes:
        A.append("images figées détectées à : " + ", ".join(f"{float(x):.1f} s" for x in figes[:5]) + " (plan trop court étiré, ou carton voulu ?)")
    res["noirs"], res["figes"] = len(noirs_int), len(figes)
    if a.boucle:  # la dernière image doit rejoindre la première (vidéo de fond en boucle)
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.fichier, "-sseof", "-0.05", "-i", a.fichier,
                            "-filter_complex", "[0:v]trim=end_frame=1[a0];[1:v]trim=end_frame=1[b0];[a0][b0]psnr", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.search(r"average:([\d.]+|inf)", p.stderr)
        if m:
            ps = float("inf") if m.group(1) == "inf" else float(m.group(1))
            res["psnr_boucle"] = ps
            (OK if ps >= 30 else E).append(f"raccord de boucle : {ps:.1f} dB entre la dernière et la première image" + ("" if ps >= 30 else " (couture visible, viser ≥ 30 dB)"))
    if aus:
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.fichier, "-af", "ebur128=peak=true", "-vn", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", p.stderr)
        tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", p.stderr)
        if m:
            lufs = float(m[-1])
            res["lufs"] = lufs
            if a.lufs is not None and abs(lufs - float(a.lufs)) > 1.5:
                A.append(f"loudness {lufs} LUFS (cible {a.lufs})")
            else:
                OK.append(f"loudness {lufs} LUFS")
        if tp:
            res["true_peak"] = float(tp[-1])
            if float(tp[-1]) > -1.0:
                A.append(f"crête {tp[-1]} dBTP : risque de saturation (viser −1,5)")
    res["erreurs"], res["avertissements"], res["ok"] = E, A, OK
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"== {os.path.basename(a.fichier)} : {W}x{H} ({res['ratio']}), {res['fps']} i/s, {res['duree']} s, {res['codec']}, "
              f"{res['taille_mo']} Mo, audio {'oui' if aus else 'non'}")
        for e in E:
            print(f"  ERREUR        {e}")
        for x in A:
            print(f"  AVERTISSEMENT {x}")
        for x in OK:
            print(f"  OK            {x}")
        print("  => " + ("CONFORME" if not E else "NON CONFORME"))
    return 1 if E else 0


# ---------------------------------------------------------------- interface
def main(argv=None):
    ap = argparse.ArgumentParser(prog="video4k.py", description="Vidéo 4K 2.0 — moteur", formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("audit"); s.set_defaults(f=cmd_audit)
    s = sp.add_parser("valider"); s.add_argument("projet"); s.set_defaults(f=cmd_valider)
    s = sp.add_parser("dossier"); s.add_argument("projet"); s.add_argument("-o"); s.set_defaults(f=cmd_dossier)
    s = sp.add_parser("srt"); s.add_argument("projet"); s.add_argument("-o"); s.set_defaults(f=cmd_srt)
    s = sp.add_parser("animatique"); s.add_argument("projet"); s.add_argument("-o"); s.add_argument("--format"); s.add_argument("--voix")
    s.set_defaults(f=cmd_animatique)
    s = sp.add_parser("monter"); s.add_argument("projet"); s.add_argument("--plans", required=True); s.add_argument("-o")
    s.add_argument("--format"); s.add_argument("--voix"); s.add_argument("--musique"); s.add_argument("--logo")
    s.add_argument("--sous-titres", action="store_true"); s.add_argument("--brouillon", action="store_true"); s.add_argument("--lufs", default="-16")
    s.add_argument("--preset-x264", default="medium", help="medium (défaut), slow (plus compact, plus lent)")
    s.set_defaults(f=cmd_monter)
    s = sp.add_parser("exporter"); s.add_argument("master"); s.add_argument("--preset", required=True); s.add_argument("-o", default="exports")
    s.add_argument("--projet"); s.add_argument("--budget-mo", help="poids maximal (web-presentation, web-hero) : encodage en deux passes")
    s.set_defaults(f=cmd_exporter)
    s = sp.add_parser("controler"); s.add_argument("fichier"); s.add_argument("--ratio"); s.add_argument("--resolution")
    s.add_argument("--duree"); s.add_argument("--budget-mo"); s.add_argument("--sans-son", action="store_true"); s.add_argument("--lufs")
    s.add_argument("--json", action="store_true"); s.add_argument("--projet", help="ignore les images fixes des cartons graphiques")
    s.add_argument("--boucle", action="store_true", help="vérifie le raccord fin → début d'une vidéo de fond")
    s.set_defaults(f=cmd_controler)
    a = ap.parse_args(argv)
    return a.f(a)


if __name__ == "__main__":
    sys.exit(main())
