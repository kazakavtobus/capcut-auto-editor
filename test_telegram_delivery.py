import tempfile, unittest, hashlib, json
from pathlib import Path
from unittest.mock import patch
import telegram_delivery as t

TOKEN='123456:abcdefghijklmnopqrstuvwxyz'
class TelegramTests(unittest.TestCase):
    def test_tags_and_recipient_validation(self):
        text=t.caption({'account_1_name':'Unison Muz'},'1','Моя песня','abcdef123456789')
        for tag in ('#UnisonMuz','#account1','#Песня_Мояпесня','#Ролик_abcdef123456'):self.assertIn(tag,text)
        self.assertIn('#Аккаунт2',t.caption({},'2','Песня','abc'))
        self.assertEqual(t.chat_ids('123, -100123 123'),['123','-100123'])
        with self.assertRaises(t.TelegramError):t.chat_ids('@unknown')
    def test_config_and_exact_file_and_dedup(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(t,'APPDATA',Path(tmp)):
            t.save_config(TOKEN,'123,-100456')
            self.assertEqual(t.load_config()['token'],TOKEN)
            p=Path(tmp)/'song.mp4';data=b'\x00\x00\x00\x18ftypmp42'+b'video';p.write_bytes(data)
            with patch.object(t,'api',return_value={'message_id':12}) as api:
                result=t.send_export(TOKEN,'123,-100456',p,{'account_1_name':'Unison Muz'},'1','Song')
                self.assertEqual([x[1] for x in result],['Отправлено','Отправлено'])
                self.assertEqual(api.call_count,2)
                self.assertEqual(api.call_args.args[3],data)
                self.assertIn('#UnisonMuz',api.call_args.args[2]['caption'])
                self.assertEqual(api.call_args.args[1],'sendDocument')
                t.send_export(TOKEN,'123,-100456',p,{},'1','Song')
                self.assertEqual(api.call_count,2)
                t.send_export(TOKEN,'123',p,{},'2','Song')
                self.assertEqual(api.call_count,3)
    def test_unknown_not_retried_rejected_can_retry(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(t,'APPDATA',Path(tmp)):
            p=Path(tmp)/'song.mp4';p.write_bytes(b'\x00\x00\x00\x18ftypmp42'+b'video')
            with patch.object(t,'api',side_effect=t.UnknownDelivery('uncertain')) as api:
                t.send_export(TOKEN,'123',p,{},'1','Song')
                t.send_export(TOKEN,'123',p,{},'1','Song')
                self.assertEqual(api.call_count,1)
            with patch.object(t,'api',side_effect=t.TelegramError('rejected')) as api:
                t.send_export(TOKEN,'456',p,{},'1','Song')
                t.send_export(TOKEN,'456',p,{},'1','Song')
                self.assertEqual(api.call_count,2)
    def test_discovery_does_not_send(self):
        with patch.object(t,'api',side_effect=[{'username':'ZavodBot'},[{'message':{'chat':{'id':123,'first_name':'A'}}}]]) as api:
            self.assertEqual(t.discover(TOKEN),{'bot':'@ZavodBot','chats':{'123':'A'}})
            self.assertEqual([x.args[1] for x in api.call_args_list],['getMe','getUpdates'])
