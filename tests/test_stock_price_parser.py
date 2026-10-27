import json
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup

import app as monitor


class PriceParserTests(unittest.TestCase):
    def test_parses_common_indonesian_and_decimal_formats(self):
        cases = {
            "Rp240.000": Decimal("240000.00"),
            "Rp12.000.847": Decimal("12000847.00"),
            "SGD 18.90": Decimal("18.90"),
            "$1,299.99": Decimal("1299.99"),
            "1.299,50": Decimal("1299.50"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(monitor.parse_price(raw), expected)

    def test_missing_or_non_price_text_does_not_create_a_price(self):
        self.assertIsNone(monitor.parse_price(None))
        self.assertIsNone(monitor.parse_price("Harga hubungi toko"))


class StockParserTests(unittest.TestCase):
    def extract_card(self, card_html):
        soup = BeautifulSoup(card_html, "html.parser")
        products = monitor.extract_products(soup, "panoramafoto.co.id")
        self.assertEqual(len(products), 1)
        return products[0]

    def test_explicit_available_and_sold_out_cards_are_recognized(self):
        available = self.extract_card(
            '<li class="product instock"><h2 class="woocommerce-loop-product__title">'
            'Instax Mini Film</h2><span class="price">Rp240.000</span>'
            '<span class="stock">Tersedia</span></li>'
        )
        sold_out = self.extract_card(
            '<li class="product outofstock"><h2 class="woocommerce-loop-product__title">'
            'Instax Square Film</h2><span class="price">Rp280.000</span>'
            '<span class="stock">Stok habis</span></li>'
        )
        self.assertEqual(available["status"], "TERSEDIA")
        self.assertEqual(available["price"], Decimal("240000.00"))
        self.assertEqual(sold_out["status"], "HABIS")
        self.assertEqual(sold_out["price"], Decimal("280000.00"))

    def test_price_without_a_stock_signal_stays_unknown(self):
        product = self.extract_card(
            '<li class="product"><h2 class="woocommerce-loop-product__title">'
            'Instax Wide Film</h2><span class="price">Rp130.000</span>'
            '<span class="shipping">Pengiriman tersedia 25 Okt</span></li>'
        )
        self.assertEqual(product["status"], "TIDAK DIKETAHUI")
        self.assertEqual(product["price"], Decimal("130000.00"))

    def test_product_card_keeps_its_individual_product_link(self):
        soup = BeautifulSoup(
            '<li class="product instock"><a class="woocommerce-LoopProduct-link" '
            'href="/product/instax-mini-film/"><h2 '
            'class="woocommerce-loop-product__title">Instax Mini Film</h2></a></li>',
            "html.parser",
        )
        product = monitor.extract_products(soup, "panoramafoto.co.id")[0]
        self.assertEqual(product["product_url"], "/product/instax-mini-film/")

    def test_direct_product_page_ignores_related_instax_products(self):
        target = "https://panoramafoto.co.id/product/instax-mini-paper-polos-isi-20/"
        html = (
            '<h1 class="product_title">Fujifilm Instax Mini Paper Polos isi 20</h1>'
            '<div class="product"><h2>Fujifilm Instax Mini Paper Mermaid Tail</h2>'
            '<a href="/product/instax-mini-paper-mermaid-tail/"></a></div>'
        )
        response = Mock(status_code=200, text=html, headers={})
        with patch.object(monitor.requests, "get", return_value=response):
            products = monitor.fetch_catalog_products(target, {"User-Agent": "test"})
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "Fujifilm Instax Mini Paper Polos isi 20")
        self.assertEqual(products[0]["product_url"], target)
        self.assertEqual(products[0]["status"], "TIDAK DIKETAHUI")
        self.assertIsNone(products[0]["price"])

    def test_category_results_drop_non_instax_items_and_ui_labels(self):
        target = "https://fujishop.id/collections/instax"
        html = (
            '<li class="product"><h2>Instax Mini 13 Camera</h2></li>'
            '<li class="product"><h2>Fujifilm X-T50 Camera</h2></li>'
            '<li class="product"><h2>Quick View</h2></li>'
        )
        response = Mock(status_code=200, text=html, headers={})
        with patch.object(monitor.requests, "get", return_value=response):
            products = monitor.fetch_catalog_products(target, {"User-Agent": "test"})
        self.assertEqual([item["name"] for item in products], ["Instax Mini 13 Camera"])
        self.assertIsNone(products[0]["product_url"])

    def test_json_ld_availability_and_price_currency_are_preserved(self):
        payload = {
            "@type": "Product",
            "name": "Instax Mini Film",
            "offers": {
                "price": "240000",
                "priceCurrency": "IDR",
                "availability": "https://schema.org/InStock",
            },
        }
        soup = BeautifulSoup(
            '<script type="application/ld+json">'
            + json.dumps(payload)
            + "</script>",
            "html.parser",
        )
        product = monitor.extract_products(soup, "panoramafoto.co.id")[0]
        self.assertEqual(product["status"], "TERSEDIA")
        self.assertEqual(product["price"], Decimal("240000.00"))
        self.assertEqual(product["price_currency"], "IDR")

    def test_json_ld_without_availability_does_not_guess_stock(self):
        payload = {
            "@type": "Product",
            "name": "Instax Wide Film",
            "offers": {"price": "130000", "priceCurrency": "IDR"},
        }
        soup = BeautifulSoup(
            '<script type="application/ld+json">'
            + json.dumps(payload)
            + "</script>",
            "html.parser",
        )
        product = monitor.extract_products(soup, "panoramafoto.co.id")[0]
        self.assertEqual(product["status"], "TIDAK DIKETAHUI")

    def test_unknown_observation_preserves_only_a_confirmed_or_current_state(self):
        cases = (
            ("TERSEDIA", "HABIS", "TERSEDIA"),
            ("HABIS", "TERSEDIA", "HABIS"),
            (None, "TERSEDIA", "TERSEDIA"),
            (None, "TIDAK DIKETAHUI", "TIDAK DIKETAHUI"),
        )
        for confirmed, current, expected in cases:
            with self.subTest(confirmed=confirmed, current=current):
                self.assertEqual(
                    monitor.preserve_last_confirmed_stock(
                        "TIDAK DIKETAHUI", confirmed, current
                    ),
                    expected,
                )

    def test_unknown_observation_cannot_invent_available_status(self):
        self.assertEqual(
            monitor.preserve_last_confirmed_stock("TIDAK DIKETAHUI"),
            "TIDAK DIKETAHUI",
        )


class LazadaPageTests(unittest.TestCase):
    def test_unavailable_sku_page_is_detected_from_title_or_body(self):
        self.assertTrue(monitor._lazada_unavailable_page(
            "Maaf! Produk ini tidak tersedia", "Hanya Untukmu Rp28.000"
        ))
        self.assertTrue(monitor._lazada_unavailable_page(
            "Nama Produk | Lazada Indonesia", "Oops. Produk ini tidak tersedia"
        ))

    def test_regular_product_page_is_not_marked_unavailable_by_recommendations(self):
        self.assertFalse(monitor._lazada_unavailable_page(
            "Fujifilm Instax Mini Film | Lazada Indonesia",
            "Produk tersedia. Rekomendasi produk lain Rp28.000",
        ))


class ShopifyDetailTests(unittest.TestCase):
    def response(self, data):
        response = Mock(status_code=200)
        response.json.return_value = data
        return response

    def lookup(self, data):
        with patch.object(monitor.requests, "get", return_value=self.response(data)):
            return monitor._shopify_product_details(
                "https://shop.8storeytree.com/collections/film",
                "/products/instax-wide-film",
                {"User-Agent": "parser-test"},
            )

    def test_shopify_uses_available_variant_prices_and_stock(self):
        result = self.lookup({
            "variants": [
                {"available": False, "price": 2200000},
                {"available": True, "price": 2400000},
                {"available": True, "price": 2600000},
            ],
        })
        self.assertEqual(result["status"], "TERSEDIA")
        self.assertEqual(result["price"], Decimal("24000.00"))

    def test_shopify_all_variants_unavailable_means_sold_out(self):
        result = self.lookup({
            "variants": [{"available": False, "price": 2400000}],
        })
        self.assertEqual(result["status"], "HABIS")
        self.assertEqual(result["price"], Decimal("24000.00"))

    def test_shopify_missing_availability_stays_unknown(self):
        result = self.lookup({"variants": [{"price": 2400000}]})
        self.assertEqual(result["status"], "TIDAK DIKETAHUI")

    def test_shopify_request_failure_returns_no_observation(self):
        with patch.object(
            monitor.requests, "get", side_effect=requests.Timeout()
        ):
            result = monitor._shopify_product_details(
                "https://shop.8storeytree.com/collections/film",
                "/products/instax-wide-film",
                {"User-Agent": "parser-test"},
            )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
