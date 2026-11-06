#!/usr/bin/env python3
"""tiktok-serie-virale — moteur de série TikTok (complète Vidéo 4K 2.0, ne le remplace pas).

Ce moteur prépare et finit ; l'assemblage, l'export et le contrôle passent par video4k.py.

  analyser   CLIPS... [-o analyse.json] [--planches DOSSIER]  durée, rythme, moments forts, qualité, planches-contacts
  rythme     MUSIQUE [-o beats.json]                           tempo et temps forts (coupes sur le rythme)
  caler      DECOUPAGE --beats beats.json [-o sortie.json]     cale les coupes sur les temps (plans 1 à 3,5 s)
  plan       DECOUPAGE [-o plan.md]                            plan seconde par seconde, à faire valider
  voix       DECOUPAGE --repliques DOSSIER [-o voix.wav]       place chaque réplique ; mots.json (faster-whisper si présent)
  plans      DECOUPAGE --clips DOSSIER [-o plans/]             extrait chaque plan en 1080x1920, zoom léger, incrustation
  projet     DECOUPAGE --bible bible.json [-o projet.json]     projet au format Vidéo 4K 2.0 (valider puis monter)
  finitions  MASTER DECOUPAGE [--mots mots.json] [-o ep.mp4]   sous-titres mot à mot, flash et impact du cliffhanger
  grille     VIDEO DECOUPAGE [--mots mots.json]                grille de viralité interne /100 (pas une prédiction)
  bible      init|md|episode ...                               bible de série (personnages, voix, style, épisodes)
"""
import argparse, glob, json, math, os, re, shutil, subprocess, sys, tempfile

W, H, FPS = 1080, 1920, 30


def die(m, c=2):
    print("ERREUR : " + m, file=sys.stderr); sys.exit(c)


def run(cmd, out=False):
    r = subprocess.run(cmd, capture_output=True, text=not out)
    if r.returncode != 0:
        die("commande échouée : " + " ".join(map(str, cmd[:6])) + " …\n" + (r.stderr if not out else r.stderr.decode(errors="ignore"))[-1500:], 1)
    return r.stdout


def need():
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            die(f"{t} absent : l'installer avant de commencer (winget install ffmpeg / brew install ffmpeg / apt install ffmpeg)")


def probe(f):
    return json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", f]))


