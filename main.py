import os
import random
import string
import requests
import re
import tweepy
import logging
from openai import OpenAI
from datetime import datetime, timedelta, timezone
from supabase import create_client

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── Supabase ───────────────────────────────────────────────────────────────────
supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# ── Config ─────────────────────────────────────────────────────────────────────
# Weighted so Tony appears more (he's your best performer)
CHARACTERS = [
    "Tony Soprano", "Tony Soprano", "Tony Soprano",
    "Christopher Moltisanti", "Christopher Moltisanti",
    "Paulie Gualtieri",
    "Junior Soprano",
    "Silvio Dante",
]

# Weighted moods — Funny + Wise tend to get most engagement
MOODS = [
    "Funny", "Funny", "Funny",
    "Wise", "Wise",
    "Existential",
    "Depression",
]

# Post hours (UTC). Your existing ones were good — keeping them.
POST_HOURS = {13, 17, 21, 1}

# Hashtags — bot always uses #Sopranos + picks 1-2 extras
HASHTAG_POOL = [
    "#HBO", "#SopranosQuotes", "#TonySoprano", "#BadaBing",
    "#MobLife", "#ClassicTV", "#NJMob",
]

# ── Helpers ────────────────────────────────────────────────────────────────────
def extract_clean(text: str) -> str:
    """Strips the quote down to lowercase letters only — used for dedup hashing."""
    matches = re.findall(r'"(.*?)"', text)
    combined = ''.join(matches)
    no_punct = combined.translate(str.maketrans('', '', string.punctuation))
    return re.sub(r'\s+', '', no_punct.lower())

def pick_hashtags(character: str) -> str:
    tags = {"#Sopranos", f"#{character.split()[0]}"}  # e.g. #Tony, #Paulie
    extras = random.sample(HASHTAG_POOL, 1)
    tags.update(extras)
    return " ".join(sorted(tags))

# ── GitHub image fetch ─────────────────────────────────────────────────────────
def get_random_image(character: str, mood: str):
    parts = character.strip().title().split()
    mood_fmt = mood.strip().title()
    repo_name = f"SopranosQuotesImages-{'-'.join(parts + [mood_fmt])}"
    api_url = f"https://api.github.com/repos/martinv9000/{repo_name}/contents/"

    headers = {}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    resp = requests.get(api_url, headers=headers, timeout=10)
    resp.raise_for_status()
    files = [f for f in resp.json() if f["type"] == "file"]
    if not files:
        raise ValueError(f"No images found in repo {repo_name}")

    chosen = random.choice(files)
    return chosen["name"], chosen["download_url"]

# ── Grok quote generation ──────────────────────────────────────────────────────
def ask_ai(character: str, mood: str) -> tuple[str, str]:
    """Returns (full tweet text, cleaned dedup string)."""
    client = OpenAI(
        api_key=os.environ["xai_API_KEY"],
        base_url="https://api.x.ai/v1"
    )

    hashtags = pick_hashtags(character)

    prompt = f"""You write for a popular Sopranos Twitter bot.

Write a {mood.lower()} quote from {character} in The Sopranos. It should sound completely authentic to their voice and personality.

Output ONLY this format — nothing else:
"[quote]" — {character}

{hashtags}

The full output including hashtags must be under 270 characters. Do not use the most famous/overused Sopranos quotes."""

    response = client.chat.completions.create(
        model="grok-4.20-reasoning",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
    )

    full_text = response.choices[0].message.content.strip()
    cleaned = extract_clean(full_text)
    return full_text, cleaned

# ── Supabase dedup checks ──────────────────────────────────────────────────────
def quote_exists_recently(cleaned_text: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = supabase.table("SopranosQuotes") \
        .select("id") \
        .eq("text", cleaned_text) \
        .gte("created_at", cutoff) \
        .execute()
    return len(res.data) > 0

def imgname_exists_recently(img_name: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    res = supabase.table("SopranosQuotes") \
        .select("id") \
        .eq("imgname", img_name) \
        .gte("created_at", cutoff) \
        .execute()
    return len(res.data) > 0

def save_post(cleaned_text: str, img_name: str):
    supabase.table("SopranosQuotes").insert({
        "text": cleaned_text,
        "imgname": img_name
    }).execute()

# ── Twitter posting ────────────────────────────────────────────────────────────
def post(tweet_text: str, image_url: str):
    api_key    = os.environ["x_api_key"]
    api_secret = os.environ["x_api_secret"]
    acc_token  = os.environ["x_access_token"]
    acc_secret = os.environ["x_access_token_secret"]

    img_data = requests.get(image_url, timeout=15).content
    tmp = "temp_image.png"
    with open(tmp, "wb") as f:
        f.write(img_data)

    try:
        auth = tweepy.OAuth1UserHandler(api_key, api_secret, acc_token, acc_secret)
        v1 = tweepy.API(auth)
        media = v1.media_upload(tmp)

        v2 = tweepy.Client(
            consumer_key=api_key, consumer_secret=api_secret,
            access_token=acc_token, access_token_secret=acc_secret
        )
        v2.create_tweet(text=tweet_text, media_ids=[media.media_id])
        log.info("Tweet posted successfully.")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    log.info("Script started.")

    # 1. Check posting hour
    if datetime.utcnow().hour not in POST_HOURS:
        log.info("Not a posting hour. Exiting.")
        return

    # 2. Random skip to avoid looking like a bot (your original logic — keeping it)
    if random.random() > 0.7:
        log.info("Random skip triggered. Exiting.")
        return

    # 3. Pick character + mood
    character = random.choice(CHARACTERS)
    mood = random.choice(MOODS)
    log.info("Character: %s | Mood: %s", character, mood)

    # 4. Generate a unique quote (retry until not a duplicate)
    for attempt in range(1, 6):
        log.info("Generating quote (attempt %d)...", attempt)
        tweet_text, cleaned = ask_ai(character, mood)
        if len(tweet_text) > 280:
            log.warning("Tweet too long (%d chars), retrying.", len(tweet_text))
            continue
        if quote_exists_recently(cleaned):
            log.warning("Duplicate quote, retrying.")
            continue
        log.info("Quote accepted:\n%s", tweet_text)
        break
    else:
        log.error("Could not generate a unique quote after 5 attempts. Exiting.")
        return

    # 5. Map mood for image folder (your original Existential/Wise → Other logic)
    img_mood = mood if mood not in ("Existential", "Wise") else "Other"

    # 6. Find a non-duplicate image (retry until fresh)
    for attempt in range(1, 11):
        log.info("Fetching image (attempt %d)...", attempt)
        try:
            img_name, img_url = get_random_image(character, img_mood)
        except Exception as e:
            log.error("Image fetch error: %s", e)
            return
        if not imgname_exists_recently(img_name):
            log.info("Image accepted: %s", img_name)
            break
        log.warning("Image already used recently, retrying.")
    else:
        log.error("Could not find a fresh image after 10 attempts. Exiting.")
        return

    # 7. Post to Twitter
    log.info("Posting to Twitter...")
    try:
        post(tweet_text, img_url)
    except Exception as e:
        log.error("Failed to post tweet: %s", e)
        return

    # 8. Save to Supabase
    log.info("Saving to Supabase...")
    save_post(cleaned, img_name)
    log.info("All done. ")

if __name__ == "__main__":
    main()
