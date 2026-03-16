#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║              Koni's Archive – Daily English Content Creator          ║
║         Korean Sentence → Card News → Instagram Draft Asset          ║
╚══════════════════════════════════════════════════════════════════════╝

PREREQUISITES (install via pip):
    pip install openai pillow requests python-dotenv

API KEYS REQUIRED:
    Create a file named `.env` in the same directory as this script:

        OPENAI_API_KEY=sk-proj-...your-key-here...

    Or export the variable in your shell:
        export OPENAI_API_KEY="sk-proj-..."

    • OpenAI API Key  → https://platform.openai.com/api-keys
      Used for: GPT-4o (content generation) + DALL-E 3 (image generation)

    Cost estimate per run (approximate, as of 2025):
      • GPT-4o input/output  ~$0.005–$0.015
      • DALL-E 3 (1024×1024) ~$0.040
      Total per card: ~$0.05–$0.06

WORKFLOW:
    Step 1 → User inputs a Korean sentence
    Step 2 → GPT-4o generates translation, expression notes, image prompt
    Step 3 → DALL-E 3 generates the background image
    Step 4 → Pillow composes the branded Card News image
    Step 5 → Caption & hashtag text is generated
    Step 6 → Assets saved to Koni'sArchive_Drafts/[Date]/
              + staging_manifest.json for Make.com integration
"""

import os
import sys
import json
import textwrap
import requests
import math
from datetime import datetime
from io import BytesIO
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional: load .env file if python-dotenv is installed
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env support is optional; rely on shell environment instead

from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI

# ===========================================================================
# CONFIGURATION
# ===========================================================================

BRAND_NAME     = "Koni's Archive"
CARD_SIZE      = (1080, 1080)   # Instagram square (1:1)
OUTPUT_ROOT    = Path("Koni'sArchive_Drafts")

# Colour palette
COLOR_WHITE        = (255, 255, 255, 255)
COLOR_BLACK        = (0, 0, 0, 255)
COLOR_SHADOW       = (0, 0, 0, 160)
COLOR_OVERLAY_DARK = (0, 0, 0, 140)   # translucent dark strip
COLOR_BRAND_BG     = (30, 30, 30, 200)
COLOR_ACCENT       = (255, 215, 80, 255)   # warm gold for branding

# Font sizes  (fallback to default PIL font if system fonts unavailable)
FS_KOREAN    = 38
FS_ENGLISH   = 56
FS_NOTES     = 30
FS_BRAND     = 26

# Branding
BRANDING_HASHTAGS = (
    "#KonisArchive #LearningLog #DailyFlow #EnglishKoni #DailyEnglish #하루문장"
)
VIRAL_HASHTAGS = (
    "#studygram #englishlearning #motivation #lifelonglearning #koni_s_archive "
    "#dailyenglish #languagelearning #englishpractice"
)

# ===========================================================================
# UTILITY: Font Loader
# ===========================================================================

def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    Try to load a nice system TrueType font. Falls back gracefully to the
    PIL default (bitmap) font if nothing is found.
    """
    candidates_bold = [
        # macOS
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        # Linux (common packages)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        # Windows
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ]
    # Korean-capable fonts (needed to render the original KR sentence)
    candidates_korean = [
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "C:/Windows/Fonts/malgun.ttf",
    ]

    candidates = candidates_bold if bold else candidates_regular
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue

    # Last resort: PIL default
    print(f"  ⚠️  No TrueType font found (size={size}). Using PIL default – text may look blocky.")
    return ImageFont.load_default()


def load_korean_font(size: int) -> ImageFont.FreeTypeFont:
    """Tries Korean-aware fonts first, then falls back to load_font()."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return load_font(size)


# ===========================================================================
# STEP 2: GPT-4o Content Generation
# ===========================================================================

SYSTEM_PROMPT = """
You are a professional English language educator and content creator specializing
in natural, everyday American/British English. Your audience is Korean learners
who want real, native-sounding expressions – not textbook translations.

