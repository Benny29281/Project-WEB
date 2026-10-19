from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime

app = Flask(__name__)
# Kunci rahasia untuk keamanan sesi (session) browser
app.config['SECRET_KEY'] = 'rahasia123'  # Ganti dengan kunci rahasia yang lebih aman di produksi
# Konfigurasi database SQLite (akan otomatis membuat file database.db)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # Arahkan ke halaman login jika belum masuk

# ==========================================
# 1. MODEL DATABASE (Tabel)
# ==========================================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(255))

class ProdukTarget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(255), default="Belum dicek")
    url = db.Column(db.String(500), unique=True)
    status_stok = db.Column(db.String(50), default="Menunggu Pengecekan")
    terakhir_dicek = db.Column(db.String(50), default="-")

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==========================================
# 2. LOGIKA SCRAPING AMAN & UPDATE DATABASE
# ==========================================
def jalankan_pengecekan_stok():
    with app.app_context(): # Wajib agar background task bisa akses database
        target_list = ProdukTarget.query.all()
        if not target_list:
            return

        waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{waktu_sekarang}] Memulai pengecekan {len(target_list)} URL target...")

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"}

        for target in target_list:
            try:
                response = requests.get(target.url, headers=headers, timeout=10)
                if response.status_code == 200:
                    # Logika pengecekan sederhana (Nanti disesuaikan dengan HTML Fujishop)
                    teks_halaman = response.text.lower()
                    if "out of stock" in teks_halaman or "habis" in teks_halaman:
                        target.status_stok = "HABIS"
                    else:
                        target.status_stok = "TERSEDIA"
                    
                    target.terakhir_dicek = waktu_sekarang
                    db.session.commit()
                    print(f"Update: {target.url} -> {target.status_stok}")
            except Exception as e:
                print(f"Error pada {target.url}: {e}")
            
            time.sleep(5) # Jeda aman 5 detik per URL

# Menjalankan scheduler setiap 30 menit
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(jalankan_pengecekan_stok, 'interval', minutes=30)
scheduler.start()

# ==========================================
# 3. RUTE WEBSITE (Halaman Web)
# ==========================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Username atau Password salah!')
            
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST':
        url_baru = request.form.get('url_produk')
        # Cek apakah URL sudah ada
        if ProdukTarget.query.filter_by(url=url_baru).first():
            flash('URL tersebut sudah ada dalam daftar pantauan.')
        else:
            produk_baru = ProdukTarget(url=url_baru)
            db.session.add(produk_baru)
            db.session.commit()
            flash('URL berhasil ditambahkan!')
            
    daftar_produk = ProdukTarget.query.all()
    return render_template('dashboard.html', produk_list=daftar_produk)

# ==========================================
# 4. INISIALISASI DATABASE & SERVER
# ==========================================
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Buat file database otomatis
        
        # Buat akun Admin jika belum ada
        if not User.query.filter_by(username='admin').first():
            hashed_password = generate_password_hash('admin123', method='pbkdf2:sha256')
            admin_user = User(username='admin', password=hashed_password)
            db.session.add(admin_user)
            db.session.commit()
            print("Akun admin berhasil dibuat (Username: admin | Password: admin123)")

    app.run(debug=True, use_reloader=False)