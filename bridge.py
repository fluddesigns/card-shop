from app import app, db, Card, CardReference

def run_bridge():
    with app.app_context():
        print("Starting the Bridge Script...")
        inventory = Card.query.all()
        updated_count = 0
        missed_count = 0
        
        for card in inventory:
            if card.reference_id:
                continue  # Skip if already linked
            
            # Search the cache for an exact match
            query = CardReference.query.filter(CardReference.name == card.card_name)
            if card.set_name:
                query = query.filter(CardReference.set_name == card.set_name)
            if card.card_number:
                query = query.filter(CardReference.number == card.card_number)
            
            match = query.first()
            if match:
                card.reference_id = match.id
                updated_count += 1
            else:
                print(f"⚠️ No dictionary match found for: {card.card_name} ({card.set_name})")
                missed_count += 1
        
        db.session.commit()
        print(f"✅ Successfully linked {updated_count} cards to the Pokedex dictionary!")
        if missed_count > 0:
            print(f"⚠️ {missed_count} cards could not be linked (likely due to typos or missing set info).")

if __name__ == '__main__':
    run_bridge()