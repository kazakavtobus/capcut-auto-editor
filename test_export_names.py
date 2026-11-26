import tempfile,unittest
from pathlib import Path
from export_names import manual_metadata,publish_export

SETTINGS={'account_1_name':'Unison Muz','account_2_name':'Аккаунт 2'}

class ExportNameTests(unittest.TestCase):
    def test_manual_filename(self):
        self.assertEqual(manual_metadata('Аккаунт 2 — Ночной Хулиган - Сумасшедшая (TT).mp4',SETTINGS),
                         ('2','Ночной Хулиган - Сумасшедшая (TT)'))
        self.assertEqual(manual_metadata('Unison Muz – Другой трек.mp4',SETTINGS),('1','Другой трек'))
        self.assertEqual(manual_metadata('unison muz - Песня.mp4',SETTINGS),('1','Песня'))
        self.assertEqual(manual_metadata('Unison Muz — Песня — ролик 002.mp4',SETTINGS),('1','Песня'))
        self.assertEqual(manual_metadata('Артист - Песня.mp4',SETTINGS),(None,'Артист - Песня'))
        self.assertEqual(manual_metadata('Аккаунт 1 — Песня.mp4',SETTINGS),('1','Песня'))
        self.assertEqual(manual_metadata('Новый канал — Песня.mp4',dict(SETTINGS,account_2_name='Новый канал')),('2','Песня'))
        self.assertEqual(manual_metadata('Unison Muz — Песня.mp4',dict(SETTINGS,account_2_name='Unison Muz')),(None,'Unison Muz — Песня'))
    def test_archive_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'exports';stage=Path(tmp)/'stage';stage.mkdir()
            src=stage/'video.mp4';src.write_bytes(b'one')
            first=publish_export(src,root,SETTINGS,'2','Трек')
            src.write_bytes(b'two')
            second=publish_export(src,root,SETTINGS,'2','Трек')
            self.assertEqual(first.name,'Аккаунт 2 — Трек.mp4')
            self.assertEqual(second.name,'Аккаунт 2 — Трек — ролик 002.mp4')
            self.assertEqual(first.read_bytes(),b'one')
            self.assertEqual(second.read_bytes(),b'two')
            self.assertFalse(src.exists())
            self.assertEqual(manual_metadata(second,SETTINGS),('2','Трек'))
