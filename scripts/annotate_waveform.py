"""Dev tool: annotate a stereo waveform PNG (from ffmpeg showwavespic) with measured findings.
Usage: uv run --with pillow python scripts/annotate_waveform.py <raw.png> <out.png> <duration_s> "<label>@start-end" ...
"""

import sys

from PIL import Image, ImageDraw, ImageFont

raw, out, dur = sys.argv[1], sys.argv[2], float(sys.argv[3])
im = Image.open(raw).convert("RGB")
W, H = im.size
canvas = Image.new("RGB", (W, H + 70), "white")
canvas.paste(im, (0, 40))
d = ImageDraw.Draw(canvas)
try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 22)
    small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 17)
except Exception:
    font = small = ImageFont.load_default()
d.text((10, 8), "AGENT under test  (left channel)", fill=(30, 64, 175), font=font)
d.text((10, 40 + H // 2 + 6), "SIMULATED CALLER  (right channel)", fill=(180, 83, 9), font=font)
d.text((W - 200, 12), f"0 s  →  {dur:.0f} s   (16 kHz stereo)", fill=(107, 114, 128), font=small)
px = W / dur
for spec in sys.argv[4:]:
    label, rng = spec.rsplit("@", 1)
    a, b = (float(x) for x in rng.split("-"))
    x0, x1 = int(a * px), int(b * px)
    d.rectangle([x0, 42, x1, 40 + H - 2], outline=(220, 38, 38), width=3)
    tw = d.textlength(label, font=small)
    tx = min(max(x0, 4), W - tw - 4)
    d.rectangle([tx - 4, H + 42, tx + tw + 4, H + 66], fill=(254, 226, 226))
    d.text((tx, H + 44), label, fill=(185, 28, 28), font=small)
canvas.save(out)
print("wrote", out, canvas.size)
