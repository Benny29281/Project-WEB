# Project Web Scraping

Dashboard diperbarui di latar belakang setiap 60 detik tanpa memuat ulang seluruh halaman; kata kunci dan filter yang sedang dipakai dipertahankan. Waktu pengecekan dan notifikasi ditampilkan dalam zona WIB (`Asia/Jakarta`), dengan format `hari-bulan-tahun jam:menit WIB`.

Dashboard juga memiliki widget chat katalog melayang di kanan bawah yang dapat dibuka dan diminimalkan. Widget menyediakan kategori semua informasi, stok tersedia, stok habis, dan harga termurah. Pencarian mencocokkan semua kata penting tanpa memperhatikan urutannya, mengabaikan kata tanya umum, mengenali variasi sederhana seperti `kamera/camera`, dan memberi toleransi typo kecil untuk kata alfabet; angka model harus cocok tepat. Pengguna dapat menanyakan nama atau kata kunci produk untuk melihat toko, harga, status stok, waktu pengecekan terakhir, dan halaman sumber dari data yang sudah tersimpan. Fitur ini adalah pencarian katalog lokal, belum memakai model AI/API berbayar, dan tidak mencari produk di luar URL toko yang dipantau.

Aplikasi Flask untuk memantau stok produk dari halaman HTTPS pada domain yang memang diizinkan untuk dipantau.

Dashboard menampilkan toko asal, status stok, dan harga terakhir yang berhasil dibaca. Jika pembacaan baru gagal atau halaman tidak mengandung harga, nilai terakhir tidak dihapus; waktu pembacaan terakhir ditampilkan agar umur datanya terlihat. Mata uang disimpan bersama harga; perbandingan hanya dilakukan pada mata uang yang sama. Daftar dapat difilter per toko dan diurutkan berdasarkan harga, dengan grafik 8 harga terendah dari hasil yang sedang ditampilkan. Harga diambil dari data terstruktur halaman serta pola umum kartu WooCommerce/Shopify; hasilnya bergantung pada markup setiap toko. Produk yang sudah tersimpan sebelumnya baru memiliki harga setelah pengecekan ulang. Saat aplikasi startup, kolom harga ditambahkan otomatis ke database lama bila belum tersedia.

Dashboard memakai sidebar Bootstrap yang menyesuaikan layar ponsel dan tablet. Bagian perbandingan menampilkan harga produk bernama sama dari toko berbeda, dan memilih harga terendah yang masih tersedia bila ada. Nama produk dicocokkan setelah huruf besar/kecil dan tanda baca dinormalisasi; produk yang judul tokonya berbeda mungkin tidak tergabung. Notifikasi dalam aplikasi dicatat saat pengecekan menemukan perubahan status stok atau harga. Jika email dikonfigurasi, aplikasi mengirim email saat produk yang sudah pernah dipantau berubah menjadi tersedia, atau berubah dari tersedia menjadi habis. Produk baru tidak langsung memicu email agar setup awal tidak membanjiri kotak masuk.

Pencarian kata kunci bekerja pada katalog produk yang sudah dikumpulkan dari URL toko yang ditambahkan, bukan pencarian menyeluruh di semua marketplace. Parser mengenali format umum dan tautan produk Blibli (`/p/`); toko dengan markup khusus mungkin perlu parser atau API resmi. Halaman kategori TA Kamera menggunakan pola URL kategori WooCommerce yang dicakup parser umum, tetapi hasilnya tetap perlu diperiksa karena markup tiap toko dapat berbeda. Tokopedia kini diizinkan sebagai target, tetapi halaman pencariannya belum memiliki parser khusus dan dapat memuat data melalui JavaScript; produk, harga, dan stok mungkin tidak terbaca atau tidak lengkap. Halaman kategori Focus Nusantara yang diuji juga memuat produk melalui JavaScript, sehingga parser HTML biasa mungkin tidak mendapat katalog dari URL tersebut. Status stok yang tidak memiliki indikator jelas ditampilkan sebagai "Tidak diketahui" dan tidak dianggap tersedia; kegagalan baca tidak dihitung sebagai perubahan stok dan status terakhir yang terverifikasi dipertahankan dengan waktu verifikasinya. Pengecekan otomatis berjalan setiap 30 menit saat proses aplikasi aktif.

