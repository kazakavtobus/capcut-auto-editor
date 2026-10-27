"""Version 7.3 regressions: 7-day source uniqueness, one theme, short subtitles."""
import tempfile
import unittest
from pathlib import Path

from auto_pipeline import THEME_QUERIES, choose_theme, unique_project_name
from video_history import VideoHistory,source_id,visually_same
from semantic_captions import two_line_layout, phrase_rows


class V73Tests(unittest.TestCase):
    def test_seven_day_policy(self):
        with tempfile.TemporaryDirectory() as td:
            t=[1_700_000_000.0]
            path=Path(td)/'video_history.json'
            a={'page':'https://www.pinterest.com/pin/123456/?utm_source=x',
               'provider':'pinterest','id':'pinterest-123456'}
            history=VideoHistory(path,now=lambda:t[0])
            self.assertEqual(history.reason(a),'')
            history.add_candidate(a,'ab'*32,['2f2f2f2f2f2f2f2f:000000']*3,'night')
            self.assertTrue(history.reason(a))
            history.commit()
            history=VideoHistory(path,now=lambda:t[0]+6*86400)
            self.assertTrue(history.reason({'page':'https://www.pinterest.com/pin/123456/'}))
            self.assertTrue(history.reason({'id':'other','sha256':'','page':'',},sha='ab'*32))
            t[0]+=7*86400+1
            self.assertEqual(VideoHistory(path,now=lambda:t[0]).reason(a),'')

    def test_same_frames_new_url(self):
        with tempfile.TemporaryDirectory() as td:
            h=VideoHistory(Path(td)/'hist.json',now=lambda:1000000.)
            h.add_candidate({'page':'https://pinterest.com/pin/100','provider':'pinterest'},
                'a'*64,['0000000000000000:505050']*3,'rain')
            other={'page':'https://pinterest.com/pin/200','provider':'pinterest'}
            self.assertIn('кадры',h.reason(other,'b'*64,['0000000000000001:50504e']*3))

    def test_theme_queries_consistent(self):
        names=[]
        for cue,theme in [('дождь','rain'),('ночь','night'),('люблю','love'),('дорога','road')]:
            selected,terms=choose_theme([(0,1000,cue)],[])
            self.assertEqual(selected,theme)
            self.assertEqual(terms,THEME_QUERIES[theme])
            self.assertGreaterEqual(len(terms),10)
            names.append(selected)
        self.assertEqual(len(names),4)

    def test_safe_two_lines(self):
        t='счастливой ты с правильным мужиком'
        result=two_line_layout(t)
        self.assertIsNotNone(result)
        lines=result.splitlines()
        self.assertEqual(len(lines),2)
        self.assertTrue(all(len(x)<=25 and len(x.split())<=4 for x in lines))
        self.assertNotIn('правильным\nмужиком',result)

    def test_too_long_is_separate_captions(self):
        tokens='счастливой ты с правильным мужиком который будет тебя любить'.split()
        rows=phrase_rows([(i*.24,i*.24+.18,t,0.98,False) for i,t in enumerate(tokens)],5_000_000)
        self.assertGreaterEqual(len(rows),2)
        self.assertEqual(' '.join(s for _,_,s in rows),' '.join(tokens))
        for _,_,s in rows:self.assertIsNotNone(two_line_layout(s))

    def test_title_not_prefixed(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td)
            name=unique_project_name(folder,Path('Тестовый артист - Мелодия.mp3'))
            self.assertEqual(name,'Тестовый артист - Мелодия')
            (folder/name).mkdir()
            self.assertEqual(unique_project_name(folder,Path('Тестовый артист - Мелодия.mp3')),
                             name+' (2)')


if __name__=='__main__':unittest.main()
