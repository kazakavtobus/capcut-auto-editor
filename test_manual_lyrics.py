import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from manual_lyrics import text_to_draft_rows,validate_manual_rows,import_srt_rows
from song_library import SongLibrary

class ManualLyricsTests(unittest.TestCase):
    def test_short_song(self):
        rows=text_to_draft_rows('Фраза первая\nФраза вторая\nФраза третья',23_353_450)
        self.assertEqual(len(rows),3)
        self.assertLessEqual(rows[-1][1],23_353_450)
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(rows,rows[1:])))

    def test_validation(self):
        with self.assertRaises(ValueError):
            validate_manual_rows([(0,2_000_000,'первое'),(1_000_000,3_000_000,'второе')],5_000_000)
        with self.assertRaises(ValueError):
            validate_manual_rows([(0,6_000_000,'первое')],5_000_000)
        with self.assertRaises(ValueError):
            validate_manual_rows([(0,1_000_000,'[ДОПИШИ ТЕКСТ]')],5_000_000)

    def test_srt(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'lyrics.srt'
            p.write_text('1\n00:00:01,000 --> 00:00:02,500\nПервое\n\n'
                         '2\n00:00:02,500 --> 00:00:05,000\nВторое\n',encoding='utf-8')
            self.assertEqual(import_srt_rows(p,6_000_000)[0],(1_000_000,2_500_000,'Первое'))

    def test_saved_verification_skips_whisper(self):
        from caption_engine import obtain_captions
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);song=root/'Вредная.mp3';song.write_bytes(b'audio bytes')
            rows=text_to_draft_rows('Первая\nВторая\nТретья\nЧетвертая',23_353_450)
            lib=SongLibrary(root/'lib')
            lib.save(song,validate_manual_rows(rows,23_353_450),verified=True,source='manual-library')
            with patch('caption_engine.SongLibrary',return_value=lib),\
                 patch('caption_engine._transcribe',side_effect=AssertionError('Whisper should be skipped')):
                self.assertEqual(obtain_captions(song,23_353_450),rows)

if __name__=='__main__': unittest.main()
