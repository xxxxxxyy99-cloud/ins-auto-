"""Multi-provider image generation + AI caption generation."""

import io
import random
import hashlib
import time
import requests
from pathlib import Path
from urllib.parse import quote
from typing import Optional

from .config import OPENROUTER_API_KEY, GEMINI_API_KEY, BASE_DIR

IMAGE_DIR = BASE_DIR / "generated_images"
IMAGE_DIR.mkdir(exist_ok=True)

# ── API endpoints ──────────────────────────────────────────

CAPTION_URL = "https://openrouter.ai/api/v1/chat/completions"
OR_IMAGE_URL = "https://openrouter.ai/api/v1/chat/completions"
# Default image model for OpenRouter (Gemini Flash Image — cheap, good quality)
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"

CAPTION_HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}


# ═══════════════════════════════════════════════════════════
#  CONTENT TOPICS (Instagram niche themes)
# ═══════════════════════════════════════════════════════════

TOPICS: dict[str, str] = {
    "travel":      "Travel & Adventure — destinations, landscapes, travel tips",
    "fashion":     "Fashion & Style — outfits, accessories, trends",
    "fitness":     "Fitness & Health — workouts, nutrition, wellness",
    "pets":        "Pets & Animals — cute animals, pet care, pet products",
    "quotes":      "Quotes & Motivation — inspirational quotes, life wisdom",
    "food":        "Food & Cooking — recipes, food photography, kitchen tips",
    "lifestyle":   "Lifestyle & Home — decor, routines, daily life",
    "tech":        "Tech & Gadgets — gadgets, reviews, digital life",
    "business":    "Business & Hustle — entrepreneurship, productivity, marketing",
    "art":         "Art & Creative — artwork, design, DIY projects",
}

TOPIC_KEYS = list(TOPICS.keys())


# ═══════════════════════════════════════════════════════════
#  PRODUCT / NICHE SYSTEM
# ═══════════════════════════════════════════════════════════

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "kitchen": [
        "lemon press", "ice maker", "juicer", "kitchen grater", "ice cube mold",
        "non-stick pan", "cast iron pot", "chef knife", "cutting board", "blender",
        "air fryer", "coffee maker", "toaster", "measuring cup set", "silicone spatula",
        "stainless steel whisk", "garlic press", "salad spinner", "mandoline slicer",
    ],
    "home": [
        "aroma diffuser", "LED desk lamp", "cordless vacuum", "silk pillowcase",
        "bamboo organizer", "smart speaker", "weighted blanket", "desk plant pot",
        "scented candle set", "wall-mounted shelf", "digital alarm clock",
    ],
    "fitness": [
        "resistance band set", "yoga mat", "stainless water bottle", "foam roller",
        "jump rope", "adjustable dumbbell", "gym gloves", "ankle weights",
    ],
    "beauty": [
        "jade roller", "facial steamer", "hair straightener", "makeup brush set",
        "electric toothbrush", "silk hair scrunchie", "nail art kit",
    ],
}

FOOD_MAP: dict[str, str] = {
    "lemon press": "juicy lemon halves and fresh mint",
    "ice maker": "sparkling water glass with ice cubes and lemon slice",
    "juicer": "fresh oranges and carrots with pulp",
    "kitchen grater": "zested lemon and grated parmesan cheese",
    "ice cube mold": "colorful ice cubes with berries and mint",
    "non-stick pan": "golden pancakes with fresh blueberries",
    "cast iron pot": "rustic bread with rosemary and olive oil",
    "chef knife": "rainbow of fresh vegetables on a cutting board",
    "cutting board": "fresh herbs and colorful peppers",
    "blender": "tropical smoothie with mango and berries",
    "air fryer": "crispy golden fries with parsley",
    "coffee maker": "steaming latte with latte art",
    "toaster": "golden artisan bread with avocado",
}

# ── Scene templates (for Pollinations) ───────────────────

