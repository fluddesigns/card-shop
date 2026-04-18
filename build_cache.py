import requests
import time
import re
from app import app, db, CardReference

def get_clean_finishes(tcgplayer_data):
    """Parses TCGPlayer pricing tiers to determine available card variants."""
    if not tcgplayer_data or not isinstance(tcgplayer_data, dict) or 'prices' not in tcgplayer_data:
        return "Normal"
    
    raw_finishes = tcgplayer_data['prices'].keys()
    clean_finishes = []
    
    for f in raw_finishes:
        f_lower = f.lower()
        if f_lower == 'normal': 
            clean_finishes.append('Normal')
        elif f_lower == 'holofoil': 
            clean_finishes.append('Holo')
        elif f_lower == 'reverseholofoil': 
            clean_finishes.append('Reverse Holo')
        elif f_lower == '1steditionholofoil': 
            clean_finishes.append('1st Edition Holo')
        elif f_lower == '1steditionnormal' or f_lower == '1stedition': 
            clean_finishes.append('1st Edition')
        elif f_lower == 'unlimitedholofoil': 
            clean_finishes.append('Unlimited Holo')
        else: 
            cleaned = re.sub('([A-Z])', r' \1', f).strip().title()
            clean_finishes.append(cleaned)
            
    return ",".join(clean_finishes) if clean_finishes else "Normal"

def build_database():
    with app.app_context():
        print("🚀 Starting Master Dictionary Build...")
        page = 1
        total_added = 0
        
        while True:
            print(f"Fetching page {page}...")
            url = "https://api.pokemontcg.io/v2/cards"
            params = {'page': page, 'pageSize': 250}
            
            try:
                headers = {'User-Agent': 'FludInventory/1.0'}
                r = requests.get(url, params=params, headers=headers, timeout=30)
                
                # Handle API rate limiting gracefully
                if r.status_code == 429:
                    print("⚠️ Rate limited! Sleeping for 10 seconds...")
                    time.sleep(10)
                    continue
                    
                if r.status_code != 200:
                    print(f"❌ Failed to fetch page {page}. Status: {r.status_code}")
                    break
                    
                data = r.json().get('data', [])
                
                # If the page is empty, we've hit the end of the database
                if not data:
                    print("✅ Reached the end of the API data!")
                    break
                    
                count_for_page = 0
                for item in data:
                    c_id = item.get('id')
                    if not c_id: continue
                    
                    exists = CardReference.query.get(c_id)
                    if not exists:
                        card_set = item.get('set') or {}
                        images = item.get('images') or {}
                        
                        ref = CardReference(
                            id=c_id,
                            name=item.get('name', 'Unknown'),
                            set_name=card_set.get('name', 'Unknown'),
                            set_id=card_set.get('id'),
                            number=item.get('number', ''),
                            image_url=images.get('small'),
                            release_date=card_set.get('releaseDate'),
                            available_finishes=get_clean_finishes(item.get('tcgplayer'))
                        )
                        db.session.add(ref)
                        count_for_page += 1
                        
                db.session.commit()
                total_added += count_for_page
                print(f"✅ Page {page} complete. Added {count_for_page} cards. Total so far: {total_added}")
                
                page += 1
                time.sleep(1) # Be nice to the API so it doesn't kick us out
                
            except Exception as e:
                print(f"❌ Error on page {page}: {e}")
                break
                
        print(f"🎉 Build complete! Total cards added to cache: {total_added}")

if __name__ == '__main__':
    build_database()