Dashboard menyembunyikan ringkasan, grafik, daftar, perbandingan, dan notifikasi produk sampai kata kunci dimasukkan. Form pencarian dan pengelolaan URL toko tetap tersedia. Hasil produk, ringkasan stok, grafik, perbandingan, dan notifikasi kemudian difilter mengikuti kata kunci tersebut.

## Setup (PowerShell)

Jalankan perintah dari folder `Project-Web-Scraping`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
notepad .env
python app.py
```

Sebelum menjalankan aplikasi untuk pertama kali, edit `.env` dan ganti `ADMIN_PASSWORD` dengan password kuat milik Anda. Jangan jalankan aplikasi dengan nilai contoh `replace-with-a-strong-unique-password`. Untuk instalasi baru, akun admin dibuat dari nilai `ADMIN_USERNAME` dan `ADMIN_PASSWORD` itu. Jika memakai database lama yang sudah memiliki akun, jangan menyalin `.env.example` lalu menjalankan aplikasi sebelum mengganti nilai tersebut: konfigurasi admin akan memperbarui password akun yang namanya cocok.

Jika PowerShell tidak mengenali perintah `py` dan memakai Python Laragon di komputer ini, buat environment baru tanpa mengubah `.venv` lama:

```powershell
& 'C:\laragon\bin\python\python-3.10\python.exe' -m venv .venv-laragon
.\.venv-laragon\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item .env.example .env
notepad .env
python app.py
```

Folder `.venv-laragon` juga diabaikan Git. Setelah environment aktif, gunakan `python app.py ...` untuk perintah lain di bawah. File `.env` lokal juga diabaikan Git; jangan unggah atau kirim isinya.

Saat pertama dijalankan, aplikasi membuat tabel dan akun admin dari `ADMIN_USERNAME` serta `ADMIN_PASSWORD`. Akun bawaan dengan password tetap tidak dibuat. Jika `SECRET_KEY` kosong, aplikasi membuat kunci sesi lokal di `instance/.session_secret` agar sesi login tetap konsisten setelah server direstart; folder `instance/` diabaikan Git. Jika mengatur `SECRET_KEY` sendiri di `.env` atau environment, gunakan nilai yang sama setiap kali aplikasi dijalankan. SQLite digunakan secara default; untuk MySQL, atur `DATABASE_URL`, misalnya `mysql+pymysql://user:password@localhost/project_web`.

Atur `SCRAPE_ALLOWED_HOSTS` sebagai daftar domain dipisahkan koma. Default mengizinkan Instaxshop, JPC Kemang, Fujishop, Galaxy, DOSS, Focus Nusantara, Blibli, Lazada Indonesia, Plaza Kamera, Tokopedia, Shopee, TA Kamera, Aneka Foto (`shop.anekafoto.com`), Camera.co.id, Hop Market, Winstore, Sinar Photo, Borneo Digital, Sentra Digital, Enter Komputer, 8storeytree (`shop.8storeytree.com`), dan Panorama Foto (`panoramafoto.co.id`). Hanya HTTPS dan host yang tercantum persis yang diterima. Scraper memakai User-Agent yang mengidentifikasi aplikasi, tidak mengikuti redirect untuk pengecekan HTML biasa, dan memberi jeda antar target. Jika menerima HTTP 429, aplikasi menghormati `Retry-After` (atau jeda bawaan 15 menit), menyimpan waktu pengecekan berikutnya untuk semua URL pada host tersebut, dan melewati target sampai jeda berakhir. HTTP 526 dicatat sebagai masalah sertifikat server asal, bukan sebagai perubahan stok. Harga 8storeytree dicatat sebagai SGD; perbandingan dengan harga IDR tidak dicampur. Gunakan API resmi jika tersedia dan patuhi ketentuan situs; scraper tidak mencoba melewati proteksi anti-bot.