def charger(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def ecrire(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def police():
    for c in ["/usr/share/fonts/truetype/higgsfield/Montserrat-ExtraBold.ttf", "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf", "/Library/Fonts/Arial Bold.ttf"]:
        if os.path.exists(c):
            return c
    r = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True)
    return r.stdout.strip() or None


def famille(fp):
    r = subprocess.run(["fc-scan", "--format", "%{family[0]}", fp], capture_output=True, text=True) if fp else None
    return (r.stdout.strip() if r and r.returncode == 0 else "") or "Sans"


def plans_de(d):
    p = d.get("plans") or []
    if not p:
        die("découpage sans plans")
    return p


def timeline(d):
    t, out = 0.0, []
    for p in plans_de(d):
        out.append((t, t + float(p["duree"]), p))
        t += float(p["duree"])
    return out


# ------------------------------------------------------------------ analyser
def gris(f, fps=4, w=96, h=96):
    raw = run(["ffmpeg", "-v", "error", "-i", f, "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"], out=True)
    import numpy as np
    n = len(raw) // (w * h)
    return np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype("float32")


def cmd_analyser(a):
    need()
    import numpy as np
    fichiers = []
    for c in a.clips:
        fichiers += sorted(glob.glob(os.path.join(c, "*"))) if os.path.isdir(c) else [c]
    fichiers = [f for f in fichiers if f.lower().endswith((".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"))]
    if not fichiers:
        die("aucun clip vidéo trouvé")
    fp = police()
    if a.planches:
        os.makedirs(a.planches, exist_ok=True)
    res = []
    for f in fichiers:
        info = probe(f)
        v = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
        if not v:
            continue
        dur = float(info["format"].get("duration", 0))
        w, h = int(v["width"]), int(v["height"])
        rot = int((v.get("tags") or {}).get("rotate", 0) or next((sd.get("rotation", 0) for sd in v.get("side_data_list", []) if "rotation" in sd), 0) or 0)
        if abs(rot) in (90, 270):
            w, h = h, w
        num, den = (v.get("r_frame_rate", "30/1").split("/") + ["1"])[:2]
        fps = float(num) / float(den or 1)
        a_ok = any(s.get("codec_type") == "audio" for s in info["streams"])
        g = gris(f)
        lum = g.mean(axis=(1, 2))
        mvt = np.r_[0, np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))]
        lap = g[:, :-2, 1:-1] + g[:, 2:, 1:-1] + g[:, 1:-1, :-2] + g[:, 1:-1, 2:] - 4 * g[:, 1:-1, 1:-1]
        net = lap.var(axis=(1, 2))
        seuil = mvt.mean() + 3 * mvt.std() if len(mvt) > 4 else 1e9
        coupes = [round(i / 4, 2) for i in range(1, len(mvt)) if mvt[i] > max(seuil, 18)]
        sec = []
        for s in range(int(math.ceil(dur))):
            sl = slice(s * 4, s * 4 + 4)
            if len(lum[sl]) == 0:
                break
            sec.append({"t": s, "luminosite": round(float(lum[sl].mean()), 1), "mouvement": round(float(mvt[sl].mean()), 2),
                        "nettete": round(float(net[sl].mean()), 1)})
        forts = sorted(sec, key=lambda x: -x["mouvement"])
        moments = []
        for x in forts:
            if all(abs(x["t"] - m) > 1 for m in moments):
                moments.append(x["t"])
            if len(moments) == 4:
                break
        lufs = None
        if a_ok:
            r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", f, "-vn", "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
            m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
            lufs = float(m[-1]) if m else None
        alertes = []
        if min(w, h) < 720: alertes.append(f"résolution faible ({w}x{h}) : mise à l'échelle visible")
        if fps < 24: alertes.append(f"{fps:.0f} i/s : mouvement saccadé")
        if lum.mean() < 55: alertes.append("image sombre : éclaircir ou écarter")
        if lum.mean() > 215: alertes.append("image surexposée")
        if np.median(net) < 25: alertes.append("image peu nette (flou ou compression)")
        if mvt.mean() > 14: alertes.append("caméra très mobile : préférer les passages stables")
        if w > h: alertes.append("clip horizontal : recadrage 9:16, vérifier le sujet (cadrage_focus)")
        moy = float(mvt.mean())
        rythme = "statique" if moy < 2 else "calme" if moy < 6 else "dynamique" if moy < 14 else "très agité"
        item = {"clip": os.path.basename(f), "chemin": f, "duree": round(dur, 2), "resolution": f"{w}x{h}", "orientation": "vertical" if h > w else "horizontal",
                "fps": round(fps, 2), "audio": a_ok, "lufs": lufs, "rythme": rythme, "coupes_internes": coupes[:20], "moments_forts": moments,
                "luminosite_moyenne": round(float(lum.mean()), 1), "nettete_mediane": round(float(np.median(net)), 1), "alertes": alertes, "par_seconde": sec}
        if a.planches:
            n = 12
            pas = max(dur / n, 0.5)
            dt = f",drawtext=fontfile='{fp}':text='%{{pts\\:hms}}':x=6:y=6:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6" if fp else ""
            sortie = os.path.join(a.planches, os.path.splitext(os.path.basename(f))[0] + "-planche.jpg")
            run(["ffmpeg", "-y", "-v", "error", "-i", f, "-vf", f"fps=1/{pas:.3f},scale=240:-2{dt},tile=4x3:padding=4:margin=4", "-frames:v", "1", "-q:v", "4", sortie])
            item["planche"] = sortie
        res.append(item)
        print(f"{item['clip']:<28} {dur:6.1f} s  {item['resolution']:>10}  {rythme:<10} forts {moments}  " + ("; ".join(alertes) or "RAS"))
    ecrire(a.o, {"clips": res})
    print(f"Analyse : {a.o}")


# ------------------------------------------------------------------ rythme
def cmd_rythme(a):
    need()
    import numpy as np
    sr = 22050
    raw = run(["ffmpeg", "-v", "error", "-i", a.musique, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], out=True)
    x = np.frombuffer(raw, dtype=np.float32)
    if len(x) < sr:
        die("musique trop courte")
    hop, n = 512, 1024
    fr = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    sp = np.abs(np.fft.rfft(fr, axis=1))
    flux = np.r_[0, np.maximum(0, np.diff(np.log1p(sp), axis=0)).sum(axis=1)]
    flux = (flux - flux.mean()) / (flux.std() + 1e-9)
    fps_env = sr / hop
    ac = np.correlate(flux, flux, "full")[len(flux) - 1:]
    lags = np.arange(len(ac))
    bpm_l = 60 * fps_env / np.maximum(lags, 1)
    ok = (bpm_l >= 70) & (bpm_l <= 180)
    li = int(lags[ok][np.argmax(ac[ok])])
    y0, y1, y2 = ac[li - 1], ac[li], ac[li + 1]
    lag = li + 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2 + 1e-12)  # sommet affiné (sous-échantillon)
    bpm = 60 * fps_env / lag
    best, phase = -1e9, 0.0
    for ph in np.arange(0, lag, 0.25):
        idx = (ph + lag * np.arange(int((len(flux) - ph) / lag))).round().astype(int)
        s = flux[idx[idx < len(flux)]].sum()
        if s > best:
            best, phase = s, ph
    beats = [round((phase + k * lag) / fps_env, 3) for k in range(int((len(flux) - phase) / lag) + 1)]
    forts = beats[::4]
    duree = len(x) / sr
    ecrire(a.o, {"bpm": round(bpm, 1), "duree": round(duree, 2), "beats": beats, "temps_forts": forts})
    print(f"Tempo ≈ {bpm:.1f} bpm, {len(beats)} temps, {duree:.1f} s → {a.o}")


