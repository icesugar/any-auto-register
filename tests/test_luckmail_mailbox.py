import unittest
import types
from unittest import mock

from core.base_mailbox import LuckMailMailbox, MailboxAccount, create_mailbox
from core.luckmail.models import TokenMailItem, TokenMailList


class LuckMailMailboxTests(unittest.TestCase):
    def _build_mailbox(self):
        mailbox = LuckMailMailbox.__new__(LuckMailMailbox)
        mailbox._client = mock.Mock()
        mailbox._project_code = "openai"
        mailbox._email_type = None
        mailbox._domain = None
        mailbox._order_no = None
        mailbox._purchase_id = 0
        mailbox._result_tag_ids = {}
        mailbox._token_mode = False
        mailbox._token_pool_text = ""
        mailbox._token = "tok_demo"
        mailbox._email = "demo@example.com"
        mailbox._base_url = "https://mails.luckyous.com"
        mailbox._log_fn = None
        return mailbox

    @mock.patch("time.sleep", return_value=None)
    def test_wait_for_code_skips_excluded_purchase_code_and_keeps_polling_for_fresh_mail(self, _sleep):
        mailbox = self._build_mailbox()
        mailbox.get_current_ids = mock.Mock(return_value={"m1"})
        mailbox._client.user.get_token_mails.side_effect = [
            TokenMailList(
                email_address="demo@example.com",
                project="openai",
                mails=[
                    TokenMailItem(message_id="m1", subject="Your OpenAI code is 111111"),
                ],
            ),
            TokenMailList(
                email_address="demo@example.com",
                project="openai",
                mails=[
                    TokenMailItem(message_id="m1", subject="Your OpenAI code is 111111"),
                    TokenMailItem(message_id="m2", subject="Your OpenAI code is 222222"),
                ],
            ),
        ]

        code = mailbox.wait_for_code(
            MailboxAccount(email="demo@example.com", account_id="tok_demo"),
            timeout=5,
            exclude_codes={"111111"},
        )

        self.assertEqual(code, "222222")
        mailbox.get_current_ids.assert_called_once()
        self.assertEqual(mailbox._client.user.get_token_mails.call_count, 2)

    @mock.patch("core.base_mailbox.LuckMailMailbox")
    def test_create_mailbox_luckmail_forwards_proxy(self, mock_mailbox_cls):
        create_mailbox(
            "luckmail",
            extra={
                "luckmail_base_url": "https://example.com",
                "luckmail_api_key": "k",
            },
            proxy="socks5://127.0.0.1:7890",
        )
        mock_mailbox_cls.assert_called_once()
        self.assertEqual(
            mock_mailbox_cls.call_args.kwargs.get("proxy"),
            "socks5://127.0.0.1:7890",
        )

    @mock.patch("core.luckmail.LuckMailClient")
    def test_mailbox_constructor_forwards_proxy_to_luckmail_client(self, mock_client_cls):
        LuckMailMailbox(
            base_url="https://example.com",
            api_key="k",
            project_code="openai",
            proxy="socks5://127.0.0.1:7890",
        )
        mock_client_cls.assert_called_once()
        self.assertEqual(
            mock_client_cls.call_args.kwargs.get("proxy_url"),
            "socks5://127.0.0.1:7890",
        )

    @mock.patch("core.luckmail.LuckMailClient")
    def test_luckmail_token_mode_pops_first_email_and_persists_remaining(
        self,
        mock_client_cls,
    ):
        mock_config_store = mock.Mock()
        mock_config_store.get.return_value = (
            "first@hotmail.com----tok_first\nsecond@hotmail.com----tok_second"
        )

        fake_config_module = types.SimpleNamespace(config_store=mock_config_store)
        with mock.patch.dict("sys.modules", {"core.config_store": fake_config_module}):
            mailbox = LuckMailMailbox(
                base_url="https://mails.luckyous.com",
                api_key="",
                token_emails="first@hotmail.com----tok_first\nsecond@hotmail.com----tok_second",
                token_mode=True,
            )

            account = mailbox.get_email()

            self.assertEqual(account.email, "first@hotmail.com")
            self.assertEqual(account.account_id, "tok_first")
            mock_config_store.set.assert_called_once_with(
                "luckmail_token_emails",
                "second@hotmail.com----tok_second",
            )
            mock_client_cls.assert_called_once()

    def test_parse_luckmail_token_pool_rejects_invalid_line(self):
        with self.assertRaisesRegex(RuntimeError, "LuckMail\\(token\\)"):
            LuckMailMailbox._parse_token_pool_text("broken-line")

    def test_ensure_result_tags_creates_missing_tags(self):
        mailbox = self._build_mailbox()
        mailbox._client.user.get_tags.return_value = [
            types.SimpleNamespace(id=7, name="其他标签"),
        ]
        mailbox._client.user.create_tag.side_effect = [
            types.SimpleNamespace(id=11, name="注册成功"),
            types.SimpleNamespace(id=12, name="注册失败"),
        ]

        result = mailbox._ensure_result_tags()

        self.assertEqual(
            result,
            {
                "注册成功": 11,
                "注册失败": 12,
            },
        )
        self.assertEqual(mailbox._client.user.create_tag.call_count, 2)
        mailbox._client.user.create_tag.assert_any_call(
            name="注册成功",
            limit_type=0,
        )
        mailbox._client.user.create_tag.assert_any_call(
            name="注册失败",
            limit_type=0,
        )

    def test_ensure_result_tags_reuses_existing_tags(self):
        mailbox = self._build_mailbox()
        mailbox._client.user.get_tags.return_value = [
            types.SimpleNamespace(id=21, name="注册成功"),
            types.SimpleNamespace(id=22, name="注册失败"),
        ]

        result = mailbox._ensure_result_tags()

        self.assertEqual(
            result,
            {
                "注册成功": 21,
                "注册失败": 22,
            },
        )
        mailbox._client.user.create_tag.assert_not_called()

    def test_mark_purchase_result_tag_sets_expected_tag_name(self):
        mailbox = self._build_mailbox()
        mailbox._result_tag_ids = {
            "注册成功": 31,
            "注册失败": 32,
        }

        mailbox.mark_purchase_result_tag(123, success=True)
        mailbox.mark_purchase_result_tag(456, success=False)

        self.assertEqual(mailbox._client.user.set_purchase_tag.call_count, 2)
        mailbox._client.user.set_purchase_tag.assert_any_call(
            123,
            tag_name="注册成功",
        )
        mailbox._client.user.set_purchase_tag.assert_any_call(
            456,
            tag_name="注册失败",
        )

    def test_mark_purchase_result_tag_skips_token_mode(self):
        mailbox = self._build_mailbox()
        mailbox._token_mode = True

        mailbox.mark_purchase_result_tag(123, success=True)

        mailbox._client.user.get_tags.assert_not_called()
        mailbox._client.user.create_tag.assert_not_called()
        mailbox._client.user.set_purchase_tag.assert_not_called()

    def test_get_email_purchase_mode_stores_purchase_id_and_initializes_tags(self):
        mailbox = self._build_mailbox()
        mailbox._token = None
        mailbox._ensure_result_tags = mock.Mock()
        mailbox._client.user.purchase_emails.return_value = {
            "purchases": [
                {
                    "id": 123,
                    "email_address": "fresh@example.com",
                    "token": "tok_fresh",
                }
            ]
        }

        account = mailbox.get_email()

        mailbox._ensure_result_tags.assert_called_once_with()
        self.assertEqual(mailbox._purchase_id, 123)
        self.assertEqual(account.email, "fresh@example.com")
        self.assertEqual(account.account_id, "tok_fresh")
        self.assertEqual(account.extra.get("purchase_id"), 123)


if __name__ == "__main__":
    unittest.main()