Always respond with a single, valid JSON object – no markdown fences, no extra text.
""".strip()

USER_PROMPT_TEMPLATE = """
Korean input sentence: "{korean}"

Please generate the following fields and return them as a JSON object:

1. "english_translation": A natural, everyday-life English translation (how a native
   speaker would actually say this, not a literal translation).

2. "key_phrase": The single most important phrase or idiom in that translation
   (3–6 words).

3. "expression_notes": A short, punchy alternative expression or common idiom that
   could replace or complement the key_phrase (e.g. "Also say: '...' ").

4. "nuance_explanation": 2–3 sentences explaining *why* this expression is the most
   natural choice, the cultural/contextual nuance, and when to use it.

5. "image_prompt": A highly detailed DALL-E 3 prompt for a cinematic, emotionally
   resonant 1:1 square image that visually captures the core mood and scene of the
   sentence. CRITICAL: the image must contain absolutely NO text, letters, or words
   of any kind. Style: warm photographic realism or soft illustrated art.

Return ONLY valid JSON. Example structure:
{{
  "english_translation": "...",
  "key_phrase": "...",
  "expression_notes": "...",
  "nuance_explanation": "...",
  "image_prompt": "..."
}}
""".strip()


def generate_content(client: OpenAI, korean_sentence: str) -> dict:
    """Call GPT-4o and return the structured content dict."""
    print("\n📡 Step 2: Calling GPT-4o for content generation...")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": USER_PROMPT_TEMPLATE.format(korean=korean_sentence)},
        ],
        temperature=0.7,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)

    required = ["english_translation", "key_phrase", "expression_notes",
                 "nuance_explanation", "image_prompt"]
    for field in required:
        if field not in data:
            raise ValueError(f"GPT-4o response is missing required field: '{field}'")

    print("  ✅  Content generated successfully.")
    return data


# ===========================================================================
# STEP 3: DALL-E 3 Image Generation
# ===========================================================================

def generate_image(client: OpenAI, image_prompt: str) -> Image.Image:
    """Call DALL-E 3 and return a PIL Image object."""
    print("\n🎨 Step 3: Calling DALL-E 3 for background image...")

    # Enforce no-text rule in the prompt
    safe_prompt = (
        image_prompt.rstrip(".")
        + ". No text, letters, words, signs, or typography anywhere in the image."
    )

    response = client.images.generate(
        model="dall-e-3",
        prompt=safe_prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    img_data  = requests.get(image_url, timeout=60).content
    image     = Image.open(BytesIO(img_data)).convert("RGBA")
    image     = image.resize(CARD_SIZE, Image.LANCZOS)

    print("  ✅  Image downloaded and resized to 1080×1080.")
    return image


# ===========================================================================
# BRANDING LOGO (drawn with Pillow – no external assets required)
# ===========================================================================

def draw_brand_logo(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 32):
    """
    Draws a minimal 'ink pen + open book' icon inline.
    The icon sits to the LEFT of the brand name text.

    Layout (relative to x, y = top-left of icon bounding box):
      • Open book:  two trapezoids meeting at the spine
      • Pen nib:    small triangle above-right

    size: overall icon height in pixels
    """
    s  = size
    cx = x + s // 2   # horizontal centre of the icon
    # --- Open book (two pages) ---
    book_top    = y + s * 10 // 32
    book_bottom = y + s * 28 // 32
    spine_x     = cx

    left_page = [
        (spine_x,          book_top),
        (spine_x - s//2,   book_top + s//8),
        (spine_x - s//2,   book_bottom),
        (spine_x,          book_bottom - s//8),
    ]
    right_page = [
        (spine_x,          book_top),
        (spine_x + s//2,   book_top + s//8),
        (spine_x + s//2,   book_bottom),
        (spine_x,          book_bottom - s//8),
    ]
    draw.polygon(left_page,  fill=COLOR_ACCENT,   outline=COLOR_WHITE)
    draw.polygon(right_page, fill=(255, 190, 40, 255), outline=COLOR_WHITE)

    # Spine line
    draw.line([(spine_x, book_top), (spine_x, book_bottom)],
              fill=COLOR_WHITE, width=2)

    # --- Pen nib (small triangle, top-right of icon) ---
    pen_tip  = (cx + s * 14 // 32, y + s * 3 // 32)
    pen_left = (cx + s * 8  // 32, y + s * 10 // 32)
    pen_right= (cx + s * 20 // 32, y + s * 10 // 32)
    draw.polygon([pen_tip, pen_left, pen_right], fill=COLOR_WHITE)

    # Pen body
    body_top_left  = (cx + s * 9  // 32, y)
    body_top_right = (cx + s * 19 // 32, y)
    draw.rectangle([body_top_left, (body_top_right[0], pen_left[1] - 1)],
                   fill=(200, 200, 220, 255))


# ===========================================================================
# STEP 4: Card Composition with Pillow
# ===========================================================================

def draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    position: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple   = COLOR_WHITE,
    shadow_offset: int = 3,
    stroke_width: int  = 2,
):
    """Draw text with a drop-shadow and optional stroke for maximum readability."""
    x, y = position
    # Shadow
    draw.text((x + shadow_offset, y + shadow_offset), text,
              font=font, fill=COLOR_SHADOW)
    # Stroke / outline
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=COLOR_BLACK)
    # Main text
    draw.text((x, y), text, font=font, fill=fill)


def wrap_text(text: str, font: ImageFont.FreeTypeFont,
              max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines, current = [], []
    for word in words:
        trial = " ".join(current + [word])
        bbox  = font.getbbox(trial)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines or [text]


def compose_card(
    base_image:   Image.Image,
    korean:       str,
    english:      str,
    notes:        str,
) -> Image.Image:
    """
    Compose the final Card News image:
      • Full-bleed background image
      • Dark gradient strips (top & bottom)
      • Korean original (top)
      • English translation (centre, large)
      • Expression notes (bottom centre)
      • Koni's Archive brand logo + name (bottom right)
    """
    W, H = CARD_SIZE
    card = base_image.copy()
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw    = ImageDraw.Draw(overlay)

    # ── Dark strips for readability ───────────────────────────────────────
    top_strip_h = 160
    bot_strip_h = 200
    draw.rectangle([(0, 0), (W, top_strip_h)],  fill=(0, 0, 0, 150))
    draw.rectangle([(0, H - bot_strip_h), (W, H)], fill=(0, 0, 0, 165))

    # Fonts
    font_kr     = load_korean_font(FS_KOREAN)
    font_en     = load_font(FS_ENGLISH, bold=True)
    font_notes  = load_font(FS_NOTES)
    font_brand  = load_font(FS_BRAND, bold=True)

    margin = 54

    # ── Korean sentence (top strip) ───────────────────────────────────────
    kr_lines = wrap_text(korean, font_kr, W - margin * 2)
    kr_y     = 28
    for line in kr_lines:
        bbox = font_kr.getbbox(line)
        tw   = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((W - tw) // 2, kr_y), line,
                               font_kr, fill=COLOR_WHITE, shadow_offset=2, stroke_width=1)
        kr_y += bbox[3] - bbox[1] + 8

    # ── English translation (centre) ──────────────────────────────────────
    en_lines = wrap_text(english, font_en, W - margin * 2)
    line_h   = font_en.getbbox("A")[3] + 14
    total_h  = len(en_lines) * line_h
    en_y     = (H - total_h) // 2 - 20

    for line in en_lines:
        bbox = font_en.getbbox(line)
        tw   = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((W - tw) // 2, en_y), line,
                               font_en, fill=COLOR_WHITE, shadow_offset=3, stroke_width=2)
        en_y += line_h

    # ── Expression notes (bottom strip, upper part) ───────────────────────
    notes_max = W - margin * 2
    note_lines = wrap_text(notes, font_notes, notes_max)
    note_line_h = font_notes.getbbox("A")[3] + 10
    note_y = H - bot_strip_h + 22

    for line in note_lines:
        bbox = font_notes.getbbox(line)
        tw   = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((W - tw) // 2, note_y), line,
                               font_notes, fill=(220, 220, 220, 255),
                               shadow_offset=2, stroke_width=1)
        note_y += note_line_h

    # ── Koni's Archive brand (bottom right) ───────────────────────────────
    icon_size   = 36
    brand_text  = BRAND_NAME
    bbrand      = font_brand.getbbox(brand_text)
    brand_tw    = bbrand[2] - bbrand[0]
    brand_th    = bbrand[3] - bbrand[1]
    gap         = 8   # space between icon and text

    total_brand_w = icon_size + gap + brand_tw
    brand_x = W - margin - total_brand_w
    brand_y = H - 52

    # Subtle pill background for brand
    pill_pad = 10
    draw.rounded_rectangle(
        [(brand_x - pill_pad, brand_y - pill_pad),
         (brand_x + total_brand_w + pill_pad,
          brand_y + max(icon_size, brand_th) + pill_pad)],
        radius=14, fill=COLOR_BRAND_BG
    )

    # Draw logo icon
    draw_brand_logo(draw, brand_x, brand_y, size=icon_size)

    # Draw brand name text (gold accent)
    text_y = brand_y + (icon_size - brand_th) // 2
    draw_text_with_shadow(
        draw, (brand_x + icon_size + gap, text_y),
        brand_text, font_brand,
        fill=COLOR_ACCENT, shadow_offset=1, stroke_width=1
    )

    # Merge overlay onto card
    card = Image.alpha_composite(card, overlay)
    return card


# ===========================================================================
# STEP 5: Caption Generation
# ===========================================================================

INTROS = [
    "Today's Fragment in Koni's Archive ✨",
    "A piece of my daily flow 🌿",
    "One sentence. One step forward. 📖",
    "Collecting moments, one phrase at a time 🗂️",
]

def generate_caption(
    korean:       str,
    english:      str,
    key_phrase:   str,
    notes:        str,
    nuance:       str,
    run_index:    int = 0,
) -> str:
    """Build the full Instagram caption text."""
    intro = INTROS[run_index % len(INTROS)]

    caption = f"""{intro}