SCENES_PRODUCT = [
    "Bright flat lay of a {product} on pale marble, fresh ingredients beside it, soft natural light, top-down view, 4K food photography",
    "Aesthetic kitchen counter with a {product}, morning sunlight streaming in, warm tones, shallow depth of field, lifestyle photo",
    "Close-up of a {product} with condensation droplets, cold refreshing vibe, crisp details, macro photography, 4K",
    "Hands using a {product}, action shot, golden hour lighting, candid kitchen moment, authentic lifestyle",
    "Minimalist white kitchen corner featuring a {product}, fresh ingredients scattered nearby, clean composition, hygge aesthetic",
    "High-end product shot of a {product} on textured stone counter, dramatic side lighting, culinary elegance, 4K",
    "Rustic wooden table with {product}, soft window light, warm cozy atmosphere, editorial food styling",
    "Modern kitchen scene with a {product}, bright airy room, photorealistic product photography, magazine quality",
    "{product} on a dark moody background, spotlight effect, premium product shot, cinematic lighting, 4K",
    "Summer vibe flat lay with {product}, colorful fruits and ice, vibrant colors, tropical feel, ultra-detailed",
]

SCENES_BEAUTY = [
    "Luxury spa setting with {product} on white marble, eucalyptus sprig, soft diffused light, zen aesthetic, 4K",
    "{product} on a vanity table, morning light through sheer curtains, elegant feminine aesthetic, soft focus, 4K",
    "Close-up of {product} with water droplets, fresh and clean vibe, bright white background, product photography",
]

SCENES_HOME = [
    "Scandinavian interior with {product} styled on a wooden shelf, morning light, cozy minimal aesthetic, 4K",
    "{product} centered on a clean desk setup, natural light from window, modern workspace vibe, 4K",
    "Cozy bedroom corner with {product}, warm fairy lights, hygge atmosphere, soft focus, lifestyle photo",
]

SCENES_FITNESS = [
    "{product} on a gym floor, dramatic lighting, sweat and determination vibe, fitness photography, 4K",
    "Outdoor morning workout scene with {product}, golden sunrise, park setting, active lifestyle, 4K",
    "Minimal home gym with {product}, clean white walls, natural light, modern fitness aesthetic",
]


def _pick_scenes(niche: str) -> list[str]:
    """Pick scene templates based on niche keywords."""
    n = niche.lower()
    if any(k in n for k in ["beauty", "beauté", "美容", "护肤", "化妆"]):
        return SCENES_BEAUTY
    if any(k in n for k in ["home", "家居", "生活", "interior", "decor"]):
        return SCENES_HOME
    if any(k in n for k in ["fitness", "gym", "运动", "健身", "workout"]):
        return SCENES_FITNESS
    return SCENES_PRODUCT


def _get_food(product: str) -> str:
    """Get food pairing for a product, with fuzzy matching."""
    if product in FOOD_MAP:
        return FOOD_MAP[product]
    # fuzzy fallback
    for key, val in FOOD_MAP.items():
        if key in product or product in key:
            return val
    return "fresh seasonal ingredients"


# ═══════════════════════════════════════════════════════════
#  PROMPT ENGINEERING
# ═══════════════════════════════════════════════════════════

def generate_prompt(
    product: Optional[str] = None,
    niche: str = "",
    custom_style: str = "",
    category: str = "kitchen",
) -> tuple[str, str]:
    """
    Generate an image prompt + product name.
    If product is None, picks one from the niche category.
    """
    if not product:
        cats = DEFAULT_CATEGORIES.get(category, DEFAULT_CATEGORIES["kitchen"])
        product = random.choice(cats)

    food = _get_food(product)
    scenes = _pick_scenes(niche or category)
    template = random.choice(scenes)

    # Replace placeholders
    prompt = template.format(product=product)
    if "{food}" in prompt:
        prompt = prompt.format(food=food)

    # Append niche/style modifiers
    extras = []
    if niche:
        extras.append(f"{niche} aesthetic, {niche} lifestyle")
    if custom_style:
        extras.append(custom_style)
    if extras:
        prompt = f"{prompt}, {', '.join(extras)}"

    return prompt, product


def build_caption(text: str, hashtags: Optional[list[str]] = None,
                  limit: Optional[int] = None) -> str:
    """Append a cleaned, deduplicated hashtag block to a caption.

    limit: max number of tags to append. None keeps every tag (hard-capped
    at Instagram's 30). Tags are normalized to start with '#'.
    """
    if not hashtags:
        return text
    seen = set()
    picked = []
    for raw in hashtags:
        t = str(raw).strip().strip(",").strip(".")
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        if len(t) < 2 or t.lower() in seen:
            continue
        seen.add(t.lower())
        picked.append(t)
    cap = 30 if limit is None else max(1, min(int(limit), 30))
    picked = picked[:cap]
    if not picked:
        return text
    return f"{text}\n.\n.\n{' '.join(picked)}"


