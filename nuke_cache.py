from app import app, db, CardReference

def nuke_dictionary():
    with app.app_context():
        print("☢️  Initiating cache wipe...")
        try:
            # Delete all rows in the CardReference table
            num_deleted = db.session.query(CardReference).delete()
            db.session.commit()
            print(f"✅ Successfully wiped {num_deleted} cards from the dictionary cache!")
            print("You are clear to run build_cache.py.")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error wiping cache: {str(e)}")

if __name__ == '__main__':
    nuke_dictionary()