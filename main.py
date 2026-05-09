import os
import random
import string
import requests
from openai import OpenAI
import re
import tweepy
import supabase
from datetime import datetime, timedelta, timezone
from supabase import create_client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def extract_and_clean(text: str) -> str:
    # Extract content inside double quotes
    matches = re.findall(r'"(.*?)"', text)
    
    # Join all matches into one string (in case there are multiple quoted parts)
    combined = ''.join(matches)
    
    # Remove punctuation
    no_punct = combined.translate(str.maketrans('', '', string.punctuation))
    
    # Convert to lowercase
    lower = no_punct.lower()
    
    # Remove all whitespace
    cleaned = re.sub(r'\s+', '', lower)
    
    return cleaned

def get_random_image(name, mood):
    # Format repo name
    parts = name.strip().title().split()
    mood = mood.strip().title()
    repo_name = "-".join(parts + [mood])

    # GitHub API URL
    api_url = f"https://api.github.com/repos/martinv9000/SopranosQuotesImages-{repo_name}/contents/"

    # Get file list
    response = requests.get(api_url)
    response.raise_for_status()
    files = [f for f in response.json() if f["type"] == "file"]

    # Pick random file
    random_file = random.choice(files)
    image_url = random_file["download_url"]
    file_name = random_file["name"]

    return file_name, image_url

def ask_ai():
    xai_API_KEY = os.environ.get("xai_API_KEY")

    characters = ["Tony Soprano", "Christopher Moltisanti", "Paulie Gualtieri", "Junior Soprano", "Silvio Dante", "Tony Soprano", "Tony Soprano", "Tony Soprano", "Christopher Moltisanti"]
    moods = ["Funny", "Existential", "Depression", "Wise", "Existential", "Wise"]
    character = random.choice(characters)
    mood = random.choice(moods)

    prompt = f"Give me an iconic quote of {character} from The Sopranos with a {mood} mood. Only give me the quote, in quotations and then - the characters name as I gave it to you"



    client = OpenAI(
        api_key=xai_API_KEY,
        base_url="https://api.x.ai/v1"
    )
    response = client.chat.completions.create(
        model="grok-4.20-reasoning",
        messages=[{"role": "user", "content": prompt}]
    )

    response = response.choices[0].message.content
    quote = extract_and_clean(response)
    return response, quote, character, mood

def post(quote, url_img):
    x_api_key=os.environ.get("x_api_key")
    x_api_secret=os.environ.get("x_api_secret")
    x_access_token=os.environ.get("x_access_token")
    x_access_token_secret=os.environ.get("x_access_token_secret")

    # ===== STEP 2: DOWNLOAD IMAGE =====
    img_data = requests.get(url_img).content

    with open("temp_image.png", "wb") as f:
        f.write(img_data)

    # ===== STEP 3: UPLOAD TO X =====
    auth = tweepy.OAuth1UserHandler(
        x_api_key, x_api_secret,
        x_access_token, x_access_token_secret
    )

    api = tweepy.API(auth)
    media = api.media_upload("temp_image.png")

    # ===== STEP 4: POST TWEET =====
    client = tweepy.Client(
        consumer_key=x_api_key,
        consumer_secret=x_api_secret,
        access_token=x_access_token,
        access_token_secret=x_access_token_secret
    )

    client.create_tweet(
        text=quote,
        media_ids=[media.media_id]
    )

    # Cleanup
    os.remove("temp_image.png")

def quote_exists_recently(text):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    res = supabase.table("SopranosQuotes") \
        .select("id") \
        .eq("text", text) \
        .gte("created_at", cutoff.isoformat()) \
        .execute()
    
    return len(res.data) > 0

def imgname_exists_recently(text):
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    res = supabase.table("SopranosQuotes") \
        .select("id") \
        .eq("imgname", text) \
        .gte("created_at", cutoff.isoformat()) \
        .execute()
    
    return len(res.data) > 0

def save_post(text, imgname):
    response = supabase.table("SopranosQuotes").insert({
        "text": text,
        "imgname": imgname
    }).execute()
    
    return response


def main():
    print("Starting script")
    # Only post 4 times a day at good hours for traffic
    now = datetime.utcnow()
    hour = now.hour

    if hour not in [13, 17, 21, 1]:
        print("Not the right time")
        return

    print("Now is the right time")
    print("Getting quote")
    quoteExists = True
    while quoteExists==True:
        response, quote, character, mood = ask_ai()
        print(quote)
        print(character)
        #If quote exists in database look for new one
        #If quote does not exist in database, find image. Set newquote=True
        quoteExists = quote_exists_recently(quote)

    
    if mood == "Existential" or "Wise":
        mood == "Other"
    print("Getting image")
    imageExists = True
    while imageExists==True:
        img_name, url_img = get_random_image(character, mood)
        #If imgname exists in database look for new one
        #If imgname does not exist in database, post to X. Set newimage=True
        imageExists = imgname_exists_recently(img_name)
    print("Posting...")
    post(response, url_img)
    # Store quote to database
    # Store img name to database\
    print("Saving to database")
    save_post(quote, img_name)


if __name__ == "__main__":
    main()





