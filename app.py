import argparse
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()
JAKARTA_TZ = ZoneInfo("Asia/Jakarta")


def get_session_secret():
    configured_secret = os.environ.get("SECRET_KEY")
    if configured_secret:
        return configured_secret

    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    secret_path = os.path.join(instance_dir, ".session_secret")
    os.makedirs(instance_dir, exist_ok=True)
    try:
        with open(secret_path, "r", encoding="utf-8") as secret_file:
            saved_secret = secret_file.read().strip()
            if saved_secret:
                return saved_secret
    except FileNotFoundError:
        pass

    generated_secret = secrets.token_hex(32)
    try:
        with open(secret_path, "x", encoding="utf-8") as secret_file:
            secret_file.write(generated_secret)
        return generated_secret
    except FileExistsError:
        with open(secret_path, "r", encoding="utf-8") as secret_file:
            return secret_file.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=get_session_secret(),
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
try:
    SGD_TO_IDR_RATE = Decimal(os.environ.get("SGD_TO_IDR_RATE", "14168.95"))
    if SGD_TO_IDR_RATE <= 0:
        raise InvalidOperation
except (InvalidOperation, ValueError):
    SGD_TO_IDR_RATE = Decimal("14168.95")

# Set SCRAPE_ALLOWED_HOSTS to a comma-separated list of approved store domains.
DEFAULT_ALLOWED_HOSTS = (
    "instaxshop.co.id,www.instaxshop.co.id,jpckemang.com,www.jpckemang.com,"
    "fujishop.id,www.fujishop.id,galaxy.co.id,www.galaxy.co.id,"
    "doss.co.id,www.doss.co.id,focusnusantara.com,www.focusnusantara.com,"
    "blibli.com,www.blibli.com,lazada.co.id,www.lazada.co.id,plazakamera.com,www.plazakamera.com,"
    "tokopedia.com,www.tokopedia.com,shopee.co.id,www.shopee.co.id,taskamera.id,www.taskamera.id,"
    "shop.anekafoto.com,camera.co.id,www.camera.co.id,"
    "hopmarket.id,www.hopmarket.id,winstore.co.id,www.winstore.co.id,"
    "sinarphoto.com,www.sinarphoto.com,borneodigital.co.id,www.borneodigital.co.id,"
    "sentradigital.com,www.sentradigital.com,enterkomputer.com,www.enterkomputer.com,"
    "panoramafoto.co.id,www.panoramafoto.co.id,"
    "shop.8storeytree.com,iqos.com,www.iqos.com"
)
ALLOWED_HOSTS = {
    host.strip().lower().rstrip(".")
    for host in DEFAULT_ALLOWED_HOSTS.split(",")
    if host.strip()
}
ALLOWED_HOSTS.update(
    host.strip().lower().rstrip(".")
    for host in os.environ.get("SCRAPE_ALLOWED_HOSTS", "").split(",")
    if host.strip()
)
DEFAULT_IDR_HOSTS = {
    host.strip().lower().rstrip(".")
    for host in DEFAULT_ALLOWED_HOSTS.split(",")
    if host.strip() and host.strip().lower().rstrip(".") != "shop.8storeytree.com"
}
SCRAPER_USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT", "ProjectWebScraping/1.0 (stock-monitor; contact: admin)"
)
TOKOPEDIA_USER_AGENT = os.environ.get(
    "TOKOPEDIA_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
MAIL_SERVER = os.environ.get("MAIL_SERVER", "").strip()
MAIL_PORT = os.environ.get("MAIL_PORT", "587").strip()
MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "").strip()
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER", "").strip()
STOCK_ALERT_EMAIL = os.environ.get("STOCK_ALERT_EMAIL", "").strip()
STOCK_ALERT_EMAILS = os.environ.get("STOCK_ALERT_EMAILS", "").strip()
MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
MAIL_USE_SSL = os.environ.get("MAIL_USE_SSL", "0") == "1"

LANGUAGES = {"id": "Bahasa Indonesia", "en": "English", "zh": "中文", "ko": "한국어"}
TEXT = {
    "id": {
        "page_title": "Dashboard Stok", "brand_subtitle": "Pemantauan stok produk",
        "logout": "Keluar", "eyebrow": "Ringkasan pemantauan", "dashboard_title": "Dashboard Admin",
        "dashboard_intro": "Pantau ketersediaan produk dari halaman toko yang kamu tambahkan.",
        "admin": "Admin", "total_products": "Total produk", "stored_products": "Produk yang tersimpan di pantauan",
        "available": "Tersedia", "available_desc": "Produk dengan stok tersedia", "out_of_stock": "Habis",
        "out_desc": "Produk yang terdeteksi habis", "unknown_stock": "Tidak diketahui",
        "unknown_desc": "Halaman tidak memberi tanda stok yang jelas", "add_target": "Tambah target",
        "add_help": "Untuk membaca banyak produk, masukkan URL kategori/koleksi, misalnya https://instaxshop.co.id/collections/camera.", "url_label": "URL halaman produk atau kategori",
        "add_url": "Tambah URL", "monitored_urls": "URL dipantau", "targets": "target",
        "check_now": "Cek sekarang", "no_urls": "Belum ada URL pantauan.", "product_list": "Daftar produk",
        "last_check_help": "Status stok dari pengecekan terakhir", "search": "Cari kata kunci produk...",
        "search_scope": "Pencarian mencakup produk yang sudah terbaca dari URL toko pantauan.",
        "search_prompt": "Masukkan kata kunci untuk menampilkan produk dan data pantauannya.",
        "all_status": "Semua status", "number": "No.", "product": "Produk", "stock_status": "Status stok",
        "last_checked": "Terakhir dicek", "source": "Sumber", "source_product": "Produk",
        "source_listing": "Halaman toko", "no_products": "Belum ada produk",
        "add_then_check": "Tambahkan URL toko, lalu mulai pengecekan.",
        "no_results": "Produk tidak ditemukan dengan filter ini.",
        "data_note": "Data stok bergantung pada format halaman sumber dan waktu pengecekan terakhir.",
        "footer": "Pemantauan stok", "login_title": "Masuk Admin", "username": "Nama pengguna",
        "password": "Kata sandi", "login": "Masuk", "login_error": "Nama pengguna atau kata sandi salah!",
        "check_started": "Pengecekan stok dimulai di latar belakang.",
        "url_deleted": "URL dan produk terkait berhasil dihapus.",
        "url_invalid": "URL harus HTTPS dan host persisnya harus tercantum di SCRAPE_ALLOWED_HOSTS sebelum aplikasi dijalankan.",
        "url_duplicate": "URL tersebut sudah ada dalam daftar pantauan.",
        "url_added": "URL ditambahkan. Pengecekan berjalan di latar belakang.",
        "delete_target": "Hapus URL", "confirm_delete": "Hapus URL ini beserta produk terkait?",
        "language": "Bahasa", "product_summary": "Ringkasan produk", "filter_status": "Filter status stok",
        "price_comparison": "Perbandingan harga", "price_chart_help": "Semua produk yang memiliki harga ditampilkan, dipisahkan per toko",
        "store": "Toko", "all_stores": "Semua toko", "price": "Harga", "sort_price": "Urutkan harga",
        "cheapest_first": "Termurah ke termahal", "expensive_first": "Termahal ke termurah",
        "no_price_data": "Belum ada harga yang terbaca. Jalankan pengecekan stok terlebih dahulu.",
        "price_unavailable": "Harga tidak terbaca",
        "cheapest_chart_title": "Harga terendah yang ditemukan", "chart_products": "produk di grafik",
        "nav_overview": "Ringkasan", "nav_targets": "Toko pantauan", "nav_stock": "Semua stok",
        "nav_compare": "Perbandingan harga", "nav_notifications": "Notifikasi", "notifications_title": "Notifikasi perubahan",
        "mark_all_read": "Tandai dibaca", "no_notifications": "Belum ada perubahan stok atau harga.",
        "stock_change": "Perubahan stok", "price_change": "Perubahan harga", "unread": "belum dibaca",
        "email_sent_label": "Email terkirim", "email_pending_label": "Email menunggu dikirim",
        "email_retry_label": "Email gagal, akan dicoba lagi", "email_error_label": "Info pengiriman",
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
        "out_desc": "Products detected as out of stock", "unknown_stock": "Unknown",
        "unknown_desc": "The page did not provide a clear stock signal", "add_target": "Add a target",
        "add_help": "For many products, use a category or collection URL, such as https://instaxshop.co.id/collections/camera.", "url_label": "Product or category URL",
        "add_url": "Add URL", "monitored_urls": "Monitored URLs", "targets": "targets",
        "check_now": "Check now", "no_urls": "No monitored URLs yet.", "product_list": "Products",
        "last_check_help": "Stock status from the latest check", "search": "Search product keywords...",
        "search_scope": "Search covers products already read from monitored store URLs.",
        "search_prompt": "Enter a keyword to display matching products and monitoring data.",
        "all_status": "All statuses", "number": "No.", "product": "Product", "stock_status": "Stock status",
        "last_checked": "Last checked", "source": "Source", "source_product": "Product",
        "source_listing": "Store listing", "no_products": "No products yet",
        "add_then_check": "Add a store URL, then start a check.", "no_results": "No products match these filters.",
        "data_note": "Stock data depends on the source page format and the time of the latest check.",
        "footer": "Stock monitoring", "login_title": "Admin sign in", "username": "Username",
        "password": "Password", "login": "Sign in", "login_error": "Incorrect username or password!",
        "check_started": "Stock check started in the background.", "url_deleted": "URL and related products were deleted.",
        "url_invalid": "Use HTTPS and make sure the exact hostname is in SCRAPE_ALLOWED_HOSTS before starting the app.",
        "url_duplicate": "That URL is already on the monitoring list.",
        "url_added": "URL added. The check is running in the background.",
        "delete_target": "Delete URL", "confirm_delete": "Delete this URL and its related products?",
        "language": "Language", "product_summary": "Product summary", "filter_status": "Filter stock status",
        "price_comparison": "Price comparison", "price_chart_help": "All products with prices are shown, separated by store",
        "store": "Store", "all_stores": "All stores", "price": "Price", "sort_price": "Sort by price",
        "cheapest_first": "Lowest to highest", "expensive_first": "Highest to lowest",
        "no_price_data": "No prices found yet. Run a stock check first.", "price_unavailable": "Price unavailable",
        "cheapest_chart_title": "Lowest prices found", "chart_products": "products in chart",
        "nav_overview": "Overview", "nav_targets": "Monitored stores", "nav_stock": "All stock",
        "nav_compare": "Price comparison", "nav_notifications": "Notifications", "notifications_title": "Change notifications",
        "mark_all_read": "Mark all read", "no_notifications": "No stock or price changes yet.",
        "stock_change": "Stock changed", "price_change": "Price changed", "unread": "unread",
        "email_sent_label": "Email sent", "email_pending_label": "Email queued",
        "email_retry_label": "Email failed; it will be retried", "email_error_label": "Delivery info",
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
        "source": "来源", "source_product": "商品", "source_listing": "店铺列表",
        "no_products": "尚无商品", "add_then_check": "添加店铺链接后开始检查。",
        "no_results": "没有符合筛选条件的商品。", "data_note": "库存数据取决于来源页面格式和最近检查时间。",
        "footer": "库存监控", "login_title": "管理员登录", "username": "用户名", "password": "密码",
        "login": "登录", "login_error": "用户名或密码错误！", "check_started": "已在后台开始库存检查。",
        "url_deleted": "链接及相关商品已删除。", "url_invalid": "请使用 HTTPS，并确保域名已获允许。",
        "url_duplicate": "该链接已在监控列表中。", "url_added": "链接已添加，正在后台检查。",
        "delete_target": "删除链接", "confirm_delete": "删除此链接及其相关商品？",
        "language": "语言", "product_summary": "商品概览", "filter_status": "筛选库存状态",
        "price_comparison": "价格对比", "price_chart_help": "显示所有有价格的商品，并按商店分开",
        "store": "商店", "all_stores": "所有商店", "price": "价格", "sort_price": "按价格排序",
        "cheapest_first": "从低到高", "expensive_first": "从高到低",
        "no_price_data": "尚未读取到价格。请先运行库存检查。", "price_unavailable": "无法读取价格",
        "cheapest_chart_title": "当前最低价格", "chart_products": "个商品",
        "nav_overview": "概览", "nav_targets": "监控商店", "nav_stock": "全部库存",
        "nav_compare": "价格对比", "nav_notifications": "通知", "notifications_title": "变更通知",
        "mark_all_read": "全部标为已读", "no_notifications": "尚无库存或价格变更。",
        "stock_change": "库存变更", "price_change": "价格变更", "unread": "条未读",
        "email_sent_label": "邮件已发送", "email_pending_label": "邮件等待发送",
        "email_retry_label": "邮件发送失败，将重试", "email_error_label": "发送信息",
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
        "source": "출처", "source_product": "상품", "source_listing": "스토어 목록",
        "no_products": "상품이 없습니다.", "add_then_check": "쇼핑몰 URL을 추가한 후 확인을 시작하세요.",
        "no_results": "필터와 일치하는 상품이 없습니다.", "data_note": "재고 정보는 원본 페이지 형식과 마지막 확인 시간에 따라 달라집니다.",
        "footer": "재고 모니터링", "login_title": "관리자 로그인", "username": "사용자 이름", "password": "비밀번호",
        "login": "로그인", "login_error": "사용자 이름 또는 비밀번호가 올바르지 않습니다.",
        "check_started": "백그라운드에서 재고 확인을 시작했습니다.", "url_deleted": "URL과 관련 상품을 삭제했습니다.",
        "url_invalid": "HTTPS와 허용된 도메인을 사용하세요.", "url_duplicate": "이미 모니터링 목록에 있는 URL입니다.",
        "url_added": "URL을 추가했습니다. 백그라운드에서 확인 중입니다.",
        "delete_target": "URL 삭제", "confirm_delete": "이 URL과 관련 상품을 삭제할까요?",
        "language": "언어", "product_summary": "상품 요약", "filter_status": "재고 상태 필터",
        "price_comparison": "가격 비교", "price_chart_help": "가격이 있는 모든 상품을 매장별로 표시합니다",
        "store": "매장", "all_stores": "모든 매장", "price": "가격", "sort_price": "가격순 정렬",
        "cheapest_first": "낮은 가격순", "expensive_first": "높은 가격순",
        "no_price_data": "아직 가격을 읽지 못했습니다. 재고 확인을 먼저 실행하세요.", "price_unavailable": "가격 정보 없음",
        "cheapest_chart_title": "확인된 최저 가격", "chart_products": "개 상품",
        "nav_overview": "요약", "nav_targets": "모니터링 매장", "nav_stock": "전체 재고",
        "nav_compare": "가격 비교", "nav_notifications": "알림", "notifications_title": "변경 알림",
        "mark_all_read": "모두 읽음으로 표시", "no_notifications": "아직 재고 또는 가격 변동이 없습니다.",
        "stock_change": "재고 변경", "price_change": "가격 변경", "unread": "읽지 않음",
        "email_sent_label": "이메일 전송됨", "email_pending_label": "이메일 전송 대기 중",
        "email_retry_label": "이메일 전송 실패, 다시 시도합니다", "email_error_label": "전송 정보",
        "comparison_help": "다른 매장에서 이름이 같은 상품의 가격입니다.",
        "no_comparisons": "여러 매장에서 가격을 읽을 수 있는 동일한 이름의 상품이 없습니다.",
        "best_price": "최저가", "other_offers": "다른 매장 가격", "savings": "가격 차이",
    },
}

# Keep the stock-confidence and keyword-search labels available in every UI language.
TEXT["zh"].update({
    "unknown_stock": "\u672a\u77e5", "unknown_desc": "\u9875\u9762\u6ca1\u6709\u660e\u786e\u7684\u5e93\u5b58\u4fe1\u53f7",
    "search": "\u6309\u5173\u952e\u8bcd\u641c\u7d22\u5546\u54c1...",
    "search_scope": "\u641c\u7d22\u5df2\u4ece\u76d1\u63a7\u5546\u5e97\u9875\u9762\u8bfb\u53d6\u7684\u5546\u54c1\u3002",
    "search_prompt": "\u8f93\u5165\u5173\u952e\u8bcd\u4ee5\u663e\u793a\u5339\u914d\u7684\u5546\u54c1\u548c\u76d1\u63a7\u6570\u636e\u3002",
})
TEXT["ko"].update({
    "unknown_stock": "\uc54c \uc218 \uc5c6\uc74c", "unknown_desc": "\ud398\uc774\uc9c0\uc5d0 \uba85\ud655\ud55c \uc7ac\uace0 \ud45c\uc2dc\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
    "search": "\ud0a4\uc6cc\ub4dc\ub85c \uc0c1\ud488 \uac80\uc0c9...",
    "search_scope": "\uac10\uc2dc \uc911\uc778 \ub9e4\uc7a5 URL\uc5d0\uc11c \uc77d\uc740 \uc0c1\ud488\uc744 \uac80\uc0c9\ud569\ub2c8\ub2e4.",
    "search_prompt": "\ud0a4\uc6cc\ub4dc\ub97c \uc785\ub825\ud558\uba74 \uc77c\uce58\ud558\ub294 \uc0c1\ud488\uacfc \ubaa8\ub2c8\ud130\ub9c1 \ub370\uc774\ud130\uac00 \ud45c\uc2dc\ub429\ub2c8\ub2e4.",
})

