"""Multi-provider image generation + AI caption generation."""

import io
import random
import hashlib
import time
import requests
from pathlib import Path
from urllib.parse import quote
from typing import Optional

from .config import OPENROUTER_API_KEY, BASE_DIR

IMAGE_DIR = BASE_DIR / "generated_images"
IMAGE_DIR.mkdir(exist_ok=True)

# ── API endpoints ──────────────────────────────────────────

CAPTION_URL = "https://openrouter.ai/api/v1/chat/completions"
OR_IMAGE_URL = "https://openrouter.ai/api/v1/images/generations"

CAPTION_HEADERS = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}


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


def build_caption(text: str, hashtags: Optional[list[str]] = None) -> str:
    """Append hashtags to caption."""
    if hashtags:
        picked = random.sample(hashtags, min(8, len(hashtags)))
        tags = " ".join(picked)
        return f"{text}\n.\n.\n{tags}"
    return text


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
    """Generate image via Pollinations.ai (free)."""
    encoded = quote(prompt, safe="")
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&nologo=true"
    if model and model != "pollinations":
        url += f"&model={quote(model)}"
    if seed is not None:
        url += f"&seed={seed}"

    print(f"  [Pollinations] Generating...")
    data = _download_image(url, timeout=90)
    if not data:
        return None
    return _save_image(data, prompt)


# ── Provider 2: OpenRouter image models ──────────────────

def _gen_openrouter(
    prompt: str,
    width: int = 1080,
    height: int = 1350,
    model: str = "openai/dall-e-3",
    quality: str = "standard",
) -> str | None:
    """
    Generate image via OpenRouter (requires API key).
    Supports: openai/dall-e-3, flux, stability-ai, etc.
    """
    if not OPENROUTER_API_KEY or OPENROUTER_API_KEY.startswith("your-"):
        print("  [OpenRouter] No API key configured, skipping")
        return None

    # Map model names to OpenRouter's expected format
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
    }

    # DALL-E specific
    if "dall-e" in model:
        size_map = {
            (1024, 1024): "1024x1024",
            (1024, 1792): "1024x1792",
            (1792, 1024): "1792x1024",
        }
        s = size_map.get((width, height), "1024x1024")
        payload["size"] = s
        payload["quality"] = quality
    else:
        payload["size"] = f"{width}x{height}"

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
            # Response format varies by model
            if "data" in data and len(data["data"]) > 0:
                img_data = data["data"][0]
                if "url" in img_data:
                    img_bytes = _download_image(img_data["url"])
                    if img_bytes:
                        return _save_image(img_bytes, prompt, "png" if "dall-e" in model else "jpg")
                if "b64_json" in img_data:
                    import base64
                    return _save_image(base64.b64decode(img_data["b64_json"]), prompt, "png")
            if "url" in data:
                img_bytes = _download_image(data["url"])
                if img_bytes:
                    return _save_image(img_bytes, prompt)
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
        provider: 'pollinations' | 'openrouter'
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

    if provider == "openrouter":
        or_model = model or "openai/dall-e-3"
        path = _gen_openrouter(prompt, width=w, height=h, model=or_model, quality=quality)
    else:
        # Default: pollinations
        path = _gen_pollinations(prompt, width=w, height=h, model=model, seed=seed)

    if not path:
        # Fallback: try Pollinations if OpenRouter failed
        if provider != "pollinations":
            print("  Falling back to Pollinations.ai...")
            path = _gen_pollinations(prompt, width=w, height=h, seed=seed)

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