# ═══════════════════════════════════════════════════════════
#  IMAGE GENERATION — Multiple Providers
# ═══════════════════════════════════════════════════════════

def _save_image(data: bytes, prompt: str, fmt: str = "jpg") -> str:
    h = hashlib.md5(prompt.encode()).hexdigest()[:12]
    path = IMAGE_DIR / f"{h}_{int(time.time())}.{fmt}"
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def _download_image(url: str, timeout: int = 60) -> bytes | None:
    """Download image from URL with retries."""
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.content
            print(f"  Download attempt {attempt+1}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  Download attempt {attempt+1}: {e}")
        if attempt < 2:
            time.sleep(2 ** attempt)
    return None


# ── Provider 1: Pollinations.ai (free, no API key) ───────

def _gen_pollinations(
    prompt: str,
    width: int = 1080,
    height: int = 1350,
    model: str = "",
    seed: Optional[int] = None,
) -> str | None:
    """Generate image via Pollinations.ai (free). Tries multiple endpoints."""
    encoded = quote(prompt, safe="")

    # Strategy 1: New JSON API (OpenAI-compatible)
    print(f"  [Pollinations] Trying JSON API...")
    try:
        import random as _rnd
        payload = {
            "model": model or "flux",
            "prompt": prompt,
            "n": 1,
            "size": f"{width}x{height}",
        }
        if seed is not None:
            payload["seed"] = seed
        resp = requests.post(
            "https://gen.pollinations.ai/v1/images/generations",
            headers={
                "Authorization": "Bearer pollinations",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Try b64_json first, then url
            img_list = data.get("data", [])
            if img_list:
                img = img_list[0]
                if "b64_json" in img:
                    import base64
                    return _save_image(base64.b64decode(img["b64_json"]), prompt, "png")
                if "url" in img:
                    img_bytes = _download_image(img["url"])
                    if img_bytes:
                        return _save_image(img_bytes, prompt)
            print(f"  JSON API returned unexpected format")
    except Exception as e:
        print(f"  JSON API failed: {e}")

    # Strategy 2: Old URL format with explicit model
    print(f"  [Pollinations] Trying URL API (flux)...")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true&model=flux"
    if seed is not None:
        url += f"&seed={seed}"
    data = _download_image(url, timeout=60)
    if data:
        return _save_image(data, prompt)

    # Strategy 3: Try without model parameter (let Pollinations choose)
    print(f"  [Pollinations] Trying URL API (default model)...")
    url2 = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true"
    data = _download_image(url2, timeout=60)
    if data:
        return _save_image(data, prompt)

    # Strategy 4: Try with enhance=true for better results
    print(f"  [Pollinations] Trying with enhance...")
    url3 = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&enhance=true"
    data = _download_image(url3, timeout=60)
    if data:
        return _save_image(data, prompt)

    return None


# ── Provider 2: Google Gemini (free — 500 images/day) ──

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/"


def _gen_gemini(
    prompt: str,
    width: int = 1080,
    height: int = 1350,
    model: str = "",
) -> str | None:
    """Generate image via Google Gemini (free tier: 500/day, no credit card)."""
    if not GEMINI_API_KEY:
        print("  [Gemini] No API key configured, skipping")
        return None

    model = model or GEMINI_IMAGE_MODEL
    url = f"{GEMINI_URL}{model}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
        },
    }

    print(f"  [Gemini] Generating with {model}...")
    try:
        resp = requests.post(url, json=payload, timeout=90)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            for c in candidates:
                parts = c.get("content", {}).get("parts", [])
                for p in parts:
                    inline = p.get("inlineData", {})
                    if inline.get("mimeType", "").startswith("image/"):
                        import base64
                        img_bytes = base64.b64decode(inline["data"])
                        return _save_image(img_bytes, prompt, "png")
            # Also try text content for URLs (fallback)
            for c in candidates:
                parts = c.get("content", {}).get("parts", [])
                for p in parts:
                    text = p.get("text", "")
                    if text and "http" in text:
                        print(f"  Gemini returned text (no inline image)")
        elif resp.status_code == 403:
            print(f"  [Gemini] 403 Forbidden — API key may be invalid or region-blocked")
        else:
            print(f"  [Gemini] API error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  [Gemini] API failed: {e}")

    return None


# ── Provider 3: OpenRouter image models (Chat Completions API) ──