TEXT["id"].update({
    "nav_assistant": "Tanya katalog", "chat_error": "Maaf, pencarian katalog gagal. Coba lagi sebentar.",
    "chat_price_missing": "Harga belum terbaca",
    "chat_title": "Tanya katalog stok", "chat_help": "Tanyakan produk; jawaban diambil dari data yang sudah tersimpan.",
    "chat_placeholder": "Contoh: Ada Instax Mini 12 yang tersedia?", "chat_send": "Kirim",
    "chat_welcome": "Halo! Tanyakan nama produk yang ingin kamu cek. Saya mencari di katalog toko yang sudah dipantau.",
    "chat_scope": "Jawaban berdasarkan hasil pengecekan terakhir, bukan pencarian seluruh internet.",
    "chat_empty": "Tulis nama atau kata kunci produk yang ingin dicari.",
    "chat_not_found": "Saya belum menemukan produk yang cocok di katalog yang tersimpan. Pastikan URL tokonya sudah dipantau dan pengecekan sudah berjalan.",
    "chat_found": "Saya menemukan {count} produk yang cocok di katalog pantauan:",
})
TEXT["en"].update({
    "nav_assistant": "Ask catalog", "chat_error": "Sorry, the catalog search failed. Please try again.",
    "chat_price_missing": "Price unavailable",
    "chat_title": "Ask the stock catalog", "chat_help": "Ask about a product; answers come from saved monitoring data.",
    "chat_placeholder": "Example: Is Instax Mini 12 in stock?", "chat_send": "Send",
    "chat_welcome": "Hi! Ask for a product name. I’ll search the catalog from stores you monitor.",
    "chat_scope": "Answers use the latest saved checks, not a search of the whole internet.",
    "chat_empty": "Enter a product name or keyword to search.",
    "chat_not_found": "I couldn’t find a matching product in the saved catalog. Make sure its store URL is monitored and has been checked.",
    "chat_found": "I found {count} matching products in your monitored catalog:",
})
TEXT["zh"].update({
    "nav_assistant": "è¯¢é—®ç›®å½•", "chat_error": "ç›®å½•æœç´¢å¤±è´¥ï¼Œè¯·ç¨åŽé‡è¯•ã€‚",
    "chat_price_missing": "æš‚æ— ä»·æ ¼",
    "chat_title": "询问库存目录", "chat_help": "询问商品；回答来自已保存的监控数据。",
    "chat_placeholder": "例如：Instax Mini 12 有现货吗？", "chat_send": "发送",
    "chat_welcome": "你好！请输入商品名称，我会在已监控店铺的目录中查找。",
    "chat_scope": "回答基于最近保存的检查结果，不会搜索整个互联网。",
    "chat_empty": "请输入商品名称或关键词。",
    "chat_not_found": "已保存的目录中没有找到匹配商品。请确认店铺 URL 已加入监控并完成检查。",
    "chat_found": "在监控目录中找到 {count} 个匹配商品：",
})
TEXT["ko"].update({
    "nav_assistant": "ì¹´íƒˆë¡œê·¸ ì§ˆë¬¸", "chat_error": "ì¹´íƒˆë¡œê·¸ ê²€ìƒ‰ì— ì‹¤íŒ¨í–ˆìŠµë‹ˆë‹¤. ìž ì‹œ í›„ ë‹¤ì‹œ ì‹œë„„í•˜ì„¸ìš”.",
    "chat_price_missing": "ê°€ê²© ì •ë³´ ì—†ìŒ",
    "chat_title": "재고 카탈로그에 질문하기", "chat_help": "상품을 물어보세요. 저장된 모니터링 데이터로 답합니다.",
    "chat_placeholder": "예: Instax Mini 12 재고 있나요?", "chat_send": "보내기",
    "chat_welcome": "안녕하세요! 상품명을 입력하면 모니터링 중인 매장 카탈로그에서 찾습니다.",
    "chat_scope": "답변은 최근 저장된 확인 결과를 기준으로 하며 전체 인터넷 검색은 아닙니다.",
    "chat_empty": "검색할 상품명이나 키워드를 입력하세요.",
    "chat_not_found": "저장된 카탈로그에서 일치하는 상품을 찾지 못했습니다. 매장 URL을 추가하고 확인을 실행했는지 확인하세요.",
    "chat_found": "모니터링 카탈로그에서 일치하는 상품 {count}개를 찾았습니다:",
})

TEXT["id"].update({
    "chat_category_label": "Kategori pertanyaan", "chat_category_all": "Semua informasi",
    "chat_category_available": "Stok tersedia", "chat_category_out": "Stok habis",
    "chat_category_cheapest": "Harga termurah", "chat_filtered_none": "Belum ada produk cocok dengan kategori ini.",
})
TEXT["en"].update({
    "chat_category_label": "Question category", "chat_category_all": "All information",
    "chat_category_available": "In stock", "chat_category_out": "Out of stock",
    "chat_category_cheapest": "Lowest price", "chat_filtered_none": "No matching products fit this category.",
})
TEXT["zh"].update({
    "chat_category_label": "问题类别", "chat_category_all": "所有信息",
    "chat_category_available": "有库存", "chat_category_out": "无库存",
    "chat_category_cheapest": "最低价格", "chat_filtered_none": "没有符合此类别的匹配商品。",
})
TEXT["ko"].update({
    "chat_category_label": "질문 카테고리", "chat_category_all": "모든 정보",
    "chat_category_available": "재고 있음", "chat_category_out": "품절",
    "chat_category_cheapest": "최저 가격", "chat_filtered_none": "이 카테고리에 해당하는 상품이 없습니다.",
})

TEXT["id"].update({"chat_minimize": "Tutup chat"})
TEXT["en"].update({"chat_minimize": "Minimize chat"})
TEXT["zh"].update({"chat_minimize": "收起聊天"})
TEXT["ko"].update({"chat_minimize": "채팅 최소화"})

TEXT["id"].update({"variant": "Varian", "units": "unit"})
TEXT["en"].update({"variant": "Variant", "units": "units"})
TEXT["zh"].update({"variant": "规格", "units": "件"})
TEXT["ko"].update({"variant": "옵션", "units": "개"})
TEXT["id"].update({"variant_stock": "Stok jenis ini", "overall_stock": "Ringkasan produk"})
TEXT["en"].update({"variant_stock": "This variant", "overall_stock": "Product summary"})
TEXT["zh"].update({"variant_stock": "此规格库存", "overall_stock": "商品汇总"})
TEXT["ko"].update({"variant_stock": "이 옵션 재고", "overall_stock": "상품 요약"})

TEXT["id"].update({"last_confirmed_stock": "Terakhir terverifikasi"})
TEXT["en"].update({"last_confirmed_stock": "Last confirmed"})
TEXT["zh"].update({"last_confirmed_stock": "最近确认"})
TEXT["ko"].update({"last_confirmed_stock": "마지막 확인"})
TEXT["id"].update({"last_read_price": "Harga terakhir terbaca"})
TEXT["en"].update({"last_read_price": "Last price read"})
TEXT["zh"].update({"last_read_price": "最近读取的价格"})
TEXT["ko"].update({"last_read_price": "마지막으로 읽은 가격"})

TEXT["id"].update({"check_not_verified": "Pengecekan terbaru belum mengonfirmasi stok"})
TEXT["en"].update({"check_not_verified": "Latest check did not confirm stock"})
TEXT["zh"].update({"check_not_verified": "æœ€è¿‘æ£€æŸ¥æœªç¡®è®¤åº“å­˜"})
TEXT["ko"].update({"check_not_verified": "ìµœê·¼ í™•ì¸ì—ì„œ ìž¬ê³ ë¥¼ í™•ì¸í•˜ì§€ ëª»í–ˆìŠµë‹ˆë‹¤"})

SOURCE_UI_TEXT = {
    "id": {
        "source_check_label": "Kondisi sumber", "source_last_attempt": "Percobaan terakhir",
        "source_last_success": "Terakhir berhasil dibaca",
        "source_next_check": "Bisa dicek lagi",
        "source_status_BELUM_DICEK": "Belum dicek", "source_status_MEMERIKSA": "Sedang dicek",
        "source_status_BERHASIL": "Halaman terbaca", "source_status_AKSES_DIBATASI": "Akses dibatasi",
        "source_status_GAGAL": "Pengecekan gagal", "source_status_TIDAK_ADA_DATA": "Produk tidak terbaca",
        "source_reason_SHOPEE_VERIFIKASI": "Shopee mengalihkan scraper ke verifikasi trafik.",
        "source_reason_TANTANGAN_AKSES": "Toko meminta verifikasi atau membatasi akses otomatis.",
        "source_reason_HALAMAN_TIDAK_LENGKAP": "Halaman tidak memuat detail produk yang cukup.",
        "source_reason_REDIRECT_DILARANG": "Halaman mengalihkan ke alamat yang tidak diizinkan.",
        "source_reason_HTTP_GAGAL": "Toko tidak mengirim halaman produk yang dapat dibaca.",
        "source_reason_RATE_LIMITED": "Toko membatasi permintaan otomatis; pengecekan dijeda sementara.",
        "source_reason_TLS_GATEWAY_ERROR": "Toko mengalami kegagalan sertifikat pada server asal (HTTP 526).",
        "source_reason_DATA_PRODUK_TIDAK_DITEMUKAN": "Halaman terbuka, tetapi data produk tidak ditemukan.",
        "source_reason_STOK_TIDAK_TERBACA": "Halaman terbaca, tetapi indikator stok tidak ditemukan.",
        "source_reason_TIMEOUT": "Toko tidak merespons dalam batas waktu pengecekan.",
        "source_reason_PROSES_GAGAL": "Halaman gagal diproses.",
        "source_reason_HOST_TIDAK_DIIJINKAN": "Domain target tidak ada di daftar host yang diizinkan.",
    },
    "en": {
        "source_check_label": "Source health", "source_last_attempt": "Last attempt",
        "source_last_success": "Last successful read",
        "source_next_check": "Eligible for next check",
        "source_status_BELUM_DICEK": "Not checked", "source_status_MEMERIKSA": "Checking",
        "source_status_BERHASIL": "Page readable", "source_status_AKSES_DIBATASI": "Access restricted",
        "source_status_GAGAL": "Check failed", "source_status_TIDAK_ADA_DATA": "No product data read",
        "source_reason_SHOPEE_VERIFIKASI": "Shopee redirected the scraper to traffic verification.",
        "source_reason_TANTANGAN_AKSES": "The store requested verification or restricted automated access.",
        "source_reason_HALAMAN_TIDAK_LENGKAP": "The page did not contain enough product details.",
        "source_reason_REDIRECT_DILARANG": "The page redirected to a host that is not allowed.",
        "source_reason_HTTP_GAGAL": "The store did not return a readable product page.",
        "source_reason_RATE_LIMITED": "The store rate limited automated requests; checks are temporarily paused.",
        "source_reason_TLS_GATEWAY_ERROR": "The store origin has a certificate error (HTTP 526).",
        "source_reason_DATA_PRODUK_TIDAK_DITEMUKAN": "The page opened, but product data was not found.",
        "source_reason_STOK_TIDAK_TERBACA": "The page was readable, but no stock signal was found.",
        "source_reason_TIMEOUT": "The store did not respond before the check timed out.",
        "source_reason_PROSES_GAGAL": "The page could not be processed.",
        "source_reason_HOST_TIDAK_DIIJINKAN": "The target domain is not in the allowed host list.",
    },
}
TEXT["id"].update(SOURCE_UI_TEXT["id"])
TEXT["en"].update(SOURCE_UI_TEXT["en"])
TEXT["zh"].update(SOURCE_UI_TEXT["en"])
TEXT["ko"].update(SOURCE_UI_TEXT["en"])
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
scrape_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stock-scrape")
scrape_lock = threading.Lock()
email_delivery_lock = threading.Lock()
scheduler = BackgroundScheduler(daemon=True)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)


class KategoriPantauan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(500), unique=True, nullable=False)
    status_pengecekan = db.Column(db.String(30), nullable=False, default="BELUM_DICEK")
    alasan_pengecekan = db.Column(db.String(50), nullable=True)
    waktu_pengecekan_terakhir = db.Column(db.String(50), nullable=True)
    waktu_berhasil_dibaca = db.Column(db.String(50), nullable=True)
    waktu_cek_berikutnya = db.Column(db.String(50), nullable=True)