# ------------------------------------------------------------------ caler
def cmd_caler(a):
    d = charger(a.decoupage)
    b = charger(a.beats)
    beats = b["beats"]
    off = float(d.get("musique_debut", 0))
    pl = plans_de(d)
    t, coupes = 0.0, []
    for p in pl[:-1]:
        t += float(p["duree"]); coupes.append(t)
    nouv, prec = [], 0.0
    for i, c in enumerate(coupes):
        mini = prec + 1.0
        maxi = prec + (2.0 if i == 0 else 3.5)
        cand = [bt - off for bt in beats if mini <= bt - off <= maxi]
        c2 = min(cand, key=lambda x: abs(x - c)) if cand and abs(min(cand, key=lambda x: abs(x - c)) - c) <= a.tolerance else min(max(c, mini), maxi)
        nouv.append(round(c2, 3)); prec = c2
    total = float(sum(float(p["duree"]) for p in pl))
    fin = max(total, prec + 1.0)
    bornes = [0.0] + nouv + [round(fin, 3)]
    for i, p in enumerate(pl):
        p["duree"] = round(bornes[i + 1] - bornes[i], 3)
        p["debut_timeline"] = bornes[i]
    d["cale_sur"] = {"bpm": b["bpm"], "tolerance_s": a.tolerance, "musique_debut": off}
    ecrire(a.o or a.decoupage, d)
    print(f"Coupes calées sur {b['bpm']} bpm : " + ", ".join(f"{x:.2f}" for x in nouv) + f" → {a.o or a.decoupage}")


# ------------------------------------------------------------------ plan
def cmd_plan(a):
    d = charger(a.decoupage)
    ep = d.get("episode", {})
    L = [f"# {ep.get('serie', 'Série')} — Épisode {ep.get('numero', '?')} : {ep.get('titre', '')}", "",
         f"Durée : **{sum(float(p['duree']) for p in plans_de(d)):.1f} s** · Format 9:16 · Hook : « {d.get('hook', {}).get('texte', '')} »", "",
         "| Temps | Plan | Ce qu'on voit | Voix (perso : réplique) | Texte écran | Son / effet | Rôle |", "|---|---|---|---|---|---|---|"]
    for t0, t1, p in timeline(d):
        r = p.get("replique") or {}
        voix = f"{r.get('perso', '')} : « {r.get('texte', '')} »" if r.get("texte") else "—"
        texte = p.get('texte') or (d.get('hook', {}).get('texte') if t0 == 0 else '') or '—'
        L.append(f"| {t0:4.1f}–{t1:4.1f} s | {p.get('id', '')} ({float(p['duree']):.1f} s) | {p.get('action', '')} | {voix} | {texte} | "
                 f"{p.get('son', '') or '—'} | {p.get('fonction', '')} |")
    L += ["", f"Cliffhanger : {d.get('cliffhanger', {}).get('texte', '')} · CTA discret : « {d.get('cta', '')} »"]
    txt = "\n".join(L) + "\n"
    if a.o:
        open(a.o, "w", encoding="utf-8").write(txt)
    print(txt)