URL produk langsung Shopee dan Blibli (`/p/...`), serta Lazada Indonesia (`/products/...`), diproses menggunakan Playwright Chromium. Tokopedia memakai metadata harga dan stok yang tersedia pada halaman produk publik; angka stok tidak disimpan, hanya dipakai untuk menetapkan status. Untuk Shopee, aplikasi mencoba membaca dan memilih opsi dalam grup yang berlabel `Jenis`/`Varian`, lalu menyimpan setiap opsi sebagai baris terpisah. URL yang meminta varian tertentu hanya diberi harga/stok jika opsi tersebut berhasil ditemukan dan dipilih; status produk umum tidak dipinjam untuk menebak status varian. Status ringkasan produk menjadi `TERSEDIA` jika ada varian tersedia; menjadi `HABIS` hanya jika semua opsi yang terdeteksi tercatat habis; selain itu `TIDAK DIKETAHUI`. Opsi yang baru tersedia dan varian yang berubah dari tersedia menjadi habis membuat notifikasi dalam aplikasi; email dikirim jika SMTP dikonfigurasi. Hasil bergantung pada elemen pilihan yang berhasil dikenali di halaman publik. Renderer tidak menyamarkan browser, menyelesaikan CAPTCHA, atau mencoba melewati pembatasan akses. Kolom baru ditambahkan otomatis ke database lama saat aplikasi dimulai. Jika halaman tidak memberikan sinyal yang bisa dibaca, status tetap `Tidak diketahui`; cocokkan hasil terhadap halaman toko.

## Notifikasi stok melalui email

1. Dari folder `Project-Web-Scraping`, salin `.env.example` ke `.env`: gunakan `Copy-Item .env.example .env` di PowerShell atau `cp .env.example .env` di Git Bash.
2. Isi `MAIL_USERNAME` dengan satu akun pengirim, `MAIL_PASSWORD` dengan kredensial SMTP akun pengirim itu, `MAIL_DEFAULT_SENDER` dengan alamat pengirim, dan `STOCK_ALERT_EMAILS` dengan daftar penerima dipisahkan koma. Contoh lima penerima: `STOCK_ALERT_EMAILS=orang1@example.com,orang2@example.com,orang3@example.com,orang4@example.com,orang5@example.com`. Pemisah titik koma juga didukung. Kelima orang menerima notifikasi yang sama; alamat penerima disembunyikan dari satu sama lain. Penerima tidak perlu memasukkan password atau menghubungkan akun mereka ke aplikasi. Untuk Gmail, App Password memerlukan Verifikasi 2 Langkah dan tidak tersedia untuk semua jenis akun. Gunakan App Password di `MAIL_PASSWORD`, bukan kata sandi login biasa.
3. Contoh Gmail: `MAIL_SERVER=smtp.gmail.com`, `MAIL_PORT=587`, `MAIL_USE_TLS=1`, `MAIL_USE_SSL=0`. Sesuaikan server dan pengaturan TLS/SSL jika memakai penyedia email lain.
4. Dengan virtual environment aktif, jalankan `python app.py test-email` untuk mengirim email uji ke penerima yang dikonfigurasi. Perintah ini tidak mengubah database. Jika gagal, pesan terminal menyebut konfigurasi yang belum diisi atau memberi arahan untuk memeriksa autentikasi SMTP.
5. Jika email uji berhasil, jalankan ulang aplikasi (`python app.py`). Kredensial tetap lokal di `.env`, yang diabaikan Git; jangan membagikannya atau mengunggahnya ke GitHub.

