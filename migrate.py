import sqlite3

def run_migration():
    conn = sqlite3.connect('instance/inventory.db')
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE card_reference ADD COLUMN available_finishes VARCHAR(255) DEFAULT 'Normal'")
        print("✅ Successfully added 'available_finishes' to CardReference.")
    except Exception as e:
        print(f"⚠️ Skipped: {e}")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    run_migration()