class ProdukDetail(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_produk = db.Column(db.String(255), nullable=False)
    status_stok = db.Column(db.String(50), nullable=False)
    # Keep the existing VARCHAR schema compatible with current databases.
    terakhir_dicek = db.Column(db.String(50), nullable=False)
    url_sumber = db.Column(db.String(500), nullable=False)
    # URL used for the product's source link; url_sumber remains the monitored
    # category/listing URL used to associate products with a target.
    url_produk = db.Column(db.String(500), nullable=True)
    harga = db.Column(db.Numeric(14, 2), nullable=True)
    mata_uang = db.Column(db.String(3), nullable=True)
    stok_kuantitas = db.Column(db.Integer, nullable=True)
    varian_produk = db.Column(db.String(255), nullable=True)
    jumlah_varian = db.Column(db.Integer, nullable=True)
    status_terakhir_terverifikasi = db.Column(db.String(50), nullable=True)
    waktu_terakhir_terverifikasi = db.Column(db.String(50), nullable=True)
    harga_terakhir_terbaca = db.Column(db.Numeric(14, 2), nullable=True)
    mata_uang_terakhir = db.Column(db.String(3), nullable=True)
    waktu_harga_terakhir_terbaca = db.Column(db.String(50), nullable=True)


class Notifikasi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nama_produk = db.Column(db.String(255), nullable=False)
    toko = db.Column(db.String(255), nullable=False)
    jenis = db.Column(db.String(20), nullable=False)
    nilai_lama = db.Column(db.String(100), nullable=False)
    nilai_baru = db.Column(db.String(100), nullable=False)
    dibuat_pada = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    sudah_dibaca = db.Column(db.Boolean, nullable=False, default=False)
    sumber_url = db.Column(db.String(500), nullable=True)
    email_status = db.Column(db.String(20), nullable=False, default="TIDAK_PERLU")
    email_attempts = db.Column(db.Integer, nullable=False, default=0)
    email_last_attempt = db.Column(db.String(50), nullable=True)
    email_next_attempt = db.Column(db.String(50), nullable=True)
    email_sent_at = db.Column(db.String(50), nullable=True)
    email_error = db.Column(db.String(255), nullable=True)


class SourceCheckFailure(Exception):
    """A classified page failure that provides no evidence of a stock change."""

    def __init__(self, status, reason, retry_after=None):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


def format_idr(value):
    if value is None:
        return "—"
    return "Rp " + f"{float(value):,.0f}".replace(",", ".")


def format_money(value, currency=None):
    """Format prices in IDR for Indonesian dashboard display; retain other currencies."""
    if value is None:
        return "—"
    currency = (currency or "").upper()
    amount = float(value)
    if currency == "IDR":
        return format_idr(amount)
    if currency == "SGD":
        return format_idr(amount * float(SGD_TO_IDR_RATE))
    if currency == "USD":
        return "US$ " + f"{amount:,.2f}"
    if currency and currency != "UNKNOWN":
        return f"{currency} " + f"{amount:,.2f}"
    return f"{amount:,.2f} (mata uang tidak diketahui)"


def display_price_value(value, currency=None):
    if value is None:
        return None
    if (currency or "").upper() == "SGD":
        return float(value) * float(SGD_TO_IDR_RATE)
    return float(value)


def display_price_currency(currency=None):
    return "IDR" if (currency or "").upper() == "SGD" else (currency or "UNKNOWN")


def money_conversion_note(currency=None):
    if (currency or "").upper() == "SGD":
        return f"Konversi: 1 SGD = {format_idr(SGD_TO_IDR_RATE)} (kurs dapat diatur melalui SGD_TO_IDR_RATE)"
    return ""


def format_notification_price(value):
    """Format older numeric notification records as IDR and retain newer labels."""
    if value is None:
        return "—"
    value = str(value).strip()
    if value.startswith("S$ "):
        amount = parse_price(value[3:])
        return format_idr(amount * SGD_TO_IDR_RATE) if amount is not None else value
    if value.startswith(("Rp ", "US$ ")):
        return value
    amount = parse_price(value)
    return format_idr(amount) if amount is not None else value


def format_jakarta(value):
    """Render stored UTC timestamps in Indonesia western time (WIB)."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return ""
    # Existing database timestamps are naive UTC values.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JAKARTA_TZ).strftime("%d-%m-%Y %H:%M WIB")


app.jinja_env.filters["idr"] = format_idr
app.jinja_env.filters["money"] = format_money
app.jinja_env.filters["money_value"] = display_price_value
app.jinja_env.filters["money_currency"] = display_price_currency
app.jinja_env.filters["money_note"] = money_conversion_note
app.jinja_env.filters["notification_price"] = format_notification_price
app.jinja_env.filters["jakarta"] = format_jakarta


def store_name(url):
    hostname = (urlsplit(url).hostname or "Toko tidak diketahui").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def aggregate_variant_status(observations):
    """Return the parent product state from the individual observed variants."""
    observations = list(observations)
    if observations and isinstance(observations[0], tuple):
        expected_counts = [item[2] for item in observations if len(item) > 2 and item[2]]
        if expected_counts:
            expected_count = max(expected_counts)
            current = [
                item for item in observations
                if len(item) > 2 and item[2] == expected_count and item[1]
            ]
            statuses = [item[0] for item in current]
            variant_names = {item[1] for item in current}
        else:
            statuses = [item[0] for item in observations]
            variant_names = {item[1] for item in observations if item[1]}
    else:
        statuses = observations
        variant_names = set()
        expected_counts = []
    if any(status == "TERSEDIA" for status in statuses):
        return "TERSEDIA"
    expected_count = max(expected_counts, default=None)
    # Only claim the parent is sold out when every option discovered on the page
    # has its own recorded sold-out observation.
    if (expected_count and len(variant_names) == expected_count
            and all(status == "HABIS" for status in statuses)):
        return "HABIS"
    return "TIDAK DIKETAHUI"


def is_shopee_product_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return host == "shopee.co.id" and re.search(r"-i\.\d+\.\d+", parts.path) is not None


def normalize_product_name(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


SEARCH_STOPWORDS = {
    "ada", "produk", "barang", "ini", "itu", "gak", "nggak", "enggak",
    "tidak", "apakah", "kah", "ya", "dong", "tolong", "saya", "mau",
    "cari", "cek", "lihat", "di", "ke", "dari", "untuk", "yang", "dan",
    "atau", "berapa", "harga", "stok", "stock", "ready", "tersedia", "terjual",
    "jual", "toko", "termurah", "murah", "mahal", "paling", "terbaik", "best",
    "cheapest", "low", "cost", "available", "is", "are", "there", "any",
    "do", "you", "have", "the", "in", "please", "check", "find", "price",
    "of", "can", "has", "for", "i", "www", "com", "co", "id",
}
SEARCH_SYNONYMS = {
    "camera": {"camera", "kamera"}, "kamera": {"kamera", "camera"},
    "instant": {"instant", "instan"}, "instan": {"instan", "instant"},
}


def search_keywords(value):
    """Normalize a natural-language question into meaningful catalog keywords."""
    tokens = normalize_product_name(value).split()
    return [token for token in tokens if token not in SEARCH_STOPWORDS and len(token) > 1]


def keyword_matches(term, product_tokens):
    aliases = SEARCH_SYNONYMS.get(term, {term})
    if aliases.intersection(product_tokens):
        return True
    # Keep model numbers exact; use a small typo tolerance for alphabetic words only.
    if not term.isalpha() or len(term) < 5:
        return False
    return any(
        candidate.isalpha() and len(candidate) >= 5
        and SequenceMatcher(None, term, candidate).ratio() >= 0.84
        for candidate in product_tokens
    )


def _configured_email_recipients():
    """Read recipient addresses without exposing them in logs or message headers."""
    configured_recipients = STOCK_ALERT_EMAILS or STOCK_ALERT_EMAIL
    return list(dict.fromkeys(
        address.strip()
        for address in re.split(r"[,;]", configured_recipients)
        if address.strip()
    ))


def _send_email_message(email, recipients):
    try:
        port = int(MAIL_PORT)
        if MAIL_USE_SSL:
            with smtplib.SMTP_SSL(
                MAIL_SERVER, port, timeout=15,
                context=ssl.create_default_context(),
            ) as smtp:
                smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
                smtp.send_message(email, to_addrs=recipients)
        else:
            with smtplib.SMTP(MAIL_SERVER, port, timeout=15) as smtp:
                smtp.ehlo()
                if MAIL_USE_TLS:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
                smtp.send_message(email, to_addrs=recipients)
        app.logger.info("Email berhasil dikirim")
        return True, None
    except smtplib.SMTPAuthenticationError as exc:
        app.logger.warning("Autentikasi SMTP ditolak (kode %s)", exc.smtp_code)
        return False, "Autentikasi SMTP ditolak. Periksa username dan App Password."
    except smtplib.SMTPServerDisconnected:
        app.logger.warning(
            "Server SMTP memutus koneksi; periksa host, port, TLS/SSL, dan jaringan"
        )
        return False, "Koneksi SMTP terputus. Periksa host, port, TLS/SSL, dan jaringan."
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        app.logger.warning("Pengiriman SMTP gagal (%s)", exc.__class__.__name__)
        return False, "Pengiriman SMTP gagal. Periksa konfigurasi server dan jaringan."


def _email_configuration_error(recipients):
    missing = []
    if not MAIL_SERVER:
        missing.append("MAIL_SERVER")
    if not MAIL_USERNAME:
        missing.append("MAIL_USERNAME")
    if not MAIL_PASSWORD:
        missing.append("MAIL_PASSWORD")
    if not MAIL_DEFAULT_SENDER:
        missing.append("MAIL_DEFAULT_SENDER")
    if not recipients:
        missing.append("STOCK_ALERT_EMAILS")
    try:
        int(MAIL_PORT)
    except (TypeError, ValueError):
        missing.append("MAIL_PORT")
    if MAIL_USE_SSL and MAIL_USE_TLS:
        missing.append("pilih salah satu: MAIL_USE_SSL atau MAIL_USE_TLS")
    if missing:
        return "Lengkapi konfigurasi ini di file .env: " + ", ".join(missing)
    return None


def should_notify_stock_change(previous_status, observed_status, target_has_baseline=False):
    """Alert confirmed stock transitions and newly discovered available items."""
    known = {"TERSEDIA", "HABIS"}
    if observed_status not in known:
        return False
    if previous_status in known:
        return previous_status != observed_status
    return observed_status == "TERSEDIA" and target_has_baseline


def notification_email_content(notification):
    """Build a message for either a confirmed stock or price notification."""
    safe_name = re.sub(r"[\r\n]+", " ", notification.nama_produk).strip()
    if notification.jenis == "harga":
        subject = f"Harga berubah: {safe_name}"
        description = "Perubahan harga terdeteksi."
    else:
        subject = f"Stok berubah: {safe_name}"
        description = "Perubahan stok terdeteksi."
    body = (
        f"{description}\n\n"
        f"Produk: {notification.nama_produk}\n"
        f"Toko: {notification.toko}\n"
        f"Perubahan: {notification.nilai_lama} -> {notification.nilai_baru}\n"
        f"Waktu: {format_jakarta(notification.dibuat_pada)}\n"
        f"Sumber: {notification.sumber_url or 'URL toko tidak tersimpan'}"
    )
    return subject, body


def notification_retry_delay_minutes(attempts):
    """Use bounded exponential retry spacing for transient SMTP failures."""
    safe_attempts = max(1, int(attempts or 1))
    return min(5 * (2 ** min(safe_attempts - 1, 7)), 360)


def process_pending_notification_emails():
    """Deliver queued stock emails and retain failed deliveries for retry."""
    if not email_delivery_lock.acquire(blocking=False):
        return 0
    delivered = 0
    try:
        with app.app_context():
            now = datetime.utcnow()
            now_text = now.strftime("%Y-%m-%d %H:%M:%S")
            pending = Notifikasi.query.filter_by(email_status="MENUNGGU").order_by(
                Notifikasi.dibuat_pada.asc()
            ).limit(50).all()
            for notification in pending:
                if notification.email_next_attempt and notification.email_next_attempt > now_text:
                    continue
                recipients = _configured_email_recipients()
                error = _email_configuration_error(recipients)
                notification.email_attempts = (notification.email_attempts or 0) + 1
                notification.email_last_attempt = now_text
                db.session.commit()

                if not error:
                    subject, body = notification_email_content(notification)
                    email = EmailMessage()
                    email["Subject"] = subject
                    email["From"] = MAIL_DEFAULT_SENDER
                    email["To"] = "undisclosed-recipients:;"
                    email.set_content(body)
                    sent, error = _send_email_message(email, recipients)
                    if not sent and not error:
                        error = "Pengiriman SMTP belum berhasil."

                if error:
                    retry_minutes = notification_retry_delay_minutes(
                        notification.email_attempts
                    )
                    notification.email_status = "MENUNGGU"
                    notification.email_error = error[:255]
                    notification.email_next_attempt = (
                        now + timedelta(minutes=retry_minutes)
                    ).strftime("%Y-%m-%d %H:%M:%S")
                    app.logger.warning(
                        "Email notifikasi #%s belum terkirim; percobaan ulang setelah %s menit",
                        notification.id, retry_minutes,
                    )
                else:
                    notification.email_status = "TERKIRIM"
                    notification.email_error = None
                    notification.email_next_attempt = None
                    notification.email_sent_at = datetime.utcnow().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    delivered += 1
                db.session.commit()
    finally:
        email_delivery_lock.release()
    return delivered


def send_test_notification_email():
    """Send a manual test message to configured recipients, without DB changes."""
    recipients = _configured_email_recipients()
    error = _email_configuration_error(recipients)
    if error:
        return False, error

    email = EmailMessage()
    email["Subject"] = "Tes notifikasi pemantauan stok"
    email["From"] = MAIL_DEFAULT_SENDER
    email["To"] = "undisclosed-recipients:;"
    email.set_content(
        "Email uji berhasil dikirim. Konfigurasi SMTP dan penerima notifikasi berfungsi."
    )
    return _send_email_message(email, recipients)


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
        "allowed_hosts": sorted(ALLOWED_HOSTS),
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


def canonical_target_url(value):
    """Remove tracking-only query strings while retaining variant selectors."""
    raw_value = (value or "").strip()
    try:
        parsed = urlsplit(raw_value)
        host = (parsed.hostname or "").lower().rstrip(".")
        path = parsed.path or "/"
    except ValueError:
        return raw_value
    # These product identifiers are part of the path. Their query strings are
    # analytics/recommendation context and otherwise create duplicate targets.
    if host in {
        "tokopedia.com", "www.tokopedia.com",
        "lazada.co.id", "www.lazada.co.id",
        "shop.8storeytree.com",
    }:
        query = ""
    else:
        # A bare trailing '?' has no meaning, but keep non-empty query strings
        # for stores such as Shopee where they can select a product variant.
        query = parsed.query
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, path, query, ""))


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


def _currency_for_host(source_host):
    host = (source_host or "").lower().rstrip(".")
    if host == "shop.8storeytree.com":
        return "SGD"
    if host in DEFAULT_IDR_HOSTS or host.endswith(".id"):
        return "IDR"
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
                if "outofstock" in availability or "soldout" in availability:
                    stock_status = "HABIS"
                elif any(marker in availability for marker in ("instock", "limitedavailability", "preorder", "backorder")):
                    stock_status = "TERSEDIA"
                else:
                    stock_status = "TIDAK DIKETAHUI"
                found.append({
                    "name": str(value["name"]).strip(),
                    "price": parse_price(offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None,
                    "price_currency": (str(offers.get("priceCurrency", "")).upper() or None)
                    if isinstance(offers, dict) else None,
                    "status": stock_status,
                    "product_url": str(value.get("url", "")).strip(),
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


def _galaxy_embedded_products(soup):
    """Read Galaxy's Shopify Hydrogen product data embedded in Remix state."""
    products = {}

    def visit(value):
        if isinstance(value, dict):
            handle = value.get("handle")
            title = value.get("title")
            price_range = value.get("priceRange") or {}
            min_price = price_range.get("minVariantPrice") or {}
            price = parse_price(min_price.get("amount"))
            if handle and title and price is not None:
                products[str(handle).casefold()] = {
                    "name": str(title).strip(),
                    "price": price,
                    "status": (
                        "TERSEDIA" if value.get("availableForSale") is True
                        else "HABIS" if value.get("availableForSale") is False
                        else "TIDAK DIKETAHUI"
                    ),
                }
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text()
        marker = "window.__remixContext ="
        marker_index = script_text.find(marker)
        if marker_index < 0:
            continue
        object_start = script_text.find("{", marker_index + len(marker))
        if object_start < 0:
            continue
        try:
            state, _ = decoder.raw_decode(script_text[object_start:])
        except (json.JSONDecodeError, TypeError):
            continue
        visit(state)
    return products


def _price_in(element):
    price_selectors = (
        "ins .woocommerce-Price-amount", ".price-item--sale", ".sale-price",
        ".special-price", "[itemprop='price']", ".woocommerce-Price-amount",
        ".product-price", ".sellprice", ".price", ".money", ".price__regular",
        ".information-price",
    )
    for selector in price_selectors:
        candidate = element.select_one(selector)
        if candidate:
            raw = candidate.get("content") or candidate.get_text(" ", strip=True)
            parsed = parse_price(raw)
            if parsed is not None:
                return parsed
    # Storefronts may render prices as plain text without standard price classes.
    for text_value in element.stripped_strings:
        match = re.search(r"\bRp\.?\s*\d[\d.,]*", text_value, flags=re.IGNORECASE)
        if match:
            parsed = parse_price(match.group(0))
            if parsed is not None:
                return parsed
    return None


def _camera_co_id_detail_price(soup):
    """Read the WooCommerce price from Camera.co.id's product summary."""
    for selector in (
        "div.summary p.price", ".summary.entry-summary p.price",
        ".product-summary p.price", "p.price",
    ):
        node = soup.select_one(selector)
        if node:
            price = parse_price(node.get_text(" ", strip=True))
            # WooCommerce templates can contain hidden Rp 0 placeholders.
            if price is not None and price > 0:
                return price
    return None


def _galaxy_detail_price(soup):
    """Read Galaxy Camera's product price from its Shopify Open Graph metadata."""
    for selector in (
        "meta[property='product:price:amount']",
        "meta[property='og:price:amount']",
        "meta[itemprop='price']",
    ):
        node = soup.select_one(selector)
        if node:
            price = parse_price(node.get("content", ""))
            if price is not None and price > 0:
                return price
    return None


def _stock_in(element):
    class_names = set()
    for node in [element, *element.select("[class]")]:
        classes = node.get("class", [])
        class_names.update(str(item).lower().replace("_", "-") for item in classes)
    labels = {
        re.sub(r"\s+", " ", node.get_text(" ", strip=True)).casefold()
        for node in [element, *element.select("span, p, div, strong, b, em, small")]
    }
    out_of_stock_labels = {
        "sold out", "out of stock", "unavailable", "not available",
        "stock kosong", "stock habis", "stok habis", "stok kosong",
        "tidak tersedia", "\u65e0\u8d27", "\u7f3a\u8d27", "\ud488\uc808",
    }
    available_labels = {
        "available", "in stock", "tersedia", "stok tersedia", "ready stock",
        "\u6709\u8d27", "\uc7ac\uace0 \uc788\uc74c",
    }
    if class_names.intersection({"outofstock", "out-of-stock", "sold-out", "soldout"}) or labels.intersection(
        out_of_stock_labels
    ):
        return "HABIS"
    if class_names.intersection({"instock", "in-stock", "available", "product-available"}) or labels.intersection(
        available_labels
    ) or any(re.search(r"\btersisa\s+\d+\s+produk\b", label) for label in labels):
        return "TERSEDIA"
    return "TIDAK DIKETAHUI"


def _sentradigital_detail_stock(soup):
    """Use Sentra Digital's product purchase controls as detail-page evidence."""
    explicit_status = _stock_in(soup)
    if explicit_status != "TIDAK DIKETAHUI":
        return explicit_status

    purchase_controls = soup.select(
        "#MainContent_btnAdd, #MainContent_btnBuy, "
        "#btnAdd, #btnBuy, .btn-addcart, .btn-buy"
    )
    if not purchase_controls:
        return "TIDAK DIKETAHUI"
    if any(
        control.has_attr("disabled")
        or control.get("aria-disabled", "").casefold() == "true"
        or "disabled" in control.get("class", [])
        for control in purchase_controls
    ):
        return "HABIS"

    quantity = soup.select_one("#txtQty, input[name*='Qty'], input[name*='quantity']")
    if quantity:
        try:
            return "TERSEDIA" if int(quantity.get("value", "1")) > 0 else "HABIS"
        except (TypeError, ValueError):
            return "TIDAK DIKETAHUI"
    return "TIDAK DIKETAHUI"


def preserve_last_confirmed_stock(observed_status, last_confirmed_status=None,
                                  current_status=None):
    """Avoid treating an unreadable page as a new stock observation."""
    known_statuses = {"TERSEDIA", "HABIS"}
    if observed_status in known_statuses:
        return observed_status
    if observed_status != "TIDAK DIKETAHUI":
        return "TIDAK DIKETAHUI"
    for candidate in (last_confirmed_status, current_status):
        if candidate in known_statuses:
            return candidate
    return "TIDAK DIKETAHUI"


def _marketplace_stock_status(marketplace, indicator="", page_text=""):
    """Use product-area evidence only; recommendation text is not stock data."""
    indicator = re.sub(r"\s+", " ", str(indicator or "")).strip().casefold()
    if re.search(r"\b(?:stok habis|habis|sold out|out of stock)\b", indicator):
        return "HABIS"
    if re.search(r"\b(?:tersedia|tersisa|stok tersedia|in stock)\b", indicator):
        return "TERSEDIA"
    if (marketplace == "Shopee"
            and re.search(r"(?:^|\n)\s*habis\s*(?:\n|$)", page_text or "", re.I)):
        return "HABIS"
    # A cart button can belong to a recommendation card elsewhere on the page.
    # Without an explicit product-area signal, leave stock unconfirmed.
    return "TIDAK DIKETAHUI"


def _is_direct_product_page(url):
    parts = [part for part in (urlsplit(url).path or "").lower().split("/") if part]
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if host in {"iqos.com", "www.iqos.com"}:
        return (urlsplit(url).path or "").lower().startswith("/id/id/shop/")
    if host in {"tokopedia.com", "www.tokopedia.com"} and len(parts) >= 2:
        return True
    path = "/" + "/".join(parts) + "/"
    return (
        re.search(r"/(?:products?|detail|p)/", path) is not None
        and "/product-category/" not in path
    )


def _tokopedia_detail_stock(soup, target_url=None):
    """Read stock only from matching Product schema or the heading's nearby area."""
    if target_url:
        product = _tokopedia_schema_product(soup, target_url)
        if product and product.get("status") in {"TERSEDIA", "HABIS"}:
            return product["status"]

    text = ""
    heading = soup.select_one("h1")
    if heading:
        for parent in heading.parents:
            if not parent.name or parent.name in {"body", "html", "main"}:
                break
            candidate = parent.get_text(" ", strip=True)
            if len(candidate) > 4000:
                break
            if re.search(r"\bStok(?:\s+Total)?\s*:?\s*[\d.,]+\b", candidate, re.I):
                text = candidate
                break
    match = (
        re.search(r"\bStok\s+Total\s*:?\s*([\d.,]+)\b", text, re.IGNORECASE)
        or re.search(r"\bStok\s*:\s*([\d.,]+)\b", text, re.IGNORECASE)
    )
    if not match:
        return "TIDAK DIKETAHUI"
    digits = re.sub(r"\D", "", match.group(1))
    if not digits:
        return "TIDAK DIKETAHUI"
    return "TERSEDIA" if int(digits) > 0 else "HABIS"


def _tokopedia_schema_product(soup, target_url):
    """Return Tokopedia Product JSON-LD that matches the requested item."""
    target_path = urlsplit(target_url).path.rstrip("/").casefold()
    candidates = [
        item for item in _schema_products(soup)
        if _is_relevant_instax_item(item.get("name", ""))
    ]
    exact = [
        item for item in candidates
        if item.get("product_url")
        and urlsplit(urljoin(target_url, item["product_url"])).path.rstrip("/").casefold()
        == target_path
    ]
    if len(exact) == 1:
        return exact[0]
    if (not exact and len(candidates) == 1
            and not candidates[0].get("product_url")):
        return candidates[0]
    return None


def _tokopedia_detail_name(soup, target_url):
    """Read the main Tokopedia product name from its heading or matching schema."""
    heading = soup.select_one("h1")
    name = heading.get_text(" ", strip=True) if heading else ""
    if _is_relevant_instax_item(name):
        return name
    product = _tokopedia_schema_product(soup, target_url)
    if product:
        return product["name"]
    title = soup.select_one('meta[property="og:title"], meta[name="title"]')
    name = title.get("content", "").strip() if title else ""
    return name if _is_relevant_instax_item(name) else ""


def _tokopedia_detail_price(soup, target_url=None):
    """Use Tokopedia product metadata or matching Product schema, in rupiah."""
    for selector in ("meta[property='product:price:amount']", "meta[itemprop='price']"):
        node = soup.select_one(selector)
        if node:
            raw = node.get("content", "")
            price = parse_price(raw)
            if price is not None:
                return price
    if target_url:
        product = _tokopedia_schema_product(soup, target_url)
        if product and product.get("price") is not None:
            return product["price"]
    return None


def _is_relevant_instax_item(name):
    normalized = " ".join((name or "").casefold().split())
    if "instax" not in normalized:
        return False
    noise = (
        "load image into gallery viewer", "quick view", "share :",
        "description", "reviews", "shop all", "find your perfect camera",
    )
    return not any(label in normalized for label in noise)


def _is_relevant_iqos_terea_item(name):
    """Keep the IQOS target scoped to TEREA consumable product listings."""
    normalized = " ".join((name or "").casefold().split())
    noise = ("quick view", "shop all", "filter", "temukan", "pelajari")
    return normalized.startswith("terea ") and not any(label in normalized for label in noise)


def _is_relevant_iqos_product(name):
    """Accept direct IQOS ILUMA device pages and TEREA consumable pages."""
    normalized = " ".join((name or "").casefold().split())
    if _is_relevant_iqos_terea_item(name):
        return True
    is_iluma_device = "iluma" in normalized and (
        "iqos" in normalized or normalized.startswith("iluma ")
        or normalized.startswith("paket ")
    )
    noise = ("quick view", "shop all", "temukan", "pelajari")
    return is_iluma_device and not any(label in normalized for label in noise)


def _iqos_detail_product(soup, target_url):
    """Read the main TEREA or ILUMA item from an IQOS detail page."""
    heading = soup.select_one("main h1, h1[itemprop='name'], h1")
    name = heading.get_text(" ", strip=True) if heading else ""
    if not _is_relevant_iqos_product(name):
        schema_products = [
            item for item in _schema_products(soup)
            if _is_relevant_iqos_product(item.get("name", ""))
        ]
        target_path = urlsplit(target_url).path.rstrip("/").casefold()
        exact = [
            item for item in schema_products
            if item.get("product_url")
            and urlsplit(urljoin(target_url, item["product_url"]))
            .path.rstrip("/").casefold() == target_path
        ]
        if len(exact) == 1:
            return {
                **exact[0], "price_currency": exact[0].get("price_currency") or "IDR",
                "product_url": target_url,
            }
        return None

    schema_product = next((
        item for item in _schema_products(soup)
        if " ".join(item.get("name", "").casefold().split())
        == " ".join(name.casefold().split())
    ), {})
    price = schema_product.get("price")
    if price is None:
        for selector in (
            "meta[property='product:price:amount']",
            "meta[property='og:price:amount']",
            "meta[itemprop='price']",
        ):
            node = soup.select_one(selector)
            if node:
                price = parse_price(node.get("content", ""))
                if price is not None:
                    break
    if price is None and heading:
        for parent in heading.parents:
            if not parent.name or parent.name in {"body", "html"}:
                break
            if len(parent.get_text(" ", strip=True)) > 8000:
                break
            price = _price_in(parent)
            if price is not None:
                break
    if price is None:
        price = _price_in(soup)

    status = schema_product.get("status", "TIDAK DIKETAHUI")
    if status == "TIDAK DIKETAHUI":
        status = _stock_in(soup)
    if status == "TIDAK DIKETAHUI":
        alt_labels = {
            " ".join((node.get("alt") or "").casefold().split())
            for node in soup.select("img[alt]")
        }
        if alt_labels.intersection({"stok habis", "stock habis", "sold out", "out of stock"}):
            status = "HABIS"
        elif alt_labels.intersection({"tersedia", "stok tersedia", "in stock", "available"}):
            status = "TERSEDIA"

    return {
        "name": name, "price": price,
        "price_currency": schema_product.get("price_currency") or "IDR",
        "status": status, "product_url": target_url,
    }


def extract_products(soup, source_host=""):
    """Extract structured products first, then common WooCommerce/Shopify cards."""
    products = {}
    for item in _schema_products(soup):
        item["price_currency"] = item.get("price_currency") or _currency_for_host(source_host)
        key = item["name"].casefold()
        products[key] = item

    cards = soup.select(
        "li.product, li.grid__item, .product-card, .product-card-wrapper, "
        ".product-item, .product-grid-item, .grid-product, "
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
        product_link = card.select_one(
            'a.woocommerce-LoopProduct-link[href], '
            'a.woocommerce-loop-product__link[href], '
            'a[href*="/products/"], a[href*="/product/"], '
            'a[href*="/detail/"]'
        )
        if (not product_link
                and source_host in {"iqos.com", "www.iqos.com"}):
            product_link = card.select_one("a[href]")
        item = {
            "name": name,
            "price": _price_in(card),
            "price_currency": _currency_for_host(source_host),
            "status": _stock_in(card),
            "product_url": product_link.get("href", "") if product_link else "",
        }
        previous = products.get(key)
        if previous:
            if item["price"] is not None:
                previous["price"] = item["price"]
                if not previous.get("price_currency"):
                    previous["price_currency"] = item.get("price_currency")
            if item["status"] != "TIDAK DIKETAHUI":
                previous["status"] = item["status"]
            if item.get("product_url"):
                previous["product_url"] = item["product_url"]
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
                "price_currency": _currency_for_host(source_host),
                "status": _stock_in(soup),
            }

    # Some stores use nonstandard product card markup. Find the smallest ancestor
    # containing a single product link; Blibli uses /p/ paths instead of /products/.
    is_blibli = source_host in {"blibli.com", "www.blibli.com"}
    product_links = soup.select('a[href*="/products/"]')
    if is_blibli:
        product_links.extend(soup.select('a[href^="/p/"], a[href*="blibli.com/p/"]'))
    for link in product_links:
        card = None
        for parent in link.parents:
            if not parent.name or parent.name in {"body", "html"}:
                break
            card_links = parent.select('a[href*="/products/"]')
            if is_blibli:
                card_links.extend(parent.select('a[href^="/p/"], a[href*="blibli.com/p/"]'))
            product_hrefs = {urlsplit(candidate.get("href", "")).path for candidate in card_links}
            if len(product_hrefs) > 1:
                break
            if product_hrefs:
                card = parent
        if card is None:
            continue
        title = card.select_one(
            ".card__heading, .product-title, .product__title, h2, h3"
        )
        name = (title.get_text(" ", strip=True) if title else "") or link.get_text(" ", strip=True)
        if not name:
            image = link.select_one("img[alt]")
            name = (link.get("title") or link.get("aria-label")
                    or (image.get("alt") if image else "") or "")
        name = name.strip()
        if not name:
            continue
        key = name.casefold()
        item = {
            "name": name, "price": _price_in(card), "status": _stock_in(card),
            "price_currency": _currency_for_host(source_host),
            "product_url": link.get("href", ""),
        }
        previous = products.get(key)
        if previous:
            if item["price"] is not None:
                previous["price"] = item["price"]
                if not previous.get("price_currency"):
                    previous["price_currency"] = item.get("price_currency")
            if item["status"] != "TIDAK DIKETAHUI":
                previous["status"] = item["status"]
            if item.get("product_url"):
                previous["product_url"] = item["product_url"]
        else:
            products[key] = item

    if source_host in {"galaxy.co.id", "www.galaxy.co.id"}:
        embedded = _galaxy_embedded_products(soup)
        for item in products.values():
            product_url = item.get("product_url") or ""
            parts = [part for part in urlsplit(product_url).path.split("/") if part]
            if len(parts) < 2 or parts[-2].casefold() != "products":
                continue
            product_data = embedded.get(parts[-1].casefold())
            if not product_data:
                continue
            item["price"] = product_data["price"]
            item["price_currency"] = "IDR"
            if product_data["status"] != "TIDAK DIKETAHUI":
                item["status"] = product_data["status"]
    return list(products.values())


def _shopify_product_details(listing_url, product_url, headers):
    """Read Shopify's public product JSON for accurate variant price/availability."""
    if not product_url:
        return None
    product_page = urljoin(listing_url, product_url)
    page_parts = urlsplit(product_page)
    listing_host = (urlsplit(listing_url).hostname or "").lower().rstrip(".")
    if (not validate_target_url(product_page)
            or (page_parts.hostname or "").lower().rstrip(".") != listing_host
            or "/products/" not in page_parts.path):
        return None
    api_url = page_parts._replace(path=page_parts.path.rstrip("/") + ".js", query="", fragment="").geturl()
    try:
        response = requests.get(
            api_url, headers={**headers, "Accept": "application/json"},
            timeout=(5, 15), allow_redirects=False,
        )
        if response.status_code != 200:
            app.logger.info("Detail produk merespons HTTP %s", response.status_code)
            return None
        data = response.json()
    except (requests.RequestException, ValueError):
        return None

    variants = data.get("variants") or []
    available_variants = [variant for variant in variants if variant.get("available") is True]
    price_variants = available_variants or variants
    prices = []
    for variant in price_variants:
        raw_price = variant.get("price")
        if raw_price is not None:
            try:
                # Shopify Ajax Product API reports monetary amounts in subunits.
                prices.append((Decimal(str(raw_price)) / Decimal(100)).quantize(Decimal("0.01")))
            except (InvalidOperation, ValueError):
                parsed = parse_price(raw_price)
                if parsed is not None:
                    prices.append(parsed)
    if not prices and data.get("price") is not None:
        try:
            prices.append((Decimal(str(data["price"])) / Decimal(100)).quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError):
            parsed = parse_price(data["price"])
            if parsed is not None:
                prices.append(parsed)

    if available_variants:
        stock_status = "TERSEDIA"
    elif ((variants and all(variant.get("available") is False for variant in variants))
          or (not variants and data.get("available") is False)):
        stock_status = "HABIS"
    else:
        stock_status = "TIDAK DIKETAHUI"
    return {"price": min(prices) if prices else None, "status": stock_status}


def _next_catalog_page(soup, current_url, original_host):
    """Return a same-host HTTPS pagination URL, if the page exposes one."""
    for link in soup.find_all("a", href=True):
        label = " ".join((link.get("aria-label", ""), link.get_text(" ", strip=True))).lower()
        classes = " ".join(link.get("class", [])).lower()
        candidate = urljoin(current_url, link.get("href"))
        direction = parse_qs(urlsplit(candidate).query).get("direction", [])
        rel = link.get("rel", [])
        if isinstance(rel, str):
            rel = rel.split()
        is_next = (
            "next" in [str(value).lower() for value in rel]
            or "next" in label
            or "load more" in label
            or "pagination__item--next" in classes
            or any(value.lower() == "next" for value in direction)
        )
        if not is_next:
            continue
        if (validate_target_url(candidate)
                and urlsplit(candidate).hostname.lower().rstrip(".") == original_host):
            return candidate
    return None


def _close_marketplace_page(page, browser):
    """Drain registered Playwright routes before closing the browser context."""
    if page is not None:
        try:
            page.unroute_all(behavior="wait")
        except Exception:
            pass
        try:
            page.close()
        except Exception:
            pass
    if browser is not None:
        try:
            browser.close()
        except Exception:
            pass


def _fetch_rendered_focus_product(target_url):
    """Read Focus Nusantara's client-rendered public product detail page."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        app.logger.warning("Playwright belum terpasang untuk membaca produk Focus Nusantara")
        return None

    browser = None
    page = None
    original_host = (urlsplit(target_url).hostname or "").lower().rstrip(".")
    allowed_host = {"focusnusantara.com", "www.focusnusantara.com"}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="id-ID")

            def keep_navigation_on_focus(route):
                request_parts = urlsplit(route.request.url)
                request_host = (request_parts.hostname or "").lower().rstrip(".")
                if (route.request.is_navigation_request()
                        and (request_parts.scheme != "https" or request_host not in allowed_host)):
                    route.abort()
                elif route.request.resource_type in {"image", "media", "font"}:
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", keep_navigation_on_focus)
            response = page.goto(
                target_url, wait_until="domcontentloaded", timeout=25000,
            )
            final_url = page.url
            final_parts = urlsplit(final_url)
            if (not validate_target_url(final_url)
                    or (final_parts.hostname or "").lower().rstrip(".") not in allowed_host):
                raise SourceCheckFailure("AKSES_DIBATASI", "REDIRECT_DILARANG")
            if response is None:
                raise SourceCheckFailure("GAGAL", "HTTP_GAGAL")
            if response.status >= 400:
                if response.status == 429:
                    raise SourceCheckFailure(
                        "AKSES_DIBATASI", "RATE_LIMITED",
                        response.headers.get("retry-after"),
                    )
                if response.status == 526:
                    raise SourceCheckFailure("GAGAL", "TLS_GATEWAY_ERROR")
                if response.status in {401, 403, 503}:
                    raise SourceCheckFailure("AKSES_DIBATASI", "TANTANGAN_AKSES")
                raise SourceCheckFailure("GAGAL", "HTTP_GAGAL")

            try:
                page.locator("h1").first.wait_for(state="visible", timeout=12000)
                page.wait_for_timeout(1500)
            except PlaywrightTimeoutError:
                pass

            title = page.locator("h1").first.inner_text(timeout=3000).strip() if page.locator("h1").count() else ""
            body_text = page.locator("body").inner_text(timeout=5000)
            lowered = body_text.casefold()
            if any(marker in lowered for marker in (
                "captcha", "verify you are human", "access denied", "akses ditolak",
                "verifikasi bahwa anda manusia", "traffic verification",
            )):
                raise SourceCheckFailure("AKSES_DIBATASI", "TANTANGAN_AKSES")
            if not _is_relevant_instax_item(title):
                app.logger.warning(
                    "Focus Nusantara tidak menampilkan judul produk Instax (judul=%r)", title,
                )
                return None

            order_start = re.search(r"\bset your order\b", body_text, re.IGNORECASE)
            product_section = body_text[order_start.start():] if order_start else body_text
            related_start = re.search(r"\brelated products\b", product_section, re.IGNORECASE)
            if related_start:
                product_section = product_section[:related_start.start()]

            status = "TIDAK DIKETAHUI"
            if re.search(r"\b(?:out of stock|sold out|stok habis|habis)\b", product_section, re.I):
                status = "HABIS"
            elif re.search(r"\b(?:in stock|tersedia|ready stock)\b", product_section, re.I):
                status = "TERSEDIA"

            price_match = re.search(r"(?:Rp\.?|IDR)\s*[\d.,]+", product_section, re.I)
            price = parse_price(price_match.group(0)) if price_match else None
            return {
                "name": title,
                "price": price,
                "price_currency": _currency_for_host(original_host),
                "status": status,
                "stock_quantity": None,
                "variant": None,
                "product_url": target_url,
            }
    except SourceCheckFailure:
        raise
    except Exception as error:
        app.logger.warning(
            "Pengecekan browser Focus Nusantara gagal: %s", type(error).__name__,
        )
        reason = "TIMEOUT" if "timeout" in type(error).__name__.casefold() else "PROSES_GAGAL"
        raise SourceCheckFailure("GAGAL", reason) from error
    finally:
        if browser is not None:
            _close_marketplace_page(page, browser)


def _lazada_unavailable_page(page_title, body_text):
    page_summary = " ".join((page_title or "", body_text or ""))
    return bool(re.search(
        r"maaf[!\s,.:;-]{0,30}produk ini tidak tersedia|"
        r"produk ini tidak tersedia|product is no longer available",
        page_summary, re.IGNORECASE,
    ))


def _fetch_rendered_marketplace_product(target_url, marketplace, marketplace_hosts):
    """Render one public marketplace product page without bypassing access controls."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError:
        app.logger.warning(
            "Playwright belum terpasang; instal dependensi dan browser Chromium untuk memantau %s",
            marketplace,
        )
        return None

    browser = None
    page = None
    rendered_page_title = ""
    variant_snapshots = []
    requested_variant_label = None
    target_parts = urlsplit(target_url)
    if marketplace == "Shopee" and ".47554402197" in target_parts.path:
        query = parse_qs(target_parts.query)
        try:
            extra_params = json.loads(query.get("extraParams", [""])[0])
        except (TypeError, json.JSONDecodeError):
            extra_params = {}
        if str(extra_params.get("display_model_id", "")) == "370411572210":
            requested_variant_label = "White Twinpack"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="id-ID")
            def allow_page_request(route):
                request_parts = urlsplit(route.request.url)
                request_host = (request_parts.hostname or "").lower().rstrip(".")
                if (route.request.is_navigation_request()
                        and (request_parts.scheme != "https"
                             or request_host not in marketplace_hosts)):
                    route.abort()
                elif route.request.resource_type in {"image", "media", "font"}:
                    route.abort()
                else:
                    route.continue_()

            # Product images and decorative fonts are not needed for stock checks.
            page.route("**/*", allow_page_request)
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            final_url = page.url
            final_parts = urlsplit(final_url)
            if (marketplace == "Shopee" and "/verify/" in final_parts.path.casefold()):
                raise SourceCheckFailure("AKSES_DIBATASI", "SHOPEE_VERIFIKASI")
            if response is None:
                app.logger.info("Halaman produk %s tidak memberi respons yang bisa dibaca", marketplace)
                raise SourceCheckFailure("GAGAL", "HTTP_GAGAL")
            if response.status >= 400:
                if response.status == 429:
                    raise SourceCheckFailure(
                        "AKSES_DIBATASI", "RATE_LIMITED",
                        response.headers.get("retry-after"),
                    )
                if response.status == 526:
                    raise SourceCheckFailure("GAGAL", "TLS_GATEWAY_ERROR")
                if response.status in {401, 403, 503}:
                    raise SourceCheckFailure("AKSES_DIBATASI", "TANTANGAN_AKSES")
                raise SourceCheckFailure("GAGAL", "HTTP_GAGAL")
            original_host = (urlsplit(target_url).hostname or "").lower().rstrip(".")
            if (not validate_target_url(final_url)
                    or (final_parts.hostname or "").lower().rstrip(".") not in marketplace_hosts):
                app.logger.warning("Navigasi %s dialihkan ke host lain; pengecekan dihentikan", marketplace)
                raise SourceCheckFailure("AKSES_DIBATASI", "REDIRECT_DILARANG")
            try:
                page.locator("body").wait_for(state="visible", timeout=5000)
                # Give the selected variant's public product details time to render.
                page.wait_for_timeout(5000)
                if requested_variant_label:
                    page.get_by_text(
                        requested_variant_label, exact=False
                    ).first.wait_for(state="visible", timeout=12000)
            except PlaywrightTimeoutError:
                pass
            body_text = page.locator("body").inner_text(timeout=5000)
            rendered_page_title = page.title()
            if (marketplace == "Shopee"
                    and (urlsplit(final_url).path.rstrip("/") == ""
                         or (len(body_text) < 1200
                             and re.search(r"shopee indonesia.*situs belanja online", page.title(), re.I)))):
                # Some Shopee responses route the query-string product URL to
                # the storefront home. Retry the same public item path without
                # tracking/variant query parameters; still select the requested
                # human-readable variant below when the product page loads.
                clean_product_url = urlunsplit((
                    target_parts.scheme, target_parts.netloc, target_parts.path, "", ""
                ))
                if clean_product_url != target_url:
                    app.logger.warning(
                        "Shopee mengirim beranda untuk URL produk; mencoba ulang URL produk tanpa query"
                    )
                    try:
                        page.goto(
                            clean_product_url, wait_until="domcontentloaded", timeout=25000
                        )
                        page.wait_for_timeout(7000)
                    except PlaywrightTimeoutError:
                        pass
                    final_url = page.url
                    final_parts = urlsplit(final_url)
                    if (not validate_target_url(final_url)
                            or (final_parts.hostname or "").lower().rstrip(".") not in marketplace_hosts):
                        app.logger.warning(
                            "URL Shopee bersih dialihkan ke alamat yang tidak diizinkan; pengecekan dihentikan"
                        )
                        if "/verify/" in final_parts.path.casefold():
                            raise SourceCheckFailure("AKSES_DIBATASI", "SHOPEE_VERIFIKASI")
                        raise SourceCheckFailure("AKSES_DIBATASI", "REDIRECT_DILARANG")
                    body_text = page.locator("body").inner_text(timeout=5000)
                if (len(body_text) < 1200
                        and re.search(r"shopee indonesia.*situs belanja online", page.title(), re.I)):
                    app.logger.warning(
                        "Shopee tetap mengembalikan beranda, bukan halaman produk "
                        "(url_akhir=%s, judul=%r, panjang_teks=%d)",
                        final_url, page.title(), len(body_text),
                    )
                    raise SourceCheckFailure("AKSES_DIBATASI", "SHOPEE_VERIFIKASI")
            if (marketplace == "Shopee"
                    and urlsplit(final_url).path.rstrip("/") == ""):
                app.logger.warning(
                    "Shopee mengirim halaman beranda untuk URL produk; pengecekan stok dihentikan"
                )
                raise SourceCheckFailure("AKSES_DIBATASI", "SHOPEE_VERIFIKASI")
            if marketplace == "Shopee" and len(body_text) < 1200:
                # A product title in metadata is not enough: the rendered body
                # must contain actual product details before parsing or saving it.
                app.logger.warning(
                    "Shopee hanya mengirim kerangka halaman tanpa detail produk "
                    "(url_akhir=%s, judul=%r, panjang_teks=%d); data lama dipertahankan",
                    final_url, page.title(), len(body_text),
                )
                raise SourceCheckFailure("GAGAL", "HALAMAN_TIDAK_LENGKAP")
            lowered_text = body_text.casefold()
            stock_indicator = page.evaluate("""() => {
                const visible = element => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const nodes = [...document.querySelectorAll('span,div,p,strong,b')]
                    .filter(element => visible(element) && element.children.length === 0);
                const quantityNodes = nodes.filter(element =>
                    /^(kuantitas|quantity)$/i.test((element.innerText || element.textContent || '').trim())
                );
                for (const element of nodes) {
                    const label = (element.innerText || element.textContent || '')
                        .trim().replace(/\\s+/g, ' ').toLocaleLowerCase('id-ID');
                    if (!/^(tersedia(?:\\s+[\\d.,]+)?|tersisa\\s+[\\d.,]+|stok tersedia|stok habis|habis|sold out|out of stock)$/.test(label))
                        continue;
                    const rect = element.getBoundingClientRect();
                    if (quantityNodes.some(quantity => {
                        const quantityRect = quantity.getBoundingClientRect();
                        return Math.abs(rect.top - quantityRect.top) <= 140 &&
                            Math.abs(rect.left - quantityRect.left) <= 1000;
                    })) return label;
                }
                return '';
            }""")
            selected_variant_selector = "button,[role='radio'],[role='option']"
            if marketplace == "Lazada":
                selected_variant_selector += ", [class*='sku-variable-img-wrap-selected']"
            selected_variant_labels = page.locator(selected_variant_selector).evaluate_all(
                "elements => elements.filter(element => {"
                "const state = (element.className || '').toString();"
                "return element.getAttribute('aria-pressed') === 'true' || "
                "element.getAttribute('aria-selected') === 'true' || "
                "/selected|checked/i.test(state);"
                "}).map(element => (element.innerText || element.textContent || '').trim())"
                ".filter(text => text && text.length <= 60)"
            )
            challenge_markers = (
                "captcha", "verify you are human", "i'm not a robot",
                "aktivitas tidak biasa", "verifikasi bahwa anda manusia",
                "access denied", "akses ditolak",
            )
            if any(marker in lowered_text for marker in challenge_markers):
                app.logger.warning(
                    "%s meminta verifikasi atau menolak akses; pengecekan dihentikan", marketplace
                )
                raise SourceCheckFailure("AKSES_DIBATASI", "TANTANGAN_AKSES")

            if marketplace == "Shopee":
                option_labels = page.evaluate("""() => {
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0 &&
                            style.visibility !== 'hidden' && style.display !== 'none';
                    };
                    const labels = [...document.querySelectorAll('label,span,div')]
                        .filter(element => element.children.length === 0 &&
                            /^(jenis|varian|tipe|type)$/i.test((element.innerText || '').trim()));
                    let group = null;
                    for (const label of labels) {
                        let parent = label.parentElement;
                        for (let depth = 0; parent && depth < 6; depth++, parent = parent.parentElement) {
                            const controls = [...parent.querySelectorAll(
                                'button,[role="radio"],[role="option"],[class*="variation"],[class*="sku-item"]'
                            )].filter(visible);
                            if (controls.length >= 2 && controls.length <= 60) {
                                group = controls;
                                break;
                            }
                        }
                        if (group) break;
                    }
                    if (!group) return [];
                    const blocked = /beli|keranjang|cart|chat|toko|kuantitas|jumlah|search|cari/i;
                    return [...new Set(group.map(element => ({
                        label: (element.getAttribute('aria-label') || element.innerText ||
                            element.textContent || '').trim().replace(/\\s+/g, ' '),
                        disabled: !!element.disabled || element.getAttribute('aria-disabled') === 'true'
                    })).filter(item => item.label && item.label.length <= 90 && !blocked.test(item.label))
                      .map(item => JSON.stringify(item)))].map(item => JSON.parse(item));
                }""")
                if requested_variant_label:
                    matching_options = [
                        option for option in option_labels
                        if requested_variant_label.casefold() in re.sub(
                            r"\s+", " ", option["label"]
                        ).strip().casefold()
                    ]
                    if matching_options:
                        option_labels = matching_options
                    else:
                        # Some Shopee layouts wrap the label in custom elements
                        # that the option-group detector cannot enumerate. Keep
                        # a visible-text locator fallback for this requested SKU.
                        try:
                            visible_match_count = page.get_by_text(
                                requested_variant_label, exact=False
                            ).count()
                        except Exception:
                            visible_match_count = 0
                        if visible_match_count:
                            option_labels = [{
                                "label": requested_variant_label,
                                "disabled": False,
                            }]
                            app.logger.info(
                                "Shopee %s: White Twinpack ditemukan lewat teks halaman",
                                target_url,
                            )
                        else:
                            option_labels = []
                            app.logger.warning(
                                "Shopee %s: teks White Twinpack tidak tersedia di halaman "
                                "(judul=%r, panjang_teks=%d)",
                                target_url, page.title(), len(body_text),
                            )
                app.logger.info(
                    "Shopee %s: %d opsi varian dipantau",
                    target_url, len(option_labels),
                )
                for option in option_labels[:40]:
                    option_label = option["label"]
                    clicked = False
                    if not option.get("disabled"):
                        try:
                            page.get_by_text(option_label, exact=True).first.click(timeout=2500)
                            # Shopee updates the selected SKU's price and stock
                            # asynchronously after a variant click.
                            page.wait_for_timeout(2500)
                            clicked = True
                        except PlaywrightTimeoutError:
                            pass
                    snapshot = page.evaluate("""() => ({
                        text: document.body ? document.body.innerText : '',
                        stock_indicator: (() => {
                            const visible = element => {
                                const rect = element.getBoundingClientRect();
                                const style = getComputedStyle(element);
                                return rect.width > 0 && rect.height > 0 &&
                                    style.visibility !== 'hidden' && style.display !== 'none';
                            };
                            const nodes = [...document.querySelectorAll('span,div,p,strong,b')]
                                .filter(element => visible(element) && element.children.length === 0);
                            const quantityNodes = nodes.filter(element =>
                                /^(kuantitas|quantity)$/i.test((element.innerText || element.textContent || '').trim())
                            );
                            for (const element of nodes) {
                                const label = (element.innerText || element.textContent || '')
                                    .trim().replace(/\\s+/g, ' ').toLocaleLowerCase('id-ID');
                                if (!/^(tersedia(?:\\s+[\\d.,]+)?|tersisa\\s+[\\d.,]+|stok tersedia|stok habis|habis|sold out|out of stock)$/.test(label))
                                    continue;
                                const rect = element.getBoundingClientRect();
                                if (quantityNodes.some(quantity => {
                                    const quantityRect = quantity.getBoundingClientRect();
                                    return Math.abs(rect.top - quantityRect.top) <= 140 &&
                                        Math.abs(rect.left - quantityRect.left) <= 1000;
                                })) return label;
                            }
                            return '';
                        })(),
                        price: document.querySelector(
                            'meta[property="product:price:amount"],meta[itemprop="price"]'
                        )?.content || [...document.querySelectorAll(
                            '[data-sqe="price"],[data-testid*="price"],'
                            + '.product-briefing [class*="price"],.product-briefing [class*="Price"]'
                        )].map(el => (el.innerText || el.textContent || '').trim())
                          .find(text => /Rp\\.?\\s*[\\d.,]+/i.test(text)) || '',
                    })""")
                    variant_snapshots.append({
                        "variant": option_label,
                        "disabled": option.get("disabled", False),
                        "clicked": clicked,
                        **snapshot,
                    })

            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()
    except SourceCheckFailure:
        _close_marketplace_page(page, browser)
        raise
    except Exception as error:
        # Playwright can fail when Chromium is not installed or the site is unavailable.
        _close_marketplace_page(page, browser)
        app.logger.info("Pengecekan Playwright %s gagal: %s", marketplace, type(error).__name__)
        reason = "TIMEOUT" if "timeout" in type(error).__name__.casefold() else "PROSES_GAGAL"
        raise SourceCheckFailure("GAGAL", reason) from error

    schema_products = _schema_products(soup)
    title_tag = soup.select_one("meta[property='og:title'], meta[name='title']")
    heading = soup.select_one("h1")
    page_title = ((title_tag.get("content", "") if title_tag else "")
                  or (heading.get_text(" ", strip=True) if heading else "")
                  or (soup.title.get_text(" ", strip=True) if soup.title else "")
                  or (schema_products[0]["name"] if len(schema_products) == 1 else ""))
    page_title = re.sub(
        r"\s*[|–-]\s*(?:Shopee Indonesia|Blibli(?:\.com)?)\s*$", "", page_title,
        flags=re.IGNORECASE,
    ).strip()
    path_parts = [part for part in urlsplit(target_url).path.split("/") if part]
    slug = path_parts[1] if marketplace == "Blibli" and len(path_parts) > 1 else (
        path_parts[0] if path_parts else ""
    )
    if marketplace == "Shopee":
        slug = re.sub(r"-i\.\d+\.\d+$", "", slug)
    elif marketplace == "Blibli":
        slug = re.sub(r"/ps--.*$", "", slug, flags=re.IGNORECASE)
    slug_title = re.sub(r"[-_]+", " ", slug).strip()
    is_store_heading = any(
        marker in page_title.casefold()
        for marker in ("toko online", "official store", "officialstore")
    )
    title = slug_title if is_store_heading and slug_title else page_title or slug_title
    if not title or any(site in title.casefold() for site in ("shopee indonesia", "blibli.com")):
        app.logger.info("Nama produk %s tidak ditemukan pada halaman yang dirender", marketplace)
        return None
    lazada_unavailable = marketplace == "Lazada" and _lazada_unavailable_page(
        rendered_page_title, body_text
    )
    if lazada_unavailable:
        app.logger.info("SKU Lazada tidak tersedia di halaman; harga/stok belum terverifikasi")
        return {
            "name": title,
            "price": None,
            "price_currency": _currency_for_host(original_host),
            "status": "TIDAK DIKETAHUI",
            "stock_quantity": None,
            "variant": None,
            "variant_total": None,
            "product_url": target_url,
        }
    normalized_title = normalize_product_name(title)
    schema_product = next(
        (item for item in schema_products
         if normalize_product_name(item["name"]) == normalized_title),
        schema_products[0] if len(schema_products) == 1 else None,
    )

    price_tag = soup.select_one(
        "meta[property='product:price:amount'], meta[property='og:price:amount'], "
        "meta[itemprop='price'], [itemprop='price'][content]"
    )
    price = parse_price(price_tag.get("content")) if price_tag else None
    if price is None and marketplace == "Lazada":
        # Keep the price lookup inside Lazada's product-detail price module.
        # Broad page scans can pick a recommendation card's price instead.
        for price_node in soup.select(
            '#module_product_price_1, [data-spm="product_price"], '
            '[class*="pdp-price"], [class*="pdp-product-price"]'
        ):
            price_match = re.search(
                r"Rp\.?\s*[\d.,]+", price_node.get_text(" ", strip=True),
                flags=re.IGNORECASE,
            )
            if price_match:
                price = parse_price(price_match.group(0))
                if price is not None:
                    break
    if price is None and marketplace != "Lazada":
        # Marketplaces may render the product price in the page rather than
        # exposing Product/Offer metadata.
        for price_node in soup.select(
            '[data-sqe="price"], [data-testid*="price"], '
            '[data-sqe*="price"], .product-briefing [class*="price"], '
            '.product-briefing [class*="Price"]'
        ):
            price_match = re.search(
                r"Rp\.?\s*[\d.,]+", price_node.get_text(" ", strip=True),
                flags=re.IGNORECASE,
            )
            if price_match:
                price = parse_price(price_match.group(0))
                if price is not None:
                    break
    if price is None and schema_product:
        price = schema_product["price"]

    stock_quantity = None

    selected_variants = list(dict.fromkeys(
        label for label in selected_variant_labels
        if not any(word in label.casefold() for word in ("beli", "keranjang", "toko", "chat"))
    ))
    variant_label = (requested_variant_label
                     or ", ".join(selected_variants)[:255]
                     or None)
    # Do not show Shopee's internal display_model_id as a user-facing variant;
    # use the requested human-readable variant label when the page omits it.

    stock_status = _marketplace_stock_status(
        marketplace, stock_indicator, body_text,
    )
    if (stock_status == "TIDAK DIKETAHUI" and schema_product
            and marketplace != "Shopee"):
        stock_status = schema_product["status"]
    if marketplace == "Lazada":
        # The body also contains recommendations; only accept a stock label
        # located next to the product quantity control or exact Product schema.
        indicator_status = _marketplace_stock_status("Lazada", stock_indicator)
        if indicator_status in {"TERSEDIA", "HABIS"}:
            stock_status = indicator_status
        elif schema_product and schema_product["status"] in {"TERSEDIA", "HABIS"}:
            stock_status = schema_product["status"]
        else:
            stock_status = "TIDAK DIKETAHUI"
            stock_quantity = None

    if marketplace == "Shopee" and stock_status == "TIDAK DIKETAHUI":
        app.logger.warning(
            "Shopee tidak dapat memastikan stok: judul=%r teks=%d indikator=%r "
            "harga=%r",
            page_title, len(body_text), stock_indicator,
            price,
        )

    base_product = {
        "name": title,
        "price": price,
        "price_currency": _currency_for_host(original_host),
        "status": stock_status,
        "stock_quantity": stock_quantity,
        "variant": variant_label,
        "variant_total": None,
        "product_url": target_url,
    }
    if requested_variant_label:
        initially_selected = {
            label.strip().casefold() for label in selected_variant_labels if label.strip()
        }
        requested_snapshot = next((
            snapshot for snapshot in variant_snapshots
            if snapshot["variant"].casefold() == requested_variant_label.casefold()
            and not snapshot.get("disabled")
            and (snapshot.get("clicked")
                 or snapshot["variant"].strip().casefold() in initially_selected)
        ), None)
        if requested_snapshot is None:
            # A generic product page does not prove the selected SKU's price
            # or stock. Do not attach the base product's values to this variant.
            return {
                **base_product,
                "price": None,
                "status": "TIDAK DIKETAHUI",
                "stock_quantity": None,
            }
    if marketplace != "Shopee" or not variant_snapshots:
        return base_product
    # If the DOM exposed options but Playwright could not select any of them,
    # keep the original page observation. It may still contain a reliable
    # quantity or an enabled purchase action for the already-selected option.
    if not any(snapshot.get("clicked") for snapshot in variant_snapshots):
        return base_product

    products_by_variant = {}
    for snapshot in variant_snapshots:
        output_variant_label = requested_variant_label or snapshot["variant"]
        text = snapshot.get("text", "")
        lowered = text.casefold()
        quantity = None
        snapshot_price = parse_price(snapshot.get("price"))


        snapshot_status = "TIDAK DIKETAHUI"
        if snapshot.get("clicked") and not snapshot.get("disabled"):
            snapshot_status = _marketplace_stock_status(
                "Shopee", snapshot.get("stock_indicator"), text,
            )

        initial_selected = {
            label.strip().casefold() for label in selected_variant_labels if label.strip()
        }
        is_requested_variant = (
            requested_variant_label
            and output_variant_label.casefold() == requested_variant_label.casefold()
        )
        is_initial_variant = snapshot["variant"].strip().casefold() in initial_selected
        if is_initial_variant:
            if (snapshot_status == "TIDAK DIKETAHUI"
                    and base_product["status"] in {"TERSEDIA", "HABIS"}):
                snapshot_status = base_product["status"]
                quantity = base_product["stock_quantity"]
            if snapshot_price is None:
                snapshot_price = base_product["price"]

        if is_requested_variant:
            app.logger.info(
                "Shopee %s varian %s: harga=%s stok=%s jumlah=%s",
                target_url, output_variant_label, snapshot_price,
                snapshot_status, quantity,
            )

        products_by_variant[output_variant_label.casefold()] = {
            "name": title,
            "price": snapshot_price,
            "status": snapshot_status,
            "stock_quantity": quantity,
            "variant": output_variant_label[:255],
            "variant_total": len({option["label"].casefold() for option in option_labels}),
            "product_url": target_url,
        }
    variant_products = list(products_by_variant.values())
    # Shopee sometimes lets the option click succeed while its stock/price
    # widgets remain stale or unreadable. Keep the verified initial-page
    # observation in that case; otherwise a previously visible "Tersedia"
    # state would be replaced by unknown just because variant details failed.
    if (variant_products and not requested_variant_label
            and base_product["status"] in {"TERSEDIA", "HABIS"}
            and not any(item["status"] in {"TERSEDIA", "HABIS"}
                        for item in variant_products)):
        return base_product
    return variant_products or [base_product]


