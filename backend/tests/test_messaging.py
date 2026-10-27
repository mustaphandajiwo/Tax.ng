"""Production email adapter: configuration gates and the Resend request shape."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from taxng.platform.adapters import NotConfigured
from taxng.platform.notify import ProductionMessaging


class _Resp:
    status = 200

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class ProductionMessagingTest(unittest.TestCase):
    def test_unconfigured_refuses_to_send(self) -> None:
        with mock.patch.dict(os.environ, {"TAXNG_RESEND_API_KEY": "", "TAXNG_MAIL_FROM": ""}):
            adapter = ProductionMessaging()
            self.assertFalse(adapter.is_configured())
            self.assertFalse(adapter.authorised)
            with self.assertRaises(NotConfigured):
                adapter.deliver("email", "a@example.com", "Code", "123456")

    def test_non_email_channels_stay_unconfigured(self) -> None:
        env = {"TAXNG_RESEND_API_KEY": "k", "TAXNG_MAIL_FROM": "tax.ng <no-reply@tax.ng>"}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(NotConfigured):
                ProductionMessaging().deliver("whatsapp", "+234000", "", "hi")

    def test_configured_posts_to_resend(self) -> None:
        env = {"TAXNG_RESEND_API_KEY": "re_test", "TAXNG_MAIL_FROM": "tax.ng <no-reply@tax.ng>"}
        with mock.patch.dict(os.environ, env):
            adapter = ProductionMessaging()
            self.assertTrue(adapter.authorised)
            with mock.patch("urllib.request.urlopen", return_value=_Resp()) as urlopen:
                adapter.deliver("email", "a@example.com", "Your code", "123456")
            req = urlopen.call_args[0][0]
            self.assertEqual(req.full_url, "https://api.resend.com/emails")
            self.assertEqual(req.get_header("Authorization"), "Bearer re_test")
            sent = json.loads(req.data)
            self.assertEqual(sent["to"], ["a@example.com"])
            self.assertEqual(sent["from"], "tax.ng <no-reply@tax.ng>")
            self.assertEqual(sent["text"], "123456")

    def test_provider_outage_raises_provider_unavailable(self) -> None:
        import urllib.error

        from taxng.platform.adapters import ProviderUnavailable

        env = {"TAXNG_RESEND_API_KEY": "re_test", "TAXNG_MAIL_FROM": "tax.ng <no-reply@tax.ng>"}
        with mock.patch.dict(os.environ, env):
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
                with self.assertRaises(ProviderUnavailable):
                    ProductionMessaging().deliver("email", "a@example.com", "Code", "123456")


if __name__ == "__main__":
    unittest.main()
