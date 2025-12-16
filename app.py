import os
import pandas as pd
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_name = db.Column(db.String(150), nullable=False)
    set_name = db.Column(db.String(100))
    sale_price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    # Auto-promote 'flud' logic on startup
    admin_user = User.query.filter_by(username='flud').first()
    if admin_user and not admin_user.is_admin:
        admin_user.is_admin = True
        db.session.commit()

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
    # Landing page listing all active traders
    users = User.query.all()
    return render_template('landing.html', users=users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    # LOCKED DOWN: Registration disabled per user request
    if request.method == 'POST':
        flash("Registration is currently disabled.")
        return redirect(url_for('login'))
    
    # If they try to visit the page manually
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
            'variant': card.variant
        })
    return jsonify(data)

# --- ADMIN PANEL ---

@app.route('/admin')
@login_required
def admin():
    settings = get_user_settings(current_user.id)
    inventory = Card.query.filter_by(user_id=current_user.id).order_by(Card.id.desc()).all()
    return render_template('admin.html', inventory=inventory, settings=settings)

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
        new_card = Card(
            user_id = current_user.id,
            game = request.form.get('game'),
            card_name = request.form.get('card_name'),
            set_name = request.form.get('set_name'),
            card_number = request.form.get('card_number'),
            condition = request.form.get('condition'),
            finish = request.form.get('finish'),
            price = float(request.form.get('price', 0.0)),
            quantity = int(request.form.get('quantity', 1)),
            image_url = request.form.get('image_url', ''),
            variant = request.form.get('variant', ''),
            location = request.form.get('location', '')
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
            
            # Create a map of { 'lowercase_stripped_header': 'Original Header' }
            # This ensures we find 'quantity' even if the CSV says 'Quantity ' or 'QUANTITY'
            col_map = {c.lower().strip(): c for c in df.columns}
            
            def get_val(row, candidates, default=None):
                for cand in candidates:
                    if cand in col_map:
                        col_name = col_map[cand]
                        val = row[col_name]
                        return val if pd.notna(val) else default
                return default

            total_qty_imported = 0
            
            for _, row in df.iterrows():
                # Extract Quantity with robust fallback logic
                q_raw = get_val(row, ['quantity', 'qty', 'total quantity', 'add to quantity', 'count', 'amount'], 1)
                
                # Handle cases like "4x" or string inputs
                try:
                    if isinstance(q_raw, str):
                        q_clean = re.sub(r'[^\d]', '', q_raw) # Remove non-digits
                        qty = int(q_clean) if q_clean else 1
                    else:
                        qty = int(q_raw)
                except:
                    qty = 1

                # Extract other fields using the case-insensitive helper
                game_val = get_val(row, ['game', 'product line', 'category'], 'TCGPlayer Import')
                set_val = get_val(row, ['set', 'set name', 'expansion'], 'Unknown')
                name_val = get_val(row, ['name', 'card name', 'product name', 'title'], 'Unknown')
                num_val = str(get_val(row, ['number', 'card number', 'no.'], ''))
                cond_val = get_val(row, ['condition', 'cond'], 'NM')
                
                # specific handling for price to avoid crashes on currency symbols
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
                
                # Add to total count
                total_qty_imported += qty
                
            db.session.commit()
            flash(f'Imported {total_qty_imported} cards')
        except Exception as e:
            flash(f'Error: {e}')
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
            
            if total_price_input:
                final_sale_price = float(total_price_input)
            else:
                final_sale_price = card.price * qty_sold

            if card.quantity >= qty_sold:
                card.quantity -= qty_sold
                
                # Check if empty immediately after subtracting
                if card.quantity == 0:
                    db.session.delete(card)

                # Create Sale Record
                sale = Sale(
                    user_id=current_user.id,
                    card_name=card.card_name,
                    set_name=card.set_name,
                    sale_price=final_sale_price,
                    quantity=qty_sold
                )
                db.session.add(sale)
                flash(f"Sold {qty_sold}x {card.card_name} for ${final_sale_price:.2f}")
            else:
                flash("Not enough quantity.")
        except ValueError:
            flash("Invalid quantity or price.")

    elif action == 'delete':
        db.session.delete(card)
        
    elif action == 'update_details':
        try:
            card.price = float(request.form.get('price'))
            
            # Check for manual 0 quantity entry
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