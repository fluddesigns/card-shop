import os
import pandas as pd
import re
import requests
import urllib3
import threading
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_session import Session
from flask_mail import Mail, Message
from sqlalchemy import text
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from functools import wraps

# Suppress InsecureRequestWarning for local dev if SSL certs are missing
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# --- Configuration ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
# Updated
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///inventory.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Super_Admin credentials are now set via environment variables for security
app.config['SUPER_ADMIN'] = os.environ.get('SUPER_ADMIN_USERNAME', 'flud').lower()

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

# Initialize the token generator using your app's secret key
token_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

mail = Mail(app)
db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(150), unique=True, nullable=False)
    # What actually shows up on screen (e.g. Poke Master 99)
    display_name = db.Column(db.String(150), nullable=True) 
    # New Security Columns
    email = db.Column(db.String(150), unique=True, nullable=False)
    is_verified = db.Column(db.Boolean, default=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # --- UPDATED RELATIONSHIP ---
    inventory_items = db.relationship('Inventory', backref='owner', lazy=True, cascade="all, delete-orphan")
    
    sales = db.relationship('Sale', backref='seller', lazy=True, cascade="all, delete-orphan")
    settings = db.relationship('StorefrontSettings', backref='owner', uselist=False, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def super_user_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # First check if they are logged in at all
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        # Then check if they possess the super user flag
        if not current_user.is_admin:
            flash("Unauthorized: Super User privileges required.", "error")
            return redirect(url_for('admin')) # Kick them back to their own dashboard
        return f(*args, **kwargs)
    return decorated_function

class StorefrontSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    show_prices = db.Column(db.Boolean, default=False)

class MasterTracker(db.Model):
    """Tracks the umbrella species you are hunting (e.g. 'Meowth') to group all wildcards."""
    id = db.Column(db.Integer, primary_key=True)
    species_name = db.Column(db.String(50), unique=True, nullable=False)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    card_name = db.Column(db.String(150), nullable=False)
    set_name = db.Column(db.String(100))
    sale_price = db.Column(db.Float, default=0.0)
    quantity = db.Column(db.Integer, default=1)
    sale_date = db.Column(db.DateTime, default=datetime.utcnow)

# --- New DB models ---
class ExpansionSet(db.Model):
    __tablename__ = 'expansion_sets'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    series = db.Column(db.String(100), nullable=False)
    set_code = db.Column(db.String(20), unique=True, nullable=False)
    release_date = db.Column(db.Date, nullable=True)
    total_cards = db.Column(db.Integer, nullable=True)
    
    # Relationship: One Set has many Master Cards
    cards = db.relationship('MasterCard', backref='expansion_set', lazy=True, cascade="all, delete-orphan")

class MasterCard(db.Model):
    __tablename__ = 'master_cards'
    
    id = db.Column(db.Integer, primary_key=True)
    set_id = db.Column(db.Integer, db.ForeignKey('expansion_sets.id'), nullable=False)
    
    name = db.Column(db.String(150), nullable=False)
    card_number = db.Column(db.String(20), nullable=False)
    rarity = db.Column(db.String(50), nullable=True)
    card_type = db.Column(db.String(50), nullable=True)
    variant_type = db.Column(db.String(50), nullable=True) # e.g., Normal, Reverse Holo, 1st Edition
    
    # API Links
    tcgplayer_id = db.Column(db.String(50), unique=True, nullable=True)
    pricecharting_id = db.Column(db.String(50), unique=True, nullable=True)
    
    # Ready for local hosting (e.g., 'img/cards/base1/4.webp')
    image_url = db.Column(db.String(255), nullable=True) 

    # Relationship: One Master Card has many Inventory Items
    inventory_items = db.relationship('Inventory', backref='master_card', lazy=True, cascade="all, delete-orphan")

class Inventory(db.Model):
    __tablename__ = 'inventory'
    
    id = db.Column(db.Integer, primary_key=True)
    master_card_id = db.Column(db.Integer, db.ForeignKey('master_cards.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # Links to your existing User model
    
    condition = db.Column(db.String(20), nullable=False, default='NM')
    grading_company = db.Column(db.String(20), nullable=True)
    grade_value = db.Column(db.Numeric(3, 1), nullable=True) # Numeric is perfect for precise grades like 9.5
    
    variant = db.Column(db.String(50), nullable=False, default='Normal')

    status = db.Column(db.String(30), nullable=False, default='personal_collection')
    
    # Financial tracking for the future POS
    acquired_price = db.Column(db.Numeric(10, 2), nullable=True)
    
    notes = db.Column(db.Text, nullable=True)
    date_added = db.Column(db.DateTime, default=db.func.current_timestamp())

# --- Startup & Migration Check ---
with app.app_context():
    db.create_all()
    
    super_admin_name = app.config.get('SUPER_ADMIN')
    admin_user = User.query.filter_by(username=super_admin_name).first()
    if admin_user and not admin_user.is_admin:
        admin_user.is_admin = True
        db.session.commit()

# --- Helper Functions ---

def get_user_settings(user_id):
    # Updated to query the new StorefrontSettings model
    settings = StorefrontSettings.query.filter_by(user_id=user_id).first()
    
    if not settings:
        settings = StorefrontSettings(user_id=user_id, show_prices=True)
        db.session.add(settings)
        db.session.commit()
        
    return settings

# --- Helper Functions CONT.---

def get_clean_finishes(tcgplayer_data):
    """Parses TCGPlayer pricing tiers to determine available card variants."""
    if not tcgplayer_data or 'prices' not in tcgplayer_data:
        return "Normal"
    
    raw_finishes = tcgplayer_data['prices'].keys()
    clean_finishes = []
    
    for f in raw_finishes:
        f_lower = f.lower()
        if f_lower == 'normal': 
            clean_finishes.append('Normal')
        elif f_lower == 'holofoil': 
            clean_finishes.append('Holo')
        elif f_lower == 'reverseholofoil': 
            clean_finishes.append('Reverse Holo')
        elif f_lower == '1steditionholofoil': 
            clean_finishes.append('1st Edition Holo')
        elif f_lower == '1steditionnormal' or f_lower == '1stedition': 
            clean_finishes.append('1st Edition')
        elif f_lower == 'unlimitedholofoil': 
            clean_finishes.append('Unlimited Holo')
        else: 
            # Fallback for unexpected finishes: split CamelCase
            cleaned = re.sub('([A-Z])', r' \1', f).strip().title()
            clean_finishes.append(cleaned)
            
    return ",".join(clean_finishes) if clean_finishes else "Normal"

# --- Routes ---

@app.route('/')
def index():
    users = User.query.all()
    return render_template('landing.html', users=users)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))

    if request.method == 'POST':
        # 1. Honeypot Bot Trap
        if request.form.get('hp_check'):
            flash("Registration failed.")
            return redirect(url_for('register'))

        email = request.form.get('email').lower().strip()
        username = request.form.get('username').lower().strip()
        display_name = request.form.get('display_name', username).strip()
        password = request.form.get('password')

        # 2. Availability Checks
        if User.query.filter_by(email=email).first():
            flash("Email is already registered.")
            return redirect(url_for('register'))
        
        if User.query.filter_by(username=username).first():
            flash("Username is already taken.")
            return redirect(url_for('register'))
        
        # 3. Create the Unverified User
        new_user = User(username=username, display_name=display_name, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        
        # 4. Generate Token & Send Email
        token = token_serializer.dumps(email, salt='email-verify')
        verify_url = url_for('verify_email', token=token, _external=True)
        
        msg = Message("Verify your Flud Media Account", recipients=[email])
        msg.body = f"Welcome to Flud Media TCG!\n\nPlease click the link below to verify your account and start managing your inventory:\n{verify_url}\n\nThis link will expire in 24 hours."
        mail.send(msg)
        
        flash("Registration successful! Please check your email to verify your account.")
        return redirect(url_for('login'))
        
    return render_template('register.html')

@app.route('/verify/<token>')
def verify_email(token):
    try:
        # Max age is in seconds (86400 = 24 hours)
        email = token_serializer.loads(token, salt='email-verify', max_age=86400)
    except SignatureExpired:
        flash("The verification link has expired. Please log in to request a new one.")
        return redirect(url_for('login'))
    except BadSignature:
        flash("Invalid verification link.")
        return redirect(url_for('login'))
        
    user = User.query.filter_by(email=email).first_or_404()
    if user.is_verified:
        flash("Account already verified. Please log in.")
    else:
        user.is_verified = True
        db.session.commit()
        flash("Email verified successfully! You can now access your Binder.")
        login_user(user) # Auto-login upon clicking the link
        return redirect(url_for('admin'))
        
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

            # --- NEW VERIFICATION LOCK ---
            if not user.is_verified:
                flash("Please check your email and verify your account before logging in.")
                return redirect(url_for('login'))
            # -----------------------------

            if user.username == app.config['SUPER_ADMIN'] and not user.is_admin:
                user.is_admin = True
                db.session.commit()
                
            login_user(user)
            return redirect(url_for('admin'))
            
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email').lower().strip()
        user = User.query.filter_by(email=email).first()
        
        if user:
            token = token_serializer.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
            
            msg = Message("Password Reset Request", recipients=[email])
            msg.body = f"Click the link below to reset your password:\n{reset_url}\n\nIf you did not request this, please ignore this email. This link expires in 30 minutes."
            mail.send(msg)
            
        # Silent Failure: Always return this message so attackers can't fish for emails
        flash("If an account with that email exists, a reset link has been sent to your inbox.")
        return redirect(url_for('login'))
        
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        # Max age is in seconds (1800 = 30 minutes)
        email = token_serializer.loads(token, salt='password-reset', max_age=1800)
    except (SignatureExpired, BadSignature):
        flash("The password reset link is invalid or has expired.")
        return redirect(url_for('forgot_password'))
        
    if request.method == 'POST':
        user = User.query.filter_by(email=email).first_or_404()
        user.set_password(request.form.get('password'))
        db.session.commit()
        
        flash("Your password has been successfully updated! You may now log in.")
        return redirect(url_for('login'))
        
    return render_template('reset_password.html', token=token)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/admin/link_orphans', methods=['POST'])
@login_required
def link_orphans():
    # Find all Pokemon cards in your inventory that aren't linked to the dictionary
    orphans = Card.query.filter_by(user_id=current_user.id, reference_id=None, game='Pokemon TCG').all()
    count = 0
    
    for card in orphans:
        ref_match = None
        
        # 1. Normalize the data (The "Straggler Hunter" fix)
        # Converts "5/62" -> "5", and strips trailing spaces
        clean_num = str(card.card_number).split('/')[0].strip() if card.card_number else None
        clean_name = card.card_name.strip()
        clean_set = card.set_name.strip()

        # 2. Strict Number Match (but case-insensitive for names/sets)
        if clean_num:
            ref_match = CardReference.query.filter(
                CardReference.name.ilike(clean_name),
                CardReference.set_name.ilike(f"%{clean_set}%"),
                CardReference.number == clean_num
            ).first()
            
        # 3. Fallback to just Name + Set if Number still fails
        if not ref_match:
            ref_match = CardReference.query.filter(
                CardReference.name.ilike(clean_name),
                CardReference.set_name.ilike(f"%{clean_set}%")
            ).first()
        
        # 4. Link it!
        if ref_match:
            card.reference_id = ref_match.id
            count += 1
            
    db.session.commit()
    flash(f"🔗 Successfully linked {count} orphaned cards to the Pokedex!")
    return redirect(url_for('admin'))

# --- PUBLIC STOREFRONTS ---

@app.route('/u/<username>')
def user_storefront(username):
    user = User.query.filter_by(username=username).first_or_404()
    settings = StorefrontSettings.query.filter_by(user_id=user.id).first()
    
    # Fetch only items marked for Sales, ordered by highest price first
    inventory = Inventory.query.join(MasterCard).filter(
        Inventory.user_id == user.id,
        Inventory.status == 'Sales'
    ).order_by(Inventory.acquired_price.desc()).all()
    
    return render_template('storefront.html', user=user, inventory=inventory, settings=settings)

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

# --- AUTOCOMPLETE & SYNC ---

@app.route('/api/search_reference')
@login_required
def search_reference():
    query = request.args.get('q', '').lower().strip()
    if len(query) < 2: return jsonify([])
    
    terms = query.split()
    filters = []
    
    for term in terms:
        filters.append(
            db.or_(
                MasterCard.name.ilike(f'%{term}%'),
                ExpansionSet.name.ilike(f'%{term}%')
            )
        )
    
    # We join ExpansionSet so we can search/sort by set data!
    results = MasterCard.query.join(ExpansionSet).filter(db.and_(*filters)).order_by(ExpansionSet.release_date.desc()).limit(20).all()
    
    data = []
    for card in results:
        data.append({
            'id': card.id,
            'name': card.name,
            'set': card.expansion_set.name,
            'number': card.card_number,
            'image': card.image_url,
            'label': f"{card.name} ({card.expansion_set.name}) #{card.card_number}"
        })
    return jsonify(data)

def run_full_sync(app_context):
    """Background worker to handle pagination without timing out the web browser."""
    with app_context:
        api_url = "https://api.pokemontcg.io/v2/cards"
        page = 1
        has_more = True
        
        print("--- STARTING BACKGROUND API SYNC ---", flush=True)
        
        while has_more:
            params = {'pageSize': 250, 'page': page} 
            headers = {'User-Agent': 'FludInventory/1.0', 'Accept': 'application/json'}
            
            try:
                r = requests.get(api_url, params=params, headers=headers, timeout=30, verify=False)
                
                if r.status_code != 200:
                    print(f"API Error on page {page}: {r.status_code}. Stopping sync.", flush=True)
                    break
                    
                data = r.json()
                cards = data.get('data', [])
                
                # If the page is empty, we've reached the end of the database
                if not cards:
                    has_more = False
                    break
                    
                for item in cards:
                    try:
                        # --- 1. HANDLE THE EXPANSION SET ---
                        api_set = item.get('set', {})
                        set_api_id = api_set.get('id') 
                        
                        if not set_api_id: continue
                        
                        db_set = ExpansionSet.query.filter_by(set_code=set_api_id).first()
                        
                        if not db_set:
                            rel_date_str = api_set.get('releaseDate')
                            parsed_date = None
                            if rel_date_str:
                                try:
                                    parsed_date = datetime.strptime(rel_date_str, '%Y/%m/%d').date()
                                except ValueError:
                                    parsed_date = None
                            
                            db_set = ExpansionSet(
                                name=api_set.get('name', 'Unknown'),
                                series=api_set.get('series', 'Unknown'),
                                set_code=set_api_id, 
                                release_date=parsed_date,
                                total_cards=api_set.get('printedTotal')
                            )
                            db.session.add(db_set)
                            db.session.flush() 

                        # --- 2. HANDLE THE MASTER CARD ---
                        c_name = item.get('name', 'Unknown')
                        c_number = item.get('number', '')
                        
                        db_card = MasterCard.query.filter_by(
                            set_id=db_set.id, 
                            card_number=c_number, 
                            name=c_name
                        ).first()
                        
                        if not db_card:
                            images = item.get('images', {})
                            db_card = MasterCard(
                                set_id=db_set.id,
                                name=c_name,
                                card_number=c_number,
                                rarity=item.get('rarity'),
                                card_type=item.get('supertype'),
                                variant_type=get_clean_finishes(item.get('tcgplayer')),
                                image_url=images.get('small') 
                            )
                            db.session.add(db_card)
                            
                    except Exception as e:
                        print(f"Crash on card {item.get('id')}: {str(e)}", flush=True)
                        continue
                
                # Commit at the end of every page. If it crashes on page 50, we keep the first 49!
                db.session.commit()
                print(f"Successfully synced Page {page} ({len(cards)} cards).", flush=True)
                
                # If we get less than 250 cards, it means we hit the very last page
                if len(cards) < 250:
                    has_more = False
                else:
                    page += 1
                    
            except Exception as e:
                print(f"Background Sync Crashed on page {page}: {str(e)}", flush=True)
                db.session.rollback()
                break
                
        print("--- BACKGROUND SYNC COMPLETE ---", flush=True)


@app.route('/admin/sync_db', methods=['POST'])
@super_user_required
def sync_db():
    if not current_user.is_admin:
        return redirect(url_for('admin'))
        
    # Grab the active database context and pass it to a new background thread
    app_context = app.app_context()
    thread = threading.Thread(target=run_full_sync, args=(app_context,))
    thread.start()
    
    flash("🔄 Master Database Sync started in the background! It will take several minutes to pull all 15,000+ cards. Refresh the page periodically to see the cache count go up.")
    return redirect(url_for('admin'))

@app.route('/api/pos_search')
@login_required
def pos_search():
    try:
        query = request.args.get('q', '').lower().strip()
        if len(query) < 2: 
            return jsonify({'inventory': [], 'dictionary': []})
        
        terms = query.split()
        
        # 1. Search User's Inventory
        inv_filters = [Card.user_id == current_user.id, Card.quantity > 0]
        for term in terms:
            inv_filters.append(db.or_(Card.card_name.ilike(f'%{term}%'), Card.set_name.ilike(f'%{term}%')))
        
        inv_results = Card.query.filter(db.and_(*inv_filters)).limit(30).all()
        
        grouped_inv = {}
        for c in inv_results:
            # SAFEGUARDS: Prevent Null values from crashing the loop
            c_name = c.card_name or "Unknown"
            c_set = c.set_name or "Unknown"
            c_finish = c.finish or "Normal"
            c_qty = c.quantity or 0
            c_price = c.price or 0.0
            c_cond = c.condition or "NM"
            
            key = f"{c_name}_{c_set}_{c_finish}"
            if key not in grouped_inv:
                grouped_inv[key] = {
                    'name': c_name,
                    'set': c_set,
                    'number': c.card_number or "",
                    'finish': c_finish,
                    'image': c.image_url or "",
                    'total_qty': 0,
                    'variants': []
                }
            
            grouped_inv[key]['total_qty'] += c_qty
            
            cond_str = c_cond
            if c.grading_company and c.grade:
                cond_str = f"{c.grading_company} {c.grade}"
                
            grouped_inv[key]['variants'].append({
                'id': c.id,
                'condition': cond_str,
                'price': float(c_price),
                'qty': c_qty
            })
            
        inv_data = list(grouped_inv.values())
        
        # 2. Search Master Dictionary
        dict_filters = []
        for term in terms:
            dict_filters.append(db.or_(CardReference.name.ilike(f'%{term}%'), CardReference.set_name.ilike(f'%{term}%')))
            
        dict_results = CardReference.query.filter(db.and_(*dict_filters)).order_by(CardReference.release_date.desc()).limit(15).all()
        dict_data = [{
            'id': r.id,
            'name': r.name or "Unknown",
            'set': r.set_name or "Unknown",
            'number': r.number or "",
            'image': r.image_url or ""
        } for r in dict_results]
        
        return jsonify({'inventory': inv_data, 'dictionary': dict_data})
        
    except Exception as e:
        # If it crashes, log it and return empty data so the UI doesn't freeze
        print(f"POS Search Crash: {str(e)}")
        return jsonify({'inventory': [], 'dictionary': []})

@app.route('/admin/update_price/<int:card_id>', methods=['POST'])
@login_required
def update_single_price(card_id):
    """
    STRICT MODE PRICE FETCHER
    - If Card Number is provided: Uses Strict Name + Number match. (Gold Standard)
    - If No Number: Uses Name + Strict Set Name match.
    - If ambiguous: FAILS safely.
    """
    card = Card.query.get_or_404(card_id)
    if card.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        clean_name = re.sub(r'[^\w\s]', '', card.card_name.split('(')[0]).strip()
        
        # 1. BUILD STRICT QUERY
        # Using exact match operator (!) from PokemonTCG API
        query_parts = [f'name:"{clean_name}"']
        
        # Priority: CARD NUMBER
        if card.card_number and card.card_number.strip():
            query_parts.append(f'number:"{card.card_number}"')
        
        query = " ".join(query_parts)
        
        api_url = "https://api.pokemontcg.io/v2/cards"
        params = {'q': query, 'pageSize': 10} 
        headers = {'User-Agent': 'FludInventory/1.0', 'Accept': 'application/json'}
        
        r = requests.get(api_url, params=params, headers=headers, timeout=15, verify=False)
        data = r.json()
        
        match = None
        candidates = data.get('data', [])
        
        # 2. FILTER CANDIDATES
        valid_matches = []
        user_set_clean = (card.set_name or "").lower().replace('set', '').strip()
        
        for cand in candidates:
            # If we queried by number, we trust the result heavily
            if card.card_number:
                valid_matches.append(cand)
            else:
                # If no number, we MUST match set name reasonably well
                api_set = cand['set']['name'].lower().replace('set', '').strip()
                if user_set_clean == api_set:
                     valid_matches.append(cand)
                # Allow strict containment if unambiguous (e.g. User: "Evolutions", API: "XY - Evolutions")
                elif user_set_clean in api_set and len(user_set_clean) > 4:
                     valid_matches.append(cand)

        if len(valid_matches) == 1:
            match = valid_matches[0]
        elif len(valid_matches) > 1:
            return jsonify({'success': False, 'error': f'Ambiguous: Found {len(valid_matches)} matches (e.g. {valid_matches[0]["set"]["name"]}). Add Card Number for precision.'})
        else:
             return jsonify({'success': False, 'error': f'No exact match found for Name="{clean_name}" Set="{card.set_name}" Number="{card.card_number}"'})

        # --- Pricing Logic ---
        new_price = 0.0
        
        def get_price(prices_obj, price_type):
            if prices_obj and price_type in prices_obj and prices_obj[price_type]:
                return prices_obj[price_type].get('market', 0.0) or prices_obj[price_type].get('mid', 0.0)
            return 0.0

        if 'tcgplayer' in match and 'prices' in match['tcgplayer']:
            prices = match['tcgplayer']['prices']
            finish_lower = (card.finish or 'normal').lower()
            
            # Strict Finish Matching
            if 'reverse' in finish_lower:
                new_price = get_price(prices, 'reverseHolofoil')
            elif 'holo' in finish_lower or 'foil' in finish_lower:
                new_price = get_price(prices, 'holofoil')
            elif '1st' in finish_lower:
                new_price = get_price(prices, '1stEditionHolofoil') or get_price(prices, '1stEdition')
            
            # Fallback to Normal ONLY if finish wasn't specified as something else
            if new_price == 0.0 and ('normal' in finish_lower or not card.finish):
                new_price = get_price(prices, 'normal')
            
            # Absolute Last Resort: If the card exists but we missed the specific finish pricing,
            # DO NOT UPDATE. (Prevent updating a Holo price with a Normal price)
            if new_price == 0.0:
                 return jsonify({'success': False, 'error': f'Card found, but no price for finish "{card.finish}". Available: {list(prices.keys())}'})

        if new_price > 0:
            card.price = new_price
            card.last_updated = datetime.utcnow()
            # Update image if missing
            if not card.image_url and 'images' in match:
                card.image_url = match['images']['small']
            
            db.session.commit()
            return jsonify({
                'success': True, 
                'new_price': new_price, 
                'message': f'Updated to ${new_price:.2f}'
            })
        else:
            return jsonify({'success': False, 'error': 'No market price available.'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

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
    
    # Fetch inventory, ordered by newest added
    inventory = Inventory.query.filter_by(user_id=current_user.id).order_by(Inventory.date_added.desc()).all()
    
    # Count total unique master cards instead of the old CardReference
    cache_count = MasterCard.query.count()
    
    return render_template('admin.html', inventory=inventory, settings=settings, cache_count=cache_count)

@app.route('/sales')
@login_required
def sales():
    sales_history = Sale.query.filter_by(user_id=current_user.id).order_by(Sale.sale_date.desc()).all()
    total_revenue = sum(s.sale_price for s in sales_history)
    return render_template('sales.html', sales=sales_history, total=total_revenue)

@app.route('/super_admin')
@super_user_required
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
    if user_to_delete.username == app.config['SUPER_ADMIN']:
        flash("Cannot delete the Super Admin account!")
        return redirect(url_for('super_admin'))
        
    db.session.delete(user_to_delete)
    db.session.commit()
    flash(f"User {user_to_delete.username} deleted.")
    return redirect(url_for('super_admin'))

@app.route('/admin/update_settings', methods=['POST'])
@login_required
def update_settings():
    if not current_user.is_admin:
        return redirect(url_for('admin'))

    settings = StorefrontSettings.query.filter_by(user_id=current_user.id).first()
    
    # If the user doesn't have a settings row yet, create one
    if not settings:
        settings = StorefrontSettings(user_id=current_user.id)
        db.session.add(settings)

    # HTML Checkboxes only send data in the form if they are checked
    settings.show_prices = 'show_prices' in request.form

    db.session.commit()
    flash("✅ Storefront settings updated.")
    return redirect(url_for('admin'))

@app.route('/add_card', methods=['POST'])
@login_required
def add_card():
    try:
        is_graded = request.form.get('is_graded') == 'on'
        grading_company = request.form.get('grading_company') if is_graded else None
        
        # Convert empty grade string to None, or parse to float if possible
        grade_raw = request.form.get('grade')
        grade_val = None
        if is_graded and grade_raw and grade_raw.strip() != '':
            try:
                grade_val = float(grade_raw)
            except ValueError:
                grade_val = None

        # Safely parse empty strings into numbers
        price_raw = request.form.get('price')
        price_val = float(price_raw) if price_raw and price_raw.strip() != '' else 0.0
        
        card_name = request.form.get('card_name')
        set_name = request.form.get('set_name')
        card_number = request.form.get('card_number')
        
        # --- THE RELATIONAL FIX ---
        # We must find the MasterCard to link the physical inventory item to.
        # We use a join to match both the card name and the expansion set name.
        master_match = MasterCard.query.join(ExpansionSet).filter(
            MasterCard.name.ilike(card_name),
            ExpansionSet.name.ilike(set_name),
            MasterCard.card_number == card_number
        ).first()

        if not master_match:
            # Fallback: If no card number was provided, try a looser match just by name and set
            master_match = MasterCard.query.join(ExpansionSet).filter(
                MasterCard.name.ilike(card_name),
                ExpansionSet.name.ilike(set_name)
            ).first()

        if not master_match:
            # Enforce the relational structure: It MUST exist in the Master DB first.
            flash(f"Error: Could not find '{card_name}' from '{set_name}' in the Master Database. Please sync it from the API first.", "error")
            return redirect(url_for('admin'))

        # Strict Scenario A: If quantity > 1, loop to insert individual rows
        qty_raw = request.form.get('quantity')
        qty_val = int(qty_raw) if qty_raw and qty_raw.strip() != '' else 1

        for _ in range(qty_val):
            new_item = Inventory(
                master_card_id=master_match.id,
                user_id=current_user.id,
                condition=request.form.get('condition', 'NM'),
                grading_company=grading_company,
                grade_value=grade_val,
                variant=request.form.get('finish', 'Normal'),
                status=request.form.get('status', 'personal_collection'),
                acquired_price=price_val,
                notes=f"Cert: {request.form.get('cert_number')}" if is_graded and request.form.get('cert_number') else None
            )
            db.session.add(new_item)
            
        db.session.commit()
        flash(f'Successfully added {qty_val}x {master_match.name} to your inventory.')
        
    except Exception as e:
        db.session.rollback()
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

                ref_match = None
                # 1. Try a strict match including Card Number first (Gold Standard)
                if num_val:
                    ref_match = CardReference.query.filter_by(name=name_val, set_name=set_val, number=num_val).first()
                # 2. Fallback to just Name + Set if Number is missing
                if not ref_match:
                    ref_match = CardReference.query.filter_by(name=name_val, set_name=set_val).first()
                
                ref_id = ref_match.id if ref_match else None

                db.session.add(Card(
                    user_id=current_user.id,
                    reference_id=ref_id, # <-- INJECTED HERE
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
            # Updated to query Inventory
            item = Inventory.query.get(int(c_id))
            if item and item.user_id == current_user.id:
                if action == 'delete':
                    db.session.delete(item)
                    count += 1
                elif action == 'sell':
                    # New schema handles prices via acquired_price and quantity is always 1 per row
                    base_price = item.acquired_price or 0.0
                    final_price = float(base_price) * multiplier
                    
                    sale = Sale(
                        user_id=current_user.id,
                        card_name=item.master_card.name,
                        set_name=item.master_card.expansion_set.name,
                        sale_price=final_price,
                        quantity=1 
                    )
                    db.session.add(sale)
                    db.session.delete(item) # Remove the physical item from inventory
                    count += 1

        db.session.commit()
        
        if action == 'delete':
            flash(f"Deleted {count} cards.")
        elif action == 'sell':
            msg = f"Sold {count} cards."
            if discount_pct > 0: msg += f" Applied {discount_pct}% discount."
            flash(msg)
            
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {str(e)}")

    return redirect(url_for('admin'))

@app.route('/update_card/<int:id>', methods=['POST'])
@login_required
def update_card(id):
    item = Inventory.query.get_or_404(id)
    
    if item.user_id != current_user.id:
        if request.is_json:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        flash("Unauthorized")
        return redirect(url_for('admin'))

    # Support both standard form data and JSON payloads
    action = request.form.get('action') or request.json.get('action')
    
    if action == 'delete':
        db.session.delete(item)
        db.session.commit()
        
        if request.is_json:
            return jsonify({'success': True, 'action': 'delete', 'id': id})
            
        flash(f"Deleted {item.master_card.name} from inventory.")
        
    elif action == 'update_details':
        try:
            new_price = request.form.get('price') or request.json.get('price')
            new_cond = request.form.get('condition') or request.json.get('condition')
            
            item.acquired_price = float(new_price)
            item.condition = new_cond
            db.session.commit()
            
            if request.is_json:
                return jsonify({
                    'success': True, 
                    'action': 'update', 
                    'id': id,
                    'price': float(item.acquired_price), 
                    'condition': item.condition
                })
                
            flash("Card details updated.")
        except Exception as e: 
            if request.is_json:
                return jsonify({'success': False, 'error': 'Invalid input for price.'}), 400
            flash("Invalid input for price.")
        
    return redirect(url_for('admin'))

# --- POKEDEX & HUNT MODE ---

@app.route('/pokedex')
@login_required
def pokedex_hub():
    trackers = MasterTracker.query.all()
    stats = []
    
    for t in trackers:
        species = t.species_name
        # Find all Master Cards that belong to this species
        master_cards = MasterCard.query.filter(MasterCard.name.ilike(f"%{species}%")).all()
        
        total_slots = 0
        owned_count = 0
        
        if master_cards:
            master_ids = [m.id for m in master_cards]

            # Fetch all owned inventory for this species at once for speed
            owned_inventory = Inventory.query.filter(
                Inventory.user_id == current_user.id,
                Inventory.master_card_id.in_(master_ids)
            ).all()

            # Create a fast lookup dictionary: { master_card_id: set_of_lowercase_finishes }
            owned_dict = {}
            for item in owned_inventory:
                if item.master_card_id not in owned_dict:
                    owned_dict[item.master_card_id] = set()
                owned_dict[item.master_card_id].add(item.variant.lower().strip())
        
            for ref in master_cards:
                # Variant types are stored as a comma-separated string (e.g., "Normal,Reverse Holofoil")
                finishes = [f.strip() for f in ref.variant_type.split(',')] if ref.variant_type else ["Normal"]
                
                for f in finishes:
                    total_slots += 1 
                    
                    # Check if the user owns THIS specific variant
                    if ref.id in owned_dict and f.lower() in owned_dict[ref.id]:
                        owned_count += 1
        
        pct = int((owned_count / total_slots) * 100) if total_slots > 0 else 0
        stats.append({'name': species, 'total': total_slots, 'owned': owned_count, 'percent': pct})
        
    return render_template('pokedex.html', stats=stats)

@app.route('/pokedex/<species>')
@login_required
def pokedex_binder(species):
    # 1. Fetch all Master Cards for the requested species, ordered by newest set
    master_cards = MasterCard.query.join(ExpansionSet).filter(
        MasterCard.name.ilike(f"%{species}%")
    ).order_by(ExpansionSet.release_date.desc()).all()

    if not master_cards:
        flash(f"No cards found for {species} in the Master Database yet.")
        return redirect(url_for('pokedex_hub'))

    # 2. Find which of these specific Master Cards the user actually owns
    master_ids = [c.id for c in master_cards]
    owned_inventory = Inventory.query.filter(
        Inventory.user_id == current_user.id,
        Inventory.master_card_id.in_(master_ids)
    ).all()

    # 3. Group the user's owned inventory by MasterCard ID for the UI to easily read
    # We store the 'variant' (Normal, Reverse Holo, etc.) so the UI knows what finishes you have
    owned_dict = {}
    for item in owned_inventory:
        if item.master_card_id not in owned_dict:
            owned_dict[item.master_card_id] = []
        
        finish_clean = item.variant.lower().strip()
        if finish_clean not in owned_dict[item.master_card_id]:
            owned_dict[item.master_card_id].append(finish_clean)

    return render_template('pokedex_binder.html', 
                           species=species.title(), 
                           master_cards=master_cards, 
                           owned_dict=owned_dict)

@app.route('/api/toggle_favorite', methods=['POST'])
@login_required
def toggle_favorite():
    species_name = request.form.get('species_name').strip().title()
    if not species_name:
        return redirect(url_for('pokedex_hub'))
        
    existing = MasterTracker.query.filter_by(species_name=species_name).first()
    
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash(f"Removed {species_name} from Master Sets.")
    else:
        new_tracker = MasterTracker(species_name=species_name)
        db.session.add(new_tracker)
        db.session.commit()
        flash(f"Added {species_name} umbrella to Master Sets. Tracking all variants!")
        
    return redirect(url_for('pokedex_hub'))

@app.route('/api/quick_capture', methods=['POST'])
@login_required
def quick_capture():
    master_id = request.form.get('master_id')
    finish = request.form.get('finish', 'Normal')
    
    master = MasterCard.query.get_or_404(master_id)
    
    # Generate the physical inventory row
    new_item = Inventory(
        master_card_id=master.id,
        user_id=current_user.id,
        condition='NM',              # Default for a quick capture
        variant=finish,
        status='personal_collection',
        acquired_price=0.0
    )
    db.session.add(new_item)
    db.session.commit()
    
    # If called via AJAX (which we will setup later for a smoother UI)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': f'Captured {finish}'})
    
    flash(f"🎉 Captured {master.name} ({finish}) into your Binder!")
    return redirect(request.referrer or url_for('pokedex_hub'))

@app.route('/api/force_variant', methods=['POST'])
@login_required
def force_variant():
    # 🔒 SECURITY CHECK: Kick out non-admins immediately
    if not current_user.is_admin:
        flash("Unauthorized access.")
        return redirect(url_for('admin'))

    api_id = request.form.get('api_id')
    new_finish = request.form.get('new_finish')
    
    if not api_id or not new_finish:
        flash("Missing ID or Finish.")
        return redirect(url_for('admin'))

    # Parse the API ID (e.g., "neo4-6" -> set_code="neo4", card_number="6")
    parts = api_id.strip().rsplit('-', 1)
    if len(parts) != 2:
        flash("Invalid API ID format. Use format like 'neo4-6'")
        return redirect(url_for('admin'))

    set_code, card_number = parts[0], parts[1]

    # Look up the card using our relational join
    master_card = MasterCard.query.join(ExpansionSet).filter(
        ExpansionSet.set_code == set_code,
        MasterCard.card_number == card_number
    ).first()

    if master_card and new_finish:
        current_finishes = master_card.variant_type.split(',') if master_card.variant_type else []
        current_finishes = [f.strip() for f in current_finishes]
        
        if new_finish not in current_finishes:
            current_finishes.append(new_finish)
            master_card.variant_type = ",".join(current_finishes)
            db.session.commit()
            flash(f"✅ Successfully forced '{new_finish}' variant onto {master_card.name}!")
        else:
            flash(f"⚠️ {master_card.name} already has {new_finish} tracked.")
    else:
        flash(f"❌ Could not find card '{api_id}' in the database. Try a Manual API Inject first.")
            
    return redirect(url_for('admin'))

@app.route('/api/force_api_fetch', methods=['POST'])
@super_user_required
def force_api_fetch():
    # 🔒 SECURITY CHECK: Kick out non-admins immediately
    if not current_user.is_admin:
        flash("Unauthorized access.")
        return redirect(url_for('admin'))

    api_id = request.form.get('api_id')
    if not api_id:
        return redirect(url_for('admin'))
    
    api_id = api_id.strip()

    url = f"https://api.pokemontcg.io/v2/cards/{api_id}"
    headers = {'User-Agent': 'FludInventory/1.0', 'Accept': 'application/json'}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            api_data = response.json().get('data', {})
            
            # --- 1. HANDLE THE EXPANSION SET ---
            api_set = api_data.get('set', {})
            set_api_id = api_set.get('id')
            
            if not set_api_id:
                flash(f"❌ API data missing set info for ID: {api_id}")
                return redirect(url_for('admin'))
                
            db_set = ExpansionSet.query.filter_by(set_code=set_api_id).first()
            
            if not db_set:
                rel_date_str = api_set.get('releaseDate')
                parsed_date = None
                if rel_date_str:
                    try:
                        parsed_date = datetime.strptime(rel_date_str, '%Y/%m/%d').date()
                    except ValueError:
                        parsed_date = None
                
                db_set = ExpansionSet(
                    name=api_set.get('name', 'Unknown'),
                    series=api_set.get('series', 'Unknown'),
                    set_code=set_api_id, 
                    release_date=parsed_date,
                    total_cards=api_set.get('printedTotal')
                )
                db.session.add(db_set)
                db.session.flush() # Generate the Set ID immediately

            # --- 2. HANDLE THE MASTER CARD ---
            c_name = api_data.get('name', 'Unknown')
            c_number = api_data.get('number', '')
            
            db_card = MasterCard.query.filter_by(
                set_id=db_set.id, 
                card_number=c_number, 
                name=c_name
            ).first()
            
            if db_card:
                flash(f"ℹ️ {c_name} ({api_id}) already exists in your Master Database.")
            else:
                images = api_data.get('images', {})
                db_card = MasterCard(
                    set_id=db_set.id,
                    name=c_name,
                    card_number=c_number,
                    rarity=api_data.get('rarity'),
                    card_type=api_data.get('supertype'),
                    variant_type=get_clean_finishes(api_data.get('tcgplayer')),
                    image_url=images.get('small') 
                )
                db.session.add(db_card)
                db.session.commit()
                flash(f"✅ Successfully injected {c_name} ({api_id}) into your Pokedex!")
                
        else:
            flash(f"❌ API could not find a card with ID: {api_id}")
            
    except Exception as e:
        db.session.rollback()
        flash(f"❌ Error fetching card: {str(e)}")
        
    return redirect(url_for('admin'))

@app.route('/hunt/<species>')
@login_required
def hunt_mode(species):
    # THE FIX: Wildcard search for Hunt Mode
    master_cards = CardReference.query.filter(
        CardReference.name.ilike(f"%{species}%")
    ).order_by(CardReference.release_date.asc()).all()

    ref_ids = [c.id for c in master_cards]
    owned_cards = Card.query.filter(
        Card.user_id == current_user.id,
        Card.reference_id.in_(ref_ids)
    ).all()

    owned_dict = {}
    for oc in owned_cards:
        if oc.reference_id not in owned_dict:
            owned_dict[oc.reference_id] = []
        owned_dict[oc.reference_id].append(oc.finish.lower())

    hunt_targets = []
    for ref in master_cards:
        if not ref.available_finishes:
            continue
            
        available = [f.strip() for f in ref.available_finishes.split(',')]
        owned = owned_dict.get(ref.id, [])
        missing = [f for f in available if f.lower() not in owned]
        
        if missing:
            hunt_targets.append({
                'ref': ref,
                'missing_finishes': missing
            })

    return render_template('hunt_mode.html', species=species.capitalize(), targets=hunt_targets)

@app.route('/api/check-email', methods=['POST'])
def check_email():
    email = request.form.get('email', '').lower().strip()
    # Ensure they've typed at least part of an email
    if not email or '@' not in email: 
        return '<div class="form-text small mt-1">We\'ll send a secure verification link.</div>'
    
    if User.query.filter_by(email=email).first():
        return '<div class="form-text small mt-1 text-danger fw-bold"><i class="bi bi-x-circle me-1"></i>Email is already registered.</div>'
    
    return '<div class="form-text small mt-1 text-success fw-bold"><i class="bi bi-check-circle me-1"></i>Email is available!</div>'
    
@app.route('/api/check-username', methods=['POST'])
def check_username():
    username = request.form.get('username', '').lower().strip()
    if len(username) < 3: 
        return '<div class="form-text small mt-1">Your public URL. No spaces.</div>'
        
    if User.query.filter_by(username=username).first():
        return '<div class="form-text small mt-1 text-danger fw-bold"><i class="bi bi-x-circle me-1"></i>Profile ID is taken.</div>'
        
    return '<div class="form-text small mt-1 text-success fw-bold"><i class="bi bi-check-circle me-1"></i>Profile ID is available!</div>'

@app.route('/pos')
@login_required
def point_of_sale():
    # Initialize a fresh POS cart in the session
    if 'pos_cart' not in session:
        session['pos_cart'] = {'in': [], 'out': [], 'net': 0.0}
    return render_template('pos.html')

@app.route('/api/pos/action', methods=['POST'])
@login_required
def pos_action():
    """Handles all rapid AJAX requests for the POS."""
    if 'pos_cart' not in session:
        session['pos_cart'] = {'in': [], 'out': [], 'net': 0.0}
        
    action = request.json.get('action')
    data = request.json.get('data', {})
    
    # Calculate current net (Out - In)
    def update_net():
        total_out = sum(item['price'] for item in session['pos_cart']['out'])
        total_in = sum(item['price'] for item in session['pos_cart']['in'])
        session['pos_cart']['net'] = total_out - total_in

    if action == 'add_out':
        # Selling a card from inventory
        session['pos_cart']['out'].append({
            'id': data.get('id'), 
            'name': data.get('name'), 
            'price': float(data.get('price', 0))
        })
    elif action == 'add_in':
        # Taking a card/item in on trade
        base_price = float(data.get('price', 0))
        multiplier = float(data.get('multiplier', 1.0))
        final_credit = base_price * multiplier
        
        session['pos_cart']['in'].append({
            'name': data.get('name'), 
            'price': final_credit,
            'base_price': base_price,
            'multiplier': multiplier
        })
    elif action == 'clear':
        session['pos_cart'] = {'in': [], 'out': [], 'net': 0.0}
        
    update_net()
    session.modified = True
    
    return jsonify({
        'status': 'success',
        'cart': session['pos_cart']
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)