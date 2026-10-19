import hmac
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SQLALCHEMY_DATABASE_URI=os.environ.get(
        "DATABASE_URL", "sqlite:///project_web.db"
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set COOKIE_SECURE=1 when served over HTTPS.
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=16 * 1024,
)

# Set SCRAPE_ALLOWED_HOSTS to a comma-separated list of domains you are
# authorized to monitor. The default matches the existing Fujishop UI.
ALLOWED_HOSTS = {
    host.strip().lower().rstrip(".")
    for host in os.environ.get("SCRAPE_ALLOWED_HOSTS", "fujishop.id").split(",")
    if host.strip()
}
SCRAPER_USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT", "ProjectWebScraping/1.0 (stock-monitor; contact: admin)"
)

LANGUAGES = {"id": "Bahasa Indonesia", "en": "English", "zh": "中文", "ko": "한국어"}
TEXT = {
    "id": {
        "page_title": "Dashboard Stok", "brand_subtitle": "Pemantauan stok produk",
        "logout": "Keluar", "eyebrow": "Ringkasan pemantauan", "dashboard_title": "Dashboard Admin",
        "dashboard_intro": "Pantau ketersediaan produk dari halaman toko yang kamu tambahkan.",
        "admin": "Admin", "total_products": "Total produk", "stored_products": "Produk yang tersimpan di pantauan",
        "available": "Tersedia", "available_desc": "Produk dengan stok tersedia", "out_of_stock": "Habis",
        "out_desc": "Produk yang terdeteksi habis", "add_target": "Tambah target",
        "add_help": "Masukkan URL HTTPS dari domain yang diizinkan.", "url_label": "URL halaman produk",
        "add_url": "Tambah URL", "monitored_urls": "URL dipantau", "targets": "target",
        "check_now": "Cek sekarang", "no_urls": "Belum ada URL pantauan.", "product_list": "Daftar produk",
        "last_check_help": "Status stok dari pengecekan terakhir", "search": "Cari produk...",
        "all_status": "Semua status", "number": "No.", "product": "Produk", "stock_status": "Status stok",
        "last_checked": "Terakhir dicek", "source": "Sumber", "no_products": "Belum ada produk",
        "add_then_check": "Tambahkan URL toko, lalu mulai pengecekan.",
        "no_results": "Produk tidak ditemukan dengan filter ini.",
        "data_note": "Data stok bergantung pada format halaman sumber dan waktu pengecekan terakhir.",
        "footer": "Pemantauan stok", "login_title": "Masuk Admin", "username": "Nama pengguna",
        "password": "Kata sandi", "login": "Masuk", "login_error": "Nama pengguna atau kata sandi salah!",
        "check_started": "Pengecekan stok dimulai di latar belakang.",
        "url_deleted": "URL dan produk terkait berhasil dihapus.",
        "url_invalid": "URL harus HTTPS dan domainnya harus ada di daftar domain yang diizinkan.",
        "url_duplicate": "URL tersebut sudah ada dalam daftar pantauan.",
        "url_added": "URL ditambahkan. Pengecekan berjalan di latar belakang.",
        "delete_target": "Hapus URL", "confirm_delete": "Hapus URL ini beserta produk terkait?",
        "language": "Bahasa", "product_summary": "Ringkasan produk", "filter_status": "Filter status stok",
        "price_comparison": "Perbandingan harga", "price_chart_help": "Grafik dipisahkan per toko (maksimal 8 produk per toko)",
        "store": "Toko", "all_stores": "Semua toko", "price": "Harga", "sort_price": "Urutkan harga",
        "cheapest_first": "Termurah ke termahal", "expensive_first": "Termahal ke termurah",
        "no_price_data": "Belum ada harga yang terbaca. Jalankan pengecekan stok terlebih dahulu.",
        "price_unavailable": "Harga tidak terbaca",
        "cheapest_chart_title": "Harga terendah yang ditemukan", "chart_products": "produk di grafik",
        "nav_overview": "Ringkasan", "nav_targets": "Toko pantauan", "nav_stock": "Semua stok",
        "nav_compare": "Perbandingan harga", "nav_notifications": "Notifikasi", "notifications_title": "Notifikasi perubahan",
        "mark_all_read": "Tandai dibaca", "no_notifications": "Belum ada perubahan stok atau harga.",
        "stock_change": "Perubahan stok", "price_change": "Perubahan harga", "unread": "belum dibaca",
        "comparison_help": "Harga produk dengan nama yang sama di toko berbeda.",
        "no_comparisons": "Belum ada produk dengan nama sama dan harga terbaca di beberapa toko.",
        "best_price": "Harga terbaik", "other_offers": "Harga toko lain", "savings": "Selisih harga",
    },
    "en": {
        "page_title": "Stock Dashboard", "brand_subtitle": "Product stock monitoring",
        "logout": "Log out", "eyebrow": "Monitoring overview", "dashboard_title": "Admin Dashboard",
        "dashboard_intro": "Track product availability from the store pages you add.", "admin": "Admin",
        "total_products": "Total products", "stored_products": "Products saved for monitoring",
        "available": "In stock", "available_desc": "Products currently available", "out_of_stock": "Out of stock",
        "out_desc": "Products detected as out of stock", "add_target": "Add a target",
        "add_help": "Enter an HTTPS URL from an allowed domain.", "url_label": "Product page URL",
        "add_url": "Add URL", "monitored_urls": "Monitored URLs", "targets": "targets",
        "check_now": "Check now", "no_urls": "No monitored URLs yet.", "product_list": "Products",
        "last_check_help": "Stock status from the latest check", "search": "Search products...",
        "all_status": "All statuses", "number": "No.", "product": "Product", "stock_status": "Stock status",
        "last_checked": "Last checked", "source": "Source", "no_products": "No products yet",
        "add_then_check": "Add a store URL, then start a check.", "no_results": "No products match these filters.",
        "data_note": "Stock data depends on the source page format and the time of the latest check.",
        "footer": "Stock monitoring", "login_title": "Admin sign in", "username": "Username",
        "password": "Password", "login": "Sign in", "login_error": "Incorrect username or password!",
        "check_started": "Stock check started in the background.", "url_deleted": "URL and related products were deleted.",
        "url_invalid": "Use HTTPS and a domain on the allowed-domain list.",
        "url_duplicate": "That URL is already on the monitoring list.",
        "url_added": "URL added. The check is running in the background.",
        "delete_target": "Delete URL", "confirm_delete": "Delete this URL and its related products?",
        "language": "Language", "product_summary": "Product summary", "filter_status": "Filter stock status",
        "price_comparison": "Price comparison", "price_chart_help": "Separate chart for each store (up to 8 products per store)",
        "store": "Store", "all_stores": "All stores", "price": "Price", "sort_price": "Sort by price",
        "cheapest_first": "Lowest to highest", "expensive_first": "Highest to lowest",
        "no_price_data": "No prices found yet. Run a stock check first.", "price_unavailable": "Price unavailable",
        "cheapest_chart_title": "Lowest prices found", "chart_products": "products in chart",
        "nav_overview": "Overview", "nav_targets": "Monitored stores", "nav_stock": "All stock",
        "nav_compare": "Price comparison", "nav_notifications": "Notifications", "notifications_title": "Change notifications",
        "mark_all_read": "Mark all read", "no_notifications": "No stock or price changes yet.",
        "stock_change": "Stock changed", "price_change": "Price changed", "unread": "unread",
        "comparison_help": "Prices for matching product names across different stores.",
        "no_comparisons": "No matching product names with prices across multiple stores yet.",
        "best_price": "Best price", "other_offers": "Other store prices", "savings": "Price difference",
    },
    "zh": {
        "page_title": "库存仪表板", "brand_subtitle": "产品库存监控", "logout": "退出登录",
        "eyebrow": "监控概览", "dashboard_title": "管理员仪表板", "dashboard_intro": "查看已添加店铺页面中的商品库存。",
        "admin": "管理员", "total_products": "商品总数", "stored_products": "已保存监控的商品",
        "available": "有货", "available_desc": "当前有库存的商品", "out_of_stock": "缺货",
        "out_desc": "检测到缺货的商品", "add_target": "添加监控目标", "add_help": "请输入允许域名下的 HTTPS 链接。",
        "url_label": "商品页面链接", "add_url": "添加链接", "monitored_urls": "监控链接", "targets": "个目标",
        "check_now": "立即检查", "no_urls": "尚无监控链接。", "product_list": "商品列表",
        "last_check_help": "最近一次检查的库存状态", "search": "搜索商品...", "all_status": "全部状态",
        "number": "序号", "product": "商品", "stock_status": "库存状态", "last_checked": "最近检查",
        "source": "来源", "no_products": "尚无商品", "add_then_check": "添加店铺链接后开始检查。",
        "no_results": "没有符合筛选条件的商品。", "data_note": "库存数据取决于来源页面格式和最近检查时间。",
        "footer": "库存监控", "login_title": "管理员登录", "username": "用户名", "password": "密码",
        "login": "登录", "login_error": "用户名或密码错误！", "check_started": "已在后台开始库存检查。",
        "url_deleted": "链接及相关商品已删除。", "url_invalid": "请使用 HTTPS，并确保域名已获允许。",
        "url_duplicate": "该链接已在监控列表中。", "url_added": "链接已添加，正在后台检查。",
        "delete_target": "删除链接", "confirm_delete": "删除此链接及其相关商品？",
        "language": "语言", "product_summary": "商品概览", "filter_status": "筛选库存状态",
        "price_comparison": "价格对比", "price_chart_help": "每家商店单独显示图表（每家最多 8 件商品）",
        "store": "商店", "all_stores": "所有商店", "price": "价格", "sort_price": "按价格排序",
        "cheapest_first": "从低到高", "expensive_first": "从高到低",
        "no_price_data": "尚未读取到价格。请先运行库存检查。", "price_unavailable": "无法读取价格",
        "cheapest_chart_title": "当前最低价格", "chart_products": "个商品",
        "nav_overview": "概览", "nav_targets": "监控商店", "nav_stock": "全部库存",
        "nav_compare": "价格对比", "nav_notifications": "通知", "notifications_title": "变更通知",
        "mark_all_read": "全部标为已读", "no_notifications": "尚无库存或价格变更。",
        "stock_change": "库存变更", "price_change": "价格变更", "unread": "条未读",
        "comparison_help": "不同商店中名称相同商品的价格。", "no_comparisons": "尚无多个商店中名称相同且可读取价格的商品。",
        "best_price": "最优价格", "other_offers": "其他商店价格", "savings": "价差",
    },
    "ko": {
        "page_title": "재고 대시보드", "brand_subtitle": "상품 재고 모니터링", "logout": "로그아웃",
        "eyebrow": "모니터링 요약", "dashboard_title": "관리자 대시보드", "dashboard_intro": "추가한 쇼핑몰 페이지의 상품 재고를 확인하세요.",
        "admin": "관리자", "total_products": "전체 상품", "stored_products": "모니터링에 저장된 상품",
        "available": "재고 있음", "available_desc": "현재 구매 가능한 상품", "out_of_stock": "품절",
        "out_desc": "품절로 확인된 상품", "add_target": "대상 추가", "add_help": "허용된 도메인의 HTTPS 주소를 입력하세요.",
        "url_label": "상품 페이지 URL", "add_url": "URL 추가", "monitored_urls": "모니터링 URL", "targets": "개 대상",
        "check_now": "지금 확인", "no_urls": "모니터링 URL이 없습니다.", "product_list": "상품 목록",
        "last_check_help": "마지막 확인 기준 재고 상태", "search": "상품 검색...", "all_status": "전체 상태",
        "number": "번호", "product": "상품", "stock_status": "재고 상태", "last_checked": "마지막 확인",
        "source": "출처", "no_products": "상품이 없습니다.", "add_then_check": "쇼핑몰 URL을 추가한 후 확인을 시작하세요.",
        "no_results": "필터와 일치하는 상품이 없습니다.", "data_note": "재고 정보는 원본 페이지 형식과 마지막 확인 시간에 따라 달라집니다.",
        "footer": "재고 모니터링", "login_title": "관리자 로그인", "username": "사용자 이름", "password": "비밀번호",
        "login": "로그인", "login_error": "사용자 이름 또는 비밀번호가 올바르지 않습니다.",
        "check_started": "백그라운드에서 재고 확인을 시작했습니다.", "url_deleted": "URL과 관련 상품을 삭제했습니다.",
        "url_invalid": "HTTPS와 허용된 도메인을 사용하세요.", "url_duplicate": "이미 모니터링 목록에 있는 URL입니다.",
        "url_added": "URL을 추가했습니다. 백그라운드에서 확인 중입니다.",
        "delete_target": "URL 삭제", "confirm_delete": "이 URL과 관련 상품을 삭제할까요?",
        "language": "언어", "product_summary": "상품 요약", "filter_status": "재고 상태 필터",
        "price_comparison": "가격 비교", "price_chart_help": "매장별로 그래프 분리 (매장당 최대 8개 상품)",
        "store": "매장", "all_stores": "모든 매장", "price": "가격", "sort_price": "가격순 정렬",
        "cheapest_first": "낮은 가격순", "expensive_first": "높은 가격순",
        "no_price_data": "아직 가격을 읽지 못했습니다. 재고 확인을 먼저 실행하세요.", "price_unavailable": "가격 정보 없음",
        "cheapest_chart_title": "확인된 최저 가격", "chart_products": "개 상품",
        "nav_overview": "요약", "nav_targets": "모니터링 매장", "nav_stock": "전체 재고",
        "nav_compare": "가격 비교", "nav_notifications": "알림", "notifications_title": "변경 알림",
        "mark_all_read": "모두 읽음으로 표시", "no_notifications": "아직 재고 또는 가격 변동이 없습니다.",
        "stock_change": "재고 변경", "price_change": "가격 변경", "unread": "읽지 않음",
        "comparison_help": "다른 매장에서 이름이 같은 상품의 가격입니다.",
        "no_comparisons": "여러 매장에서 가격을 읽을 수 있는 동일한 이름의 상품이 없습니다.",
        "best_price": "최저가", "other_offers": "다른 매장 가격", "savings": "가격 차이",
    },
}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
scrape_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stock-scrape")
scrape_lock = threading.Lock()
scheduler = BackgroundScheduler(daemon=True)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class KategoriPantauan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False)


class ProdukDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_produk = db.Column(db.String(255), nullable=False)
    status_stok = db.Column(db.String(50), nullable=False)
    # Keep the existing VARCHAR schema compatible with current databases.
    terakhir_dicek = db.Column(db.String(50), nullable=False)
    url_sumber = db.Column(db.String(500), nullable=False)
    harga = db.Column(db.Numeric(14, 2), nullable=True)


class Notifikasi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_produk = db.Column(db.String(255), nullable=False)
    toko = db.Column(db.String(255), nullable=False)
    jenis = db.Column(db.String(20), nullable=False)
    nilai_lama = db.Column(db.String(100), nullable=False)
    nilai_baru = db.Column(db.String(100), nullable=False)
    dibuat_pada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sudah_dibaca = db.Column(db.Boolean, nullable=False, default=False)


def format_idr(value):
    if value is None:
        return "—"
    return "Rp " + f"{float(value):,.0f}".replace(",", ".")


app.jinja_env.filters["idr"] = format_idr


def store_name(url):
    hostname = (urlsplit(url).hostname or "Toko tidak diketahui").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def normalize_product_name(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


@app.context_processor
def inject_csrf_token():
    language = session.get("language", "id")
    if language not in LANGUAGES:
        language = "id"
    return {
        "csrf_token": csrf_token,
        "t": TEXT[language],
        "current_language": language,
        "languages": LANGUAGES,
    }


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(supplied, expected):
            abort(400, description="Token keamanan formulir tidak valid. Muat ulang halaman.")


@app.route("/bahasa", methods=["POST"])
def set_language():
    language = request.form.get("language", "id")
    if language in LANGUAGES:
        session["language"] = language
    destination = "dashboard" if current_user.is_authenticated else "login"
    return redirect(url_for(destination))


def validate_target_url(value):
    if not value or len(value) > 500:
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        return (
            parsed.scheme == "https"
            and host in ALLOWED_HOSTS
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def parse_price(value):
    """Convert common IDR and international price strings to Decimal."""
    if value is None:
        return None
    value = str(value).strip()
    number = re.search(r"(?<!\d)\d[\d.,]*(?!\d)", value)
    if not number:
        return None
    numeric = number.group(0)

    if "," in numeric and "." in numeric:
        if numeric.rfind(",") > numeric.rfind("."):
            numeric = numeric.replace(".", "").replace(",", ".")
        else:
            numeric = numeric.replace(",", "")
    elif "," in numeric:
        tail = numeric.rsplit(",", 1)[-1]
        numeric = numeric.replace(",", ".") if len(tail) in (1, 2) else numeric.replace(",", "")
    elif numeric.count(".") > 1:
        numeric = numeric.replace(".", "")
    elif "." in numeric:
        tail = numeric.rsplit(".", 1)[-1]
        if len(tail) == 3:
            numeric = numeric.replace(".", "")

    try:
        return Decimal(numeric).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _schema_products(soup):
    found = []

    def visit(value):
        if isinstance(value, dict):
            kinds = value.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if "Product" in kinds and value.get("name"):
                offers = value.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict) and "offers" in offers:
                    offers = offers["offers"]
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                availability = str(offers.get("availability", "")).lower() if isinstance(offers, dict) else ""
                found.append({
                    "name": str(value["name"]).strip(),
                    "price": parse_price(offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None,
                    "status": "HABIS" if "outofstock" in availability else "TERSEDIA",
                })
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (json.JSONDecodeError, TypeError):
            continue
    return found


def _price_in(element):
    price_selectors = (
        "ins .woocommerce-Price-amount", ".price-item--sale", ".sale-price",
        ".special-price", "[itemprop='price']", ".woocommerce-Price-amount",
        ".price", ".money", ".price__regular",
    )
    for selector in price_selectors:
        candidate = element.select_one(selector)
        if candidate:
            raw = candidate.get("content") or candidate.get_text(" ", strip=True)
            parsed = parse_price(raw)
            if parsed is not None:
                return parsed
    return None


def _stock_in(element):
    class_names = set()
    for node in [element, *element.select("[class]")]:
        classes = node.get("class", [])
        class_names.update(str(item).lower().replace("_", "-") for item in classes)
    content = element.get_text(" ", strip=True).lower()
    if class_names.intersection({"outofstock", "out-of-stock", "sold-out", "soldout"}) or any(
        phrase in content for phrase in ("sold out", "out of stock", "habis", "stok kosong")
    ):
        return "HABIS"
    return "TERSEDIA"


def extract_products(soup):
    """Extract structured products first, then common WooCommerce/Shopify cards."""
    products = {}
    for item in _schema_products(soup):
        key = item["name"].casefold()
        products[key] = item

    cards = soup.select(
        "li.product, .product-card, .product-item, .grid-product, "
        ".card-wrapper, [data-product-id], .product"
    )
    for card in cards:
        title = card.select_one(
            ".woocommerce-loop-product__title, .card__heading, .product-title, "
            ".product__title, [itemprop='name'], h2, h3"
        )
        if not title:
            continue
        name = title.get_text(" ", strip=True)
        if not name:
            continue
        key = name.casefold()
        item = {
            "name": name,
            "price": _price_in(card),
            "status": _stock_in(card),
        }
        previous = products.get(key)
        if previous:
            if item["price"] is not None:
                previous["price"] = item["price"]
            if item["status"] == "HABIS":
                previous["status"] = "HABIS"
        else:
            products[key] = item

    # Product-detail pages often expose price metadata but do not use product cards.
    if not products:
        price_tag = soup.select_one(
            "meta[property='product:price:amount'], meta[itemprop='price'], "
            "[itemprop='price'][content]"
        )
        page_price = parse_price(price_tag.get("content")) if price_tag else None
        title = soup.select_one("h1.product_title, h1[itemprop='name']")
        if page_price is not None and title:
            products[title.get_text(" ", strip=True).casefold()] = {
                "name": title.get_text(" ", strip=True),
                "price": page_price,
                "status": _stock_in(soup),
            }
    return list(products.values())


def jalankan_pengecekan_stok():
    """Fetch only allowlisted HTTPS pages, with redirects disabled."""
    if not scrape_lock.acquire(blocking=False):
        return False
    try:
        with app.app_context():
            targets = KategoriPantauan.query.all()
            headers = {"User-Agent": SCRAPER_USER_AGENT, "Accept": "text/html"}
            for kategori in targets:
                if not validate_target_url(kategori.url):
                    app.logger.warning("Target dilewati karena URL tidak diizinkan")
                    continue
                try:
                    response = requests.get(
                        kategori.url, headers=headers, timeout=(5, 15),
                        allow_redirects=False,
                    )
                    if response.status_code != 200:
                        app.logger.info("Target merespons HTTP %s", response.status_code)
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    for product in extract_products(soup):
                        name = product["name"]
                        row = ProdukDetail.query.filter_by(
                            nama_produk=name, url_sumber=kategori.url
                        ).first()
                        if row:
                            if row.status_stok != product["status"]:
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="stok",
                                    nilai_lama=row.status_stok, nilai_baru=product["status"],
                                ))
                            if row.harga is not None and product["price"] is not None and row.harga != product["price"]:
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="harga",
                                    nilai_lama=str(row.harga), nilai_baru=str(product["price"]),
                                ))
                            row.status_stok = product["status"]
                            row.terakhir_dicek = now
                            if product["price"] is not None:
                                row.harga = product["price"]
                        else:
                            db.session.add(ProdukDetail(
                                nama_produk=name,
                                status_stok=product["status"],
                                terakhir_dicek=now,
                                url_sumber=kategori.url,
                                harga=product["price"],
                            ))
                    db.session.commit()
                    app.logger.info("Pengecekan selesai untuk satu target")
                except requests.RequestException as exc:
                    db.session.rollback()
                    app.logger.warning("Permintaan target gagal: %s", exc.__class__.__name__)
                except Exception:
                    db.session.rollback()
                    app.logger.exception("Pengecekan target gagal")
                time.sleep(5)
        return True
    finally:
        scrape_lock.release()


