import sqlite3

def run_migration():
    print("Starting Phase 1 Database Migration...")
    
    # Connect directly to the SQLite database inside the instance folder
    conn = sqlite3.connect('instance/inventory.db')
    c = conn.cursor()

    # 1. Add is_favorite to CardReference
    try:
        c.execute("ALTER TABLE card_reference ADD COLUMN is_favorite BOOLEAN DEFAULT 0")
        print("✅ Successfully added 'is_favorite' to CardReference.")
    except Exception as e:
        print(f"⚠️ Skipped 'is_favorite' (Column might already exist): {e}")

    # 2. Add reference_id to Card
    try:
        c.execute("ALTER TABLE card ADD COLUMN reference_id VARCHAR(50)")
        print("✅ Successfully added 'reference_id' to Card.")
    except Exception as e:
        print(f"⚠️ Skipped 'reference_id' (Column might already exist): {e}")

    # Save and close
    conn.commit()
    conn.close()
    print("Migration complete! Phase 1 Database Schema is ready.")

if __name__ == '__main__':
    run_migration()