━━━━━━━━━━━━━━━━━━━━
🇰🇷 (Original KR):
{korean}

🇺🇸 (Natural EN):
{english}

💡 (Expression Key):
"{key_phrase}"
{notes}

🔍 (Why):
{nuance}
━━━━━━━━━━━━━━━━━━━━

{BRANDING_HASHTAGS}
{VIRAL_HASHTAGS}
"""
    return caption.strip()


# ===========================================================================
# STEP 6: Save Assets + Staging Manifest
# ===========================================================================

def save_assets(
    date_str:  str,
    card:      Image.Image,
    caption:   str,
) -> tuple[Path, Path, Path]:
    """
    Save card image + caption + staging_manifest.json to the output folder.
    Returns (folder_path, image_path, manifest_path).
    """
    folder = OUTPUT_ROOT / date_str
    folder.mkdir(parents=True, exist_ok=True)

    # Convert RGBA → RGB for JPEG / keep PNG for transparency
    img_path = folder / "card_news.png"
    card.save(img_path, "PNG")

    caption_path = folder / "caption.txt"
    caption_path.write_text(caption, encoding="utf-8")

    manifest = {
        "konis_archive_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "status": "Needs Verification",
        "assets": {
            "image":   str(img_path.resolve()),
            "caption": str(caption_path.resolve()),
        },
        "instagram": {
            "aspect_ratio": "1:1",
            "resolution":   "1080x1080",
            "format":       "PNG",
        },
        "make_com_trigger": {
            "watch_folder": str(folder.resolve()),
            "trigger_file": "staging_manifest.json",
            "auto_post_on_status": "Approved",
        },
    }

    manifest_path = folder / "staging_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    return folder, img_path, manifest_path


# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

def main():
    print("=" * 62)
    print("         ✨  Koni's Archive – Daily Content Creator  ✨")
    print("=" * 62)

    # ── API Key check ─────────────────────────────────────────────────────
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n❌  OPENAI_API_KEY is not set.")
        print("    Create a .env file with:  OPENAI_API_KEY=sk-proj-...")
        print("    Or run:  export OPENAI_API_KEY='sk-proj-...'")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    # ── Step 1: Korean input ──────────────────────────────────────────────
    print("\n📝 Step 1: Enter your Korean sentence")
    print("   (Example: 오늘 하루도 최선을 다했다.)")
    korean = input("   Korean → ").strip()
    if not korean:
        print("   ❌ No input provided. Exiting.")
        sys.exit(1)

    # ── Step 2: LLM content generation ───────────────────────────────────
    content = generate_content(client, korean)

    english = content["english_translation"]
    key_phrase  = content["key_phrase"]
    notes   = content["expression_notes"]
    nuance  = content["nuance_explanation"]
    img_prompt  = content["image_prompt"]

    print("\n📋 Generated Content Preview:")
    print(f"   EN  : {english}")
    print(f"   Key : {key_phrase}")
    print(f"   Note: {notes}")
    print(f"   Why : {nuance[:80]}…")

    # ── Step 3: DALL-E 3 image ────────────────────────────────────────────
    base_image = generate_image(client, img_prompt)

    # ── Step 4: Card composition ──────────────────────────────────────────
    print("\n🖼️  Step 4: Composing Card News image...")
    card = compose_card(base_image, korean, english, notes)
    print("  ✅  Card composed.")

    # ── Step 5: Caption ───────────────────────────────────────────────────
    print("\n✍️  Step 5: Generating Instagram caption...")
    caption = generate_caption(korean, english, key_phrase, notes, nuance)
    print("  ✅  Caption ready.")

    # ── Step 6: Save assets ───────────────────────────────────────────────
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    print(f"\n💾 Step 6: Saving assets to Koni'sArchive_Drafts/{date_str}/")
    folder, img_path, manifest_path = save_assets(date_str, card, caption)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  🎉  Done! Your draft is ready for verification.")
    print("=" * 62)
    print(f"  📁  Folder   : {folder}")
    print(f"  🖼️   Card     : {img_path.name}")
    print(f"  📄  Caption  : caption.txt")
    print(f"  📦  Manifest : {manifest_path.name}")
    print("\n  Next steps:")
    print("  1. Open the folder and verify the card image.")
    print("  2. Edit caption.txt if needed.")
    print(f"  3. Change manifest status from 'Needs Verification' → 'Approved'.")
    print("  4. Make.com will detect the change and post to Instagram.")
    print("=" * 62)

    # Open the card image for quick preview (best-effort)
    try:
        card.show()
    except Exception:
        pass


# ===========================================================================
# FUTURE-PROOFING NOTE: Reels / Shorts Video Workflow
# ===========================================================================
"""
VIDEO WORKFLOW (NOT implemented here – outline only):

