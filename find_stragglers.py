import csv
from app import app, db, CardReference

def compare_inventory():
    with app.app_context():
        print("🔍 Starting Reconciliation...")
        
        # 1. Load your Spreadsheet data
        # Assuming CSV columns are: Name, Set, Number
        spreadsheet_cards = []
        try:
            with open('spreadsheet.csv', mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # We normalize names to lowercase for better matching
                    spreadsheet_cards.append({
                        'name': row['Name'].strip(),
                        'number': row['Number'].strip()
                    })
        except FileNotFoundError:
            print("❌ Error: 'spreadsheet.csv' not found. Please upload it first.")
            return

        # 2. Get everything currently in your App's dictionary
        db_refs = CardReference.query.all()
        # Map them as "Name|Number" strings for quick lookup
        db_map = {f"{c.name.lower()}|{c.number}": c.id for c in db_refs}

        print(f"📊 Spreadsheet has {len(spreadsheet_cards)} cards.")
        print(f"🖥️ App has {len(db_refs)} reference cards.")
        print("-" * 30)

        missing = []
        for card in spreadsheet_cards:
            lookup_key = f"{card['name'].lower()}|{card['number']}"
            if lookup_key not in db_map:
                missing.append(f"{card['name']} ({card['number']})")

        # 3. Output the Report
        if missing:
            print(f"🚨 FOUND {len(missing)} STRAGGLERS:")
            for m in missing:
                print(f"  - {m}")
            print("-" * 30)
            print("💡 Tip: Search these names on pokemontcg.io to find their API IDs!")
        else:
            print("✅ 1:1 MATCH! Your app has every card listed in your spreadsheet.")

if __name__ == "__main__":
    compare_inventory()