def fetch_catalog_products(target_url, headers):
    """Read a listing page and its explicit pagination links, with a hard cap."""
    original_host = (urlsplit(target_url).hostname or "").lower().rstrip(".")
    if (original_host in {"focusnusantara.com", "www.focusnusantara.com"}
            and _is_direct_product_page(target_url)):
        product = _fetch_rendered_focus_product(target_url)
        found = [product] if product else []
        app.logger.info(
            "Hasil target Focus Nusantara %s: %d produk ditemukan", target_url, len(found)
        )
        return found
    if original_host in {"shopee.co.id", "www.shopee.co.id"}:
        product = _fetch_rendered_marketplace_product(
            target_url, "Shopee", {"shopee.co.id", "www.shopee.co.id"},
        )
        found = product if isinstance(product, list) else ([product] if product else [])
        app.logger.info(
            "Hasil target Shopee %s: %d produk ditemukan", target_url, len(found)
        )
        return found
    if (original_host in {"blibli.com", "www.blibli.com"}
            and urlsplit(target_url).path.startswith("/p/")):
        product = _fetch_rendered_marketplace_product(
            target_url, "Blibli", {"blibli.com", "www.blibli.com"},
        )
        found = product if isinstance(product, list) else ([product] if product else [])
        app.logger.info(
            "Hasil target Blibli %s: %d produk ditemukan", target_url, len(found)
        )
        return found
    if (original_host in {"lazada.co.id", "www.lazada.co.id"}
            and urlsplit(target_url).path.startswith("/products/")):
        product = _fetch_rendered_marketplace_product(
            target_url, "Lazada", {"lazada.co.id", "www.lazada.co.id"},
        )
        found = product if isinstance(product, list) else ([product] if product else [])
        app.logger.info(
            "Hasil target Lazada %s: %d produk ditemukan", target_url, len(found)
        )
        return found

    current_url = target_url
    visited = set()
    products = {}
    pages_fetched = 0
    for page_number in range(10):
        if current_url in visited or not validate_target_url(current_url):
            break
        visited.add(current_url)
        request_headers = headers
        if original_host in {"tokopedia.com", "www.tokopedia.com"}:
            request_headers = dict(headers)
            request_headers["User-Agent"] = TOKOPEDIA_USER_AGENT
        response = requests.get(
            current_url, headers=request_headers, timeout=(5, 15), allow_redirects=False,
        )
        if response.status_code != 200:
            app.logger.warning(
                "Target %s merespons HTTP %s; pengecekan dihentikan",
                current_url, response.status_code,
            )
            if response.status_code == 429:
                raise SourceCheckFailure(
                    "AKSES_DIBATASI", "RATE_LIMITED",
                    response.headers.get("Retry-After"),
                )
            if response.status_code == 526:
                raise SourceCheckFailure("GAGAL", "TLS_GATEWAY_ERROR")
            if response.status_code in {401, 403, 503}:
                raise SourceCheckFailure("AKSES_DIBATASI", "TANTANGAN_AKSES")
            raise SourceCheckFailure("GAGAL", "HTTP_GAGAL")
        pages_fetched += 1
        soup = BeautifulSoup(response.text, "html.parser")
        page_products = extract_products(soup, original_host)
        if (original_host in {"iqos.com", "www.iqos.com"}
                and _is_direct_product_page(current_url)):
            iqos_product = _iqos_detail_product(soup, current_url)
            page_products = [iqos_product] if iqos_product else []
        if (original_host in {"tokopedia.com", "www.tokopedia.com"}
                and _is_direct_product_page(current_url)):
            name = _tokopedia_detail_name(soup, current_url)
            if _is_relevant_instax_item(name):
                page_products = [{
                    "name": name,
                    "price": _tokopedia_detail_price(soup, current_url),
                    "price_currency": "IDR",
                    "status": _tokopedia_detail_stock(soup, current_url),
                    "product_url": current_url,
                }]
            else:
                page_products = []
        if _is_direct_product_page(current_url):
            target_path = urlsplit(current_url).path.rstrip("/").casefold()
            is_relevant_product = (
                _is_relevant_iqos_product
                if original_host in {"iqos.com", "www.iqos.com"}
                else _is_relevant_instax_item
            )
            matching_products = [
                item for item in page_products
                if item.get("product_url")
                and urlsplit(urljoin(current_url, item["product_url"])).path.rstrip("/").casefold()
                == target_path
            ]
            if matching_products and any(
                is_relevant_product(item.get("name", ""))
                for item in matching_products
            ):
                page_products = matching_products
            else:
                main_title = soup.select_one(
                    "h1.product_title, h1.product-title, h1[itemprop='name'], main h1, h1"
                )
                main_name = main_title.get_text(" ", strip=True) if main_title else ""
                matching_title = next(
                    (item for item in page_products
                     if " ".join(item.get("name", "").casefold().split())
                     == " ".join(main_name.casefold().split())),
                    None,
                )
                if is_relevant_product(main_name):
                    main_product = dict(matching_title or {
                        "name": main_name,
                        "price": None,
                        "price_currency": _currency_for_host(original_host),
                        "status": "TIDAK DIKETAHUI",
                    })
                    if (original_host in {"galaxy.co.id", "www.galaxy.co.id"}
                            and main_product.get("price") is None):
                        main_product["price"] = _galaxy_detail_price(soup)
                        main_product["price_currency"] = "IDR"
                    main_product["product_url"] = current_url
                    page_products = [main_product]
                else:
                    page_products = []
            if (original_host in {"galaxy.co.id", "www.galaxy.co.id"}
                    and _is_direct_product_page(current_url)):
                galaxy_price = _galaxy_detail_price(soup)
                for item in page_products:
                    if item.get("price") is None and galaxy_price is not None:
                        item["price"] = galaxy_price
                    item["price_currency"] = "IDR"
            if (original_host in {"sentradigital.com", "www.sentradigital.com"}
                    and _is_direct_product_page(current_url)):
                for item in page_products:
                    if item.get("price") is None:
                        item["price"] = _price_in(soup)
                    if item.get("status") == "TIDAK DIKETAHUI":
                        item["status"] = _sentradigital_detail_stock(soup)
                    item["price_currency"] = _currency_for_host(original_host)
            if (original_host in {"camera.co.id", "www.camera.co.id"}
                    and _is_direct_product_page(current_url)):
                camera_price = _camera_co_id_detail_price(soup)
                for item in page_products:
                    if camera_price is not None:
                        item["price"] = camera_price
                    item["price_currency"] = "IDR"
            if (original_host in {"tokopedia.com", "www.tokopedia.com"}
                    and _is_direct_product_page(current_url)):
                tokopedia_price = _tokopedia_detail_price(soup, current_url)
                tokopedia_stock = _tokopedia_detail_stock(soup, current_url)
                for item in page_products:
                    if tokopedia_price is not None:
                        item["price"] = tokopedia_price
                    item["price_currency"] = "IDR"
                    item["status"] = tokopedia_stock
        relevant_item = (
            (_is_relevant_iqos_product if _is_direct_product_page(current_url)
             else _is_relevant_iqos_terea_item)
            if original_host in {"iqos.com", "www.iqos.com"}
            else _is_relevant_instax_item
        )
        page_products = [
            item for item in page_products
            if relevant_item(item.get("name", ""))
        ]
        if _is_direct_product_page(current_url):
            # Do not attach related-product cards to a monitored detail URL.
            target_path = urlsplit(current_url).path.rstrip("/").casefold()
            page_products = [
                item for item in page_products
                if urlsplit(urljoin(current_url, item.get("product_url") or current_url))
                .path.rstrip("/").casefold() == target_path
            ]
        if (not page_products and original_host == "shop.8storeytree.com"
                and "/products/" in urlsplit(current_url).path):
            title = soup.select_one("h1")
            if title and title.get_text(strip=True):
                page_products = [{
                    "name": title.get_text(" ", strip=True),
                    "price": None,
                    "status": "TIDAK DIKETAHUI",
                    "product_url": current_url,
                }]
        for product in page_products:
            raw_product_url = product.get("product_url")
            candidate_url = urljoin(current_url, raw_product_url) if raw_product_url else ""
            if candidate_url and (
                (urlsplit(candidate_url).hostname or "").lower().rstrip(".") != original_host
                or not validate_target_url(candidate_url)
            ):
                candidate_url = ""
            if not candidate_url and _is_direct_product_page(current_url):
                candidate_url = current_url
            product["product_url"] = candidate_url or None
            if (original_host == "shop.8storeytree.com"
                    and (product.get("product_url") or "/products/" in urlsplit(current_url).path)):
                product_url = product.get("product_url") or current_url
                details = _shopify_product_details(
                    current_url, product_url, headers,
                )
                if details:
                    if details["price"] is not None:
                        product["price"] = details["price"]
                        product["price_currency"] = _currency_for_host(original_host)
                    product["status"] = details["status"]
                    time.sleep(0.25)
            products[product["name"].casefold()] = product
        if _is_direct_product_page(current_url):
            break
        next_url = _next_catalog_page(soup, current_url, original_host)
        if not next_url:
            break
        current_url = next_url
        if page_number < 9:
            time.sleep(1)
    price_count = sum(product["price"] is not None for product in products.values())
    app.logger.info(
        "Hasil target %s: %d halaman dibaca, %d produk ditemukan, %d harga terbaca",
        target_url, pages_fetched, len(products), price_count,
    )
    return list(products.values())


