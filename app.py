import os
import pandas as pd
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///inventory.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    cards = db.relationship('Card', backref='owner', lazy=True)
    settings = db.relationship('Settings', backref='owner', uselist=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id): return User.query.get(int(user_id))

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
    variant = db.Column(db.String(100))
    location = db.Column(db.String(100))
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context(): db.create_all()

def get_user_settings(user_id):
    settings = Settings.query.filter_by(user_id=user_id).first()
    if not settings:
        settings = Settings(user_id=user_id, show_prices=False)
        db.session.add(settings)
        db.session.commit()
    return settings

@app.route('/')
def index(): return render_template('landing.html', users=User.query.all())

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('admin'))
    if request.method == 'POST':
        if User.query.filter_by(username=request.form.get('username').lower()).first(): flash('Exists'); return redirect(url_for('register'))
        u = User(username=request.form.get('username').lower()); u.set_password(request.form.get('password'))
        db.session.add(u); db.session.commit(); login_user(u); return redirect(url_for('admin'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('admin'))
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form.get('username').lower()).first()
        if u and u.check_password(request.form.get('password')): login_user(u); return redirect(url_for('admin'))
        flash('Invalid')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile(): return render_template('profile.html', user=current_user)

@app.route('/u/<username>')
def user_storefront(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    return render_template('index.html', inventory=Card.query.filter_by(user_id=user.id, quantity=1).all(), show_prices=get_user_settings(user.id).show_prices, owner=user)

@app.route('/u/<username>/binder')
def user_binder(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    return render_template('binder.html', inventory=Card.query.filter_by(user_id=user.id, quantity=1).all(), show_prices=get_user_settings(user.id).show_prices, owner=user)

@app.route('/u/<username>/qr')
def user_qr(username): return render_template('qr.html', owner=User.query.filter_by(username=username.lower()).first_or_404())

@app.route('/trade')
def trade_tool(): return render_template('trade.html', users=User.query.all())

@app.route('/api/inventory/<username>')
def api_inventory(username):
    u = User.query.filter_by(username=username.lower()).first_or_404()
    return jsonify([{'id':c.id,'card_name':c.card_name,'set_name':c.set_name,'price':c.price,'quantity':c.quantity,'condition':c.condition,'finish':c.finish} for c in Card.query.filter_by(user_id=u.id, quantity=1).all()])

@app.route('/admin')
@login_required
def admin(): return render_template('admin.html', inventory=Card.query.filter_by(user_id=current_user.id).order_by(Card.id.desc()).all(), settings=get_user_settings(current_user.id))

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    s = get_user_settings(current_user.id); s.show_prices = request.form.get('show_prices') == 'on'; db.session.commit()
    return redirect(url_for('admin'))

@app.route('/add_card', methods=['POST'])
@login_required
def add_card():
    try:
        db.session.add(Card(user_id=current_user.id, game=request.form.get('game'), card_name=request.form.get('card_name'), set_name=request.form.get('set_name'), card_number=request.form.get('card_number'), condition=request.form.get('condition'), finish=request.form.get('finish'), price=float(request.form.get('price', 0.0)), quantity=int(request.form.get('quantity', 1))))
        db.session.commit(); flash('Added')
    except Exception as e: flash(str(e))
    return redirect(url_for('admin'))

@app.route('/paste_import', methods=['POST'])
@login_required
def paste_import():
    data = request.form.get('paste_data'); mode = request.form.get('game_mode')
    if not data: return redirect(url_for('admin'))
    count = 0
    for line in data.strip().split('\n'):
        if not line.strip(): continue
        try:
            if mode == 'magic':
                m = re.search(r'(\d+)x?\s+(.+?)\s+[\[\(]([A-Z0-9]{3,})[\]\)]\s*(\d+)?', line)
                if m: db.session.add(Card(user_id=current_user.id, game="Magic: The Gathering", card_name=m.group(2).strip(), set_name=m.group(3), card_number=m.group(4) or "", quantity=int(m.group(1)))); count+=1
            elif mode == 'pokemon':
                p = line.split()
                if len(p)>=3: 
                    q=1
                    if p[0].isdigit() or 'x' in p[0]: q=int(p[0].replace('x','')); p.pop(0)
                    db.session.add(Card(user_id=current_user.id, game="Pokemon TCG", card_name=" ".join(p[:-2]), set_name=p[-2], card_number=p[-1], quantity=q)); count+=1
        except: pass
    db.session.commit(); flash(f"Imported {count}"); return redirect(url_for('admin'))

@app.route('/upload_csv', methods=['POST'])
@login_required
def upload_csv():
    if 'file' not in request.files: return redirect(url_for('admin'))
    f = request.files['file']
    if f.filename == '': return redirect(url_for('admin'))
    try:
        df = pd.read_csv(f)
        for _, r in df.iterrows():
            def g(k,d): 
                for x in k: 
                    if x in r and pd.notna(r[x]): return r[x]
                return d
            db.session.add(Card(user_id=current_user.id, game=g(['Game','Category'],'TCGPlayer'), set_name=g(['Set','Expansion'],'Unknown'), card_name=g(['Name','Product Name'],'Unknown'), card_number=str(g(['Number','Card Number'],'')), condition=g(['Condition'],'NM'), price=float(g(['Price','Market Price'],0)), quantity=int(g(['Quantity','Qty','Add to Quantity'],1)), finish=g(['Finish'],'Normal')))
        db.session.commit(); flash('Imported')
    except Exception as e: flash(str(e))
    return redirect(url_for('admin'))

@app.route('/update_card/<int:id>', methods=['POST'])
@login_required
def update_card(id):
    c = Card.query.get_or_404(id)
    if c.user_id != current_user.id: return redirect(url_for('admin'))
    if request.form.get('action') == 'sold_one' and c.quantity > 0: c.quantity -= 1
    elif request.form.get('action') == 'delete': db.session.delete(c)
    elif request.form.get('action') == 'update_details':
        try: c.price = float(request.form.get('price')); c.quantity = int(request.form.get('quantity')); c.condition = request.form.get('condition')
        except: pass
    db.session.commit(); return redirect(url_for('admin'))

if __name__ == '__main__': app.run(host='0.0.0.0', port=5000)
