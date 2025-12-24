@app.route('/admin/sync_db', methods=['POST'])
@login_required
def sync_db():
    if not current_user.is_admin:
        return redirect(url_for('admin'))
    
    try:
        flash("Sync connection initialized...")
        
        # 1. Use a smaller page size and a timeout for safety
        api_url = "https://api.pokemontcg.io/v2/cards?pageSize=10&select=id,name,set,number,images,tcgplayer"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json'
        }
        
        # Debug print (Check your docker logs to see this)
        print(f"DEBUG: Connecting to {api_url}", flush=True)
        
        r = requests.get(api_url, headers=headers, timeout=10)
        
        print(f"DEBUG: API Status Code: {r.status_code}", flush=True)
        
        # 2. Check for HTTP Errors BEFORE trying to read JSON
        if r.status_code != 200:
            flash(f"Sync Failed: API returned status {r.status_code}")
            # print(f"DEBUG Response Body: {r.text}", flush=True) 
            return redirect(url_for('admin'))

        # 3. Safe JSON decoding
        try:
            data = r.json()
        except ValueError:
            flash("Sync Failed: API returned invalid data (not JSON).")
            return redirect(url_for('admin'))
        
        count = 0
        if 'data' in data:
            for item in data['data']:
                try:
                    c_id = item['id']
                    exists = CardReference.query.get(c_id)
                    if not exists:
                        ref = CardReference(
                            id=c_id,
                            name=item['name'],
                            set_name=item['set']['name'],
                            set_id=item['set']['id'],
                            number=item['number'],
                            image_url=item['images']['small'] if 'images' in item else None,
                        )
                        db.session.add(ref)
                        count += 1
                except: continue
            
            db.session.commit()
            flash(f"Success! Synced {count} new cards (Test Batch).")
        else:
            flash("Sync Failed: API response missing 'data' field.")
            
    except requests.exceptions.RequestException as e:
        # Catches DNS, Timeout, and Connection errors
        print(f"DEBUG: Connection Error: {e}", flush=True)
        flash(f"Connection Error: {str(e)}")
    except Exception as e:
        print(f"DEBUG: General Error: {e}", flush=True)
        flash(f"Sync Error: {str(e)}")
        
    return redirect(url_for('admin'))