def _gen_openrouter(
    prompt: str,
    width: int = 1080,
    height: int = 1350,
    model: str = "",
    quality: str = "standard",
) -> str | None:
    """
    Generate image via OpenRouter Chat Completions API with modalities.
    Supported models: google/gemini-2.5-flash-image, black-forest-labs/flux.2-klein-4b, etc.
    """
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("your-"):
        print("  [OpenRouter] No API key configured, skipping")
        return None

    model = model or DEFAULT_IMAGE_MODEL

    # Add size hint to prompt for better results
    size_hint = ""
    if "gemini" in model or "imagen" in model:
        size_hint = f" Image should be {width}x{height} portrait orientation."

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt + size_hint}],
        "modalities": ["image", "text"],
    }

    print(f"  [OpenRouter] Generating with {model}...")
    try:
        resp = requests.post(
            OR_IMAGE_URL,
            headers=CAPTION_HEADERS,
            json=payload,
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            message = data.get("choices", [{}])[0].get("message", {})

            # Extract images from response
            images = message.get("images", [])
            if images:
                for i, img in enumerate(images):
                    img_url = img.get("image_url", {}).get("url", "")
                    if img_url:
                        # Usually base64 data URL: data:image/png;base64,...
                        if img_url.startswith("data:"):
                            import base64
                            # Strip MIME header
                            b64_data = img_url.split(",", 1)[-1]
                            img_bytes = base64.b64decode(b64_data)
                            return _save_image(img_bytes, prompt, "png")
                        elif img_url.startswith("http"):
                            img_bytes = _download_image(img_url)
                            if img_bytes:
                                return _save_image(img_bytes, prompt)
                        else:
                            print(f"  Unknown image URL format: {img_url[:60]}...")

            # Some models return text with image URLs
            content = message.get("content", "")
            if content and "http" in content:
                print(f"  Checking content for image URLs...")
                import re
                urls = re.findall(r'https?://[^\s<>"]+\.(?:png|jpg|jpeg|webp)', content)
                for u in urls:
                    img_bytes = _download_image(u)
                    if img_bytes:
                        return _save_image(img_bytes, prompt)

            print(f"  No images in response. Content: {str(content)[:100]}")
        elif resp.status_code == 402:
            print(f"  [OpenRouter] 402 Payment Required — check your API credits")
        else:
            print(f"  OpenRouter image API error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  OpenRouter image API failed: {e}")

    return None


# ── Main unified API ─────────────────────────────────────

# Aspect ratio → (width, height)
ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "3:2": (1620, 1080),
    "2:3": (1080, 1620),
}


def generate_image(
    prompt: str,
    provider: str = "pollinations",
    model: str = "",
    aspect_ratio: str = "4:5",
    quality: str = "standard",
    seed: Optional[int] = None,
    return_pil: bool = False,
) -> Optional[str | "PIL.Image.Image"]:
    """
    Generate an image from a prompt.

    Args:
        prompt: Image description
        provider: 'gemini' | 'pollinations' | 'openrouter'
        model: Specific model name (provider-dependent)
        aspect_ratio: '1:1' | '4:5' | '9:16' | '16:9' | '3:2' | '2:3'
        quality: 'standard' | 'hd' (DALL-E only)
        seed: Random seed for reproducibility
        return_pil: If True, also return a PIL Image for UI preview

    Returns:
        File path string, or (path, PIL.Image) tuple if return_pil
    """
    w, h = ASPECT_RATIOS.get(aspect_ratio, (1080, 1350))

    path = None

    if provider == "gemini":
        # Gemini (free — 500/day) → Pollinations → Gemini alt model
        path = _gen_gemini(prompt, width=w, height=h, model=model)
        if not path:
            print("  Gemini failed, trying Pollinations...")
            path = _gen_pollinations(prompt, width=w, height=h, seed=seed)
        if not path:
            print("  Trying Gemini alternate model...")
            path = _gen_gemini(prompt, width=w, height=h, model="gemini-2.0-flash-exp-image-generation")
    elif provider == "openrouter":
        or_model = model or DEFAULT_IMAGE_MODEL
        path = _gen_openrouter(prompt, width=w, height=h, model=or_model, quality=quality)
        if not path:
            print("  OpenRouter failed, trying free Gemini...")
            path = _gen_gemini(prompt, width=w, height=h)
        if not path:
            print("  Trying Pollinations...")
            path = _gen_pollinations(prompt, width=w, height=h, seed=seed)
    else:
        # Pollinations (free) → Gemini → Pollinations alt
        path = _gen_pollinations(prompt, width=w, height=h, model=model, seed=seed)
        if not path:
            print("  Pollinations failed, trying Gemini...")
            path = _gen_gemini(prompt, width=w, height=h)

    if not path:
        return None

    if return_pil:
        try:
            from PIL import Image
            img = Image.open(path)
            return path, img
        except ImportError:
            return path

    return path


