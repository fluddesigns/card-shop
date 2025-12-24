import os
import pandas as pd
import re
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_session import Session
from flask_mail import Mail, Message
from sqlalchemy import text

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('SQLALCHEMY_DATABASE_URI', 'sqlite:///inventory.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- Session Config (Shopping Cart) ---
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_PERMANENT"] = False
Session(app)

# --- Email Config (SMTP2GO) ---
app.config['MAIL_SERVER'] = os.environ.get("SMTP_HOST", "mail.smtp2go.com")
app.config['MAIL_PORT'] = int(os.environ.get("SMTP_PORT", 2525))
app.config['MAIL_USERNAME'] = os.environ.get("SMTP_USER")
app.config['MAIL_PASSWORD'] = os.environ.get("SMTP_PASS")
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("FROM_EMAIL", "sales@fludmedia.com")

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    cards = db.relationship('Card', backref='owner', lazy=True, cascade="all, delete-orphan")
    sales = db.relationship('Sale', backref='seller', lazy=True, cascade="all, delete-orphan")
    settings = db.relationship('Settings', backref='owner', uselist=False, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    show_prices = db.Column(db.Boolean, default=False)

class CardReference(db.Model):
    """Local cache of all official Pokemon cards for autocomplete"""
    id = db.Column(db.String(50), primary_key=True) # API ID (e.g. base1-4)
    name = db.Column(db.String(150), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    set_id = db.Column(db.String(50))
    number = db.Column(db.String(20))
    image_url = db.Column(db.String(500))
    tcgplayer_id = db.Column(db.String(50))

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    game = db.Column(db.String(50), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    card_name = db.Column(db.String(150), nullable=False)
    card_number = db.Column(db.String(50))
    condition = db.Column(db.String(20), default='NM')
    price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    finish = db.Column(db.String(50), default='Normal')
    image_url = db.Column(db.String(500))
    variant = db.Column(db.String(100))
    location = db.Column(db.String(100))
    
    # Graded Card Fields
    grading_company = db.Column(db.String(50), nullable=True) # PSA, CGC, TAG
    grade = db.Column(db.String(20), nullable=True)           # 10, 9.5, 9
    cert_number = db.Column(db.String(100), nullable=True)    # Certification ID

    # New: 1st Edition Toggle
    is_first_edition = db.Column(db.Boolean, default=False)

    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_name = db.Column(db.String(150), nullable=False)
    set_name = db.Column(db.String(100))
    sale_price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)

# --- Startup & Migration Check ---
with app.app_context():
    db.create_all()
    
    admin_user = User.query.filter_by(username='flud').first()
    if admin_user and not admin_user.is_admin:
        admin_user.is_admin = True
        db.session.commit()

    # Manual Migration Helper
    try:
        with db.engine.connect() as conn:
            # Check for grading columns
            try:
                conn.execute(text("SELECT grading_company FROM card LIMIT 1"))
            except:
                print("Migrating DB: Adding graded card columns...")
                conn.execute(text("ALTER TABLE card ADD COLUMN grading_company VARCHAR(50)"))
                conn.execute(text("ALTER TABLE card ADD COLUMN grade VARCHAR(20)"))
                conn.execute(text("ALTER TABLE card ADD COLUMN cert_number VARCHAR(100)"))
                conn.commit()
            
            # Check for 1st Edition column
            try:
                conn.execute(text("SELECT is_first_edition FROM card LIMIT 1"))
            except:
                print("Migrating DB: Adding 1st Edition column...")
                conn.execute(text("ALTER TABLE card ADD COLUMN is_first_edition BOOLEAN DEFAULT 0"))
                conn.commit()
                
    except Exception as e:
        print(f"Migration Note: {e}")

# --- Helper Functions ---

def get_user_settings(user_id):
    settings = Settings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = Settings(user_id=user_id, show_prices=False)
        db.session.add(settings)
        db.session.commit()
    return settings

# --- Routes ---

@app.route('/')
def index():
    users = User.query.all()
    return render_template('landing.html', users=users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        flash("Registration is currently disabled.")
        return redirect(url_for('login'))
    flash("Registration is currently disabled.")
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))

    if request.method == 'POST':
        username = request.form.get('username').lower()
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            if user.username == 'flud' and not user.is_admin:
                user.is_admin = True
                db.session.commit()
                
            login_user(user)
            return redirect(url_for('admin'))
            
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

# --- PUBLIC STOREFRONTS ---

@app.route('/u/<username>')
def user_storefront(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    settings = get_user_settings(user.id)
    inventory = Card.query.filter_by(user_id=user.id).filter(Card.quantity > 0).order_by(Card.card_name.asc()).all()
    return render_template('index.html', inventory=inventory, show_prices=settings.show_prices, owner=user)

@app.route('/u/<username>/qr')
def user_qr(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    return render_template('qr.html', owner=user)

@app.route('/trade')
def trade_tool():
    users = User.query.all()
    return render_template('trade.html', users=users)

@app.route('/api/inventory/<username>')
def api_inventory(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    inventory = Card.query.filter_by(user_id=user.id).filter(Card.quantity > 0).all()
    
    data = []
    for card in inventory:
        data.append({
            'id': card.id,
            'card_name': card.card_name,
            'set_name': card.set_name,
            'price': card.price,
            'quantity': card.quantity,
            'condition': card.condition,
            'finish': card.finish,
            'variant': card.variant,
            'grading_company': card.grading_company,
            'grade': card.grade,
            'is_first_edition': card.is_first_edition
        })
    return jsonify(data)

# --- NEW: AUTOCOMPLETE API & SYNC ---

@app.route('/api/search_reference')
@login_required
def search_reference():
    query = request.args.get('q', '').lower()
    if len(query) < 2:
        return jsonify([])
    
    # Search local DB
    results = CardReference.query.filter(CardReference.name.ilike(f'%{query}%')).limit(20).all()
    
    data = []
    for card in results:
        data.append({
            'name': card.name,
            'set': card.set_name,
            'number': card.number,
            'image': card.image_url,
            'label': f"{card.name} ({card.set_name}) #{card.number}"
        })
    return jsonify(data)

@app.route('/admin/sync_db', methods=['POST'])
@login_required
def sync_db():
    if not current_user.is_admin:
        return redirect(url_for('admin'))
    
    try:
        flash("Sync connection initialized...")
        
        # CHANGED: Standard endpoint, clean User-Agent, using params dict
        api_url = "https://api.pokemontcg.io/v2/cards"
        params = {'pageSize': 10} 
        headers = {
            'User-Agent': 'FludInventory/1.0',
            'Accept': 'application/json'
        }
        
        print(f"DEBUG: Connecting to {api_url}", flush=True)
        r = requests.get(api_url, params=params, headers=headers, timeout=30)
        print(f"DEBUG: API Status Code: {r.status_code}", flush=True)
        
        if r.status_code != 200:
            print(f"DEBUG: Error Response Body: {r.text}", flush=True)
            flash(f"Sync Failed: API returned status {r.status_code}")
            return redirect(url_for('admin'))

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
            
    except requests.exceptions.ReadTimeout:
        flash("Sync Failed: Connection timed out (API was too slow). Try again later.")
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Connection Error: {e}", flush=True)
        flash(f"Connection Error: {str(e)}")
    except Exception as e:
        print(f"DEBUG: General Error: {e}", flush=True)
        flash(f"Sync Error: {str(e)}")
        
    return redirect(url_for('admin'))

# --- CART & QUOTE SYSTEM ---

@app.route('/cart/add/<int:card_id>')
def add_to_cart(card_id):
    if 'cart' not in session:
        session['cart'] = []
    
    card = Card.query.get(card_id)
    if card and card.quantity > 0:
        if card_id not in session['cart']:
            session['cart'].append(card_id)
            if not request.args.get('ajax'):
                flash(f"Added {card.card_name} to quote request.")
        else:
            if not request.args.get('ajax'):
                flash("Item already in quote.")
    
    if request.args.get('ajax'):
        return jsonify({
            'status': 'success', 
            'count': len(session['cart']),
            'id': card_id
        })
    
    return redirect(request.referrer or url_for('index'))

@app.route('/cart/remove/<int:card_id>')
def remove_from_cart(card_id):
    if 'cart' in session and card_id in session['cart']:
        session['cart'].remove(card_id)
        flash("Item removed.")
    return redirect(url_for('view_cart'))

@app.route('/cart')
def view_cart():
    cart_ids = session.get('cart', [])
    cart_items = []
    est_total = 0.0
    
    if cart_ids:
        cart_items = Card.query.filter(Card.id.in_(cart_ids)).all()
        est_total = sum(c.price for c in cart_items if c.price)
    
    return render_template('cart.html', cart=cart_items, total=est_total)

@app.route('/submit-quote', methods=['POST'])
def submit_quote():
    cart_ids = session.get('cart', [])
    if not cart_ids:
        flash("Cart is empty.")
        return redirect(url_for('index'))

    customer_email = request.form.get('email')
    customer_note = request.form.get('notes')
    
    cart_items = Card.query.filter(Card.id.in_(cart_ids)).all()
    
    if not cart_items:
        flash("Error: No valid items found.")
        return redirect(url_for('view_cart'))

    item_list = ""
    for c in cart_items:
        price_str = f"${c.price:.2f}" if c.price else "Check Market"
        cond_str = c.condition
        if c.grading_company:
            cond_str = f"{c.grading_company} {c.grade}"
        
        name_line = f"- 1x {c.card_name} ({c.set_name})"
        if c.is_first_edition:
            name_line += " [1st Edition]"
        name_line += f" [{cond_str}] - {price_str}\n"
        
        item_list += name_line

    try:
        admin_body = f"""
        New Quote Request
        =================
        Customer Email: {customer_email}
        
        Items Requested:
        {item_list}
        
        Customer Notes:
        {customer_note}
        """
        
        msg_admin = Message(
            subject=f"TCG Quote Request: {len(cart_items)} Items",
            recipients=[os.environ.get("ADMIN_EMAIL")], 
            body=admin_body,
            reply_to=customer_email
        )
        mail.send(msg_admin)

        customer_body = f"""
        Hello!
        
        We have received your request for the following cards:
        {item_list}
        
        We will review availability and pricing and email you back shortly at this address.
        
        Thank you!
        """
        
        msg_customer = Message(
            subject="Quote Request Received - Flud Media",
            recipients=[customer_email],
            body=customer_body
        )
        mail.send(msg_customer)
        
        session.pop('cart', None)
        return render_template('success.html')
        
    except Exception as e:
        flash(f"Error sending email: {str(e)}")
        return redirect(url_for('view_cart'))


# --- ADMIN PANEL ---

@app.route('/admin')
@login_required
def admin():
    settings = get_user_settings(current_user.id)
    inventory = Card.query.filter_by(user_id=current_user.id).order_by(Card.id.desc()).all()
    # Pass cache status
    cache_count = CardReference.query.count()
    return render_template('admin.html', inventory=inventory, settings=settings, cache_count=cache_count)

@app.route('/sales')
@login_required
def sales():
    sales_history = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.sale_date.desc()).all()
    total_revenue = sum(s.sale_price for s in sales_history)
    return render_template('sales.html', sales=sales_history, total=total_revenue)

@app.route('/super_admin')
@login_required
def super_admin():
    if not current_user.is_admin:
        flash("Unauthorized")
        return redirect(url_for('admin'))
    
    users = User.query.all()
    user_stats = []
    for u in users:
        count = Card.query.filter_by(user_id=u.id).count()
        user_stats.append({'user': u, 'card_count': count})
        
    return render_template('super_admin.html', stats=user_stats)

@app.route('/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash("Unauthorized")
        return redirect(url_for('admin'))
        
    user_to_delete = User.query.get_or_404(user_id)
    if user_to_delete.username == 'flud':
        flash("Cannot delete Super Admin!")
        return redirect(url_for('super_admin'))
        
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f"User {user_to_delete.username} deleted.")
    return redirect(url_for('super_admin'))

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    settings = get_user_settings(current_user.id)
    show_prices = request.form.get('show_prices') == 'on'
    settings.show_prices = show_prices
    db.session.commit()
    flash(f"Public pricing visibility set to: {show_prices}")
    return redirect(url_for('admin'))

@app.route('/add_card', methods=['POST'])
@login_required
def add_card():
    try:
        is_graded = request.form.get('is_graded') == 'on'
        is_first_edition = request.form.get('is_first_edition') == 'on'
        
        grading_company = None
        grade = None
        cert_number = None
        
        if is_graded:
            grading_company = request.form.get('grading_company')
            grade = request.form.get('grade')
            cert_number = request.form.get('cert_number')

        new_card = Card(
            user_id = current_user.id,
            game = request.form.get('game'),
            card_name = request.form.get('card_name'),
            set_name = request.form.get('set_name'),
            card_number = request.form.get('card_number'),
            condition = request.form.get('condition', 'NM'),
            finish = request.form.get('finish', 'Normal'),
            price = float(request.form.get('price', 0.0)),
            quantity = int(request.form.get('quantity', 1)),
            image_url = request.form.get('image_url', ''),
            variant = request.form.get('variant', ''),
            location = request.form.get('location', ''),
            grading_company = grading_company,
            grade = grade,
            cert_number = cert_number,
            is_first_edition = is_first_edition
        )
        db.session.add(new_card)
        db.session.commit()
        flash(f'Added {new_card.card_name} to inventory.')
    except Exception as e:
        flash(f'Error adding card: {str(e)}')
    return redirect(url_for('admin'))

@app.route('/paste_import', methods=['POST'])
@login_required
def paste_import():
    raw_text = request.form.get('paste_data')
    game_mode = request.form.get('game_mode')
    if not raw_text: return redirect(url_for('admin'))
    
    count = 0
    lines = raw_text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        try:
            if game_mode == 'magic':
                match = re.search(r'(\d+)x?\s+(.+?)\s+[\[\(]([A-Z0-9]{3,})[\]\)]\s*(\d+)?', line)
                if match:
                    qty = int(match.group(1))
                    name = match.group(2).strip()
                    set_code = match.group(3)
                    num = match.group(4) if match.group(4) else ""
                    db.session.add(Card(user_id=current_user.id, game="Magic: The Gathering", card_name=name, set_name=set_code, card_number=num, quantity=qty))
                    count += 1
            elif game_mode == 'pokemon':
                parts = line.split()
                if len(parts) >= 3:
                    qty = 1
                    if parts[0].isdigit() or (parts[0][:-1].isdigit() and parts[0].endswith('x')):
                        qty = int(parts[0].replace('x','')); parts.pop(0)
                    num = parts[-1]; set_code = parts[-2]; name = " ".join(parts[:-2])
                    db.session.add(Card(user_id=current_user.id, game="Pokemon TCG", card_name=name, set_name=set_code, card_number=num, quantity=qty))
                    count += 1
        except: pass
    db.session.commit()
    flash(f"Imported {count} cards.")
    return redirect(url_for('admin'))

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if 'file' not in request.files: return redirect(url_for('admin'))
    file = request.files['file']
    if file.filename == '': return redirect(url_for('admin'))
    if file:
        try:
            df = pd.read_csv(file)
            col_map = {c.lower().strip(): c for c in df.columns}
            
            def get_val(row, candidates, default=None):
                for cand in candidates:
                    if cand in col_map:
                        val = row[col_map[cand]]
                        return val if pd.notna(val) else default
                return default

            total_qty_imported = 0
            
            for _, row in df.iterrows():
                qty = 1
                qty_headers = ['add to quantity', 'total quantity', 'quantity', 'qty', 'count', 'amount']
                for h in qty_headers:
                    if h in col_map:
                        raw_val = row[col_map[h]]
                        try:
                            if isinstance(raw_val, str):
                                clean_val = re.sub(r'[^\d]', '', raw_val)
                                parsed = int(clean_val) if clean_val else 0
                            else:
                                parsed = int(raw_val) if pd.notna(raw_val) else 0
                            if parsed > 0:
                                qty = parsed
                                break
                        except: continue

                game_val = get_val(row, ['game', 'product line', 'category'], 'TCGPlayer Import')
                set_val = get_val(row, ['set', 'set name', 'expansion'], 'Unknown')
                name_val = get_val(row, ['name', 'card name', 'product name', 'title'], 'Unknown')
                num_val = str(get_val(row, ['number', 'card number', 'no.'], ''))
                cond_val = get_val(row, ['condition', 'cond'], 'NM')
                
                p_raw = get_val(row, ['price', 'market price', 'tcg market price'], 0.0)
                try:
                    price_val = float(str(p_raw).replace('$','').replace(',',''))
                except:
                    price_val = 0.0

                finish_val = get_val(row, ['finish', 'rarity', 'printing', 'foil'], 'Normal')
                img_val = get_val(row, ['image', 'image url', 'photo url'], '')
                loc_val = get_val(row, ['location', 'binder'], '')

                db.session.add(Card(
                    user_id=current_user.id,
                    game=game_val,
                    set_name=set_val,
                    card_name=name_val,
                    card_number=num_val,
                    condition=cond_val,
                    price=price_val,
                    quantity=qty,
                    finish=finish_val,
                    image_url=img_val,
                    location=loc_val
                ))
                total_qty_imported += qty
                
            db.session.commit()
            flash(f'Imported {total_qty_imported} cards')
        except Exception as e:
            flash(f'Error: {e}')
    return redirect(url_for('admin'))

@app.route('/bulk_actions', methods=['POST'])
@login_required
def bulk_actions():
    card_ids = request.form.getlist('card_ids')
    action = request.form.get('action')
    
    try:
        discount_raw = request.form.get('discount', '0')
        discount_pct = float(discount_raw) if discount_raw.strip() != '' else 0.0
    except ValueError:
        discount_pct = 0.0
        
    multiplier = (100 - discount_pct) / 100

    if not card_ids:
        flash("No cards selected.")
        return redirect(url_for('admin'))

    count = 0
    try:
        for c_id in card_ids:
            card = Card.query.get(int(c_id))
            if card and card.user_id == current_user.id:
                if action == 'delete':
                    db.session.delete(card)
                    count += 1
                elif action == 'sell':
                    base_price = card.price * card.quantity
                    final_price = base_price * multiplier
                    
                    sale = Sale(
                        user_id=current_user.id,
                        card_name=card.card_name,
                        set_name=card.set_name,
                        sale_price=final_price,
                        quantity=card.quantity
                    )
                    db.session.add(sale)
                    db.session.delete(card)
                    count += 1

        db.session.commit()
        
        if action == 'delete':
            flash(f"Deleted {count} cards.")
        elif action == 'sell':
            msg = f"Sold {count} lots."
            if discount_pct > 0: msg += f" Applied {discount_pct}% discount."
            flash(msg)
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}")

    return redirect(url_for('admin'))

@app.route('/update_card/<int:id>', methods=['POST'])
@login_required
def update_card(id):
    card = Card.query.get_or_404(id)
    if card.user_id != current_user.id:
        flash("Unauthorized")
        return redirect(url_for('admin'))

    action = request.form.get('action')
    
    if action == 'sold_custom':
        try:
            qty_sold = int(request.form.get('sold_quantity', 1))
            total_price_input = request.form.get('sale_total')
            
            discount_raw = request.form.get('discount', '0')
            discount_pct = float(discount_raw) if discount_raw.strip() != '' else 0.0
            multiplier = (100 - discount_pct) / 100
            
            if total_price_input and total_price_input.strip() != '':
                final_sale_price = float(total_price_input)
            else:
                final_sale_price = (card.price * qty_sold) * multiplier

            if card.quantity >= qty_sold:
                card.quantity -= qty_sold
                if card.quantity == 0:
                    db.session.delete(card)

                sale = Sale(
                    user_id=current_user.id,
                    card_name=card.card_name,
                    set_name=card.set_name,
                    sale_price=final_sale_price,
                    quantity=qty_sold
                )
                db.session.add(sale)
                
                msg = f"Sold {qty_sold}x {card.card_name} for ${final_sale_price:.2f}"
                if discount_pct > 0: msg += f" ({discount_pct}% off)"
                flash(msg)
            else:
                flash("Not enough quantity.")
        except ValueError:
            flash("Invalid quantity or price.")

    elif action == 'delete':
        db.session.delete(card)
        
    elif action == 'update_details':
        try:
            card.price = float(request.form.get('price'))
            new_qty = int(request.form.get('quantity'))
            if new_qty <= 0:
                db.session.delete(card)
            else:
                card.quantity = new_qty
            card.condition = request.form.get('condition')
            card.location = request.form.get('location')
        except: flash("Invalid input")
        
    db.session.commit()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)