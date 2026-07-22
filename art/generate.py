#!/usr/bin/env python3
"""
Generate the Preflight reaction bank with FLUX.2-dev on Modular Cloud.

Three verdict bands, each a short animated GIF of ONE consistent cartoon
mascot cycling through 3-4 expressions/actions:

  go-triumphant  -> astronaut mascot popping champagne in zero-g
  hold-close     -> mammoth mascot squinting through a magnifying glass, "so close"
  hold-rough     -> flame mascot face-palming into a puff of smoke

Frames are generated one per FLUX call, resized to ~512px, and assembled into
an animated GIF with PIL. Each GIF is kept under ~3MB.

NOTE: the PR comment now embeds a single static .png frame per band (the GIFs
read as slideshows, not motion). The .gif files are kept for future motion work;
the committed .png beside each is the hand-picked cleanest frame.

Usage:
  export MODULAR_API_KEY=$(grep -h '^MODULAR_API_KEY=' ~/modular/data-bos-warehouse/.env.local | cut -d= -f2)
  python3 art/generate.py
"""
import base64
import io
import json
import os
import sys
import time
import urllib.request

from PIL import Image

API = "https://api.modular.com/v1/responses"
KEY = os.environ.get("MODULAR_API_KEY", "").strip()
MODEL = "black-forest-labs/FLUX.2-dev"

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reactions")

# Shared style so every frame of a band is clearly the same character.
STYLE = ("cute chibi cartoon mascot, thick bold black outlines, flat vibrant colors, "
         "simple solid background, centered full-body character, sticker art style, "
         "no text, no words, no letters")

BANDS = {
    "go-triumphant": {
        "character": "a cheerful round white astronaut mascot in a puffy space suit with a glass helmet",
        "frames": [
            "floating in zero gravity holding a bottle of champagne, cork just popping off with a burst of golden sparkles, huge joyful grin",
            "arms thrown up in celebration, champagne fizz and confetti drifting around in zero gravity, eyes squeezed shut laughing",
            "doing a triumphant fist pump, tiny stars and bubbles floating around, giving a big thumbs up",
            "striking a proud victory pose with a little green GO flag, beaming with delight, sparkles everywhere",
        ],
    },
    "hold-close": {
        "character": "a fuzzy brown baby mammoth mascot with tiny tusks and a little trunk",
        "frames": [
            "holding a large magnifying glass up to one eye, squinting carefully at something, curious focused expression",
            "tilting its head with the magnifying glass lowered, one eyebrow raised, a hopeful 'so close' half-smile",
            "holding up a small measuring tape between its trunk and foot showing a tiny gap, encouraging optimistic look",
            "giving a gentle nod with a small approving smile, one tiny bandaid on its trunk, almost-there vibe",
        ],
    },
    "hold-rough": {
        "character": "a bright orange flame mascot with big cartoon eyes and little arms",
        "frames": [
            "face-palming with one hand over its eyes, a small puff of grey smoke rising off its head, exasperated",
            "slumping down and flickering low, a comic sweat drop, dramatic sigh with smoke curling upward",
            "peeking through its fingers with one worried eye, half melted into a small smoky puddle",
            "shrugging with both little arms out, a wry 'well, that happened' look, wisps of smoke around it",
        ],
    },
}


def flux(prompt):
    body = json.dumps({
        "model": MODEL,
        "input": prompt,
    }).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    b64 = d["output"][0]["content"][0]["image_data"]
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def build_band(name, spec, size=512):
    frames = []
    for i, action in enumerate(spec["frames"], 1):
        prompt = f"{STYLE}. {spec['character']}, {action}."
        print(f"  [{name}] frame {i}/{len(spec['frames'])} …", flush=True)
        for attempt in range(3):
            try:
                img = flux(prompt)
                break
            except Exception as e:
                print(f"    retry {attempt+1}: {e}", flush=True)
                time.sleep(3)
        else:
            raise SystemExit(f"FLUX failed for {name} frame {i}")
        img.thumbnail((size, size), Image.LANCZOS)
        frames.append(img)

    # Assemble animated GIF, adaptive palette, tune to stay < ~3MB.
    path = os.path.join(OUT, f"{name}.gif")
    for colors in (256, 128, 96, 64):
        pal = [f.convert("P", palette=Image.ADAPTIVE, colors=colors) for f in frames]
        pal[0].save(path, save_all=True, append_images=pal[1:], loop=0,
                    duration=700, disposal=2, optimize=True)
        mb = os.path.getsize(path) / 1e6
        if mb <= 3.0:
            break
    print(f"  [{name}] -> {path}  ({mb:.2f} MB, {len(frames)} frames, {colors} colors)")
    return path


def main():
    if not KEY:
        sys.exit("set MODULAR_API_KEY")
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:] or list(BANDS)
    for name in only:
        build_band(name, BANDS[name])
    print("done.")


if __name__ == "__main__":
    main()
