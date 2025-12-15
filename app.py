import os
import pandas as pd
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from functools import wraps

app = Flask(__name__)

# Config
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin')
CONTACT_INFO = "Message me to buy/trade!"

db = SQLAlchemy(app)

# Models
class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game = db.Column(db.String(50), nullable=False)
    set_name = db.Column(db.String(100), nullable=False)
    card_name = db.Column(db.String(150), nullable=False)
    card_number = db.Column(db.String(50))
    condition = db.Column(db.String(20), default='NM')
    price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    finish = db.Column(db.String(50), default='Normal')
    variant = db.Column(db.String(100))
    location = db.Column(db.String(100))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    show_prices = db.Column(db.Boolean, default=True)

with app.app_context():
    db.create_all()
    if not Settings.query.first():
        db.session.add(Settings(show_prices=True))
        db.session.commit()

# Auth Helpers
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def get_settings():
    return Settings.query.first()

# Routes
@app.route('/')
def index():
    settings = get_settings()
    inventory = Card.query.filter(Card.quantity > 0).order_by(Card.price.desc()).all()
    return render_template('index.html', inventory=inventory, show_prices=settings.show_prices, contact_info=CONTACT_INFO)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin'))
        flash('Incorrect password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin():
    settings = get_settings()
    inventory = Card.query.order_by(Card.id.desc()).all()
    return render_template('admin.html', inventory=inventory, settings=settings)

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    settings = get_settings()
    settings.show_prices = request.form.get('show_prices') == 'on'
    db.session.commit()
    return redirect(url_for('admin'))

@app.route('/add_card', methods=['POST'])
@login_required
def add_card():
    try:
        new_card = Card(
            game=request.form.get('game'),
            card_name=request.form.get('card_name'),
            set_name=request.form.get('set_name'),
            card_number=request.form.get('card_number'),
            condition=request.form.get('condition'),
            finish=request.form.get('finish'),
            price=float(request.form.get('price', 0.0)),
            quantity=int(request.form.get('quantity', 1)),
            variant=request.form.get('variant', ''),
            location=request.form.get('location', '')
        )
        db.session.add(new_card)
        db.session.commit()
        flash(f'Added {new_card.card_name}')
    except Exception as e:
        flash(f'Error: {e}')
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
                    db.session.add(Card(game="Magic: The Gathering", card_name=name, set_name=set_code, card_number=num, quantity=qty))
                    count += 1
            elif game_mode == 'pokemon':
                parts = line.split()
                if len(parts) >= 3:
                    qty = 1
                    if parts[0].isdigit() or (parts[0][:-1].isdigit() and parts[0].endswith('x')):
                        qty = int(parts[0].replace('x','')); parts.pop(0)
                    num = parts[-1]; set_code = parts[-2]; name = " ".join(parts[:-2])
                    db.session.add(Card(game="Pokemon TCG", card_name=name, set_name=set_code, card_number=num, quantity=qty))
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
            
            # --- IMPROVED HEADER MAPPING ---
            def get_val(row, keys, default=None):
                for k in keys:
                    if k in row: return row[k] if pd.notna(row[k]) else default
                return default
            
            count = 0
            for _, row in df.iterrows():
                # TCGPlayer exports often lack a "Game" column, so we default to 'TCGPlayer Import'
                # or you can try to infer it. For now, we make it searchable.
                game_val = get_val(row, ['Game', 'game', 'Category'], 'TCGPlayer Import')
                
                db.session.add(Card(
                    game=game_val,
                    set_name=get_val(row, ['Set', 'set', 'Set Name', 'Expansion'], 'Unknown'),
                    card_name=get_val(row, ['Name', 'name', 'Product Name', 'Card Name'], 'Unknown'),
                    card_number=str(get_val(row, ['Number', 'number', 'Card Number'], '')),
                    condition=get_val(row, ['Condition', 'cond'], 'NM'),
                    price=float(get_val(row, ['Price', 'price', 'TCG Market Price', 'Market Price'], 0.0)),
                    quantity=int(get_val(row, ['Quantity', 'qty', 'Total Quantity', 'Add to Quantity'], 1)),
                    finish=get_val(row, ['Finish', 'foil', 'Printing'], 'Normal'),
                    location=get_val(row, ['Location', 'binder'], '')
                ))
                count += 1
            db.session.commit()
            flash(f'Imported {count} cards')
        except Exception as e:
            flash(f'Error: {e}')
    return redirect(url_for('admin'))

@app.route('/update_card/<int:id>', methods=['POST'])
@login_required
def update_card(id):
    card = Card.query.get_or_404(id)
    action = request.form.get('action')
    
    if action == 'sold_one':
        if card.quantity > 0: card.quantity -= 1
    elif action == 'delete':
        db.session.delete(card)
    elif action == 'update_details':
        try:
            card.price = float(request.form.get('price'))
            card.quantity = int(request.form.get('quantity'))
            card.condition = request.form.get('condition')
            card.location = request.form.get('location')
        except: flash("Invalid input")
        
    db.session.commit()
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)