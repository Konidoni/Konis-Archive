#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║         Koni's Archive – 무료 버전 (Groq + Pollinations)             ║
╚══════════════════════════════════════════════════════════════════════╝

필요한 라이브러리 설치:
    pip3 install groq pillow requests python-dotenv

API 키 준비:
    Groq API 키 (무료) →  https://console.groq.com/keys
    .env 파일에 저장:
        GROQ_API_KEY=gsk_...your-key-here...

이미지 생성:
    Pollinations.ai 사용 → 완전 무료, API 키 불필요!
"""

import os
import sys
import json
import re
import requests
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from PIL import Image, ImageDraw, ImageFont
from groq import Groq

# ===========================================================================
# 설정
# ===========================================================================

BRAND_NAME         = "Koni's Archive"
CARD_SIZE          = (1080, 1080)
OUTPUT_ROOT        = Path("Koni'sArchive_Drafts")

COLOR_WHITE        = (255, 255, 255, 255)
COLOR_BLACK        = (0, 0, 0, 255)
COLOR_SHADOW       = (0, 0, 0, 160)
COLOR_BRAND_BG     = (30, 30, 30, 200)
COLOR_ACCENT       = (255, 215, 80, 255)

FS_KOREAN  = 38
FS_ENGLISH = 56
FS_NOTES   = 30
FS_BRAND   = 26

BRANDING_HASHTAGS = "#KonisArchive #LearningLog #DailyFlow #EnglishKoni #DailyEnglish #하루문장"
VIRAL_HASHTAGS    = "#studygram #englishlearning #motivation #lifelonglearning #koni_s_archive #dailyenglish #languagelearning #englishpractice"

# ===========================================================================
# 폰트 로더
# ===========================================================================

def load_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJKkr-Regular.otf",
        "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()

# ===========================================================================
# STEP 2: Groq 콘텐츠 생성
# ===========================================================================

PROMPT_TEMPLATE = """
다음 한국어 문장을 분석하고 아래 형식의 JSON만 반환해줘. 마크다운, 코드블록, 설명 없이 순수 JSON만.

한국어 문장: "{korean}"

