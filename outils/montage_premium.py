#!/usr/bin/env python3
"""Montage de la version premium (plans animés Seedance, dialogue natif) : coupes franches, titres, sous-titres mot à mot,
flash et fondu au noir sur le cliffhanger, carte finale avec voix off, musique atténuée sous les dialogues, −14 LUFS.

  python3 outils/montage_premium.py MONTAGE.json -o episode.mp4

MONTAGE.json :
{
  "dossier": "/home/user/films/cle-de-trop",            # où sont les clips
  "clips": [{"id": "C1", "fichier": "c1.mp4", "debut": 0, "fin": 5.0, "titre": "Qui dormait ici ?",
             "lignes": ["Quelqu'un a dormi ici."]}, …],   # lignes = texte exact du script, dans l'ordre (sous-titres)
  "carte": {"image": "…png", "duree": 4.0, "voix": "…wav", "voix_decalage": 0.4},
  "musique": {"fichier": "…mp3", "gain_db": -17, "segments": [{"debut_film": 5.0, "source": 0, "duree": 18.5}, …]},
  "accent": "#FF3130", "sous_titres_hauteur": 0.68, "titres_hauteur": 0.20
}
Les temps des mots viennent de faster-whisper sur l'audio de chaque clip ; l'orthographe vient du script.
"""
import argparse, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import serie  # noqa: E402  (police, famille, groupes, t_ass, ass_col)

W, H, FPS = 1080, 1920, 30


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg : " + r.stderr[-2000:])
    return r.stdout


def duree(f):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).strip())


def jetons(ligne):
    """Mots du script ; une ponctuation isolée (« ! », « ? ») reste collée au mot d'avant."""
    out = []
    for w in ligne.split():
        if out and not re.search(r"\w", w):
            out[-1] += " " + w
        else:
            out.append(w)
    return out


def caler(jet, wm, decal):
    res = []
    for k, mot in enumerate(jet):
        j = min(len(wm) - 1, round(k * (len(wm) - 1) / max(1, len(jet) - 1)))
        res.append({"mot": mot, "debut": round(decal + wm[j].start, 3), "fin": round(decal + wm[j].end, 3)})
    return res


