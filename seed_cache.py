import requests
from app import app, db, CardReference # Make sure 'app' matches your main file name

def seed_database():
    api_url = "https://api.pokemontcg.io/v2/cards"
    headers = {'User-Agent': 'FludInventory/1.0', 'Accept': 'application/json'}
    
    with app.app_context():
        page = 1
        total_added = 0
        
        while True:
            print(f"📥 Fetching Page {page}...")
            params = {'pageSize': 250, 'page': page}
            r = requests.get(api_url, params=params, headers=headers, timeout=30, verify=False)
            
            if r.status_code != 200:
                print(f"❌ API Error: {r.status_code}. Stopping.")
                break
                
            data = r.json()
            cards = data.get('data', [])
            
            if not cards:
                print("✅ Reached the end of the API. Sync complete!")
                break
                
            for item in cards:
                c_id = item['id']
                if not CardReference.query.get(c_id):
                    ref = CardReference(
                        id=c_id,
                        name=item['name'],
                        set_name=item['set']['name'],
                        set_id=item['set']['id'],
                        number=item['number'],
                        image_url=item['images']['small'] if 'images' in item else None,
                        release_date=item.get('set', {}).get('releaseDate')
                    )
                    db.session.add(ref)
                    total_added += 1
                    
            db.session.commit()
            print(f"💾 Saved Page {page}. Total cards cached: {total_added}")
            page += 1

if __name__ == '__main__':
    seed_database()
