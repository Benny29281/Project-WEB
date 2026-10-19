# Project Web Scraping

Aplikasi Flask untuk memantau stok produk dari halaman HTTPS pada domain yang memang diizinkan untuk dipantau.

Dashboard menampilkan toko asal, status stok, dan harga yang berhasil dibaca. Daftar dapat difilter per toko dan diurutkan berdasarkan harga, dengan grafik 8 harga terendah dari hasil yang sedang ditampilkan. Harga diambil dari data terstruktur halaman serta pola umum kartu WooCommerce/Shopify; hasilnya bergantung pada markup setiap toko. Produk yang sudah tersimpan sebelumnya baru memiliki harga setelah pengecekan ulang. Saat aplikasi startup, kolom harga ditambahkan otomatis ke database lama bila belum tersedia.

Dashboard memakai sidebar Bootstrap yang menyesuaikan layar ponsel dan tablet. Bagian perbandingan menampilkan harga produk bernama sama dari toko berbeda, dan memilih harga terendah yang masih tersedia bila ada. Nama produk dicocokkan setelah huruf besar/kecil dan tanda baca dinormalisasi; produk yang judul tokonya berbeda mungkin tidak tergabung. Notifikasi dalam aplikasi dicatat saat pengecekan menemukan perubahan status stok atau harga. Notifikasi pertama kali muncul setelah ada data sebelumnya untuk dibandingkan; tidak ada email atau push notification.

## Setup (PowerShell)

Jalankan perintah dari folder `Project-Web-Scraping`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:SECRET_KEY = (py -c "import secrets; print(secrets.token_hex(32))")
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "ganti-dengan-password-kuat"
$env:SCRAPE_ALLOWED_HOSTS = "fujishop.id"
py app.py
```

Saat pertama dijalankan, aplikasi membuat tabel dan akun admin dari `ADMIN_USERNAME` serta `ADMIN_PASSWORD`. Akun bawaan dengan password tetap tidak dibuat. SQLite digunakan secara default; untuk MySQL, atur `DATABASE_URL`, misalnya `mysql+pymysql://user:password@localhost/project_web`.

Atur `SCRAPE_ALLOWED_HOSTS` sebagai daftar domain dipisahkan koma, contohnya `fujishop.id,toko.example`. Hanya HTTPS dan host yang tercantum persis yang diterima. Pastikan kamu memiliki izin untuk memantau situs tersebut. Scraper memakai User-Agent yang mengidentifikasi aplikasi, tidak mengikuti redirect, dan memberi jeda antar target. Gunakan API resmi jika tersedia dan patuhi ketentuan situs.

Untuk deployment HTTPS, set `$env:COOKIE_SECURE = "1"`. `SECRET_KEY`, password admin, dan database URL jangan dimasukkan ke source control.

Scheduler otomatis aktif saat aplikasi dijalankan dengan `py app.py`. Jalankan hanya satu instance aplikasi dengan scheduler ini; untuk deployment multi-worker, pindahkan scheduler ke proses terpisah agar tugas tidak berjalan ganda. Server bawaan Flask hanya untuk pengembangan lokal.
