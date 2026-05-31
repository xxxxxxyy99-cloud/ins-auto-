"""Quick end-to-end test: login → generate → post."""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ins账号自动化.bot import login, post_photo, _is_logged_in
from ins账号自动化.content import generate_prompt, generate_image, generate_caption

print("=== Generate test image ===")
prompt, product = generate_prompt(niche="home cooking")
img = generate_image(prompt)
caption = generate_caption(product, style="casual")
print(f"Product: {product}")
print(f"Image:   {img}")
print(f"Caption: {caption}")
print()

print("=== Login ===")
print("A browser will open. Log in to Instagram, then press Enter here.")
cl = login()

# Debug: check what page looks like
print()
print("=== Checking login state ===")
page = cl.page
print(f"URL: {page.url}")
page.screenshot(path="debug_after_login.png")
print("Screenshot saved: debug_after_login.png")

# Check all svg aria-labels
svgs = page.query_selector_all('svg[aria-label]')
print(f"SVG aria-labels found: {len(svgs)}")
for s in svgs[:10]:
    label = s.get_attribute('aria-label')
    if label:
        print(f"  aria-label='{label}'")

# Try alternate login checks
print(f"Has 'New post' SVG: {page.query_selector('svg[aria-label=\"New post\"]') is not None}")
print(f"Has 'Home' SVG: {page.query_selector('svg[aria-label=\"Home\"]') is not None}")
print(f"Has username input: {page.query_selector('input[name=\"username\"]') is not None}")
print(f"Has 'Search' SVG: {page.query_selector('svg[aria-label=\"Search\"]') is not None}")
print(f"Has 'Reels' SVG: {page.query_selector('svg[aria-label=\"Reels\"]') is not None}")
print(f"Has 'Messages' SVG: {page.query_selector('svg[aria-label=\"Messages\"]') is not None}")

# Print page title
print(f"Page title: {page.title()}")

# Check for profile link
links = page.query_selector_all('a[href^="/"]')
profile_links = [a.get_attribute('href') for a in links if a.get_attribute('href') and '/accounts/' not in a.get_attribute('href') and len(a.get_attribute('href')) > 2]
print(f"Nav links: {profile_links[:10]}")

print()
print("=== Post ===")
ok = post_photo(img, caption)
if ok:
    print("SUCCESS!")
else:
    print("FAILED.")

cl.close()