def generate_batch(
    prompt: str,
    count: int = 3,
    provider: str = "pollinations",
    model: str = "",
    aspect_ratio: str = "4:5",
) -> list[str]:
    """
    Generate multiple image variants from the same prompt.
    Uses different seeds for variety.
    """
    results = []
    for i in range(count):
        seed = random.randint(1, 2_000_000_000)
        print(f"  Batch {i+1}/{count} (seed={seed})...")
        path = generate_image(
            prompt=prompt,
            provider=provider,
            model=model,
            aspect_ratio=aspect_ratio,
            seed=seed if provider == "pollinations" else None,
        )
        if path:
            results.append(str(path))
        else:
            print(f"  Batch {i+1}/{count} failed")
        if i < count - 1:
            time.sleep(1)  # Rate limit cushion
    return results


# ═══════════════════════════════════════════════════════════
#  CAPTION GENERATION
# ═══════════════════════════════════════════════════════════

CAPTION_STYLES: dict[str, str] = {
    "casual": (
        "Write a short Instagram caption for a {product} — a kitchen/home product. "
        "Tone: friendly, relatable, warm. Include 1-2 emojis. "
        "Make it feel like a friend sharing a life hack. "
        "Keep under 150 characters. No hashtags. No quotes."
    ),
    "luxury": (
        "Write a short Instagram caption for a {product} — a premium lifestyle product. "
        "Tone: sophisticated, elegant, aspirational. "
        "Highlight quality, design, and elevated living experience. "
        "Keep under 150 characters. No hashtags."
    ),
    "fitness": (
        "Write a short Instagram caption for a {product} — a fitness/wellness product. "
        "Tone: energetic, motivational, health-conscious. "
        "Connect the product to an active healthy lifestyle. "
        "Keep under 150 characters. No hashtags."
    ),
    "minimal": (
        "Write a short Instagram caption for a {product}. "
        "Tone: clean, simple, understated. 0-1 emojis. "
        "Focus on function and simplicity. "
        "Keep under 100 characters. No hashtags."
    ),
    "educational": (
        "Write a short Instagram caption for a {product} — a useful home/kitchen gadget. "
        "Tone: helpful, informative, practical. Include 1 quick tip or fact. "
        "Teach something useful about using this tool. "
        "Keep under 150 characters. No hashtags."
    ),
    "sale": (
        "Write a short Instagram caption for a {product} — a must-have product. "
        "Tone: exciting, persuasive. Create urgency and desire. "
        "Make it feel like a limited opportunity to upgrade daily life. "
        "Keep under 150 characters. No hashtags."
    ),
}

FALLBACK_CAPTIONS: dict[str, str] = {
    "lemon press": "Fresh squeeze, zero effort 🍋✨",
    "ice maker": "Ice cold, always ready 🧊❄️",
    "juicer": "Fresh juice, happy mood 🥤🍊",
    "kitchen grater": "Zest up your cooking 🧀✨",
    "ice cube mold": "Freeze in style 🧊🫐",
    "non-stick pan": "Perfectly golden, every time 🍳✨",
    "cast iron pot": "Slow-cooked perfection 🥘🔥",
    "blender": "Blend your dream smoothie 🥭💫",
    "air fryer": "Crispy magic, zero guilt ✨🍟",
    "coffee maker": "Morning magic in a cup ☕✨",
    "aroma diffuser": "Breathe deep, live well 🌿🕯️",
    "yoga mat": "Find your flow 🧘✨",
    "water bottle": "Stay hydrated, stay glowing 💧✨",
    "jade roller": "Roll away the stress 💆‍♀️✨",
}


