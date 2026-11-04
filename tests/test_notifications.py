import smtplib
import unittest
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch

import app as monitor


class NotificationBehaviorTests(unittest.TestCase):
    def test_stock_changes_notify_only_when_confirmed_or_newly_available_after_baseline(self):
        cases = (
            ("TERSEDIA", "HABIS", False, True),
            ("HABIS", "TERSEDIA", False, True),
            ("TERSEDIA", "TIDAK DIKETAHUI", True, False),
            (None, "TERSEDIA", False, False),
            (None, "TERSEDIA", True, True),
            (None, "HABIS", True, False),
        )
        for previous, observed, baseline, expected in cases:
            with self.subTest(previous=previous, observed=observed, baseline=baseline):
                self.assertEqual(
                    monitor.should_notify_stock_change(previous, observed, baseline),
                    expected,
                )

    def test_email_message_has_correct_subject_and_event_description(self):
        stock = SimpleNamespace(
            jenis="stok", nama_produk="Instax Film", toko="shop.test",
            nilai_lama="HABIS", nilai_baru="TERSEDIA", dibuat_pada=None,
            sumber_url="https://shop.test/item",
        )
        price = SimpleNamespace(
            jenis="harga", nama_produk="Instax Film", toko="shop.test",
            nilai_lama="Rp 240.000", nilai_baru="Rp 250.000", dibuat_pada=None,
            sumber_url="https://shop.test/item",
        )
        stock_subject, stock_body = monitor.notification_email_content(stock)
        price_subject, price_body = monitor.notification_email_content(price)
        self.assertIn("Stok berubah", stock_subject)
        self.assertIn("Perubahan stok terdeteksi", stock_body)
        self.assertIn("Harga berubah", price_subject)
        self.assertIn("Perubahan harga terdeteksi", price_body)
        self.assertIn("Rp 240.000 -> Rp 250.000", price_body)

    def test_email_retry_delay_is_exponential_and_bounded(self):
        self.assertEqual(monitor.notification_retry_delay_minutes(1), 5)
        self.assertEqual(monitor.notification_retry_delay_minutes(2), 10)
        self.assertEqual(monitor.notification_retry_delay_minutes(7), 320)
        self.assertEqual(monitor.notification_retry_delay_minutes(8), 360)
        self.assertEqual(monitor.notification_retry_delay_minutes(99), 360)

    def test_tls_and_ssl_cannot_be_enabled_together(self):
        with patch.object(monitor, "MAIL_USE_TLS", True), \
                patch.object(monitor, "MAIL_USE_SSL", True):
            error = monitor._email_configuration_error(["notify@example.com"])
        self.assertIn("MAIL_USE_SSL atau MAIL_USE_TLS", error)

    def test_disconnected_smtp_returns_actionable_error_without_traceback(self):
        email = EmailMessage()
        with patch.object(monitor, "MAIL_USE_SSL", False), \
                patch.object(monitor, "MAIL_USE_TLS", False), \
                patch.object(
                    monitor.smtplib, "SMTP",
                    side_effect=smtplib.SMTPServerDisconnected("closed"),
                ):
            sent, error = monitor._send_email_message(email, ["notify@example.com"])
        self.assertFalse(sent)
        self.assertIn("Koneksi SMTP terputus", error)


if __name__ == "__main__":
    unittest.main()
