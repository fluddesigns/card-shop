import requests
import time
from app import app, db, CardReference

def get_clean_finishes(tcgplayer_data):
    """Extracts finish types from TCGPlayer pricing data and formats them"""
    if not tcgplayer_data or 'prices' not in tcgplayer_data:
        return "Normal"
        
    prices = tcgplayer_data.get('prices', {})
    finishes = []
    
    # Map the API keys to readable strings
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

def patch_favorites():
    with app.app_context():
        # Only query cards you are actively tracking to save time!
        favorites = CardReference.query.filter_by(is_favorite=True).all()
        species_names = list(set([f.name for f in favorites]))
        
        print(f"Starting variant patch for: {', '.join(species_names)}")
        
        for name in species_names:
            print(f"Fetching variants for {name}...")
            url = f"https://api.pokemontcg.io/v2/cards?q=name:\"{name}\""
            response = requests.get(url).json()
            
            if 'data' in response:
                for api_card in response['data']:
                    # Find the matching card in your database
                    db_card = CardReference.query.get(api_card['id'])
                    if db_card:
                        # Extract the available finishes and save them
                        finishes = get_clean_finishes(api_card.get('tcgplayer'))
                        db_card.available_finishes = finishes
            
            time.sleep(1) # Be polite to the API
            
        db.session.commit()
        print("✅ Variant patch complete! Your tracker now knows about Reverse Holos!")

if __name__ == '__main__':
    patch_favorites()