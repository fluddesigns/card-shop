import csv
import re
from app import app, db, CardReference

def normalize_name(name):
    """Strips suffixes like ' - 107/088' or ' (Delta Species)'"""
    if not name: return ""
    # Remove everything after a dash, parenthesis, or hash symbol
    clean = re.split(r' \-| \(| #', name)[0]
    return clean.strip().lower()

def normalize_number(num):
    """Converts #074/132 -> 74, #SM51 -> SM51, #013 -> 13"""
    if not num: return ""
    num = str(num).replace('#', '').split('/')[0]
    # Remove leading zeros from the numeric part (e.g., 008 -> 8)
    # but keep letters (e.g., SWSH005 -> SWSH5 or SWSH005 depending on API)
    # Most common API format for numbers is stripping leading zeros:
    match = re.search(r'([a-zA-Z]*)(0*)(\d+)', num)
    if match:
        prefix, zeros, digits = match.groups()
        return f"{prefix}{digits}".strip()
    return num.strip()

def compare_inventory():
    with app.app_context():
        print("🔍 Starting Deep Reconciliation (V2)...")
        
        # 1. Load Spreadsheet
        spreadsheet_targets = []
        try:
            with open('spreadsheet.csv', mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Capture the raw data for the report, but clean it for the match
                    raw_name = row.get('Name', '')
                    raw_num = row.get('Number', '')
                    
                    spreadsheet_targets.append({
                        'raw': f"{raw_name} ({raw_num})",
                        'clean_key': f"{normalize_name(raw_name)}|{normalize_number(raw_num)}"
                    })
        except Exception as e:
            print(f"❌ CSV Error: {e}")
            return

        # 2. Load Database References (Cleaned)
        db_refs = CardReference.query.all()
        db_map = set()
        for c in db_refs:
            # We normalize the DB side too just in case
            db_key = f"{normalize_name(c.name)}|{normalize_number(c.number)}"
            db_map.add(db_key)

        print(f"📊 Spreadsheet: {len(spreadsheet_targets)} records found.")
        print(f"🖥️  Database: {len(db_map)} unique artwork references loaded.")
        print("-" * 40)

        # 3. The Match
        missing = []
        for target in spreadsheet_targets:
            if target['clean_key'] not in db_map:
                missing.append(target['raw'])

        # 4. Result
        if missing:
            # We use set() to avoid listing duplicates (like 1st Ed vs Unlimited) 
            # if the reference card itself is missing.
            unique_missing = sorted(list(set(missing)))
            print(f"🚨 FOUND {len(unique_missing)} MISSING REFERENCES:")
            for m in unique_missing:
                print(f"  - {m}")
            print("-" * 40)
            print(f"💡 Success! Found {len(spreadsheet_targets) - len(missing)} matches.")
            print("The list above are cards your Pokedex doesn't know exist yet.")
        else:
            print("✅ PERFECT MATCH! Your local database now covers every card in your CSV.")

if __name__ == "__main__":
    compare_inventory()