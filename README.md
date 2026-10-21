# Project Web Scraping

Dashboard diperbarui di latar belakang setiap 60 detik tanpa memuat ulang seluruh halaman; kata kunci dan filter yang sedang dipakai dipertahankan.

Aplikasi Flask untuk memantau stok produk dari halaman HTTPS pada domain yang memang diizinkan untuk dipantau.

Dashboard menampilkan toko asal, status stok, dan harga yang berhasil dibaca. Daftar dapat difilter per toko dan diurutkan berdasarkan harga, dengan grafik 8 harga terendah dari hasil yang sedang ditampilkan. Harga diambil dari data terstruktur halaman serta pola umum kartu WooCommerce/Shopify; hasilnya bergantung pada markup setiap toko. Produk yang sudah tersimpan sebelumnya baru memiliki harga setelah pengecekan ulang. Saat aplikasi startup, kolom harga ditambahkan otomatis ke database lama bila belum tersedia.

Dashboard memakai sidebar Bootstrap yang menyesuaikan layar ponsel dan tablet. Bagian perbandingan menampilkan harga produk bernama sama dari toko berbeda, dan memilih harga terendah yang masih tersedia bila ada. Nama produk dicocokkan setelah huruf besar/kecil dan tanda baca dinormalisasi; produk yang judul tokonya berbeda mungkin tidak tergabung. Notifikasi dalam aplikasi dicatat saat pengecekan menemukan perubahan status stok atau harga. Jika email dikonfigurasi, aplikasi mengirim email saat produk yang sudah pernah dipantau berubah menjadi tersedia, atau berubah dari tersedia menjadi habis. Produk baru tidak langsung memicu email agar setup awal tidak membanjiri kotak masuk.

Pencarian kata kunci bekerja pada katalog produk yang sudah dikumpulkan dari URL toko yang ditambahkan, bukan pencarian menyeluruh di semua marketplace. Parser mengenali format umum dan tautan produk Blibli (`/p/`); toko dengan markup khusus mungkin perlu parser atau API resmi. Halaman kategori TA Kamera menggunakan pola URL kategori WooCommerce yang dicakup parser umum, tetapi hasilnya tetap perlu diperiksa karena markup tiap toko dapat berbeda. Tokopedia kini diizinkan sebagai target, tetapi halaman pencariannya belum memiliki parser khusus dan dapat memuat data melalui JavaScript; produk, harga, dan stok mungkin tidak terbaca atau tidak lengkap. Halaman kategori Focus Nusantara yang diuji juga memuat produk melalui JavaScript, sehingga parser HTML biasa mungkin tidak mendapat katalog dari URL tersebut. Status stok yang tidak memiliki indikator jelas ditampilkan sebagai "Tidak diketahui" dan tidak dianggap tersedia; cocokkan data penting dengan halaman toko. Pengecekan otomatis berjalan setiap 30 menit saat proses aplikasi aktif.

Dashboard menyembunyikan ringkasan, grafik, daftar, perbandingan, dan notifikasi produk sampai kata kunci dimasukkan. Form pencarian dan pengelolaan URL toko tetap tersedia. Hasil produk, ringkasan stok, grafik, perbandingan, dan notifikasi kemudian difilter mengikuti kata kunci tersebut.

## Setup (PowerShell)

Jalankan perintah dari folder `Project-Web-Scraping`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "ganti-dengan-password-kuat"
$env:SCRAPE_ALLOWED_HOSTS = "instaxshop.co.id,www.instaxshop.co.id,jpckemang.com,www.jpckemang.com,fujishop.id,www.fujishop.id,galaxy.co.id,www.galaxy.co.id,doss.co.id,www.doss.co.id,focusnusantara.com,www.focusnusantara.com,blibli.com,www.blibli.com,plazakamera.com,www.plazakamera.com,tokopedia.com,www.tokopedia.com,taskamera.id,www.taskamera.id,shop.anekafoto.com,camera.co.id,www.camera.co.id,hopmarket.id,www.hopmarket.id,winstore.co.id,www.winstore.co.id,sinarphoto.com,www.sinarphoto.com,borneodigital.co.id,www.borneodigital.co.id"
py app.py
```

Saat pertama dijalankan, aplikasi membuat tabel dan akun admin dari `ADMIN_USERNAME` serta `ADMIN_PASSWORD`. Akun bawaan dengan password tetap tidak dibuat. Jika `SECRET_KEY` kosong, aplikasi membuat kunci sesi lokal di `instance/.session_secret` agar sesi login tetap konsisten setelah server direstart; folder `instance/` diabaikan Git. Jika mengatur `SECRET_KEY` sendiri di `.env` atau environment, gunakan nilai yang sama setiap kali aplikasi dijalankan. SQLite digunakan secara default; untuk MySQL, atur `DATABASE_URL`, misalnya `mysql+pymysql://user:password@localhost/project_web`.