def generate_caption(
    product_type: str,
    style: str = "casual",
    niche: Optional[str] = None,
    model: str = "qwen/qwen-2.5-7b-instruct",
    instructions: str = "",
) -> str:
    """
    Generate a caption using OpenRouter LLM.
    Falls back to pre-written captions on failure.
    """
    prompt_template = CAPTION_STYLES.get(style, CAPTION_STYLES["casual"])
    prompt = prompt_template.format(product=product_type)
    if niche:
        prompt = f"{prompt} Target audience: {niche}."
    if instructions:
        prompt = f"{prompt} Additional instructions: {instructions}"

    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("your-"):
        print("  No OpenRouter API key — using fallback caption")
        return FALLBACK_CAPTIONS.get(product_type, f"Love this {product_type}! ✨")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 100,
        "temperature": 0.8,
    }
    try:
        resp = requests.post(CAPTION_URL, headers=CAPTION_HEADERS, json=payload, timeout=15)
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text:
                return text
        print(f"  Caption API error {resp.status_code}")
    except Exception as e:
        print(f"  Caption API failed: {e}")

    # Final fallback
    for key in FALLBACK_CAPTIONS:
        if key in product_type.lower() or product_type.lower() in key:
            return FALLBACK_CAPTIONS[key]
    return f"Upgrade your life with this {product_type}! ✨"


# ═══════════════════════════════════════════════════════════
#  HASHTAG GENERATION
# ═══════════════════════════════════════════════════════════

HASHTAG_CATEGORIES = {
    "popular": "trending broad-reach hashtags with 100k-1M posts",
    "niche": "specific long-tail hashtags with 1k-50k posts for better discovery",
    "mixed": "mix of 40% popular + 60% niche for balanced reach",
}

FALLBACK_HASHTAGS = {
    "厨房": "#厨房好物 #厨房神器 #懒人厨房 #料理 #下厨 #美食分享 #homecooking #kitchengadgets #foodie #cookingtips",
    "家居": "#家居好物 #居家好物 #居家生活 #收纳 #家装 #homedecor #homeorganization #interiordesign",
    "健身": "#健身 #运动 #减脂 #塑形 #居家健身 #fitness #workout #gymlife #healthylifestyle",
    "美容": "#护肤 #美妆 #护肤日常 #变美 #skincare #beauty #makeup #glowup #selfcare",
    "饮品": "#饮品 #夏日饮品 #冰饮 #果汁 #调酒 #drinks #cocktail #juice #refreshing",
    "default": "#好物推荐 #生活好物 #好物分享 #种草 #好物 #lifestyle #musthave #dailylife",
}


def generate_hashtags(product: str, niche: str = "", category: str = "mixed",
                      model: str = "qwen/qwen-2.5-7b-instruct") -> str:
    """
    Generate Instagram hashtags for a product/niche via OpenRouter LLM.
    Falls back to curated hashtag lists on failure.

    Args:
        product: Product name / topic (e.g. "cutting board")
        niche: Content niche (e.g. "kitchen gadgets")
        category: "popular", "niche", or "mixed"
        model: OpenRouter model to use

    Returns:
        Space-separated hashtag string with # prefix on each tag.
    """
    strategy = HASHTAG_CATEGORIES.get(category, HASHTAG_CATEGORIES["mixed"])

    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("your-"):
        return _fallback_hashtags(product, niche)

    prompt = (
        f"Generate 25 Instagram hashtags for a post about: {product}.\n"
        f"Niche/context: {niche or 'general lifestyle'}.\n"
        f"Strategy: {strategy}.\n"
        f"Requirements:\n"
        f"- Mix Chinese and English hashtags (about 50/50)\n"
        f"- Each tag must start with #\n"
        f"- Space-separated on ONE line\n"
        f"- No explanation, no numbering, no markdown\n"
        f"- Include 3-5 brand/community tags\n"
        f"Output ONLY the hashtags:"
    )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 120,
        "temperature": 0.7,
    }
    try:
        resp = requests.post(CAPTION_URL, headers=CAPTION_HEADERS, json=payload, timeout=15)
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean up: remove markdown, numbering, extra spaces
            text = text.replace("\n", " ").replace("  ", " ")
            # Ensure all tags have #
            tags = []
            for t in text.split():
                t = t.strip().rstrip(",").rstrip(".")
                if t and not t.startswith("#"):
                    t = "#" + t
                if t and len(t) > 1:
                    tags.append(t)
            if len(tags) >= 10:
                return " ".join(tags[:30])
        print(f"  Hashtag API error {resp.status_code}")
    except Exception as e:
        print(f"  Hashtag API failed: {e}")

    return _fallback_hashtags(product, niche)


def _fallback_hashtags(product: str, niche: str = "") -> str:
    """Curated fallback hashtags when API is unavailable."""
    combined = (niche + " " + product).lower()
    for keyword, tags in FALLBACK_HASHTAGS.items():
        if keyword in combined:
            return tags
    return FALLBACK_HASHTAGS["default"]