반환할 JSON 형식:
{{
  "english_translation": "자연스러운 원어민 영어 번역",
  "key_phrase": "핵심 표현 3~6단어",
  "expression_notes": "Also say: '대체 표현이나 관용구'",
  "nuance_explanation": "이 표현이 왜 자연스러운지 2~3문장 영어 설명",
  "image_prompt": "DALL-E 스타일의 상세한 이미지 생성 프롬프트. 텍스트/글자/문자가 절대 포함되지 않는 시네마틱 장면 묘사"
}}
""".strip()


def generate_content(korean: str) -> dict:
    print("\n📡 Step 2: Groq으로 콘텐츠 생성 중...")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("❌ GROQ_API_KEY가 없습니다. .env 파일을 확인해주세요.")
        sys.exit(1)

    client   = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a professional English educator. Always respond with pure JSON only, no markdown, no explanation."},
            {"role": "user",   "content": PROMPT_TEMPLATE.format(korean=korean)},
        ],
        temperature=0.7,
    )
    raw = response.choices[0].message.content.strip()

    # 마크다운 코드블록 제거 (```json ... ``` 형태 대응)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data = json.loads(raw)

    required = ["english_translation", "key_phrase", "expression_notes",
                 "nuance_explanation", "image_prompt"]
    for field in required:
        if field not in data:
            raise ValueError(f"Groq 응답에 필드 없음: '{field}'")

    print("  ✅ 콘텐츠 생성 완료!")
    return data

# ===========================================================================
# STEP 3: Pollinations.ai 이미지 생성 (완전 무료)
# ===========================================================================

def generate_image(image_prompt: str) -> Image.Image:
    print("\n🎨 Step 3: Pollinations.ai로 이미지 생성 중... (무료)")

    # 프롬프트가 너무 길면 서버 오류 날 수 있으므로 200자로 제한
    short_prompt = image_prompt[:200]
    safe_prompt  = (
        short_prompt.rstrip(".")
        + ". No text, no letters, no words. Cinematic, photorealistic."
    )

    encoded = quote(safe_prompt)

    # 시도할 URL 목록 (파라미터 조합을 달리해서 시도)
    seed = abs(hash(safe_prompt)) % 99999
    urls = [
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&model=flux&seed={seed}",
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed+1}",
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024",
    ]

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            url = urls[attempt - 1]
            print(f"  ⏳ 이미지 생성 중... (시도 {attempt}/{max_retries}, 10~40초 소요)")
            response = requests.get(url, timeout=120)
            response.raise_for_status()

            image = Image.open(BytesIO(response.content)).convert("RGBA")
            image = image.resize(CARD_SIZE, Image.LANCZOS)
            print("  ✅ 이미지 생성 완료!")
            return image

        except Exception as e:
            print(f"  ⚠️  시도 {attempt} 실패: {e}")
            if attempt < max_retries:
                import time
                print(f"  🔄 5초 후 재시도...")
                time.sleep(5)
            else:
                # 모든 시도 실패 시 단색 배경으로 대체
                print("  ⚠️  이미지 생성 실패. 기본 배경으로 대체합니다.")
                fallback = Image.new("RGBA", CARD_SIZE, (30, 30, 50, 255))
                return fallback

# ===========================================================================
# 브랜딩 로고 (Pillow로 직접 그리기)
# ===========================================================================

def draw_brand_logo(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 32):
    s  = size
    cx = x + s // 2

    book_top    = y + s * 10 // 32
    book_bottom = y + s * 28 // 32
    spine_x     = cx

    left_page  = [(spine_x, book_top), (spine_x - s//2, book_top + s//8),
                  (spine_x - s//2, book_bottom), (spine_x, book_bottom - s//8)]
    right_page = [(spine_x, book_top), (spine_x + s//2, book_top + s//8),
                  (spine_x + s//2, book_bottom), (spine_x, book_bottom - s//8)]

    draw.polygon(left_page,  fill=COLOR_ACCENT, outline=COLOR_WHITE)
    draw.polygon(right_page, fill=(255, 190, 40, 255), outline=COLOR_WHITE)
    draw.line([(spine_x, book_top), (spine_x, book_bottom)], fill=COLOR_WHITE, width=2)

    pen_tip   = (cx + s * 14 // 32, y + s * 3 // 32)
    pen_left  = (cx + s * 8  // 32, y + s * 10 // 32)
    pen_right = (cx + s * 20 // 32, y + s * 10 // 32)
    draw.polygon([pen_tip, pen_left, pen_right], fill=COLOR_WHITE)
    draw.rectangle([(cx + s * 9 // 32, y), (cx + s * 19 // 32, pen_left[1] - 1)],
                   fill=(200, 200, 220, 255))

# ===========================================================================
# STEP 4: 카드 합성 (Pillow)
# ===========================================================================

def draw_text_with_shadow(draw, position, text, font, fill=COLOR_WHITE,
                           shadow_offset=3, stroke_width=2):
    x, y = position
    draw.text((x + shadow_offset, y + shadow_offset), text, font=font, fill=COLOR_SHADOW)
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=COLOR_BLACK)
    draw.text((x, y), text, font=font, fill=fill)


def wrap_text(text: str, font, max_width: int) -> list:
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


def compose_card(base_image, korean, english, notes):
    W, H   = CARD_SIZE
    card   = base_image.copy()
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw   = ImageDraw.Draw(overlay)

    # 상단/하단 어두운 스트립
    draw.rectangle([(0, 0), (W, 160)],        fill=(0, 0, 0, 150))
    draw.rectangle([(0, H - 200), (W, H)],    fill=(0, 0, 0, 165))

    font_kr    = load_font(FS_KOREAN)
    font_en    = load_font(FS_ENGLISH, bold=True)
    font_notes = load_font(FS_NOTES)
    font_brand = load_font(FS_BRAND, bold=True)

    margin = 54

    # 한국어 (상단)
    kr_lines = wrap_text(korean, font_kr, W - margin * 2)
    kr_y = 28
    for line in kr_lines:
        bbox = font_kr.getbbox(line)
        tw   = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((W - tw) // 2, kr_y), line,
                               font_kr, fill=COLOR_WHITE, shadow_offset=2, stroke_width=1)
        kr_y += bbox[3] - bbox[1] + 8

    # 영어 번역 (가운데, 크게)
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

    # 표현 노트 (하단)
    note_lines  = wrap_text(notes, font_notes, W - margin * 2)
    note_line_h = font_notes.getbbox("A")[3] + 10
    note_y      = H - 200 + 22

    for line in note_lines:
        bbox = font_notes.getbbox(line)
        tw   = bbox[2] - bbox[0]
        draw_text_with_shadow(draw, ((W - tw) // 2, note_y), line,
                               font_notes, fill=(220, 220, 220, 255),
                               shadow_offset=2, stroke_width=1)
        note_y += note_line_h

    # 브랜드 로고 (우측 하단)
    icon_size      = 36
    bbrand         = font_brand.getbbox(BRAND_NAME)
    brand_tw       = bbrand[2] - bbrand[0]
    brand_th       = bbrand[3] - bbrand[1]
    gap            = 8
    total_brand_w  = icon_size + gap + brand_tw
    brand_x        = W - margin - total_brand_w
    brand_y        = H - 52
    pill_pad       = 10

    draw.rounded_rectangle(
        [(brand_x - pill_pad, brand_y - pill_pad),
         (brand_x + total_brand_w + pill_pad, brand_y + max(icon_size, brand_th) + pill_pad)],
        radius=14, fill=COLOR_BRAND_BG
    )
    draw_brand_logo(draw, brand_x, brand_y, size=icon_size)
    text_y = brand_y + (icon_size - brand_th) // 2
    draw_text_with_shadow(draw, (brand_x + icon_size + gap, text_y),
                           BRAND_NAME, font_brand, fill=COLOR_ACCENT,
                           shadow_offset=1, stroke_width=1)

    return Image.alpha_composite(card, overlay)

# ===========================================================================
# STEP 5: 캡션 생성
# ===========================================================================

INTROS = [
    "Today's Fragment in Koni's Archive ✨",
    "A piece of my daily flow 🌿",
    "One sentence. One step forward. 📖",
    "Collecting moments, one phrase at a time 🗂️",
]

def generate_caption(korean, english, key_phrase, notes, nuance, run_index=0):
    intro = INTROS[run_index % len(INTROS)]
    return f"""{intro}

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
{VIRAL_HASHTAGS}""".strip()

# ===========================================================================
# STEP 6: 파일 저장 + 매니페스트
# ===========================================================================

def save_assets(date_str, card, caption):
    folder = OUTPUT_ROOT / date_str
    folder.mkdir(parents=True, exist_ok=True)

    img_path = folder / "card_news.png"
    card.save(img_path, "PNG")

    caption_path = folder / "caption.txt"
    caption_path.write_text(caption, encoding="utf-8")

    manifest = {
        "konis_archive_version": "1.0-free",
        "generated_at": datetime.now().isoformat(),
        "status": "Needs Verification",
        "assets": {
            "image":   str(img_path.resolve()),
            "caption": str(caption_path.resolve()),
        },
        "make_com_trigger": {
            "auto_post_on_status": "Approved"
        },
    }

    manifest_path = folder / "staging_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                              encoding="utf-8")

    return folder, img_path, manifest_path

# ===========================================================================
# 메인
# ===========================================================================

def main():
    print("=" * 58)
    print("      ✨  Koni's Archive – 무료 버전 (Groq)   ✨")
    print("=" * 58)

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("\n❌  GROQ_API_KEY 가 없습니다.")
        print("    .env 파일에 추가해주세요:")
        print("    GROQ_API_KEY=gsk_...")
        sys.exit(1)

    # Step 1: 한국어 입력
    print("\n📝 한국어 문장을 입력해주세요")
    print("   (예: 오늘 하루도 최선을 다했다.)")
    korean = input("   입력 → ").strip()
    if not korean:
        print("   입력이 없습니다. 종료합니다.")
        sys.exit(1)

    # Step 2: Groq 콘텐츠 생성
    content    = generate_content(korean)
    english    = content["english_translation"]
    key_phrase = content["key_phrase"]
    notes      = content["expression_notes"]
    nuance     = content["nuance_explanation"]
    img_prompt = content["image_prompt"]

    print(f"\n📋 생성된 콘텐츠 미리보기:")
    print(f"   EN  : {english}")
    print(f"   Key : {key_phrase}")
    print(f"   Note: {notes}")

    # Step 3: Pollinations 이미지 생성
    base_image = generate_image(img_prompt)

    # Step 4: 카드 합성
    print("\n🖼️  Step 4: 카드 이미지 합성 중...")
    card = compose_card(base_image, korean, english, notes)
    print("  ✅ 카드 합성 완료!")

    # Step 5: 캡션 생성
    print("\n✍️  Step 5: 인스타그램 캡션 생성 중...")
    caption = generate_caption(korean, english, key_phrase, notes, nuance)
    print("  ✅ 캡션 완료!")

    # Step 6: 저장
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    print(f"\n💾 Step 6: 파일 저장 중...")
    folder, img_path, manifest_path = save_assets(date_str, card, caption)

    print("\n" + "=" * 58)
    print("  🎉  완료! 검토 후 인스타에 올리면 돼요.")
    print("=" * 58)
    print(f"  📁  폴더     : {folder}")
    print(f"  🖼️   카드     : {img_path.name}")
    print(f"  📄  캡션     : caption.txt")
    print(f"  📦  매니페스트: {manifest_path.name}")
    print("=" * 58)

    try:
        card.show()
    except Exception:
        pass


if __name__ == "__main__":
    main()