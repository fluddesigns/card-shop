# --- 1. BACKEND LOGIC (app.py) ---
$app_code = @"
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
    return render_template('index.html', inventory=Card.query.filter_by(user_id=user.id).filter(Card.quantity > 0).all(), show_prices=get_user_settings(user.id).show_prices, owner=user)

@app.route('/u/<username>/binder')
def user_binder(username):
    user = User.query.filter_by(username=username.lower()).first_or_404()
    return render_template('binder.html', inventory=Card.query.filter_by(user_id=user.id).filter(Card.quantity > 0).all(), show_prices=get_user_settings(user.id).show_prices, owner=user)

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
            db.session.add(Card(user_id=current_user.id, game=g(['Game','Category'],'TCGPlayer Import'), set_name=g(['Set','Expansion'],'Unknown'), card_name=g(['Name','Product Name'],'Unknown'), card_number=str(g(['Number','Card Number'],'')), condition=g(['Condition'],'NM'), price=float(g(['Price','Market Price'],0)), quantity=int(g(['Quantity','Qty','Add to Quantity'],1)), finish=g(['Finish'],'Normal')))
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
"@
Set-Content -Path app.py -Value $app_code -Encoding UTF8

# --- 2. TEMPLATES ---

$base = @"
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{% block title %}Card Market{% endblock %}</title><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><link href="https://cdn.datatables.net/1.13.4/css/dataTables.bootstrap5.min.css" rel="stylesheet"><link href="https://cdn.datatables.net/responsive/2.4.1/css/responsive.bootstrap5.min.css" rel="stylesheet"><style>.pokeball-logo{width:36px;height:36px;background:radial-gradient(white 33%,black 33% 40%,transparent 40%),linear-gradient(to bottom,#e3350d 46%,black 46% 54%,white 54%);border:2px solid black;border-radius:50%;display:inline-block}.navbar-custom{background-color:#343a40}.nav-link{color:rgba(255,255,255,0.8)}.nav-link:hover{color:white}body{background-color:#f8f9fa}{% block styles %}{% endblock %}</style></head><body><nav class="navbar navbar-expand navbar-custom sticky-top navbar-dark"><div class="container-fluid"><a class="navbar-brand d-flex align-items-center" href="{{ url_for('index') }}"><div class="pokeball-logo me-2"></div>Home</a><button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#n"><span class="navbar-toggler-icon"></span></button><div class="collapse navbar-collapse" id="n"><ul class="navbar-nav ms-auto align-items-center">{% if current_user.is_authenticated %}<li class="nav-item dropdown me-2"><a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">☰ Menu</a><ul class="dropdown-menu dropdown-menu-end shadow"><li><a class="dropdown-item" href="{{ url_for('admin') }}">Admin</a></li><li><a class="dropdown-item" href="{{ url_for('trade_tool') }}">Trade</a></li><li><hr class="dropdown-divider"></li><li><a class="dropdown-item" href="{{ url_for('user_storefront', username=current_user.username) }}">Storefront</a></li><li><a class="dropdown-item" href="{{ url_for('user_qr', username=current_user.username) }}">QR Code</a></li><li><hr class="dropdown-divider"></li><li><a class="dropdown-item text-danger" href="{{ url_for('logout') }}">Logout</a></li></ul></li><li class="nav-item"><a class="nav-link" href="{{ url_for('profile') }}"><div class="rounded-circle bg-secondary text-white d-flex align-items-center justify-content-center" style="width:32px;height:32px">{{ current_user.username[0]|upper }}</div></a></li>{% else %}<li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li><li class="nav-item"><a class="btn btn-primary btn-sm ms-2" href="{{ url_for('register') }}">Join</a></li>{% endif %}</ul></div></div></nav>{% block content %}{% endblock %}<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>{% block scripts %}{% endblock %}</body></html>
"@
Set-Content -Path templates/base.html -Value $base -Encoding UTF8

$index = @"
{% extends "base.html" %}{% block title %}Store - {{ owner.username }}{% endblock %}{% block styles %}<style>.shop-header{background:linear-gradient(135deg,#1e3c72 0%,#2a5298 100%);color:white;padding:2rem 1rem;text-align:center;border-radius:0 0 15px 15px;margin-bottom:2rem}.binder-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:15px}.card-slot{border:none;border-radius:10px;overflow:hidden;background:#2c3e50;position:relative;aspect-ratio:2.5/3.5;transition:transform 0.2s;cursor:pointer}.card-slot:hover{transform:translateY(-5px);z-index:10}.card-image{width:100%;height:100%;object-fit:contain;position:relative;z-index:1;transition:opacity 0.3s}.skeleton-loader{width:100%;height:100%;background:linear-gradient(90deg,#34495e 25%,#2c3e50 50%,#34495e 75%);background-size:200% 100%;animation:loading 1.5s infinite;position:absolute;top:0;left:0;z-index:2}@keyframes loading{0%{background-position:200% 0}100%{background-position:-200% 0}}.price-badge{position:absolute;top:8px;right:8px;background:#27ae60;color:white;padding:2px 6px;border-radius:4px;font-size:0.8rem;font-weight:bold;z-index:5}.info-overlay{position:absolute;bottom:0;left:0;width:100%;background:rgba(0,0,0,0.85);color:white;padding:5px;font-size:0.75rem;text-align:center;z-index:5}</style>{% endblock %}{% block content %}<div class="shop-header text-center"><h1 class="fw-bold">{{ owner.username|capitalize }}'s Collection</h1></div><div class="container-fluid px-3"><div class="d-flex justify-content-between mb-3"><div class="btn-group"><input type="radio" class="btn-check" name="v" id="g" checked onchange="t('grid')"><label class="btn btn-sm btn-outline-primary" for="g">Grid</label><input type="radio" class="btn-check" name="v" id="l" onchange="t('list')"><label class="btn btn-sm btn-outline-primary" for="l">List</label></div></div><div id="vg" class="binder-grid">{% for c in inventory %}<div class="card-slot card-item" data-game="{{ c.game }}" data-name="{{ c.card_name }}" data-set="{{ c.set_name }}">{% if show_prices %}<div class="price-badge">${{ "%.2f"|format(c.price) }}</div>{% endif %}<div class="skeleton-loader"></div><img class="card-image d-none" alt="{{ c.card_name }}" loading="lazy"><div class="info-overlay"><div class="text-truncate fw-bold">{{ c.card_name }}</div><div class="opacity-75">{{ c.set_name }}</div></div></div>{% endfor %}</div><div id="vl" class="d-none"><div class="card shadow-sm"><div class="card-body p-0"><table id="tab" class="table table-striped w-100"><thead><tr><th>Name</th><th>Set</th><th>Game</th><th>Cond</th>{% if show_prices %}<th>Price</th>{% endif %}<th>Qty</th></tr></thead><tbody>{% for c in inventory %}<tr><td class="fw-bold">{{ c.card_name }}</td><td>{{ c.set_name }}</td><td>{{ c.game }}</td><td>{{ c.condition }}</td>{% if show_prices %}<td class="text-success fw-bold">${{ "%.2f"|format(c.price) }}</td>{% endif %}<td>{{ c.quantity }}</td></tr>{% endfor %}</tbody></table></div></div></div></div>{% endblock %}{% block scripts %}<script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script><script src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap5.min.js"></script><script>function t(m){if(m==='grid'){$('#vg').removeClass('d-none');$('#vl').addClass('d-none')}else{$('#vg').addClass('d-none');$('#vl').removeClass('d-none')}}$(document).ready(function(){$('#tab').DataTable({responsive:true,pageLength:50})});document.addEventListener("DOMContentLoaded",function(){const q=Array.from(document.querySelectorAll('.card-slot'));proc();function proc(){if(q.length===0)return;const c=q.shift();fetchImg(c).finally(()=>setTimeout(proc,150))}async function fetchImg(c){const g=(c.dataset.game||"").toLowerCase(),n=c.dataset.name,s=(c.dataset.set||"").trim(),i=c.querySelector('img'),l=c.querySelector('.skeleton-loader');try{if(g.includes('magic')||g.includes('mtg')){let u=`https://api.scryfall.com/cards/search?q=name:"${encodeURIComponent(n)}"`;if(s)u+=`+set:"${encodeURIComponent(s)}"`;let r=await fetch(u);if(!r.ok)r=await fetch(`https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(n)}`);if(!r.ok)throw new Error();const d=await r.json(),t=d.data&&d.data.length>0?d.data[0]:d;if(t.image_uris)load(i,l,t.image_uris.normal);else if(t.card_faces)load(i,l,t.card_faces[0].image_uris.normal);else throw new Error()}else if(g.includes('pokemon')){const cn=n.split('(')[0].trim();let u=`https://api.pokemontcg.io/v2/cards?q=name:"${encodeURIComponent(cn)}"`;if(s)u+=` set.name:"${encodeURIComponent(s)}"`;let r=await fetch(u),d=await r.json();if(!d.data||d.data.length===0){r=await fetch(`https://api.pokemontcg.io/v2/cards?q=name:"${encodeURIComponent(cn)}"`);d=await r.json()}if(d.data&&d.data.length>0)load(i,l,d.data[0].images.small);else throw new Error()}else throw new Error()}catch{fb(i,l,g)}}function load(i,l,s){i.src=s;i.onload=()=>{l.classList.add('d-none');i.classList.remove('d-none')};i.onerror=()=>fb(i,l,'default')}function fb(i,l,g){let s="https://upload.wikimedia.org/wikipedia/en/a/aa/Magic_the_gathering-card_back.jpg";if(g.includes('pokemon'))s="https://tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg";i.src=s;i.style.opacity="0.3";l.classList.add('d-none');i.classList.remove('d-none')}});</script>{% endblock %}
"@
Set-Content -Path templates/index.html -Value $index -Encoding UTF8

$binder = @"
{% extends "base.html" %}{% block title %}{{ owner.username }}'s Binder{% endblock %}{% block styles %}<style>.binder-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:15px;padding:15px}.card-slot{border-radius:10px;overflow:hidden;background:#2c3e50;position:relative;aspect-ratio:2.5/3.5;transition:transform 0.2s;box-shadow:0 4px 6px rgba(0,0,0,0.3)}.card-slot:hover{transform:translateY(-5px);z-index:10}.card-image{width:100%;height:100%;object-fit:contain;position:relative;z-index:1;transition:opacity 0.3s}.skeleton-loader{width:100%;height:100%;background:linear-gradient(90deg,#34495e 25%,#2c3e50 50%,#34495e 75%);background-size:200% 100%;animation:loading 1.5s infinite;position:absolute;top:0;left:0;z-index:2}@keyframes loading{0%{background-position:200% 0}100%{background-position:-200% 0}}.price-badge{position:absolute;top:8px;right:8px;background:#27ae60;color:white;padding:2px 6px;border-radius:4px;font-size:0.8rem;font-weight:bold;z-index:5}.info-overlay{position:absolute;bottom:0;left:0;width:100%;background:rgba(0,0,0,0.85);color:white;padding:5px;font-size:0.75rem;text-align:center;z-index:5}</style>{% endblock %}{% block content %}<div class="container-fluid p-0"><nav class="navbar navbar-dark bg-dark mb-0 shadow-sm sticky-top"><div class="container-fluid"><span class="navbar-brand h1 mb-0">{{ owner.username }}'s Binder</span><div><a href="{{ url_for('user_storefront', username=owner.username) }}" class="btn btn-sm btn-outline-light">List View</a></div></div></nav><div class="binder-grid">{% for c in inventory %}<div class="card-slot" data-game="{{ c.game }}" data-name="{{ c.card_name }}" data-set="{{ c.set_name }}">{% if show_prices %}<div class="price-badge">${{ "%.2f"|format(c.price) }}</div>{% endif %}<div class="skeleton-loader"></div><img class="card-image d-none" alt="{{ c.card_name }}" loading="lazy"><div class="info-overlay"><div class="text-truncate fw-bold">{{ c.card_name }}</div><div class="opacity-75">{{ c.set_name }}</div></div></div>{% endfor %}</div></div>{% endblock %}{% block scripts %}<script>document.addEventListener("DOMContentLoaded",function(){const q=Array.from(document.querySelectorAll('.card-slot'));proc();function proc(){if(q.length===0)return;const c=q.shift();fetchImg(c).finally(()=>setTimeout(proc,150))}async function fetchImg(c){const g=(c.dataset.game||"").toLowerCase(),n=c.dataset.name,s=(c.dataset.set||"").trim(),i=c.querySelector('img'),l=c.querySelector('.skeleton-loader');try{if(g.includes('magic')||g.includes('mtg')){let u=`https://api.scryfall.com/cards/search?q=name:"${encodeURIComponent(n)}"`;if(s)u+=`+set:"${encodeURIComponent(s)}"`;let r=await fetch(u);if(!r.ok)r=await fetch(`https://api.scryfall.com/cards/named?fuzzy=${encodeURIComponent(n)}`);if(!r.ok)throw new Error();const d=await r.json(),t=d.data&&d.data.length>0?d.data[0]:d;if(t.image_uris)load(i,l,t.image_uris.normal);else if(t.card_faces)load(i,l,t.card_faces[0].image_uris.normal);else throw new Error()}else if(g.includes('pokemon')){const cn=n.split('(')[0].trim();let u=`https://api.pokemontcg.io/v2/cards?q=name:"${encodeURIComponent(cn)}"`;if(s)u+=` set.name:"${encodeURIComponent(s)}"`;let r=await fetch(u),d=await r.json();if(!d.data||d.data.length===0){r=await fetch(`https://api.pokemontcg.io/v2/cards?q=name:"${encodeURIComponent(cn)}"`);d=await r.json()}if(d.data&&d.data.length>0)load(i,l,d.data[0].images.small);else throw new Error()}else throw new Error()}catch{fb(i,l,g)}}function load(i,l,s){i.src=s;i.onload=()=>{l.classList.add('d-none');i.classList.remove('d-none')};i.onerror=()=>fb(i,l,'default')}function fb(i,l,g){let s="https://upload.wikimedia.org/wikipedia/en/a/aa/Magic_the_gathering-card_back.jpg";if(g.includes('pokemon'))s="https://tcg.pokemon.com/assets/img/global/tcg-card-back-2x.jpg";i.src=s;i.style.opacity="0.3";l.classList.add('d-none');i.classList.remove('d-none')}});</script>{% endblock %}
"@
Set-Content -Path templates/binder.html -Value $binder -Encoding UTF8

$admin = @"
{% extends "base.html" %}{% block title %}Admin{% endblock %}{% block content %}<div class="container-fluid mt-3">{% with m=get_flashed_messages() %}{% if m %}<div class="alert alert-warning p-2">{{ m[0] }}</div>{% endif %}{% endwith %}<div class="row g-3 mb-3"><div class="col-md-3"><div class="card h-100"><div class="card-header bg-dark text-white py-2">Config</div><div class="card-body py-2"><form action="{{ url_for('update_settings') }}" method="POST"><div class="form-check form-switch"><input class="form-check-input" type="checkbox" name="show_prices" {% if settings.show_prices %}checked{% endif %}><label class="form-check-label small">Public Prices</label></div><button type="submit" class="btn btn-sm btn-outline-dark mt-2 w-100">Save</button></form></div></div></div><div class="col-md-4"><div class="card h-100 border-primary"><div class="card-header bg-primary text-white py-2">Quick Add</div><div class="card-body py-2"><form action="{{ url_for('add_card') }}" method="POST"><div class="input-group input-group-sm mb-2"><select name="game" class="form-select" style="max-width:30%"><option>Magic: The Gathering</option><option>Pokemon TCG</option></select><input type="text" name="card_name" class="form-control" placeholder="Card Name" required></div><div class="input-group input-group-sm mb-2"><input type="text" name="set_name" class="form-control" placeholder="Set" required><input type="number" name="price" class="form-control" placeholder="$0.00" step="0.01"></div><button class="btn btn-primary btn-sm w-100">Add Single Card</button></form></div></div></div><div class="col-md-5"><div class="card h-100"><div class="card-header bg-secondary text-white py-2"><ul class="nav nav-tabs card-header-tabs" id="tabs" role="tablist"><li class="nav-item"><button class="nav-link active text-dark p-1 px-3" data-bs-toggle="tab" data-bs-target="#paste">Paste</button></li><li class="nav-item"><button class="nav-link text-dark p-1 px-3" data-bs-toggle="tab" data-bs-target="#csv">CSV</button></li></ul></div><div class="card-body py-2"><div class="tab-content"><div class="tab-pane fade show active" id="paste"><form action="{{ url_for('paste_import') }}" method="POST"><textarea name="paste_data" class="form-control form-control-sm mb-1" rows="2" placeholder="1 Sol Ring [CMM] 415"></textarea><select name="game_mode" class="form-select form-select-sm mb-1"><option value="magic">Magic</option><option value="pokemon">Pokemon</option></select><button class="btn btn-secondary btn-sm w-100">Import Text</button></form></div><div class="tab-pane fade" id="csv"><form action="{{ url_for('upload_csv') }}" method="post" enctype="multipart/form-data"><input class="form-control form-control-sm mb-2" type="file" name="file" accept=".csv" required><button class="btn btn-outline-secondary btn-sm w-100">Upload File</button></form></div></div></div></div></div></div><div class="card"><div class="card-body p-0"><table id="admTable" class="table table-striped table-bordered dt-responsive nowrap w-100"><thead><tr><th>Name</th><th>Set</th><th>$$</th><th>Qty</th><th>Act</th></tr></thead><tbody>{% for c in inventory %}<tr><td>{{ c.card_name }} <small class="text-muted">{{ c.game }}</small></td><td>{{ c.set_name }}</td><form action="{{ url_for('update_card', id=c.id) }}" method="POST"><td><input type="number" step="0.01" name="price" value="{{ c.price }}" class="form-control form-control-sm" style="width:70px"></td><td><input type="number" name="quantity" value="{{ c.quantity }}" class="form-control form-control-sm" style="width:50px"></td><td><button type="submit" name="action" value="update_details" class="btn btn-success btn-sm p-0 px-1">💾</button><button type="submit" name="action" value="delete" class="btn btn-danger btn-sm p-0 px-1" onclick="return confirm('Delete?')">✕</button></td></form></tr>{% endfor %}</tbody></table></div></div></div>{% endblock %}{% block scripts %}<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script><script src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script><script src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap5.min.js"></script><script>$(document).ready(function(){ $('#admTable').DataTable({responsive:true, order:[[0,'desc']]}); });</script>{% endblock %}
"@
Set-Content -Path templates/admin.html -Value $admin -Encoding UTF8

$landing = @"
{% extends "base.html" %}{% block title %}Local Market{% endblock %}{% block content %}<div class="container py-5 text-center"><h1 class="display-4 fw-bold">Local Card Market</h1><p class="lead text-muted mb-5">Trade locally.</p><div class="row g-4 justify-content-center">{% for user in users %}<div class="col-md-4 col-sm-6"><div class="card h-100 shadow-sm border-0"><div class="card-body"><h3 class="text-primary">{{ user.username|capitalize }}</h3><div class="d-grid gap-2 mt-3"><a href="{{ url_for('user_storefront', username=user.username) }}" class="btn btn-outline-dark">Browse</a><a href="{{ url_for('user_binder', username=user.username) }}" class="btn btn-outline-secondary">Binder</a></div></div></div></div>{% else %}<div class="col-12 text-muted">No traders yet.</div>{% endfor %}</div><div class="mt-5"><a href="{{ url_for('trade_tool') }}" class="btn btn-success btn-lg">⚖️ Trade Calculator</a></div></div>{% endblock %}
"@
Set-Content -Path templates/landing.html -Value $landing -Encoding UTF8

$reg = @"
{% extends "base.html" %}{% block title %}Register{% endblock %}{% block content %}<div class="container mt-5" style="max-width:400px"><div class="card shadow"><div class="card-body p-4"><h4 class="text-center mb-3">Create Account</h4>{% with m=get_flashed_messages() %}{% if m %}<div class="alert alert-warning">{{ m[0] }}</div>{% endif %}{% endwith %}<form method="POST"><div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required autofocus></div><div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div><div class="d-grid"><button type="submit" class="btn btn-success">Register</button></div><div class="text-center mt-3"><a href="{{ url_for('login') }}" class="small">Already have an account?</a></div></form></div></div></div>{% endblock %}
"@
Set-Content -Path templates/register.html -Value $reg -Encoding UTF8

$log = @"
{% extends "base.html" %}{% block title %}Login{% endblock %}{% block content %}<div class="container mt-5" style="max-width:400px"><div class="card shadow"><div class="card-body p-4"><h4 class="text-center mb-3">Login</h4>{% with m=get_flashed_messages() %}{% if m %}<div class="alert alert-danger">{{ m[0] }}</div>{% endif %}{% endwith %}<form method="POST"><div class="mb-3"><label class="form-label">Username</label><input type="text" name="username" class="form-control" required autofocus></div><div class="mb-3"><label class="form-label">Password</label><input type="password" name="password" class="form-control" required></div><div class="d-grid gap-2"><button type="submit" class="btn btn-primary">Login</button><a href="{{ url_for('register') }}" class="btn btn-outline-secondary btn-sm">Create Account</a></div></form></div></div></div>{% endblock %}
"@
Set-Content -Path templates/login.html -Value $log -Encoding UTF8

$prof = @"
{% extends "base.html" %}{% block title %}Profile{% endblock %}{% block content %}<div class="container py-5 text-center"><div class="card shadow" style="max-width:500px;margin:auto"><div class="card-body"><h2 class="mb-4">{{ user.username|capitalize }}</h2><div class="d-grid gap-3"><a href="{{ url_for('admin') }}" class="btn btn-outline-primary">Admin Panel</a><a href="{{ url_for('user_storefront', username=user.username) }}" class="btn btn-outline-success">My Public Store</a><a href="{{ url_for('user_qr', username=user.username) }}" class="btn btn-outline-dark">Print QR Code</a></div></div></div></div>{% endblock %}
"@
Set-Content -Path templates/profile.html -Value $prof -Encoding UTF8

$trade = @"
<!DOCTYPE html><html lang="en"><head><title>Trade</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><style>body{background:#f0f2f5;height:100vh;overflow:hidden;display:flex;flex-direction:column}.trade-container{flex:1;display:flex}.trade-side{flex:1;display:flex;flex-direction:column;padding:10px;border-right:1px solid #dee2e6}.inventory-list{flex:1;overflow-y:auto;background:white;border:1px solid #ced4da;margin-bottom:10px}.cart-list{height:30%;overflow-y:auto;background:#e9ecef;border:1px solid #ced4da;padding:5px}.item-row{padding:5px;border-bottom:1px solid #eee;cursor:pointer;display:flex;justify-content:space-between}.item-row:hover{background:#f8f9fa}.diff-bar{text-align:center;padding:10px;font-weight:bold;background:#fff3cd;color:#856404}</style></head><body><nav class="navbar navbar-dark bg-dark px-3"><span class="navbar-brand mb-0 h1">⚖️ Trade</span><a href="{{ url_for('index') }}" class="btn btn-sm btn-outline-light">Exit</a></nav><div class="diff-bar" id="diffDisplay">Diff: $0.00</div><div class="trade-container"><div class="trade-side"><select class="form-select mb-2" id="userSelect1" onchange="loadInventory(1)"><option value="">Trader A...</option>{% for user in users %}<option value="{{ user.username }}">{{ user.username }}</option>{% endfor %}</select><div class="inventory-list" id="invList1"></div><div class="cart-list" id="cart1"></div><div class="text-center fw-bold" id="total1">$0.00</div></div><div class="trade-side" style="border-right:none"><select class="form-select mb-2" id="userSelect2" onchange="loadInventory(2)"><option value="">Trader B...</option>{% for user in users %}<option value="{{ user.username }}">{{ user.username }}</option>{% endfor %}</select><div class="inventory-list" id="invList2"></div><div class="cart-list" id="cart2"></div><div class="text-center fw-bold" id="total2">$0.00</div></div></div><script>let invs={1:[],2:[]},carts={1:[],2:[]};async function loadInventory(s){const u=document.getElementById(`userSelect${s}`).value;if(!u)return;const r=await fetch(`/api/inventory/${u}`);invs[s]=await r.json();renderInv(s)}function renderInv(s){document.getElementById(`invList${s}`).innerHTML=invs[s].map(c=>`<div class="item-row" onclick="add(${s},${c.id})"><span>${c.card_name}</span><span>$${c.price}</span></div>`).join('')}function add(s,id){const c=invs[s].find(x=>x.id===id);carts[s].push(c);renderCart(s);update()}function renderCart(s){document.getElementById(`cart${s}`).innerHTML=carts[s].map((c,i)=>`<div class="item-row" onclick="rem(${s},${i})"><span>${c.card_name}</span><span>$${c.price}</span></div>`).join('')}function rem(s,i){carts[s].splice(i,1);renderCart(s);update()}function update(){const t1=carts[1].reduce((a,b)=>a+b.price,0),t2=carts[2].reduce((a,b)=>a+b.price,0);document.getElementById('total1').innerText='$'+t1.toFixed(2);document.getElementById('total2').innerText='$'+t2.toFixed(2);document.getElementById('diffDisplay').innerText=`Diff: $${(t1-t2).toFixed(2)}`}</script></body></html>
"@
Set-Content -Path templates/trade.html -Value $trade -Encoding UTF8

$qr = @"
<!DOCTYPE html><html lang="en"><head><title>QR</title><meta name="viewport" content="width=device-width, initial-scale=1.0"><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"><script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script><style>body{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh}</style></head><body><h3>{{ owner.username }}</h3><div id="qrcode" class="my-4"></div><script>new QRCode(document.getElementById("qrcode"),{text:window.location.origin+"{{ url_for('user_storefront', username=owner.username) }}",width:200,height:200});</script></body></html>
"@
Set-Content -Path templates/qr.html -Value $qr -Encoding UTF8

Write-Host "All files updated to SaaS version."