Email dikirim satu kali untuk setiap perubahan status varian yang terdeteksi: varian menjadi `TERSEDIA`, atau varian yang sebelumnya `TERSEDIA` menjadi `HABIS`. Varian baru Shopee yang terdeteksi tersedia juga memicu notifikasi. Notifikasi stok disimpan sebagai antrean terlebih dahulu; jika SMTP gagal atau konfigurasi belum lengkap, dashboard menampilkan statusnya dan aplikasi mencoba lagi dengan jeda bertahap (maksimal 6 jam). Antrean dicoba lagi tiap 5 menit dan juga saat aplikasi dimulai ulang. Notifikasi perubahan harga tetap tercatat di dashboard, sedangkan email saat ini khusus perubahan stok. Pengecekan otomatis berlangsung tiap 30 menit selama aplikasi berjalan, sehingga pemberitahuan tidak selalu instan. Komputer, server lokal, dan koneksi internet harus aktif. Status bergantung pada indikator yang berhasil dibaca scraper dari halaman toko; status `TIDAK DIKETAHUI` tidak memicu email. Kolom antrean email ditambahkan otomatis ke database lama saat aplikasi dijalankan.

Untuk memantau banyak produk, tambahkan URL kategori/koleksi toko, bukan hanya halaman depan atau satu halaman produk. Contoh Instaxshop: `https://instaxshop.co.id/collections/camera`. Scraper mengikuti tautan pagination berikutnya pada host yang sama, dibatasi maksimal 10 halaman per target. Status stok hanya dianggap tersedia/habis jika halaman memberi indikator yang bisa dikenali; selain itu status tetap "Tidak diketahui".

Untuk deployment HTTPS, set `$env:COOKIE_SECURE = "1"`. `SECRET_KEY`, password admin, dan database URL jangan dimasukkan ke source control.

Untuk penggunaan lokal, `python app.py` menyiapkan database, menjalankan scheduler, dan membuka server pengembangan Flask. Proses ini harus tetap hidup agar pengecekan otomatis berjalan. Pengecekan otomatis pertama berlangsung setelah interval 30 menit; menambahkan URL toko dari dashboard memulai pengecekan untuk target tersebut.

## Menjalankan untuk penggunaan bersama

Server bawaan Flask hanya untuk pengembangan lokal. Untuk server internal/VPS, pasang dependensi dari `requirements.txt`, pastikan `.env` dan `DATABASE_URL` yang sama tersedia untuk proses web dan scheduler, lalu jalankan migrasi awal satu kali:

```powershell
python app.py init-db
```

Jalankan dua proses terpisah. Proses pertama menangani pengecekan terjadwal tiap 30 menit; proses kedua melayani dashboard:

```powershell
python app.py scheduler
```

```powershell
waitress-serve --host=127.0.0.1 --port=8080 app:app
```

Jalankan keduanya sebagai service yang otomatis hidup kembali setelah restart server, dan pastikan hanya ada satu proses `scheduler`. Pasang reverse proxy HTTPS di depan Waitress, lalu set `COOKIE_SECURE=1`. Untuk beberapa pengguna, pindahkan database dari SQLite lokal ke MySQL/PostgreSQL dan atur backup rutin. Jangan jalankan `python app.py` bersamaan dengan mode `scheduler`, karena mode lokal tersebut sudah memulai scheduler sendiri.

### Backup database SQLite

Untuk membuat salinan database yang konsisten saat aplikasi masih berjalan, aktifkan virtual environment lalu jalankan dari folder proyek:

```powershell
python -c "import sqlite3; source=sqlite3.connect('instance/project_web.db'); backup=sqlite3.connect('instance/project_web.backup.db'); source.backup(backup); backup.close(); source.close()"
```

Simpan salinan backup di lokasi terpisah dari komputer/server aplikasi dan lakukan pemulihan hanya setelah menghentikan proses web serta scheduler. Jalur database bisa berbeda jika `DATABASE_URL` diubah.
