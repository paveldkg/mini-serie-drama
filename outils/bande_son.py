#!/usr/bin/env python3
"""Bande musicale d'un épisode : thème recoupé selon le découpage + effets synthétisés (aucun droit tiers).

  python3 outils/bande_son.py DECOUPAGE --musique theme.mp3 -o musique-episode.wav

Lit la section « bande_son » du découpage :
  segments : [{debut, source, duree, gain_db?, fondu_entree?, fondu_sortie?}]  (secondes)
  effets   : [{t, type: coup | bip | toc}]
La sortie dure exactement la durée de l'épisode ; video4k.py monter l'atténue sous les voix.
"""
import argparse, json, subprocess, sys

EFFETS = {  # synthèse ffmpeg (lavfi) : coup sourd, bip électronique de coffre, coup frappé à une porte en bois
    "coup": ("sine=frequency=48:duration=0.9", "volume=1.6,afade=t=out:st=0.05:d=0.85"),
    "bip": ("sine=frequency=2100:duration=0.22", "volume=0.35,afade=t=in:d=0.005,afade=t=out:st=0.06:d=0.02,"
            "aecho=1:1:110:0.9,atrim=0:0.22"),
    "toc": ("anoisesrc=d=0.16:c=brown:a=0.9", "lowpass=f=520,highpass=f=70,volume=3.2,afade=t=in:d=0.002,afade=t=out:st=0.01:d=0.14"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("decoupage"); ap.add_argument("--musique", required=True); ap.add_argument("-o", default="musique-episode.wav")
    a = ap.parse_args()
    d = json.load(open(a.decoupage, encoding="utf-8"))
    bs = d.get("bande_son") or sys.exit("découpage sans section bande_son")
    total = round(sum(float(p["duree"]) for p in d["plans"]), 3)
    entrees, filt, n = [], [], 0
    for s in bs.get("segments", []):
        entrees += ["-i", a.musique]
        f = f"[{n}:a]atrim={s['source']}:{s['source'] + s['duree']},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo"
        if s.get("gain_db"): f += f",volume={s['gain_db']}dB"
        if s.get("fondu_entree"): f += f",afade=t=in:d={s['fondu_entree']}"
        if s.get("fondu_sortie"): f += f",afade=t=out:st={max(0, s['duree'] - s['fondu_sortie'])}:d={s['fondu_sortie']}"
        ms = int(s["debut"] * 1000)
        filt.append(f + f",adelay={ms}|{ms}[m{n}]"); n += 1
    for e in bs.get("effets", []):
        src, chaine = EFFETS[e["type"]]
        entrees += ["-f", "lavfi", "-i", src]
        ms = int(e["t"] * 1000)
        filt.append(f"[{n}:a]{chaine},aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[m{n}]"); n += 1
    filt.append("".join(f"[m{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0:duration=longest,apad,atrim=0:{total},alimiter=limit=0.9:level=false[out]")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + entrees + ["-filter_complex", ";".join(filt), "-map", "[out]", "-ar", "48000", a.o], capture_output=True, text=True)
    if r.returncode: sys.exit(r.stderr[-1500:])
    print(f"Bande son : {a.o} ({total} s, {len(bs.get('segments', []))} segments de musique, {len(bs.get('effets', []))} effets)")


if __name__ == "__main__":
    main()