def tandai_produk_target_tidak_diketahui(target_url):
    """Record a failed attempt without treating it as a stock change."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = ProdukDetail.query.filter_by(url_sumber=target_url).all()
    for row in rows:
        # A redirect/error provides no evidence that stock or price changed.
        # Keep the last observation and expose its older verification time.
        if row.status_terakhir_terverifikasi in {"TERSEDIA", "HABIS"}:
            row.status_stok = row.status_terakhir_terverifikasi
        row.terakhir_dicek = now
    if rows:
        db.session.commit()
    return len(rows)


def set_target_check_state(kategori, status, reason=None, now=None, successful=False):
    kategori.status_pengecekan = status
    kategori.alasan_pengecekan = reason
    kategori.waktu_pengecekan_terakhir = now or datetime.utcnow().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    if successful:
        kategori.waktu_berhasil_dibaca = kategori.waktu_pengecekan_terakhir


def retry_after_deadline(value, now=None):
    """Parse Retry-After seconds/date, using a conservative bounded fallback."""
    now = now or datetime.utcnow()
    deadline = None
    if value:
        try:
            seconds = max(0, int(value.strip()))
            deadline = now + timedelta(seconds=seconds)
        except (AttributeError, TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
                deadline = max(now, parsed)
            except (TypeError, ValueError, OverflowError):
                pass
    if deadline is None:
        deadline = now + timedelta(minutes=15)
    return min(deadline, now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")


def set_store_cooldown(host, until, now=None):
    """Persist a rate-limit cooldown for every monitored URL on the same host."""
    now = now or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    for category in KategoriPantauan.query.all():
        category_host = (urlsplit(category.url).hostname or "").lower().rstrip(".")
        if category_host == host:
            category.waktu_cek_berikutnya = until
            set_target_check_state(category, "AKSES_DIBATASI", "RATE_LIMITED", now)


def jalankan_pengecekan_stok(target_urls=None):
    """Fetch only allowlisted HTTPS pages, with redirects disabled."""
    if not scrape_lock.acquire(blocking=False):
        return False
    try:
        with app.app_context():
            targets = KategoriPantauan.query.all()
            if target_urls is not None:
                selected_urls = set(target_urls)
                targets = [target for target in targets if target.url in selected_urls]
            headers = {"User-Agent": SCRAPER_USER_AGENT, "Accept": "text/html"}
            last_request_by_host = {}
            for kategori in targets:
                if not validate_target_url(kategori.url):
                    set_target_check_state(
                        kategori, "GAGAL", "HOST_TIDAK_DIIJINKAN"
                    )
                    db.session.commit()
                    app.logger.warning("Target dilewati karena URL tidak diizinkan")
                    continue
                now_dt = datetime.utcnow()
                if kategori.waktu_cek_berikutnya:
                    try:
                        cooldown_until = datetime.fromisoformat(kategori.waktu_cek_berikutnya)
                    except ValueError:
                        cooldown_until = None
                    if cooldown_until and cooldown_until > now_dt:
                        app.logger.info(
                            "Target %s dilewati sampai %s karena jeda sumber",
                            store_name(kategori.url), kategori.waktu_cek_berikutnya,
                        )
                        continue
                try:
                    # A previous cooldown has expired; this is a new attempt.
                    target_has_baseline = bool(kategori.waktu_berhasil_dibaca)
                    kategori.waktu_cek_berikutnya = None
                    set_target_check_state(kategori, "MEMERIKSA")
                    db.session.commit()
                    host = (urlsplit(kategori.url).hostname or "").lower().rstrip(".")
                    last_request = last_request_by_host.get(host)
                    if last_request is not None:
                        remaining = 15 - (time.monotonic() - last_request)
                        if remaining > 0:
                            time.sleep(remaining)
                    last_request_by_host[host] = time.monotonic()
                    catalog_products = fetch_catalog_products(kategori.url, headers)
                    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    if not catalog_products:
                        set_target_check_state(
                            kategori, "TIDAK_ADA_DATA",
                            "DATA_PRODUK_TIDAK_DITEMUKAN", now,
                        )
                        stale_rows = tandai_produk_target_tidak_diketahui(kategori.url)
                        db.session.commit()
                        app.logger.warning(
                            "Target %s tidak menghasilkan data; %d hasil terakhir dipertahankan "
                            "sebagai data belum terverifikasi",
                            store_name(kategori.url), stale_rows,
                        )
                        time.sleep(5)
                        continue
                    shopee_existing_rows = (
                        ProdukDetail.query.filter_by(url_sumber=kategori.url).all()
                        if is_shopee_product_url(kategori.url) else []
                    )
                    shopee_observed_keys = {
                        (item["name"].casefold(),
                         (item.get("variant") or "").casefold())
                        for item in catalog_products
                    }
                    for product in catalog_products:
                        name = product["name"]
                        variant = product.get("variant")
                        shopee_product = is_shopee_product_url(kategori.url)
                        prior_variant_status = aggregate_variant_status(
                            (item.status_stok, item.varian_produk or item.nama_produk,
                             item.jumlah_varian)
                            for item in ProdukDetail.query.filter_by(
                                url_sumber=kategori.url
                            ).all()
                        ) if shopee_product else None
                        row = ProdukDetail.query.filter_by(
                            nama_produk=name, url_sumber=kategori.url,
                            varian_produk=variant,
                        ).first()
                        if (row is None and not shopee_product
                                and _is_direct_product_page(kategori.url)):
                            target_parts = urlsplit(kategori.url)
                            same_name_rows = ProdukDetail.query.filter_by(
                                nama_produk=name, varian_produk=variant,
                            ).all()
                            row = next((
                                candidate for candidate in same_name_rows
                                if candidate.url_produk
                                and (urlsplit(candidate.url_produk).hostname or "")
                                .lower().removeprefix("www.")
                                == (target_parts.hostname or "").lower().removeprefix("www.")
                                and urlsplit(candidate.url_produk).path.rstrip("/")
                                == target_parts.path.rstrip("/")
                                and urlsplit(candidate.url_produk).query == target_parts.query
                            ), None)
                        if (row is None and not shopee_product
                                and not _is_direct_product_page(kategori.url)):
                            target_host = (urlsplit(kategori.url).hostname or "").lower().removeprefix("www.")
                            same_store_rows = ProdukDetail.query.filter_by(
                                nama_produk=name, varian_produk=variant,
                            ).all()
                            row = next(
                                (candidate for candidate in same_store_rows
                                 if (urlsplit(candidate.url_sumber).hostname or "")
                                 .lower().removeprefix("www.") == target_host),
                                None,
                            )
                        if row is None and variant is None:
                            # Reuse the pre-variant row rather than creating a
                            # duplicate after dropping the old opaque model ID.
                            row = ProdukDetail.query.filter_by(
                                nama_produk=name, url_sumber=kategori.url
                            ).first()
                        elif row is None:
                            row = ProdukDetail.query.filter_by(
                                nama_produk=name, url_sumber=kategori.url,
                                varian_produk=None,
                            ).first()
                        notification_name = (
                            f"{name} ({variant})" if variant and variant.casefold() not in name.casefold()
                            else name
                        )
                        if row:
                            previous_confirmed_status = (
                                row.status_terakhir_terverifikasi
                                or (row.status_stok if row.status_stok in {"TERSEDIA", "HABIS"}
                                    else None)
                            )
                            # An unreadable response is not a stock transition.
                            # Keep the last confirmed state and mark it stale by
                            # advancing the attempt timestamp only.
                            effective_status = preserve_last_confirmed_stock(
                                product["status"], previous_confirmed_status,
                                row.status_stok,
                            )
                            if should_notify_stock_change(
                                    previous_confirmed_status, product["status"],
                                    target_has_baseline):
                                db.session.add(Notifikasi(
                                    nama_produk=notification_name,
                                    toko=store_name(kategori.url), jenis="stok",
                                    nilai_lama=previous_confirmed_status,
                                    nilai_baru=product["status"],
                                    sumber_url=product.get("product_url") or kategori.url,
                                    email_status="MENUNGGU",
                                ))
                            previous_confirmed_price = (
                                row.harga_terakhir_terbaca
                                if row.harga_terakhir_terbaca is not None else row.harga
                            )
                            previous_price_currency = (
                                row.mata_uang_terakhir or row.mata_uang
                            )
                            if (previous_confirmed_price is not None
                                    and product["price"] is not None
                                    and previous_price_currency == product.get("price_currency")
                                    and previous_confirmed_price != product["price"]):
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="harga",
                                    nilai_lama=format_money(previous_confirmed_price, previous_price_currency),
                                    nilai_baru=format_money(product["price"], product.get("price_currency")),
                                    sumber_url=product.get("product_url") or kategori.url,
                                    email_status="MENUNGGU",
                                ))
                            row.status_stok = effective_status
                            row.terakhir_dicek = now
                            if product["status"] in {"TERSEDIA", "HABIS"}:
                                row.status_terakhir_terverifikasi = product["status"]
                                row.waktu_terakhir_terverifikasi = now
                            row.stok_kuantitas = product.get("stock_quantity")
                            row.varian_produk = variant
                            row.url_produk = product.get("product_url") or row.url_produk
                            if product["price"] is not None:
                                row.harga = product["price"]
                                row.mata_uang = product.get("price_currency")
                                row.harga_terakhir_terbaca = product["price"]
                                row.mata_uang_terakhir = product.get("price_currency")
                                row.waktu_harga_terakhir_terbaca = now
                            row.jumlah_varian = product.get("variant_total") or row.jumlah_varian
                        else:
                            db.session.add(ProdukDetail(
                                nama_produk=name,
                                status_stok=product["status"],
                                terakhir_dicek=now,
                                url_sumber=kategori.url,
                                url_produk=(product.get("product_url")
                                            or (kategori.url
                                                if _is_direct_product_page(kategori.url)
                                                else None)),
                                harga=product["price"],
                                mata_uang=product.get("price_currency")
                                if product["price"] is not None else None,
                                stok_kuantitas=product.get("stock_quantity"),
                                varian_produk=variant,
                                jumlah_varian=product.get("variant_total"),
                                status_terakhir_terverifikasi=(
                                    product["status"]
                                    if product["status"] in {"TERSEDIA", "HABIS"}
                                    else None
                                ),
                                waktu_terakhir_terverifikasi=(
                                    now if product["status"] in {"TERSEDIA", "HABIS"}
                                    else None
                                ),
                                harga_terakhir_terbaca=product["price"],
                                mata_uang_terakhir=product.get("price_currency")
                                if product["price"] is not None else None,
                                waktu_harga_terakhir_terbaca=(
                                    now if product["price"] is not None else None
                                ),
                            ))
                            if should_notify_stock_change(
                                    None, product["status"], target_has_baseline):
                                db.session.add(Notifikasi(
                                    nama_produk=notification_name,
                                    toko=store_name(kategori.url), jenis="stok",
                                    nilai_lama="TIDAK DIKETAHUI", nilai_baru="TERSEDIA",
                                    sumber_url=product.get("product_url") or kategori.url,
                                    email_status="MENUNGGU",
                                ))
                        if shopee_product:
                            db.session.flush()
                            current_variant_status = aggregate_variant_status(
                                (item.status_stok, item.varian_produk or item.nama_produk,
                                 item.jumlah_varian)
                                for item in ProdukDetail.query.filter_by(
                                    url_sumber=kategori.url
                                ).all()
                            )
                            app.logger.info(
                                "Ringkasan varian Shopee %s: %s -> %s",
                                kategori.url, prior_variant_status, current_variant_status,
                            )
                    if _is_direct_product_page(kategori.url) and not shopee_product:
                        observed_products = {
                            (item["name"].casefold(),
                             (item.get("variant") or "").casefold())
                            for item in catalog_products
                        }
                        target_path = urlsplit(kategori.url).path.rstrip("/").casefold()
                        for stale_row in ProdukDetail.query.filter_by(
                                url_sumber=kategori.url).all():
                            row_key = (stale_row.nama_produk.casefold(),
                                       (stale_row.varian_produk or "").casefold())
                            product_path = urlsplit(
                                stale_row.url_produk or ""
                            ).path.rstrip("/").casefold()
                            if (row_key not in observed_products
                                    or (product_path and product_path != target_path)):
                                db.session.delete(stale_row)
                    if shopee_existing_rows:
                        for old_row in shopee_existing_rows:
                            row_key = (
                                old_row.nama_produk.casefold(),
                                (old_row.varian_produk or "").casefold(),
                            )
                            if row_key not in shopee_observed_keys:
                                # Partial variant enumeration must not erase a
                                # prior observation for variants not returned.
                                if old_row.status_terakhir_terverifikasi in {"TERSEDIA", "HABIS"}:
                                    old_row.status_stok = old_row.status_terakhir_terverifikasi
                                old_row.terakhir_dicek = now
                    db.session.commit()
                    stock_unknown = not any(
                        item.get("status") in {"TERSEDIA", "HABIS"}
                        for item in catalog_products
                    )
                    set_target_check_state(
                        kategori, "BERHASIL",
                        "STOK_TIDAK_TERBACA" if stock_unknown else None,
                        now, successful=True,
                    )
                    kategori.waktu_cek_berikutnya = None
                    db.session.commit()
                    app.logger.info("Pengecekan selesai untuk satu target")
                    process_pending_notification_emails()
                except SourceCheckFailure as exc:
                    db.session.rollback()
                    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    set_target_check_state(kategori, exc.status, exc.reason, now)
                    if exc.reason == "RATE_LIMITED":
                        cooldown_until = retry_after_deadline(exc.retry_after)
                        set_store_cooldown(
                            (urlsplit(kategori.url).hostname or "").lower().rstrip("."),
                            cooldown_until, now,
                        )
                        app.logger.warning(
                            "Target %s dibatasi; semua URL pada host ini dijeda sampai %s",
                            store_name(kategori.url), cooldown_until,
                        )
                    elif kategori.waktu_cek_berikutnya:
                        kategori.waktu_cek_berikutnya = None
                    stale_rows = tandai_produk_target_tidak_diketahui(kategori.url)
                    db.session.commit()
                    app.logger.warning(
                        "Target %s: %s; %d hasil terakhir dipertahankan",
                        store_name(kategori.url), exc.reason, stale_rows,
                    )
                except requests.RequestException as exc:
                    db.session.rollback()
                    reason = "TIMEOUT" if "timeout" in exc.__class__.__name__.casefold() else "PROSES_GAGAL"
                    set_target_check_state(kategori, "GAGAL", reason)
                    stale_rows = tandai_produk_target_tidak_diketahui(kategori.url)
                    db.session.commit()
                    app.logger.warning(
                        "Permintaan target %s gagal: %s; %d hasil terakhir dipertahankan "
                        "sebagai data belum terverifikasi",
                        store_name(kategori.url), exc.__class__.__name__, stale_rows,
                    )
                except Exception:
                    db.session.rollback()
                    set_target_check_state(kategori, "GAGAL", "PROSES_GAGAL")
                    stale_rows = tandai_produk_target_tidak_diketahui(kategori.url)
                    db.session.commit()
                    app.logger.warning(
                        "Target %s gagal diproses; %d hasil terakhir dipertahankan "
                        "sebagai data belum terverifikasi",
                        store_name(kategori.url), stale_rows,
                    )
                    app.logger.exception("Pengecekan target gagal")
                time.sleep(5)
        return True
    finally:
        scrape_lock.release()


def jadwalkan_pengecekan(target_urls=None):
    scrape_executor.submit(jalankan_pengecekan_stok, target_urls)


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


@app.route("/asisten-katalog", methods=["POST"])
@login_required
def asisten_katalog():
    language = session.get("language", "id")
    if language not in LANGUAGES:
        language = "id"
    labels = TEXT[language]
    question = (request.form.get("question") or "").strip()[:200]
    category = request.form.get("category", "all")
    if category not in {"all", "available", "out", "cheapest"}:
        category = "all"
    if not question:
        return jsonify(message=labels["chat_empty"], products=[])

    query_terms = search_keywords(question)
    if not query_terms:
        return jsonify(message=labels["chat_empty"], products=[])

    matches = []
    products = ProdukDetail.query.order_by(ProdukDetail.terakhir_dicek.desc()).all()
    for product in products:
        normalized_name = normalize_product_name(product.nama_produk)
        store_tokens = search_keywords(store_name(product.url_sumber))
        product_tokens = set(normalized_name.split()) | set(store_tokens)
        if not all(keyword_matches(term, product_tokens) for term in set(query_terms)):
            continue
        exact_count = sum(
            bool(SEARCH_SYNONYMS.get(term, {term}).intersection(product_tokens))
            for term in set(query_terms)
        )
        matches.append((
            exact_count,
            len(set(query_terms)),
            product,
        ))

    matching_count = len(matches)
    if category == "available":
        matches = [match for match in matches if match[2].status_stok == "TERSEDIA"]
    elif category == "out":
        matches = [match for match in matches if match[2].status_stok == "HABIS"]
    elif category == "cheapest":
        matches = [match for match in matches if (
            match[2].harga is not None or match[2].harga_terakhir_terbaca is not None
        )]

    if category == "cheapest":
        matches.sort(key=lambda match: (
            display_price_currency(match[2].mata_uang if match[2].harga is not None
             else match[2].mata_uang_terakhir),
            match[2].harga is None and match[2].harga_terakhir_terbaca is None,
            display_price_value((match[2].harga if match[2].harga is not None
             else match[2].harga_terakhir_terbaca)
            , match[2].mata_uang if match[2].harga is not None else match[2].mata_uang_terakhir)
            if (match[2].harga is not None or match[2].harga_terakhir_terbaca is not None)
            else Decimal("Infinity"),
            -match[0],
        ))
    else:
        matches.sort(
            key=lambda match: (
                match[0], match[2].terakhir_dicek or "",
            ),
            reverse=True,
        )

    if not matches:
        message = labels["chat_not_found"] if matching_count == 0 else labels["chat_filtered_none"]
        return jsonify(message=message, products=[])

    found = []
    for _, _, product in matches[:8]:
        saved_price = (product.harga if product.harga is not None
                       else product.harga_terakhir_terbaca)
        saved_currency = (product.mata_uang if product.harga is not None
                          else product.mata_uang_terakhir)
        found.append({
            "name": product.nama_produk,
            "store": store_name(product.url_sumber),
            "status": product.status_stok,
            "price": display_price_value(saved_price, saved_currency),
            "price_currency": display_price_currency(saved_currency) if saved_price is not None else None,
            "price_last_read": format_jakarta(product.waktu_harga_terakhir_terbaca),
            "stock_quantity": product.stok_kuantitas,
            "variant": product.varian_produk,
            "last_checked": format_jakarta(product.terakhir_dicek),
            "source": product.url_sumber,
        })
    return jsonify(
        message=labels["chat_found"].format(count=len(found)),
        products=found,
    )


@app.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        # Some Markdown copies escape query separators as \&; normalize before
        # validation/storage so the category filters reach the source unchanged.
        url_baru = (request.form.get("url_produk") or "").strip().replace("\\&", "&")
        url_baru = canonical_target_url(url_baru)
        if not validate_target_url(url_baru):
            flash("url_invalid")
        elif any(
            canonical_target_url(target.url) == url_baru
            for target in KategoriPantauan.query.all()
        ):
            flash("url_duplicate")
        else:
            db.session.add(KategoriPantauan(url=url_baru))
            db.session.commit()
            jadwalkan_pengecekan([url_baru])
            flash("url_added")

    daftar_kategori = KategoriPantauan.query.all()
    source_by_url = {item.url: item for item in daftar_kategori}
    daftar_produk = ProdukDetail.query.order_by(
        ProdukDetail.url_sumber, ProdukDetail.nama_produk
    ).all()
    store_for_product = {}
    for product in daftar_produk:
        store_for_product[product.id] = store_name(product.url_sumber)
    status_for_product = {}
    variant_status_for_product = {}
    stale_for_product = {
        product.id: bool(
            product.status_terakhir_terverifikasi
            and product.waktu_terakhir_terverifikasi
            and (
                product.status_stok == "TIDAK DIKETAHUI"
                or (product.terakhir_dicek
                    and product.terakhir_dicek > product.waktu_terakhir_terverifikasi)
            )
        )
        for product in daftar_produk
    }
    for product in daftar_produk:
        display_status = product.status_stok
        if (display_status == "TIDAK DIKETAHUI"
                and product.status_terakhir_terverifikasi in {"TERSEDIA", "HABIS"}):
            display_status = product.status_terakhir_terverifikasi
        status_for_product[product.id] = display_status
        variant_status_for_product[product.id] = display_status
    shopee_variant_groups = {}
    for product in daftar_produk:
        if is_shopee_product_url(product.url_sumber):
            shopee_variant_groups.setdefault(product.url_sumber, []).append(product)
    for source_url, variants in shopee_variant_groups.items():
        group_status = aggregate_variant_status(
            (variant_status_for_product[item.id], item.varian_produk or item.nama_produk,
             item.jumlah_varian)
            for item in variants
        )
        for variant in variants:
            status_for_product[variant.id] = group_status
    daftar_toko = sorted(set(store_for_product.values()))
    comparisons = {}
    for product in daftar_produk:
        saved_price = (product.harga if product.harga is not None
                       else product.harga_terakhir_terbaca)
        saved_currency = (product.mata_uang if product.harga is not None
                          else product.mata_uang_terakhir)
        if saved_price is None:
            continue
        shown_currency = display_price_currency(saved_currency)
        key = (normalize_product_name(product.nama_produk), shown_currency)
        if not key[0]:
            continue
        offer = {"store": store_for_product[product.id], "price": display_price_value(saved_price, saved_currency),
                 "status": product.status_stok, "currency": shown_currency,
                 "price_last_read": product.waktu_harga_terakhir_terbaca}
        current = comparisons.setdefault(key, {
            "name": product.nama_produk, "currency": saved_currency or "UNKNOWN",
            "offers_by_store": {},
        })
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
                "currency": item["currency"],
                "best": min(comparable_offers, key=lambda offer: offer["price"]),
                # Show the full listed price spread; stock availability only
                # influences which offer is highlighted as the best price.
                "difference": max(offer["price"] for offer in offers)
                              - min(offer["price"] for offer in offers),
            })
    comparison_groups.sort(key=lambda item: item["difference"], reverse=True)
    notifications = Notifikasi.query.order_by(Notifikasi.dibuat_pada.desc()).limit(30).all()
    unread_notifications = Notifikasi.query.filter_by(sudah_dibaca=False).count()
    total_produk = len(daftar_produk)
    total_tersedia = sum(status_for_product[p.id] == "TERSEDIA" for p in daftar_produk)
    total_habis = sum(status_for_product[p.id] == "HABIS" for p in daftar_produk)
    total_tidak_diketahui = sum(status_for_product[p.id] == "TIDAK DIKETAHUI" for p in daftar_produk)
    return render_template(
        "dashboard.html", daftar_kategori=daftar_kategori,
        daftar_produk=daftar_produk, total_produk=total_produk,
        source_by_url=source_by_url,
        status_for_product=status_for_product,
        variant_status_for_product=variant_status_for_product,
        stale_for_product=stale_for_product,
        total_tersedia=total_tersedia, total_habis=total_habis,
        total_tidak_diketahui=total_tidak_diketahui,
        daftar_toko=daftar_toko, store_for_product=store_for_product,
        comparison_groups=comparison_groups, notifications=notifications,
        unread_notifications=unread_notifications,
    )


def initialize_database():
    with app.app_context():
        db.create_all()
        notification_columns = {
            column["name"]
            for column in inspect(db.engine).get_columns(Notifikasi.__tablename__)
        }
        notification_migrations = {
            "sumber_url": "VARCHAR(500)",
            "email_status": "VARCHAR(20) NOT NULL DEFAULT 'TIDAK_PERLU'",
            "email_attempts": "INTEGER NOT NULL DEFAULT 0",
            "email_last_attempt": "VARCHAR(50)",
            "email_next_attempt": "VARCHAR(50)",
            "email_sent_at": "VARCHAR(50)",
            "email_error": "VARCHAR(255)",
        }
        for column_name, column_type in notification_migrations.items():
            if column_name not in notification_columns:
                db.session.execute(text(
                    f"ALTER TABLE {Notifikasi.__tablename__} "
                    f"ADD COLUMN {column_name} {column_type}"
                ))
        db.session.commit()
        category_columns = {
            column["name"]
            for column in inspect(db.engine).get_columns(KategoriPantauan.__tablename__)
        }
        category_migrations = {
            "status_pengecekan": "VARCHAR(30) NOT NULL DEFAULT 'BELUM_DICEK'",
            "alasan_pengecekan": "VARCHAR(50)",
            "waktu_pengecekan_terakhir": "VARCHAR(50)",
            "waktu_berhasil_dibaca": "VARCHAR(50)",
            "waktu_cek_berikutnya": "VARCHAR(50)",
        }
        for column_name, column_type in category_migrations.items():
            if column_name not in category_columns:
                db.session.execute(text(
                    f"ALTER TABLE {KategoriPantauan.__tablename__} "
                    f"ADD COLUMN {column_name} {column_type}"
                ))
        db.session.commit()
        product_columns = {column["name"] for column in inspect(db.engine).get_columns(ProdukDetail.__tablename__)}
        if "url_produk" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN url_produk VARCHAR(500)"
            ))
            db.session.commit()
            product_columns.add("url_produk")
        if "harga" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN harga NUMERIC(14, 2)"
            ))
            db.session.commit()
            product_columns.add("harga")
        if "mata_uang" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN mata_uang VARCHAR(3)"
            ))
            db.session.commit()
            product_columns.add("mata_uang")
        if "stok_kuantitas" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN stok_kuantitas INTEGER"
            ))
            db.session.commit()
            product_columns.add("stok_kuantitas")
        if "varian_produk" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN varian_produk VARCHAR(255)"
            ))
            db.session.commit()
        if "jumlah_varian" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN jumlah_varian INTEGER"
            ))
            db.session.commit()
            product_columns.add("jumlah_varian")
        if "status_terakhir_terverifikasi" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} "
                "ADD COLUMN status_terakhir_terverifikasi VARCHAR(50)"
            ))
            db.session.commit()
            product_columns.add("status_terakhir_terverifikasi")
        if "waktu_terakhir_terverifikasi" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} "
                "ADD COLUMN waktu_terakhir_terverifikasi VARCHAR(50)"
            ))
            db.session.commit()
            product_columns.add("waktu_terakhir_terverifikasi")
        if "harga_terakhir_terbaca" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} "
                "ADD COLUMN harga_terakhir_terbaca NUMERIC(14, 2)"
            ))
            db.session.commit()
            product_columns.add("harga_terakhir_terbaca")
        if "waktu_harga_terakhir_terbaca" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} "
                "ADD COLUMN waktu_harga_terakhir_terbaca VARCHAR(50)"
            ))
            db.session.commit()
            product_columns.add("waktu_harga_terakhir_terbaca")
        if "mata_uang_terakhir" not in product_columns:
            db.session.execute(text(
                f"ALTER TABLE {ProdukDetail.__tablename__} ADD COLUMN mata_uang_terakhir VARCHAR(3)"
            ))
            db.session.commit()
            product_columns.add("mata_uang_terakhir")
        for row in ProdukDetail.query.filter(
            ProdukDetail.status_stok.in_(("TERSEDIA", "HABIS"))
        ).all():
            if not row.status_terakhir_terverifikasi:
                row.status_terakhir_terverifikasi = row.status_stok
            if not row.waktu_terakhir_terverifikasi:
                row.waktu_terakhir_terverifikasi = row.terakhir_dicek
        for row in ProdukDetail.query.filter(ProdukDetail.harga.isnot(None)).all():
            source_host = (urlsplit(row.url_sumber or "").hostname or "").lower().rstrip(".")
            if source_host == "shop.8storeytree.com":
                # This Singapore store reports its prices in SGD. Earlier rows
                # may have been mislabeled IDR, which displayed values like 26
                # as Rp26 instead of converting S$26 to rupiah.
                row.mata_uang = "SGD"
            elif not row.mata_uang:
                row.mata_uang = "IDR"
            if row.harga_terakhir_terbaca is None:
                row.harga_terakhir_terbaca = row.harga
            if source_host == "shop.8storeytree.com" and row.harga_terakhir_terbaca is not None:
                row.mata_uang_terakhir = "SGD"
            elif not row.mata_uang_terakhir:
                row.mata_uang_terakhir = row.mata_uang or "IDR"
            if not row.waktu_harga_terakhir_terbaca:
                row.waktu_harga_terakhir_terbaca = row.terakhir_dicek
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


def configure_stock_scheduler():
    scheduler.add_job(
        jalankan_pengecekan_stok,
        "interval",
        minutes=30,
        id="stock-check",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        process_pending_notification_emails,
        "interval",
        minutes=5,
        id="notification-email-retry",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )


def main():
    parser = argparse.ArgumentParser(description="Dashboard pemantauan stok")
    parser.add_argument(
        "command", nargs="?",
        choices=("web", "scheduler", "init-db", "test-email"), default="web",
        help=("web menjalankan mode lokal; scheduler menjalankan worker terjadwal; "
              "init-db menyiapkan database; test-email mengirim email uji"),
    )
    args = parser.parse_args()
    if args.command == "test-email":
        sent, error = send_test_notification_email()
        if not sent:
            parser.exit(1, f"Email uji gagal: {error}\n")
        print("Email uji berhasil dikirim ke penerima yang dikonfigurasi.")
        return

    initialize_database()

    if args.command == "init-db":
        app.logger.info("Database dan migrasi sederhana siap")
        return

    process_pending_notification_emails()
    configure_stock_scheduler()
    scheduler.start()
    if args.command == "scheduler":
        app.logger.info("Worker stok aktif; pengecekan dijadwalkan setiap 30 menit")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            scheduler.shutdown(wait=False)
        return

    app.run(debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