def mots_du_clip(fichier, debut, fin, lignes, decal, modele):
    """Temps réels (whisper) + orthographe du script. Chaque réplique est calée sur son propre segment parlé quand
    whisper en trouve autant que de répliques ; sinon, sur l'ensemble des mots du clip."""
    if not lignes:
        return []
    segs, _ = modele.transcribe(fichier, language="fr", word_timestamps=True, beam_size=5)
    segs = [s for s in segs if s.words and debut - 0.05 <= s.start < fin]
    if not segs:
        return []
    base = decal - debut
    if len(segs) == len(lignes):
        out = []
        for l, sg in zip(lignes, segs):
            out += caler(jetons(l), list(sg.words), base)
        return out
    wm = [w for sg in segs for w in sg.words]
    return caler([w for l in lignes for w in jetons(l)], wm, base)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config"); ap.add_argument("-o", default="episode-premium.mp4")
    a = ap.parse_args()
    c = json.load(open(a.config, encoding="utf-8"))
    D = c.get("dossier", ".")
    clips = c["clips"]
    carte = c["carte"]
    accent = c.get("accent", "#FF3130")
    tmp = tempfile.mkdtemp()

    # 1. vidéo : chaque clip coupé, mis à l'échelle 1080x1920, 30 i/s ; puis la carte
    entrees, fv, fa, t, bornes = [], [], [], 0.0, []
    for i, cl in enumerate(clips):
        f = os.path.join(D, cl["fichier"])
        d0, d1 = float(cl.get("debut", 0)), float(cl.get("fin") or duree(f))
        entrees += ["-i", f]
        et = ""
        for e in cl.get("etalonnage", []):  # ex. {"de": 6.0, "a": 10.1, "type": "nuit"} — temps du clip source
            en = f"enable='between(t,{float(e['de']) - d0:.2f},{float(e['a']) - d0:.2f})'"
            if e.get("type", "nuit") == "nuit":
                et += (f",eq=brightness=-0.13:contrast=1.08:saturation=0.62:gamma=0.88:{en}"
                       f",colorbalance=bs=0.16:bm=0.07:rs=-0.05:rm=-0.03:{en}")
        fv.append(f"[{i}:v]trim={d0}:{d1},setpts=PTS-STARTPTS{et},scale={W}:{H}:flags=lanczos,unsharp=5:5:0.6,fps={FPS},setsar=1,format=yuv420p[v{i}]")
        fa.append(f"[{i}:a]atrim={d0}:{d1},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a{i}]")
        bornes.append((t, t + d1 - d0, cl, d0, d1))
        t += d1 - d0
    fin_clips = t
    n = len(clips)
    entrees += ["-loop", "1", "-t", str(carte["duree"]), "-i", os.path.join(D, carte["image"])]
    fv.append(f"[{n}:v]scale={W}:{H},fps={FPS},setsar=1,format=yuv420p,fade=t=in:st=0:d=0.35[v{n}]")
    total = fin_clips + float(carte["duree"])
    # flash blanc juste avant le noir, puis fondu au noir sur la fin du dernier clip
    tf = fin_clips - 0.55
    fv.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,"
              f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='between(t,{tf:.2f},{tf + 0.12:.2f})',"
              f"fade=t=out:st={fin_clips - 0.4:.2f}:d=0.4[vc]")
    fv.append(f"[vc][v{n}]concat=n=2:v=1:a=0[vfilm]")

    # 2. dialogue : sons des clips bout à bout + voix off de la carte
    entrees += ["-i", os.path.join(D, carte["voix"])]
    vo = n + 1
    dec = int((fin_clips + float(carte.get("voix_decalage", 0.4))) * 1000)
    fa.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1,afade=t=out:st={fin_clips - 0.4:.2f}:d=0.4,apad=whole_dur={total}[dlg0]")
    fa.append(f"[{vo}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={dec}|{dec}[vo]")
    fa.append(f"[dlg0][vo]amix=inputs=2:normalize=0:duration=first,asplit=2[dlg][dlgsc]")

    # 3. musique : segments du thème, atténuée sous les voix (sidechain)
    mu = c.get("musique")
    if mu:
        entrees += ["-i", os.path.join(D, mu["fichier"])] * len(mu["segments"])
        segs = []
        for k, s in enumerate(mu["segments"]):
            idx = vo + 1 + k
            ms = int(s["debut_film"] * 1000)
            fo = s.get("fondu_sortie", 0.3)
            fa.append(f"[{idx}:a]atrim={s['source']}:{s['source'] + s['duree']},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"afade=t=in:d={s.get('fondu_entree', 0.2)},afade=t=out:st={max(0, s['duree'] - fo)}:d={fo},adelay={ms}|{ms}[m{k}]")
            segs.append(f"[m{k}]")
        fa.append("".join(segs) + f"amix=inputs={len(segs)}:normalize=0,apad=whole_dur={total},volume={mu.get('gain_db', -17)}dB[mus]")
        fa.append("[mus][dlgsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[musd]")
        fa.append("[dlg][musd]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[afilm]")
    else:
        fa.append("[dlg]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[afilm]")

    # 4. sous-titres mot à mot (whisper par clip) + titres en haut
    from faster_whisper import WhisperModel
    mdl = WhisperModel("small", device="cpu", compute_type="int8")
    mots = []
    for t0, t1, cl, d0, d1 in bornes:
        mots += mots_du_clip(os.path.join(D, cl["fichier"]), d0, d1, cl.get("lignes", []), t0, mdl)
    json.dump({"source": "faster-whisper par clip", "mots": mots}, open(os.path.splitext(a.o)[0] + "-mots.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    fp = serie.police(); fam = serie.famille(fp)
    y = int(H * float(c.get("sous_titres_hauteur", 0.68))); yt = int(H * float(c.get("titres_hauteur", 0.20)))
    L = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
         f"Style: Mot,{fam},78,&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,5,2,5,70,70,0,1",
         f"Style: Titre,{fam},88,&H00FFFFFF,&H00FFFFFF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,6,3,5,70,70,0,1",
         f"Style: Nom,{fam},54,&H00FFFFFF,&H00FFFFFF,&H00101010,&H78000000,-1,0,0,0,100,100,0,0,1,4,2,4,70,70,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for t0, t1, cl, d0, d1 in bornes:
        if cl.get("titre"):
            L.append(f"Dialogue: 1,{serie.t_ass(t0 + (0 if t0 == 0 else 0.1))},{serie.t_ass(min(t1, t0 + 2.2) - 0.05)},Titre,,0,0,0,,{{\\pos({W // 2},{yt})\\fad({0 if t0 == 0 else 160},160)}}{cl['titre']}")
    yn = int(H * float(c.get("noms_hauteur", 0.30)))
    for t0, t1, cl, d0, d1 in bornes:  # nom du personnage à sa première apparition (ex. « Bana · la concierge »)
        for nm in cl.get("noms", []):
            n0, n1 = t0 + float(nm["de"]) - d0, min(t1, t0 + float(nm["a"]) - d0)
            nom, _, role = nm["texte"].partition("·")
            txt = "{\\c" + serie.ass_col(accent) + "}" + nom.strip() + ("{\\c&H00FFFFFF&} · " + role.strip() if role else "")
            L.append(f"Dialogue: 1,{serie.t_ass(n0)},{serie.t_ass(n1)},Nom,,0,0,0,,{{\\pos(70,{yn})\\fad(200,200)}}" + txt)
    G = serie.groupes([m for m in mots if m["debut"] < fin_clips])
    for gi, g in enumerate(G):
        g_fin = min(G[gi + 1][0]["debut"] if gi + 1 < len(G) else g[-1]["fin"] + 0.35, g[-1]["fin"] + 0.45, fin_clips - 0.4)
        for k, m in enumerate(g):
            a0 = m["debut"]; a1 = g[k + 1]["debut"] if k + 1 < len(g) else g_fin
            if a1 <= a0:
                continue
            parts = ["{\\c" + serie.ass_col(accent) + "}" + x["mot"] + "{\\c&H00FFFFFF&}" if j == k else x["mot"] for j, x in enumerate(g)]
            pop = "{\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
            L.append(f"Dialogue: 0,{serie.t_ass(a0)},{serie.t_ass(a1)},Mot,,0,0,0,,{{\\pos({W // 2},{y})}}{pop}" + " ".join(parts))
    ass = os.path.join(tmp, "textes.ass")
    open(ass, "w", encoding="utf-8").write("\n".join(L) + "\n")
    fv.append(f"[vfilm]subtitles='{ass}':fontsdir='{os.path.dirname(fp)}'[vout]")

    cmd = ["ffmpeg", "-y", "-v", "error"] + entrees + ["-filter_complex", ";".join(fv + fa), "-map", "[vout]", "-map", "[afilm]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-t", f"{total:.3f}", a.o]
    run(cmd)
    print(f"Épisode premium : {a.o} ({total:.1f} s ; {len(mots)} mots sous-titrés ; clips {fin_clips:.1f} s + carte {carte['duree']} s)")


if __name__ == "__main__":
    main()
