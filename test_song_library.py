import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from song_library import SongLibrary, song_hash, import_project_corrections

class SongLibraryTests(unittest.TestCase):
    def test_verified_beats_auto_and_filename_does_not_matter(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); lib=SongLibrary(root/'library')
            a=root/'song.mp3';a.write_bytes(b'fake audio hash')
            rows=[(100000,800000,'душа хочет,'),(850000,1600000,'тёплого неба')]
            lib.save(a,rows,verified=True,source='editor')
            lib.save(a,[(1,5,'ошибка автомата')],verified=False,source='whisper')
            b=root/'renamed.mp3';b.write_bytes(a.read_bytes())
            doc=lib.load(b)
            self.assertTrue(doc['verified'])
            self.assertEqual(doc['rows'][0][2],'душа хочет')
            self.assertEqual(len(doc['rows']),2)
            self.assertEqual(song_hash(a),song_hash(b))
            self.assertFalse('library' in str(doc['filename']))

    def test_unverified_can_be_replaced_by_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); a=root/'a.wav';a.write_bytes(b'abcd')
            lib=SongLibrary(root/'lib')
            lib.save(a,[(0,600000,'временно')],verified=False,source='whisper')
            lib.save(a,[(0,600000,'исправлено')],verified=True,source='editor')
            self.assertEqual(lib.load(a)['rows'][0][2],'исправлено')

    def test_confirmed_song_skips_whisper_on_second_video(self):
        from caption_engine import obtain_captions
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            a=root/'song.mp3';a.write_bytes(b'the exact same audio bytes')
            lib=SongLibrary(root/'lib')
            expected=[(200000,950000,'мой исправленный текст')]
            lib.save(a,expected,verified=True,source='editor')
            with patch('caption_engine.SongLibrary',return_value=lib), \
                 patch('caption_engine._transcribe',side_effect=AssertionError('Whisper should not run')):
                actual=obtain_captions(a,1_500_000,chosen_model='large-v3')
            self.assertEqual(expected,actual)

    def test_reject_overlapping_captions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); a=root/'a.wav';a.write_bytes(b'abcd')
            with self.assertRaises(ValueError):
                SongLibrary(root/'lib').save(a,[(0,1000000,'one'),(500000,1500000,'two')],
                                              verified=True,source='test')

    def test_import_from_mock_capcut_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lib=SongLibrary(root/'lib')
            project=root/'project';(project/'AutoAssets').mkdir(parents=True)
            (project/'AutoAssets'/'song.mp3').write_bytes(b'a song')
            material={'id':'M','content':json.dumps({'text':'Всё правильно'},ensure_ascii=False)}
            data={'materials':{'texts':[material]},'tracks':[{'type':'text','segments':[
                {'material_id':'M','id':'S','target_timerange':{'start':1234567,'duration':900000}}]}]}
            (project/'draft_content.json').write_text(json.dumps(data),encoding='utf-8')
            count,path=import_project_corrections(project,lib)
            self.assertEqual(count,1)
            self.assertTrue(lib.load(project/'AutoAssets'/'song.mp3')['verified'])
            self.assertTrue(path.exists())

if __name__=='__main__':unittest.main()