def jadwalkan_pengecekan():
    scrape_executor.submit(jalankan_pengecekan_stok)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            selected_language = session.get("language", "id")
            session.clear()
            session["language"] = selected_language
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("login_error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    selected_language = session.get("language", "id")
    logout_user()
    session.clear()
    session["language"] = selected_language
    return redirect(url_for("login"))


@app.route("/cek_sekarang", methods=["POST"])
@login_required
def cek_sekarang():
    jadwalkan_pengecekan()
    flash("check_started")
    return redirect(url_for("dashboard"))


@app.route("/notifikasi/baca", methods=["POST"])
@login_required
def tandai_notifikasi_dibaca():
    Notifikasi.query.filter_by(sudah_dibaca=False).update({"sudah_dibaca": True})
    db.session.commit()
    return redirect(url_for("dashboard", _anchor="notifications"))


@app.route("/hapus_url/<int:id>", methods=["POST"])
@login_required
def hapus_url(id):
    kategori = db.session.get(KategoriPantauan, id)
    if kategori:
        ProdukDetail.query.filter_by(url_sumber=kategori.url).delete()
        db.session.delete(kategori)
        db.session.commit()
        flash("url_deleted")
    return redirect(url_for("dashboard"))


@app.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        url_baru = (request.form.get("url_produk") or "").strip()
        if not validate_target_url(url_baru):
            flash("url_invalid")
        elif KategoriPantauan.query.filter_by(url=url_baru).first():
            flash("url_duplicate")
        else:
            db.session.add(KategoriPantauan(url=url_baru))
            db.session.commit()
            jadwalkan_pengecekan()
            flash("url_added")

    daftar_kategori = KategoriPantauan.query.all()
    daftar_produk = ProdukDetail.query.order_by(
        ProdukDetail.url_sumber, ProdukDetail.nama_produk
    ).all()
    store_for_product = {}
    for product in daftar_produk:
        store_for_product[product.id] = store_name(product.url_sumber)
    daftar_toko = sorted(set(store_for_product.values()))
    comparisons = {}
    for product in daftar_produk:
        if product.harga is None:
            continue
        key = normalize_product_name(product.nama_produk)
        if not key:
            continue
        offer = {"store": store_for_product[product.id], "price": product.harga,
                 "status": product.status_stok}
        current = comparisons.setdefault(key, {"name": product.nama_produk, "offers_by_store": {}})
        previous = current["offers_by_store"].get(offer["store"])
        if previous is None or offer["price"] < previous["price"]:
            current["offers_by_store"][offer["store"]] = offer
    comparison_groups = []
    for item in comparisons.values():
        offers = sorted(item["offers_by_store"].values(), key=lambda offer: offer["price"])
        if len(offers) > 1:
            available_offers = [offer for offer in offers if offer["status"] == "TERSEDIA"]
            comparable_offers = available_offers or offers
            comparison_groups.append({
                "name": item["name"], "offers": offers,
                "best": min(comparable_offers, key=lambda offer: offer["price"]),
                "difference": max(offer["price"] for offer in comparable_offers)
                              - min(offer["price"] for offer in comparable_offers),
            })
    comparison_groups.sort(key=lambda item: item["difference"], reverse=True)
    notifications = Notifikasi.query.order_by(Notifikasi.dibuat_pada.desc()).limit(30).all()
    unread_notifications = Notifikasi.query.filter_by(sudah_dibaca=False).count()
    total_produk = len(daftar_produk)
    total_tersedia = sum(p.status_stok == "TERSEDIA" for p in daftar_produk)
    total_habis = sum(p.status_stok == "HABIS" for p in daftar_produk)
    return render_template(
        "dashboard.html", daftar_kategori=daftar_kategori,
        daftar_produk=daftar_produk, total_produk=total_produk,
        total_tersedia=total_tersedia, total_habis=total_habis,
        daftar_toko=daftar_toko, store_for_product=store_for_product,
        comparison_groups=comparison_groups, notifications=notifications,
        unread_notifications=unread_notifications,
    )


def initialize_database():
    with app.app_context():
        db.create_all()
        product_columns = {column["name"] for column in inspect(db.engine).get_columns(ProdukDetail.__tablename__)}
        if "harga" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN harga NUMERIC(14, 2)"
            ))
            db.session.commit()
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        if username and password:
            configured_user = User.query.filter_by(username=username).first()
            if configured_user:
                # Also replaces the old default admin password in existing DBs
                # when ADMIN_USERNAME=admin is configured.
                configured_user.password = generate_password_hash(password)
            else:
                db.session.add(User(
                    username=username,
                    password=generate_password_hash(password),
                ))
            db.session.commit()
        elif not User.query.first():
            app.logger.warning(
                "Belum ada akun. Set ADMIN_USERNAME dan ADMIN_PASSWORD sebelum login pertama."
            )


if __name__ == "__main__":
    initialize_database()
    scheduler.add_job(jadwalkan_pengecekan, "interval", minutes=30, id="stock-check")
    scheduler.start()
    app.run(debug=False, use_reloader=False)
