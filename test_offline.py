"""Offline smoke test. No API key, Internet or Whisper model download required.

Requires ffmpeg/ffprobe; uses included synthetic media only when supplied explicitly.
"""
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from auto_pipeline import choose_theme, unique_project_name, _allowed_media_url, to_srt, pick_stock_videos
from builder import parse_srt

class BasicTests(unittest.TestCase):
    def test_srt_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'lyrics.srt'
            rows=[(100_000,700_000,'хороший день'),(800_000,1_400_000,'новая строка')]
            to_srt(rows,dest)
            self.assertEqual(parse_srt(dest),rows)

    def test_unique_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            a=Path('актриса.mp3')
            self.assertEqual(unique_project_name(folder,a),'актриса')
            (folder/'актриса').mkdir()
            self.assertEqual(unique_project_name(folder,a),'актриса (2)')

    def test_search_mood(self):
        self.assertEqual(choose_theme([(0,1,'дождь за окном')],[])[0],'rain')

    def test_safe_cdn_urls(self):
        self.assertTrue(_allowed_media_url('https://cdn.pixabay.com/video/123.mp4','pixabay'))
        self.assertFalse(_allowed_media_url('http://cdn.pixabay.com/video.mp4','pixabay'))
        self.assertFalse(_allowed_media_url('https://pixabay.com.attacker.example/video.mp4','pixabay'))

    def test_select_three_distinct(self):
        vids=[{'id':f'pixabay-{i}','provider':'pixabay','duration':9,
            'width':720,'height':1280,'query':'city',
            'url':f'https://cdn.pixabay.com/{i}.mp4'} for i in range(5)]
        with patch('auto_pipeline.search_stock',return_value=vids):
            result=pick_stock_videos('pixabay','fake',['city','night','nature'],'song')
        self.assertEqual(len(result),3)
        self.assertEqual(len({x['id'] for x in result}),3)

if __name__=='__main__':unittest.main()
