"""Crack captcha using sliding window correlation matching with rotation"""
import base64, json, requests, secrets
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

FONT_PATH = os.path.join(os.path.dirname(__file__), "backend", "DejaVuSans-Bold.ttf")
font = ImageFont.truetype(FONT_PATH, 32)

# Generate reference digits with ALL possible rotations
refs = {}  # {digit: [rotated_bw_images]}
for d in "0123456789":
    refs[d] = []
    for angle in range(-15, 16, 3):  # every 3 degrees
        char_img = Image.new("RGBA", (32, 36), (0, 0, 0, 0))
        char_draw = ImageDraw.Draw(char_img)
        char_draw.text((4, 1), d, fill=(50, 50, 50), font=font)
        rotated = char_img.rotate(angle, expand=1, fillcolor=(0, 0, 0, 0))
        gray = rotated.convert("L")
        bw = gray.point(lambda x: 255 if x > 128 else 0)
        refs[d].append(bw)


def score_match(segment, ref):
    """Pixel difference score (lower = better)"""
    seg_resized = segment.resize(ref.size, Image.LANCZOS)
    diff = 0
    for y in range(ref.height):
        for x in range(ref.width):
            p1 = seg_resized.getpixel((x, y))
            p2 = ref.getpixel((x, y))
            diff += abs(p1 - p2)
    return diff


# Get captcha from Railway
r = requests.get("https://ai-knowledge-base-qtme-production.up.railway.app/api/auth/captcha", timeout=10)
data = r.json()
captcha_id = data["captcha_id"]
header, bdata = data["image"].split(",", 1)
captcha_img = Image.open(BytesIO(base64.b64decode(bdata)))
captcha_img.save("captcha_original.png")

# Process captcha image
gray = captcha_img.convert("L")
bw = gray.point(lambda x: 255 if x > 240 else 0)
bw.save("captcha_bw.png")

w, h = bw.size
print(f"Image size: {w}x{h}")

# Sliding window approach: scan each row, find the best positions for each digit
# First, find vertical center of content
# Find all black pixels
pixels = []
for y in range(h):
    for x in range(w):
        p = bw.getpixel((x, y))
        if p == 0:
            pixels.append((x, y))

if not pixels:
    print("No content found!")
    exit(1)

min_y = min(p[1] for p in pixels)
max_y = max(p[1] for p in pixels)
content_h = max_y - min_y + 1
print(f"Content vertical range: {min_y}-{max_y} (h={content_h})")

# For each position in the image, try matching each digit reference
# Use a sliding window approach
results = []
step = 2  # slide by 2 pixels

# Group black pixels by vertical columns to find digit positions
col_density = {}
for x, y in pixels:
    col_density[x] = col_density.get(x, 0) + 1

# Find column ranges with high density (digit regions)
in_digit = False
digit_regions = []
region_start = 0
threshold = 2

sorted_cols = sorted(col_density.keys())
prev_x = -10
for x in sorted_cols:
    if col_density[x] > threshold:
        if not in_digit:
            region_start = x
            in_digit = True
        prev_x = x
    else:
        if in_digit and x - prev_x > 3:
            if prev_x - region_start >= 8:  # at least 8px wide
                digit_regions.append((region_start, prev_x))
            in_digit = False

if in_digit and prev_x - region_start >= 8:
    digit_regions.append((region_start, prev_x))

print(f"Digit regions: {digit_regions}")

if len(digit_regions) != 4:
    print(f"Expected 4 digits, found {len(digit_regions)}. Falling back to fixed segments.")
    # Fall back to fixed segments
    segments = [(10, 38), (42, 70), (74, 102), (106, 134)]
    digit_regions = segments

results = []
for x1, x2 in digit_regions:
    # Crop the segment (add 2px padding on each side)
    seg = bw.crop((max(0, x1-2), 0, min(w, x2+2), h))

    best_match = "?"
    best_score = float('inf')

    for d, ref_list in refs.items():
        for ref in ref_list:
            diff = score_match(seg, ref)
            if diff < best_score:
                best_score = diff
                best_match = d

    results.append(best_match)
    print(f"  Region ({x1},{x2}): matched {best_match} (score={best_score})")

code = "".join(results)
print(f"\n=== Predicted code: {code} ===")
print(f"captcha_id: {captcha_id}")

# Try to login
login_r = requests.post("https://ai-knowledge-base-qtme-production.up.railway.app/api/auth/login", data={
    "phone": "17688939632",
    "password": "123456",
    "captcha_id": captcha_id,
    "captcha_code": code,
}, timeout=10)
print(f"Login result: {login_r.json()}")