To create a 9:16 Reels/Shorts card:

1. VIDEO BACKGROUND — Two options:
   a) Runway Gen-2 API (runway-ml SDK):
        client = runwayml.RunwayML()
        task = client.image_to_video.create(
            model="gen4_turbo",
            prompt_image=dalle_image_url,
            prompt_text="Slow, cinematic camera drift. Warm ambient light.",
            ratio="720:1280", duration=5,
        )
        # Poll until complete, download MP4

   b) Simpler: loop + Ken Burns zoom on the DALL-E image using MoviePy:
        clip = ImageClip(np.array(base_image)).with_duration(5)
        zoomed = clip.resized(lambda t: 1 + 0.04 * t)   # slow zoom

2. TEXT ANIMATION (MoviePy + TextClip):
        txt = TextClip(english, fontsize=70, color='white', font='Arial-Bold')
              .with_position('center')
              .with_duration(5)
              .fadein(0.5).fadeout(0.5)
        video = CompositeVideoClip([zoomed, txt], size=(720, 1280))
        video.write_videofile("reels_draft.mp4", fps=24)

3. BRANDING: Overlay Koni's Archive logo PNG (with transparency) in corner.

4. Save MP4 alongside the PNG card in the same staging folder.
"""

if __name__ == "__main__":
    main()