Atur `SCRAPE_ALLOWED_HOSTS` sebagai daftar domain dipisahkan koma. Default mengizinkan Instaxshop, JPC Kemang, Fujishop, Galaxy, DOSS, Focus Nusantara, Blibli, Plaza Kamera, Tokopedia, TA Kamera, Aneka Foto (`shop.anekafoto.com`), Camera.co.id, Hop Market, Winstore, Sinar Photo, dan Borneo Digital. Hanya HTTPS dan host yang tercantum persis yang diterima. Scraper memakai User-Agent yang mengidentifikasi aplikasi, tidak mengikuti redirect, dan memberi jeda antar target. Gunakan API resmi jika tersedia dan patuhi ketentuan situs; scraper tidak mencoba melewati proteksi anti-bot.

## Notifikasi stok melalui email

1. Dari folder `Project-Web-Scraping`, salin `.env.example` ke `.env`: gunakan `Copy-Item .env.example .env` di PowerShell atau `cp .env.example .env` di Git Bash.
2. Isi `MAIL_USERNAME` dengan akun pengirim, `MAIL_PASSWORD` dengan kata sandi SMTP, `MAIL_DEFAULT_SENDER` dengan alamat pengirim, dan `STOCK_ALERT_EMAIL` dengan alamat penerima. Untuk Gmail, App Password memerlukan Verifikasi 2 Langkah dan tidak tersedia untuk semua jenis akun. Gunakan App Password di `MAIL_PASSWORD`, bukan kata sandi login biasa; Google menyarankan metode masuk yang lebih aman bila tersedia.
3. Contoh Gmail: `MAIL_SERVER=smtp.gmail.com`, `MAIL_PORT=587`, `MAIL_USE_TLS=1`, `MAIL_USE_SSL=0`. Sesuaikan server dan pengaturan TLS/SSL jika memakai penyedia email lain.
4. Pasang dependensi (`py -m pip install -r requirements.txt`) dan jalankan ulang aplikasi (`py app.py`). Kredensial tetap lokal di `.env`, yang diabaikan Git; jangan membagikannya atau mengunggahnya ke GitHub.

Email dikirim satu kali untuk setiap perubahan status yang terdeteksi: produk lama menjadi `TERSEDIA`, atau produk yang sebelumnya `TERSEDIA` menjadi `HABIS`. Produk baru tidak memicu email awal. Pengecekan otomatis berlangsung tiap 30 menit selama aplikasi berjalan, sehingga pemberitahuan tidak selalu instan. Komputer, server lokal, dan koneksi internet harus aktif. Status bergantung pada indikator yang berhasil dibaca scraper dari halaman toko; status `TIDAK DIKETAHUI` tidak memicu email.

Untuk memantau banyak produk, tambahkan URL kategori/koleksi toko, bukan hanya halaman depan atau satu halaman produk. Contoh Instaxshop: `https://instaxshop.co.id/collections/camera`. Scraper mengikuti tautan pagination berikutnya pada host yang sama, dibatasi maksimal 10 halaman per target. Status stok hanya dianggap tersedia/habis jika halaman memberi indikator yang bisa dikenali; selain itu status tetap "Tidak diketahui".

Untuk deployment HTTPS, set `$env:COOKIE_SECURE = "1"`. `SECRET_KEY`, password admin, dan database URL jangan dimasukkan ke source control.

Scheduler otomatis aktif saat aplikasi dijalankan dengan `py app.py`. Jalankan hanya satu instance aplikasi dengan scheduler ini; untuk deployment multi-worker, pindahkan scheduler ke proses terpisah agar tugas tidak berjalan ganda. Server bawaan Flask hanya untuk pengembangan lokal.
