import requests
import sys
from app import app, db, CardReference

def get_clean_finishes(tcgplayer_data):
    """Extracts finish types from TCGPlayer pricing data and formats them"""
    if not tcgplayer_data or 'prices' not in tcgplayer_data:
        return "Normal"
        
    prices = tcgplayer_data.get('prices', {})
    finishes = []
    
    key_map = {
        'normal': 'Normal',
        'holofoil': 'Holofoil',
        'reverseHolofoil': 'Reverse Holofoil',
        '1stEditionNormal': '1st Edition Normal',
        '1stEditionHolofoil': '1st Edition Holofoil'
    }
    
    for key in key_map:
        if key in prices:
            finishes.append(key_map[key])
            
    return ",".join(finishes) if finishes else "Normal"

def deep_dive(target_name):
    with app.app_context():
        print(f"\n🚀 Initiating Deep-Dive Protocol for: *{target_name}*")
        
        # Double wildcard search to catch Alolan, Dark, VMAX, Promos, etc.
        url = f"https://api.pokemontcg.io/v2/cards?q=name:*{target_name}*&pageSize=250"
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json().get('data', [])
        except Exception as e:
            print(f"❌ API Error: {e}")
            return

        print(f"📡 API returned {len(data)} total cards containing '{target_name}'.")
        
        new_cards = 0
        updated_cards = 0

        for api_card in data:
            db_card = CardReference.query.get(api_card['id'])
            finishes = get_clean_finishes(api_card.get('tcgplayer'))
            
            if not db_card:
                # 🚨 Missing card found! Inject it into the local database.
                images = api_card.get('images', {})
                image_url = images.get('large') or images.get('small', '')
                
                # Extract TCGPlayer ID if available
                tcg_url = api_card.get('tcgplayer', {}).get('url', '')
                tcg_id = str(tcg_url).split('/')[-1].split('?')[0] if tcg_url else None

                new_ref = CardReference(
                    id=api_card['id'],
                    name=api_card['name'],
                    set_name=api_card.get('set', {}).get('name', 'Unknown Set'),
                    set_id=api_card.get('set', {}).get('id', ''),
                    number=api_card.get('number', ''),
                    image_url=image_url,
                    release_date=api_card.get('set', {}).get('releaseDate', '1999/01/01'),
                    tcgplayer_id=tcg_id,
                    is_favorite=True, # Auto-flag as a tracked card
                    available_finishes=finishes
                )
                db.session.add(new_ref)
                new_cards += 1
            else:
                # If the card exists but was missing finish data, patch it
                if db_card.available_finishes != finishes:
                    db_card.available_finishes = finishes
                    updated_cards += 1
                if not db_card.is_favorite:
                    db_card.is_favorite = True
                    updated_cards += 1

        db.session.commit()
        print(f"\n✅ Deep-Dive Complete!")
        print(f"➕ Added {new_cards} completely new cards to your local dictionary.")
        print(f"🔄 Updated {updated_cards} existing cards with fresh variant data.\n")

if __name__ == '__main__':
    # Grab the target name directly from the terminal command
    if len(sys.argv) > 1:
        target = " ".join(sys.argv[1:])
        deep_dive(target)
    else:
        print("⚠️ Usage: python deep_dive.py <PokemonName>")
        print("💡 Example: python deep_dive.py Meowth")