# ------------------------------------------------------------------ voix
def cmd_voix(a):
    need()
    d = charger(a.decoupage)
    tl = timeline(d)
    entrees, filt, mots, n = [], [], [], 0
    fin = tl[-1][1]
    for t0, t1, p in tl:
        r = p.get("replique") or {}
        if not r.get("texte"):
            continue
        f = r.get("fichier") or os.path.join(a.repliques, f"{p['id']}.wav")
        if not os.path.exists(f):
            alt = glob.glob(os.path.join(a.repliques, p["id"] + ".*"))
            f = alt[0] if alt else None
        if not f:
            print(f"  {p['id']} : fichier de réplique absent — silence (à générer)")
            continue
        debut = t0 + float(r.get("decalage", 0.15))
        dur = float(probe(f)["format"]["duration"])
        if debut + dur > t1 + 0.6:
            print(f"  AVERTISSEMENT {p['id']} : réplique de {dur:.1f} s pour un plan de {t1 - t0:.1f} s (déborde de {debut + dur - t1:.1f} s)")
        entrees += ["-i", f]
        filt.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,adelay={int(debut * 1000)}|{int(debut * 1000)}[a{n}]")
        n += 1
        mt = r["texte"].split()
        poids = [max(1, len(re.sub(r"\W", "", m))) + 2 for m in mt]
        tot, acc = sum(poids), 0
        for m, w_ in zip(mt, poids):
            mots.append({"mot": m, "debut": round(debut + dur * acc / tot, 3), "fin": round(debut + dur * (acc + w_) / tot, 3), "perso": r.get("perso", "")})
            acc += w_
    if n == 0:
        die("aucune réplique trouvée")
    filt.append("".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0:duration=longest,apad,atrim=0:{fin:.3f}[out]")
    run(["ffmpeg", "-y", "-v", "error"] + entrees + ["-filter_complex", ";".join(filt), "-map", "[out]", "-ar", "48000", a.o])
    source = "proportionnel"
    try:
        from faster_whisper import WhisperModel
        mdl = WhisperModel(a.whisper, device="cpu", compute_type="int8")
        segs, _ = mdl.transcribe(a.o, language="fr", word_timestamps=True, vad_filter=True)
        wm = [{"mot": w.word.strip(), "debut": round(w.start, 3), "fin": round(w.end, 3)} for s in segs for w in (s.words or [])]
        if len(wm) >= 0.6 * len(mots):
            # garder l'orthographe du script, prendre les temps de la voix réelle
            for i, m in enumerate(mots):
                j = min(len(wm) - 1, round(i * (len(wm) - 1) / max(1, len(mots) - 1)))
                m["debut"], m["fin"] = wm[j]["debut"], wm[j]["fin"]
            source = "faster-whisper"
    except Exception:
        pass
    sortie_mots = os.path.splitext(a.o)[0] + "-mots.json"
    ecrire(sortie_mots, {"source": source, "mots": mots})
    print(f"Voix : {a.o} ({n} répliques) · mots : {sortie_mots} (calage {source})")


# ------------------------------------------------------------------ plans
ETALONNAGES = {  # étalonnage colorimétrique seulement (pas de retouche du décor)
    "nuit": ",eq=brightness=-0.20:contrast=1.12:saturation=0.55:gamma=0.85,colorbalance=bs=0.18:bm=0.08:bh=0.05:rs=-0.06,vignette=PI/4",
    "tension": ",eq=contrast=1.08:saturation=0.85,vignette=PI/5",
}


def cmd_plans(a):
    need()
    d = charger(a.decoupage)
    os.makedirs(a.o, exist_ok=True)
    for t0, t1, p in timeline(d):
        dur = t1 - t0
        src = p.get("clip")
        cand = [src] if src and os.path.exists(src) else glob.glob(os.path.join(a.clips, src or "§"))
        if not cand:
            die(f"{p['id']} : clip « {src} » introuvable dans {a.clips}")
        f = cand[0]
        fx, fy = p.get("focus") or [0.5, 0.5]
        z = p.get("zoom", "in")
        amp = float(p.get("zoom_amplitude", 0.045))
        nfr = max(1, int(round(dur * FPS)))
        zexpr = {"in": f"1+{amp}*on/{nfr}", "out": f"1+{amp}*(1-on/{nfr})"}.get(z, "1")
        image = f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        cadre = ""
        if p.get("cadre"):  # [cx, cy, largeur] en fractions de la source : gros plan sur un détail réel (pas de retouche)
            cx, cy, lg = p["cadre"]
            cadre = (f"crop=w='trunc(min(iw*{lg},ih*9/16)/2)*2':h='trunc(min(iw*{lg},ih*9/16)*16/9/2)*2':"
                     f"x='max(0,min(iw-ow,iw*{cx}-ow/2))':y='max(0,min(ih-oh,ih*{cy}-oh/2))',")
        entree = (["-loop", "1", "-t", f"{dur + 0.5:.3f}", "-i", f] if image else ["-ss", f"{float(p.get('debut', 0)):.3f}", "-i", f])
        vf = (f"fps={FPS},{cadre}scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=bicubic,crop={W * 2}:{H * 2}:(iw-ow)*{fx}:(ih-oh)*{fy},"
              f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
              f"tpad=stop_mode=clone:stop_duration={dur + 0.6:.3f},trim=duration={dur + 0.6:.3f},setpts=PTS-STARTPTS,setsar=1")
        vf += ETALONNAGES.get(p.get("etalonnage", ""), "")  # couleur seulement : le décor réel n'est jamais modifié
        inc = p.get("personnage_incruste")
        cmd = ["ffmpeg", "-y", "-v", "error"] + entree
        if inc:
            img = inc["image"] if os.path.exists(inc["image"]) else os.path.join(a.clips, inc["image"])
            tw = int(W * float(inc.get("taille", 0.38)))
            px, py = inc.get("position", [0.5, 0.60])  # bas du personnage ; la bande de sous-titres est à 66 %
            r = p.get("replique") or {}
            d0 = float(r.get("decalage", 0.15))
            d1 = min(dur, d0 + float(r.get("duree_estimee", dur)))
            bob = f"if(between(t,{d0:.2f},{d1:.2f}),14*abs(sin(2*PI*3.1*t)),3*sin(2*PI*0.6*t))" if inc.get("anime", True) else "0"
            sil = ",lutrgb=r=12:g=16:b=22" if inc.get("silhouette") else ""  # silhouette noire, contour conservé par l'alpha
            ox, oy = f"{W * px:.0f}-w/2", f"{H * py:.0f}-h-({bob})"
            if inc.get("ombre", not inc.get("silhouette")):  # ombre portée douce : le fruit « pose » sur le meuble réel
                graphe = (f"[0:v]{vf}[b];[1:v]scale={tw}:-1,format=rgba{sil},split[c][cs];"
                          f"[cs]colorchannelmixer=rr=0:gg=0:bb=0:aa=0.42,boxblur=10:2[sh];"
                          f"[b][sh]overlay=x='{ox}+14':y='{oy}+10':shortest=1[b2];[b2][c]overlay=x='{ox}':y='{oy}':shortest=1,format=yuv420p[v]")
            else:
                graphe = f"[0:v]{vf}[b];[1:v]scale={tw}:-1,format=rgba{sil}[c];[b][c]overlay=x='{ox}':y='{oy}':shortest=1,format=yuv420p[v]"
            cmd += ["-loop", "1", "-i", img, "-filter_complex", graphe, "-map", "[v]"]
        else:
            cmd += ["-vf", vf + ",format=yuv420p"]
        sortie = os.path.join(a.o, f"S{plans_de(d).index(p) + 1}.mp4")
        cmd += ["-an", "-t", f"{dur + 0.6:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", sortie]
        run(cmd)
        print(f"  {os.path.basename(sortie)} ← {os.path.basename(f)} @{p.get('debut', 0)} s, {dur:.2f} s, zoom {z}" + (" + personnage incrusté" if inc else ""))
    print(f"Plans prêts dans {a.o}")


# ------------------------------------------------------------------ projet (Vidéo 4K 2.0)
FONCTION_V4K = {"hook": "accroche", "accroche": "accroche", "tension": "transition", "indice": "demonstration", "revelation": "preuve",
                "cliffhanger": "transition", "decor": "ambiance", "ambiance": "ambiance", "fin": "cta", "cta": "cta"}


def cmd_projet(a):
    d = charger(a.decoupage)
    b = charger(a.bible)
    s = b.get("serie", {})
    ep = d.get("episode", {})
    scenes = []
    pl = plans_de(d)
    for i, p in enumerate(pl, 1):
        r = p.get("replique") or {}
        sc = {"id": f"S{i}", "duree": round(float(p["duree"]), 3), "fonction": FONCTION_V4K.get(p.get("fonction", ""), "ambiance"),
              "action": p.get("action", ""), "plan": p.get("cadrage", "plan vertical"), "mouvement": f"zoom léger {p.get('zoom', 'in')}",
              "source": p.get("source") or ("generation" if p.get("genere") else "client"), "statut_media": "disponible", "transition": p.get("transition", "coupe"),
              "son": p.get("son", "")}
        if i == 1 and d.get("hook", {}).get("texte"):
            sc["texte_ecran"] = d["hook"]["texte"]
        elif p.get("texte"):
            sc["texte_ecran"] = p["texte"]
        if p.get("faits_utilises"):
            sc["faits_utilises"] = p["faits_utilises"]
        if p.get("focus"):
            sc["cadrage_focus"] = p["focus"]
        if r.get("texte"):
            sc["voix_off"] = r["texte"]
        if p.get("genere"):
            sc["prompt"] = p.get("prompt") or {}
            sc["represente_entreprise_reelle"] = False
        scenes.append(sc)
    scenes[-1]["fonction"] = "cta"
    lien = next((f for f in b.get("faits", []) if f.get("id") == d.get("cta_fait", "LIEN_BIO")), {})
    projet = {
        "projet": {"id": f"{ep.get('date', '')}-dkg-{s.get('slug', 'serie')}-ep{ep.get('numero', 0)}", "client": s.get("marque", "DKG Guest House"), "langue": "fr-CA", "version": 1},
        "brief": {"entreprise": s.get("entreprise", "DKG Guest House — appartements meublés à Douala"), "secteur": "immobilier-location-meublee",
                  "offre": s.get("offre", "Séjours en appartements meublés à Douala"), "cible": s.get("cible", ""),
                  "objectif_commercial": "Faire suivre la série et obtenir des réservations directes", "action_spectateur": "Suivre le compte et toucher le lien en bio pour réserver",
                  "canal": "pub-sociale", "placement": "TikTok organique 9:16, série à épisodes", "strategie": "storytelling+conversion",
                  "justification": "Une intrigue à épisodes retient l'attention et fait revenir ; le décor réel montre les appartements sans discours de vente.",
                  "promesse": s.get("promesse", ""), "accroche": d.get("hook", {}).get("texte", ""), "benefice": s.get("benefice", ""),
                  "objections": s.get("objections", []), "kpi": "Taux de visionnage complet, abonnements, clics sur le lien en bio, réservations attribuées",
                  "test_ab": d.get("test_ab", "Deux hooks, même épisode"), "public_moins_13_ans": False},
        "faits": b.get("faits", []),
        "direction_artistique": {"idee": s.get("pitch", ""), "style": s.get("style", ""), "emotion": "suspense, curiosité", "palette": s.get("palette", ["#111418", "#FFFFFF", "#E2B868"]),
                                 "rythme": "plans de 1 à 3 s, coupes calées sur le tempo", "transitions": "coupes sèches, fondu au noir avant la carte finale",
                                 "typo": {"famille": s.get("police", "Montserrat")}, "musique": d.get("musique", {"statut": "a_trouver"}), "logo": s.get("logo", {"statut": "aucun"})},
        "formats": [{"nom": "vertical", "ratio": "9:16", "resolution_cible": "1080x1920", "usage": "TikTok, Reels"}],
        "voix_off": {"active": any((p.get("replique") or {}).get("texte") for p in pl), "voix": "voix des personnages (bible)", "outil": "Higgsfield", "statut": d.get("statut_voix", "a_generer")},
        "cta": {"texte": d.get("carte_finale", {}).get("texte") or d.get("cliffhanger", {}).get("texte", "À suivre…"),
                "coordonnees": d.get("carte_finale", {}).get("sous_texte") or d.get("cta", "Lien en bio pour réserver ton séjour DKG"),
                "statut": "verifie" if lien.get("statut") == "verifie" else "a_fournir"},
        "mention_images_illustratives": "Personnages générés par IA" if any(p.get("genere") or p.get("personnage_incruste") for p in pl) else "",
        "scenes": scenes,
        "ressources": d.get("ressources", []),
        "production": {"outil_video": d.get("outil_video", "clips DKG + Higgsfield"), "fps": FPS, "statut": "prepare"},
    }
    ecrire(a.o, projet)
    print(f"Projet Vidéo 4K 2.0 : {a.o} ({len(scenes)} scènes, {sum(x['duree'] for x in scenes):.1f} s) — lancer « video4k.py valider »")


# ------------------------------------------------------------------ finitions
def t_ass(x):
    cs = int(round(max(0, x) * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_col(hexa, alpha="00"):
    hexa = hexa.lstrip("#"); r, g, b = int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16)
    return f"&H{alpha}{b:02X}{g:02X}{r:02X}"


def groupes(mots, maxm=3, maxc=20):
    G, cur = [], []
    for m in mots:
        cur.append(m)
        txt = " ".join(x["mot"] for x in cur)
        coupe = re.search(r"[.!?…,;:]$", m["mot"]) or len(cur) >= maxm or len(txt) >= maxc
        if coupe:
            G.append(cur); cur = []
    if cur:
        G.append(cur)
    return G


def cmd_finitions(a):
    need()
    d = charger(a.decoupage)
    info = probe(a.master)
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    w, h = int(v["width"]), int(v["height"])
    dur = float(info["format"]["duration"])
    u = w / 1080
    fp = police(); fam = famille(fp)
    accent = d.get("accent", "#E2B868")
    tl = timeline(d)
    fin_contenu = tl[-1][0]
    L = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
         f"Style: Mot,{fam},{int(80 * u)},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,{max(2, int(5 * u))},{max(1, int(2 * u))},5,{int(70 * u)},{int(70 * u)},0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    y = int(h * float(d.get("sous_titres_hauteur", 0.66)))
    if a.mots and os.path.exists(a.mots):
        mots = [m for m in charger(a.mots)["mots"] if m["debut"] < fin_contenu]
        G = groupes(mots)
        for gi, g in enumerate(G):
            g_fin = min(G[gi + 1][0]["debut"] if gi + 1 < len(G) else g[-1]["fin"] + 0.35, g[-1]["fin"] + 0.45, fin_contenu)
            for k, m in enumerate(g):
                t0 = m["debut"]
                t1 = g[k + 1]["debut"] if k + 1 < len(g) else g_fin
                parts = []
                for j, x in enumerate(g):
                    mot = x["mot"].replace("{", "(").replace("}", ")")
                    parts.append("{\\c" + ass_col(accent) + "}" + mot + "{\\c&H00FFFFFF&}" if j == k else mot)
                pop = "{\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
                L.append(f"Dialogue: 0,{t_ass(t0)},{t_ass(t1)},Mot,,0,0,0,,{{\\pos({w // 2},{y})}}{pop}" + " ".join(parts))
    ass = tempfile.mktemp(suffix=".ass")
    open(ass, "w", encoding="utf-8").write("\n".join(L) + "\n")
    t_cliff = fin_contenu
    vf = [f"subtitles='{ass}'" + (f":fontsdir='{os.path.dirname(fp)}'" if fp else "")]
    if d.get("cliffhanger", {}).get("flash", True):
        vf.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='between(t,{t_cliff - 0.05:.2f},{t_cliff + 0.07:.2f})'")
    has_a = any(s.get("codec_type") == "audio" for s in info["streams"])
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", a.master]
    if has_a and d.get("cliffhanger", {}).get("impact", True):
        cmd += ["-f", "lavfi", "-t", "0.9", "-i", "sine=frequency=52:sample_rate=48000"]  # impact grave synthétisé : aucun droit tiers
        fc = (f"[0:v]{','.join(vf)}[v];[1:a]volume=0.6,afade=t=out:st=0:d=0.9,aformat=channel_layouts=stereo,adelay={int(t_cliff * 1000)}|{int(t_cliff * 1000)}[imp];"
              f"[0:a][imp]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.7:level=false[a]")
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-vf", ",".join(vf)] + (["-af", "alimiter=limit=0.7:level=false", "-c:a", "aac", "-b:a", "192k"] if has_a else ["-an"])
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", a.o]
    run(cmd)
    os.remove(ass)
    print(f"Épisode fini : {a.o} ({w}x{h}, {dur:.1f} s ; sous-titres {'mot à mot' if a.mots else 'absents'} ; cliffhanger à {t_cliff:.2f} s)")


# ------------------------------------------------------------------ grille
def cmd_grille(a):
    need()
    d = charger(a.decoupage)
    info = probe(a.video)
    v = next(s for s in info["streams"] if s.get("codec_type") == "video")
    dur = float(info["format"]["duration"])
    pl = plans_de(d)
    durs = [float(p["duree"]) for p in pl]
    contenu = durs[:-1] or durs
    med = sorted(contenu)[len(contenu) // 2]
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.video, "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
    lufs = float(m[-1]) if m else None
    mots = charger(a.mots)["mots"] if a.mots and os.path.exists(a.mots) else []
    parle = sum(1 for p in pl if (p.get("replique") or {}).get("texte"))
    C = []
    def crit(nom, pts, ok, note):
        C.append((nom, pts if ok else 0, pts, note))
    crit("Durée 30-45 s", 10, 30 <= dur <= 45.5, f"{dur:.1f} s")
    crit("Hook ≤ 2 s avec texte à l'écran", 15, durs[0] <= 2.05 and bool(d.get("hook", {}).get("texte")), f"plan 1 = {durs[0]:.1f} s")
    crit("Première coupe avant 2 s", 10, durs[0] <= 2.05, f"{durs[0]:.1f} s")
    crit("Plans courts (médiane 1-3 s)", 15, 1 <= med <= 3, f"médiane {med:.1f} s")
    crit("Montée de tension (plans qui raccourcissent)", 5, sum(contenu[-3:]) / 3 <= sum(contenu[:3]) / 3 + 0.2 if len(contenu) >= 6 else False, "fin vs début")
    crit("Sous-titres mot à mot", 10, bool(mots) or parle == 0, f"{len(mots)} mots")
    crit("Cliffhanger avant la révélation", 10, bool(d.get("cliffhanger", {}).get("texte")) and pl[-2].get("fonction") in ("cliffhanger", "tension"), pl[-2].get("fonction", "?") if len(pl) > 1 else "?")
    crit("CTA discret présent", 5, bool(d.get("cta")), d.get("cta", ""))
    crit("Sonie -14 LUFS (±1,5)", 10, lufs is not None and abs(lufs + 14) <= 1.5, f"{lufs} LUFS")
    crit("1080x1920, 30 i/s", 10, int(v["width"]) == 1080 and int(v["height"]) == 1920, f"{v['width']}x{v['height']}")
    tot = sum(c[1] for c in C)
    print("Grille de viralité INTERNE (règles de montage, pas une prédiction d'audience)")
    for nom, p, mx, note in C:
        print(f"  {'✔' if p else '✘'} {nom:<45} {p:>2}/{mx:<3} {note}")
    print(f"  TOTAL {tot}/100 → " + ("solide" if tot >= 80 else "à renforcer" if tot >= 60 else "à refaire"))
    return 0 if tot >= 60 else 1


# ------------------------------------------------------------------ bible
BIBLE_VIDE = {
    "version": 1,
    "serie": {"titre": "", "slug": "", "marque": "DKG Guest House", "entreprise": "DKG Guest House — appartements meublés à Douala", "pitch": "", "ton": "drame / mystère, premium, jamais enfantin",
              "style": "", "palette": ["#111418", "#FFFFFF", "#E2B868"], "police": "Montserrat ExtraBold (sous-titres)", "duree_cible_s": [30, 45], "format": "9:16 1080x1920",
              "cta": "Lien en bio pour réserver ton séjour DKG", "cible": "", "promesse": "", "regles": []},
    "personnages": [],
    "lieux": [],
    "musique": {"theme": "", "outil": "", "licence": "", "verifiee_le": "", "fichier": ""},
    "faits": [{"id": "LIEN_BIO", "texte": "Le lien en bio mène à la réservation DKG", "statut": "a_fournir"}],
    "episodes": [],
    "fils_ouverts": [],
}


def cmd_bible(a):
    if a.action == "init":
        if os.path.exists(a.fichier):
            die(f"{a.fichier} existe déjà : ne pas l'écraser")
        ecrire(a.fichier, BIBLE_VIDE); print(f"Bible créée : {a.fichier}"); return
    b = charger(a.fichier)
    if a.action == "episode":
        e = charger(a.episode)
        b["episodes"] = [x for x in b["episodes"] if x.get("numero") != e.get("numero")] + [e]
        b["episodes"].sort(key=lambda x: x.get("numero", 0))
        b["fils_ouverts"] = e.get("fils_ouverts", b.get("fils_ouverts", []))
        ecrire(a.fichier, b); print(f"Épisode {e.get('numero')} consigné dans la bible")
    s = b["serie"]
    L = [f"# Bible de série — {s.get('titre')}", "", f"**Pitch** : {s.get('pitch')}", f"**Ton** : {s.get('ton')} · **Style** : {s.get('style')}",
         f"**Palette** : {', '.join(s.get('palette', []))} · **Police** : {s.get('police')} · **Format** : {s.get('format')}, {s.get('duree_cible_s')} s",
         f"**CTA** : « {s.get('cta')} »", "", "## Règles", *[f"- {r}" for r in s.get("regles", [])], "", "## Personnages", ""]
    for p in b.get("personnages", []):
        vx = p.get("voix", {})
        L += [f"### {p.get('nom')} — {p.get('fruit')}", f"- Rôle : {p.get('role')}", f"- Caractère : {p.get('caractere')}", f"- Façon de parler : {p.get('parler')}",
              f"- Apparence (prompt figé) : {p.get('apparence')}", f"- Voix : {vx.get('nom', '')} ({vx.get('modele', '')}, voice_id {vx.get('voice_id', 'à choisir')}, réglages {vx.get('reglages', {})}) — statut {vx.get('statut', 'à valider')}",
              f"- Image de référence : {p.get('image_ref', {}).get('media_id') or 'à générer'}", ""]
    L += ["## Lieux (décors réels DKG)", *[f"- {l.get('nom')} : {l.get('description')} — clips : {', '.join(l.get('clips', []))}" for l in b.get("lieux", [])], "",
          "## Musique", f"- {b['musique'].get('theme')} · outil {b['musique'].get('outil')} · licence {b['musique'].get('licence')} (vérifiée le {b['musique'].get('verifiee_le')})", "",
          "## Faits vérifiables", *[f"- [{f.get('statut')}] {f.get('texte')}" + (f" — source {f.get('source')}, {f.get('date')}" if f.get('source') else "") for f in b.get("faits", [])], "",
          "## Épisodes", *[f"- Ép. {e.get('numero')} « {e.get('titre')} » — {e.get('resume')} · Cliffhanger : {e.get('cliffhanger')}" for e in b.get("episodes", [])], "",
          "## Fils ouverts", *[f"- {x}" for x in b.get("fils_ouverts", [])]]
    out = os.path.splitext(a.fichier)[0] + ".md"
    open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"Bible lisible : {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="c", required=True)
    s = sp.add_parser("analyser"); s.add_argument("clips", nargs="+"); s.add_argument("-o", default="analyse.json"); s.add_argument("--planches"); s.set_defaults(f=cmd_analyser)
    s = sp.add_parser("rythme"); s.add_argument("musique"); s.add_argument("-o", default="beats.json"); s.set_defaults(f=cmd_rythme)
    s = sp.add_parser("caler"); s.add_argument("decoupage"); s.add_argument("--beats", required=True); s.add_argument("-o"); s.add_argument("--tolerance", type=float, default=0.3); s.set_defaults(f=cmd_caler)
    s = sp.add_parser("plan"); s.add_argument("decoupage"); s.add_argument("-o"); s.set_defaults(f=cmd_plan)
    s = sp.add_parser("voix"); s.add_argument("decoupage"); s.add_argument("--repliques", required=True); s.add_argument("-o", default="voix.wav"); s.add_argument("--whisper", default="small"); s.set_defaults(f=cmd_voix)
    s = sp.add_parser("plans"); s.add_argument("decoupage"); s.add_argument("--clips", required=True); s.add_argument("-o", default="plans"); s.set_defaults(f=cmd_plans)
    s = sp.add_parser("projet"); s.add_argument("decoupage"); s.add_argument("--bible", required=True); s.add_argument("-o", default="projet.json"); s.set_defaults(f=cmd_projet)
    s = sp.add_parser("finitions"); s.add_argument("master"); s.add_argument("decoupage"); s.add_argument("--mots"); s.add_argument("-o", default="episode.mp4"); s.set_defaults(f=cmd_finitions)
    s = sp.add_parser("grille"); s.add_argument("video"); s.add_argument("decoupage"); s.add_argument("--mots"); s.set_defaults(f=cmd_grille)
    s = sp.add_parser("bible"); s.add_argument("action", choices=["init", "md", "episode"]); s.add_argument("fichier"); s.add_argument("--episode"); s.set_defaults(f=cmd_bible)
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
