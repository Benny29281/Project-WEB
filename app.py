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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from email.message import EmailMessage
from urllib.parse import parse_qs, urljoin, urlsplit
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

# Set SCRAPE_ALLOWED_HOSTS to a comma-separated list of approved store domains.
DEFAULT_ALLOWED_HOSTS = (
    "instaxshop.co.id,www.instaxshop.co.id,jpckemang.com,www.jpckemang.com,"
    "fujishop.id,www.fujishop.id,galaxy.co.id,www.galaxy.co.id,"
    "doss.co.id,www.doss.co.id,focusnusantara.com,www.focusnusantara.com,"
    "blibli.com,www.blibli.com,plazakamera.com,www.plazakamera.com,"
    "tokopedia.com,www.tokopedia.com,shopee.co.id,www.shopee.co.id,taskamera.id,www.taskamera.id,"
    "shop.anekafoto.com,camera.co.id,www.camera.co.id,"
    "hopmarket.id,www.hopmarket.id,winstore.co.id,www.winstore.co.id,"
    "sinarphoto.com,www.sinarphoto.com,borneodigital.co.id,www.borneodigital.co.id,"
    "sentradigital.com,www.sentradigital.com,enterkomputer.com,www.enterkomputer.com"
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
SCRAPER_USER_AGENT = os.environ.get(
    "SCRAPER_USER_AGENT", "ProjectWebScraping/1.0 (stock-monitor; contact: admin)"
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
        "last_checked": "Terakhir dicek", "source": "Sumber", "no_products": "Belum ada produk",
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
        "last_checked": "Last checked", "source": "Source", "no_products": "No products yet",
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
        "price_comparison": "价格对比", "price_chart_help": "显示所有有价格的商品，并按商店分开",
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
        "price_comparison": "가격 비교", "price_chart_help": "가격이 있는 모든 상품을 매장별로 표시합니다",
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
    stok_kuantitas = db.Column(db.Integer, nullable=True)
    varian_produk = db.Column(db.String(255), nullable=True)


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
app.jinja_env.filters["jakarta"] = format_jakarta


def store_name(url):
    hostname = (urlsplit(url).hostname or "Toko tidak diketahui").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


def aggregate_variant_status(observations):
    """Summarize observed variants; one captured sold-out option is insufficient."""
    observations = list(observations)
    if observations and isinstance(observations[0], tuple):
        statuses = [status for status, _variant in observations]
        variant_names = {
            variant for _status, variant in observations if variant
        }
    else:
        statuses = observations
        variant_names = set()
    if any(status == "TERSEDIA" for status in statuses):
        return "TERSEDIA"
    # Shopee pages can expose many options, but this scraper may only have
    # captured one. Require more than one observed variant before aggregating
    # a sold-out state for the whole product.
    if (len(variant_names) > 1 and all(status == "HABIS" for status in statuses)):
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


def send_stock_status_email(product_name, store, product_url, status):
    """Email a one-time alert when a monitored product changes known stock status."""
    # Accept a comma/semicolon separated list. Keep the legacy singular setting working.
    configured_recipients = STOCK_ALERT_EMAILS or STOCK_ALERT_EMAIL
    recipients = list(dict.fromkeys(
        address.strip()
        for address in re.split(r"[,;]", configured_recipients)
        if address.strip()
    ))
    if not all((MAIL_SERVER, MAIL_USERNAME, MAIL_PASSWORD,
                MAIL_DEFAULT_SENDER)) or not recipients:
        app.logger.info("Notifikasi email dilewati karena pengaturan SMTP belum lengkap")
        return False
    try:
        email = EmailMessage()
        safe_product_name = re.sub(r"[\r\n]+", " ", str(product_name))
        status_label = "tersedia" if status == "TERSEDIA" else "habis"
        email["Subject"] = f"Stok {status_label}: {safe_product_name}"
        email["From"] = MAIL_DEFAULT_SENDER
        # Do not expose the recipient list to the other recipients.
        email["To"] = "undisclosed-recipients:;"
        email.set_content(
            f"Status stok produk berubah menjadi: {status_label}.\n\n"
            f"Produk: {product_name}\n"
            f"Toko: {store}\n"
            f"Sumber: {product_url}"
        )
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
        app.logger.info("Notifikasi perubahan stok email berhasil dikirim")
        return True
    except (OSError, smtplib.SMTPException, ValueError):
        app.logger.warning("Pengiriman notifikasi perubahan stok email gagal")
        return False


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
                if "outofstock" in availability or "soldout" in availability:
                    stock_status = "HABIS"
                elif any(marker in availability for marker in ("instock", "limitedavailability", "preorder", "backorder")):
                    stock_status = "TERSEDIA"
                else:
                    stock_status = "TIDAK DIKETAHUI"
                found.append({
                    "name": str(value["name"]).strip(),
                    "price": parse_price(offers.get("price") or offers.get("lowPrice")) if isinstance(offers, dict) else None,
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
    # Storefronts may render prices as plain text without standard price classes.
    for text_value in element.stripped_strings:
        match = re.search(r"\bRp\.?\s*\d[\d.,]*", text_value, flags=re.IGNORECASE)
        if match:
            parsed = parse_price(match.group(0))
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
        phrase in content for phrase in ("sold out", "out of stock", "unavailable", "not available", "stock kosong", "stock habis", "stok habis", "stok kosong", "tidak tersedia", "\u65e0\u8d27", "\u7f3a\u8d27", "\ud488\uc808")
    ):
        return "HABIS"
    if class_names.intersection({"instock", "in-stock", "available", "product-available"}) or any(
        phrase in content for phrase in ("in stock", "available", "tersedia", "stok tersedia", "ready stock", "\u6709\u8d27", "\uc7ac\uace0 \uc788\uc74c")
    ) or re.search(r"\btersisa\s+\d+\s+produk\b", content):
        return "TERSEDIA"
    return "TIDAK DIKETAHUI"


def extract_products(soup, source_host=""):
    """Extract structured products first, then common WooCommerce/Shopify cards."""
    products = {}
    for item in _schema_products(soup):
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
        item = {
            "name": name,
            "price": _price_in(card),
            "status": _stock_in(card),
            "product_url": (card.select_one('a[href*="/products/"]').get("href")
                            if card.select_one('a[href*="/products/"]') else ""),
        }
        previous = products.get(key)
        if previous:
            if item["price"] is not None:
                previous["price"] = item["price"]
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
            "product_url": link.get("href", ""),
        }
        previous = products.get(key)
        if previous:
            if item["price"] is not None:
                previous["price"] = item["price"]
            if item["status"] != "TIDAK DIKETAHUI":
                previous["status"] = item["status"]
            if item.get("product_url"):
                previous["product_url"] = item["product_url"]
        else:
            products[key] = item
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
    elif variants or data.get("available") is False:
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
            if response is None or response.status >= 400:
                app.logger.info("Halaman produk %s tidak memberi respons yang bisa dibaca", marketplace)
                browser.close()
                return None
            final_url = page.url
            final_parts = urlsplit(final_url)
            original_host = (urlsplit(target_url).hostname or "").lower().rstrip(".")
            if (not validate_target_url(final_url)
                    or (final_parts.hostname or "").lower().rstrip(".") not in marketplace_hosts):
                app.logger.warning("Navigasi %s dialihkan ke host lain; pengecekan dihentikan", marketplace)
                browser.close()
                return None

            try:
                page.locator("body").wait_for(state="visible", timeout=5000)
                # Give the selected variant's public product details time to render.
                page.wait_for_timeout(5000)
            except PlaywrightTimeoutError:
                pass
            body_text = page.locator("body").inner_text(timeout=5000)
            lowered_text = body_text.casefold()
            purchase_actions = page.locator("button,[role='button']").evaluate_all(
                "elements => elements.map(element => ({"
                "text: (element.innerText || element.textContent || '').trim(),"
                "disabled: element.disabled || element.getAttribute('aria-disabled') === 'true'"
                "}))"
            )
            selected_variant_labels = page.locator("button,[role='radio'],[role='option']").evaluate_all(
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
                browser.close()
                return None

            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()
    except Exception as error:
        # Playwright can fail when Chromium is not installed or the site is unavailable.
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        app.logger.info("Pengecekan Playwright %s gagal: %s", marketplace, type(error).__name__)
        return None

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
    if price is None:
        # Marketplaces may render the product price in the page rather than
        # exposing Product/Offer metadata.
        for price_node in soup.select(
            '[data-sqe="price"], [data-testid*="price"], '
            '.product-briefing [class*="price"], main [class*="price"]'
        ):
            price_match = re.search(
                r"Rp\.?\s*[\d.,]+", price_node.get_text(" ", strip=True),
                flags=re.IGNORECASE,
            )
            if price_match:
                price = parse_price(price_match.group(0))
                if price is not None:
                    break
    if price is None:
        # Product detail price is normally the first currency amount in the rendered page.
        price_match = re.search(r"Rp\.?\s*[\d.,]+", body_text, flags=re.IGNORECASE)
        if price_match:
            price = parse_price(price_match.group(0))
    if price is None and schema_product:
        price = schema_product["price"]

    quantity_match = re.search(
        r"\bkuantitas\b[\s\S]{0,250}?\btersedia\s+([\d.,]+)",
        lowered_text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\btersedia\s+([1-9][\d.,]*)\b", lowered_text, flags=re.IGNORECASE,
    ) or re.search(r"\bstok\s*[:=]\s*([\d.,]+)", lowered_text, flags=re.IGNORECASE)
    stock_quantity = None
    if quantity_match:
        quantity_digits = re.sub(r"\D", "", quantity_match.group(1))
        if quantity_digits:
            stock_quantity = int(quantity_digits)

    selected_variants = list(dict.fromkeys(
        label for label in selected_variant_labels
        if not any(word in label.casefold() for word in ("beli", "keranjang", "toko", "chat"))
    ))
    variant_label = ", ".join(selected_variants)[:255] or None
    # Do not show Shopee's internal display_model_id as a user-facing variant.
    # It is an opaque identifier, not a variant name, and this scraper currently
    # checks only the option selected when the product page loads.

    stock_status = "TIDAK DIKETAHUI"
    if stock_quantity == 0 or re.search(
        r"\bstok\s*:\s*0\b|\bstok\s+(?:habis|kosong)\b|"
        r"\bproduk ini (?:sudah|telah) habis\b|\bhabis terjual\b|\bsold out\b",
        lowered_text,
    ):
        stock_status = "HABIS"
    elif (stock_quantity is not None and stock_quantity > 0) or (
        re.search(
            r"\bstok\s*:\s*[1-9]\d*\b|\bstok\s+tersedia\b|"
            r"\btersedia\s+[1-9]\d*\b|\btersisa\s+[1-9]\d*\b",
            lowered_text,
        )
        or any(
            not action["disabled"] and re.search(
                r"beli sekarang|masukkan ke keranjang|tambah ke keranjang|buy now|add to cart",
                action["text"], re.IGNORECASE,
            )
            for action in purchase_actions
        )
    ):
        stock_status = "TERSEDIA"
    if stock_status == "TIDAK DIKETAHUI" and schema_product:
        stock_status = schema_product["status"]

    return {
        "name": title,
        "price": price,
        "status": stock_status,
        "stock_quantity": stock_quantity,
        "variant": variant_label,
        "product_url": final_url,
    }


def fetch_catalog_products(target_url, headers):
    """Read a listing page and its explicit pagination links, with a hard cap."""
    original_host = (urlsplit(target_url).hostname or "").lower().rstrip(".")
    if original_host in {"shopee.co.id", "www.shopee.co.id"}:
        product = _fetch_rendered_marketplace_product(
            target_url, "Shopee", {"shopee.co.id", "www.shopee.co.id"},
        )
        found = [product] if product else []
        app.logger.info(
            "Hasil target Shopee %s: %d produk ditemukan", target_url, len(found)
        )
        return found
    if (original_host in {"blibli.com", "www.blibli.com"}
            and urlsplit(target_url).path.startswith("/p/")):
        product = _fetch_rendered_marketplace_product(
            target_url, "Blibli", {"blibli.com", "www.blibli.com"},
        )
        found = [product] if product else []
        app.logger.info(
            "Hasil target Blibli %s: %d produk ditemukan", target_url, len(found)
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
        response = requests.get(
            current_url, headers=headers, timeout=(5, 15), allow_redirects=False,
        )
        if response.status_code != 200:
            app.logger.warning(
                "Target %s merespons HTTP %s; pengecekan dihentikan",
                current_url, response.status_code,
            )
            break
        pages_fetched += 1
        soup = BeautifulSoup(response.text, "html.parser")
        for product in extract_products(soup, original_host):
            if original_host in {"galaxy.co.id", "www.galaxy.co.id"}:
                details = _shopify_product_details(
                    current_url, product.get("product_url"), headers,
                )
                if details:
                    if details["price"] is not None:
                        product["price"] = details["price"]
                    product["status"] = details["status"]
                    time.sleep(0.25)
            products[product["name"].casefold()] = product
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
                    catalog_products = fetch_catalog_products(kategori.url, headers)
                    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    stock_alerts = []
                    for product in catalog_products:
                        name = product["name"]
                        variant = product.get("variant")
                        shopee_product = is_shopee_product_url(kategori.url)
                        prior_variant_status = aggregate_variant_status(
                            (item.status_stok, item.varian_produk)
                            for item in ProdukDetail.query.filter_by(
                                url_sumber=kategori.url
                            ).all()
                        ) if shopee_product else None
                        row = ProdukDetail.query.filter_by(
                            nama_produk=name, url_sumber=kategori.url,
                            varian_produk=variant,
                        ).first()
                        if row is None and variant is None:
                            # Reuse the pre-variant row rather than creating a
                            # duplicate after dropping the old opaque model ID.
                            row = ProdukDetail.query.filter_by(
                                nama_produk=name, url_sumber=kategori.url
                            ).first()
                        if row:
                            effective_status = product["status"]
                            # A failed read is not evidence that a previously
                            # confirmed product went out of stock.
                            if (effective_status == "TIDAK DIKETAHUI"
                                    and row.status_stok in {"TERSEDIA", "HABIS"}):
                                effective_status = row.status_stok
                            if (not shopee_product
                                    and product["status"] in {"TERSEDIA", "HABIS"}
                                    and row.status_stok != product["status"]
                                    and (product["status"] == "TERSEDIA"
                                         or row.status_stok == "TERSEDIA")):
                                stock_alerts.append((
                                    name,
                                    store_name(kategori.url),
                                    product.get("product_url") or kategori.url,
                                    product["status"],
                                ))
                            if (not shopee_product
                                    and row.status_stok in {"TERSEDIA", "HABIS"}
                                    and product["status"] in {"TERSEDIA", "HABIS"}
                                    and row.status_stok != product["status"]):
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="stok",
                                    nilai_lama=row.status_stok, nilai_baru=product["status"],
                                ))
                            if row.harga is not None and product["price"] is not None and row.harga != product["price"]:
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="harga",
                                    nilai_lama=str(row.harga), nilai_baru=str(product["price"]),
                                ))
                            row.status_stok = effective_status
                            row.terakhir_dicek = now
                            if product.get("stock_quantity") is not None:
                                row.stok_kuantitas = product["stock_quantity"]
                            row.varian_produk = variant
                            if product["price"] is not None:
                                row.harga = product["price"]
                        else:
                            db.session.add(ProdukDetail(
                                nama_produk=name,
                                status_stok=product["status"],
                                terakhir_dicek=now,
                                url_sumber=kategori.url,
                                harga=product["price"],
                                stok_kuantitas=product.get("stock_quantity"),
                                varian_produk=variant,
                            ))
                        if shopee_product:
                            db.session.flush()
                            current_variant_status = aggregate_variant_status(
                                (item.status_stok, item.varian_produk)
                                for item in ProdukDetail.query.filter_by(
                                    url_sumber=kategori.url
                                ).all()
                            )
                            if (prior_variant_status != current_variant_status
                                    and current_variant_status in {"TERSEDIA", "HABIS"}):
                                db.session.add(Notifikasi(
                                    nama_produk=name, toko=store_name(kategori.url), jenis="stok",
                                    nilai_lama=prior_variant_status,
                                    nilai_baru=current_variant_status,
                                ))
                                if prior_variant_status in {
                                    "TERSEDIA", "HABIS", "TIDAK DIKETAHUI"
                                }:
                                    stock_alerts.append((
                                        name, store_name(kategori.url),
                                        product.get("product_url") or kategori.url,
                                        current_variant_status,
                                    ))
                    db.session.commit()
                    app.logger.info("Pengecekan selesai untuk satu target")
                    for alert in stock_alerts:
                        send_stock_status_email(*alert)
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
        matches = [match for match in matches if match[2].harga is not None]

    if category == "cheapest":
        matches.sort(key=lambda match: (
            match[2].harga is None,
            match[2].harga if match[2].harga is not None else Decimal("Infinity"),
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
        found.append({
            "name": product.nama_produk,
            "store": store_name(product.url_sumber),
            "status": product.status_stok,
            "price": float(product.harga) if product.harga is not None else None,
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
    status_for_product = {product.id: product.status_stok for product in daftar_produk}
    shopee_variant_groups = {}
    for product in daftar_produk:
        if is_shopee_product_url(product.url_sumber):
            shopee_variant_groups.setdefault(product.url_sumber, []).append(product)
    for source_url, variants in shopee_variant_groups.items():
        group_status = aggregate_variant_status(
            (item.status_stok, item.varian_produk) for item in variants
        )
        for variant in variants:
            status_for_product[variant.id] = group_status
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
        status_for_product=status_for_product,
        total_tersedia=total_tersedia, total_habis=total_habis,
        total_tidak_diketahui=total_tidak_diketahui,
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
            product_columns.add("harga")
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
