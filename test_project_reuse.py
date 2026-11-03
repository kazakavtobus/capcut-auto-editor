import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from caption_engine import MISSING_LYRICS, fill_unrecognized_vocals, obtain_captions
from song_library import SongLibrary, sync_previous_capcut_edits

def project_with_rows(folder, name, audio, baseline, actual):
    p=folder/name
    assets=p/'AutoAssets'
    assets.mkdir(parents=True)
    (assets/'song.mp3').write_bytes(audio.read_bytes())
    def stamp(u):
        ms=u//1000
        return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
    (assets/'lyrics.srt').write_text('\n\n'.join(
        f'{i}\n{stamp(a)} --> {stamp(b)}\n{t}' for i,(a,b,t) in enumerate(baseline,1)),encoding='utf-8')
    data={'materials':{'texts':[{'id':f'M{i}','content':json.dumps({'text':t},ensure_ascii=False)}
                                 for i,(_,_,t) in enumerate(actual)]},
          'tracks':[{'type':'text','segments':[
              {'id':f'S{i}','material_id':f'M{i}','target_timerange':{'start':a,'duration':b-a}}
              for i,(a,b,_) in enumerate(actual)]}]}
    (p/'draft_content.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return p

class ProjectReuse(unittest.TestCase):
    def test_reuses_only_manual_changes_and_skips_whisper(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);audio=root/'song.mp3';audio.write_bytes(b'fixed audio bytes')
            drafts=root/'drafts';drafts.mkdir()
            lib=SongLibrary(root/'library')
            original=[(100000,900000,'ошибка'),(1100000,2100000,'еще ошибка')]
            corrected=[(100000,980000,'правильный текст'),(1100000,2200000,'новые слова')]
            p=project_with_rows(drafts,'first',audio,original,corrected)
            self.assertEqual(sync_previous_capcut_edits(audio,drafts,library=lib),p)
            self.assertTrue(lib.load(audio)['verified'])
            with patch('caption_engine.SongLibrary',return_value=lib), \
                 patch('caption_engine._transcribe',side_effect=AssertionError('Whisper must not run')):
                self.assertEqual(obtain_captions(audio,3_000_000),corrected)

    def test_does_not_import_unedited_machine_draft(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); audio=root/'song.mp3';audio.write_bytes(b'fixed audio bytes')
            drafts=root/'drafts';drafts.mkdir(); lib=SongLibrary(root/'library')
            original=[(100000,900000,'авто текст')]
            project_with_rows(drafts,'first',audio,original,original)
            self.assertIsNone(sync_previous_capcut_edits(audio,drafts,library=lib))
            self.assertIsNone(lib.load(audio))

    def test_checks_audio_bytes_not_name_and_prefers_real_correction(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);audio=root/'song.mp3';audio.write_bytes(b'first song')
            other=root/'same_name.mp3';other.write_bytes(b'another song')
            drafts=root/'drafts';drafts.mkdir(); lib=SongLibrary(root/'library')
            original=[(0,900000,'старый')]
            project_with_rows(drafts,'wrong',other,original,[(0,900000,'ошибка')])
            p=project_with_rows(drafts,'correct',audio,original,[(0,900000,'исправлено')])
            later=project_with_rows(drafts,'unedited',audio,original,original)
            os.utime(p/'draft_content.json',(time.time()-4,time.time()-4))
            os.utime(later/'draft_content.json',(time.time()-1,time.time()-1))
            self.assertEqual(sync_previous_capcut_edits(audio,drafts,library=lib),p)
            self.assertEqual(lib.load(audio)['rows'][0][2],'исправлено')

    def test_older_capcut_draft_does_not_override_newer_verified(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);audio=root/'song.mp3';audio.write_bytes(b'abc song')
            drafts=root/'drafts';drafts.mkdir(); lib=SongLibrary(root/'library')
            p=project_with_rows(drafts,'old',audio,[(0,800000,'авто')],[(0,800000,'старая правка')])
            os.utime(p/'draft_content.json',(time.time()-3600,time.time()-3600))
            lib.save(audio,[(0,900000,'последняя правка')],verified=True,source='editor')
            self.assertIsNone(sync_previous_capcut_edits(audio,drafts,library=lib))
            self.assertEqual(lib.load(audio)['rows'][0][2],'последняя правка')

    def test_vocal_gap_placeholder(self):
        recognized=[(500000,1400000,'слова'),(4000000,4800000,'другие слова')]
        got=fill_unrecognized_vocals(recognized,[(1800000,3400000)],6_000_000)
        self.assertEqual([t for _,_,t in got].count(MISSING_LYRICS),1)
        self.assertTrue(all(a[1]<=b[0] for a,b in zip(got,got[1:])))

    def test_no_all_placeholder_timeline(self):
        self.assertEqual(fill_unrecognized_vocals([],[(0,2_000_000),(3_000_000,5_000_000)],8_000_000),[])
        self.assertEqual(fill_unrecognized_vocals([(0,400_000,'а')],[(500_000,1_500_000)],8_000_000),
                         [(0,400_000,'а')])

    def test_placeholder_count_bounded_and_real_words_preserved(self):
        source=[(i*2_000_000,i*2_000_000+1_000_000,f'правильные слова {i}')
                for i in range(12)]
        voice=[(i*2_000_000+1_200_000,i*2_000_000+1_950_000) for i in range(12)]
        result=fill_unrecognized_vocals(source,voice,25_000_000)
        self.assertLessEqual(sum(x[2]==MISSING_LYRICS for x in result),2)
        self.assertTrue(all(x in result for x in source))

    def test_fully_failed_transcription_stops_not_placeholder(self):
        from caption_engine import CaptionsNotRecognized
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'song.mp3';a.write_bytes(b'mock')
            with patch('caption_engine._cached_captions',return_value=None), \
                 patch('caption_engine._transcribe',return_value=([],0.0)), \
                 patch('caption_engine.enhance_for_recognition',return_value=None), \
                 patch('caption_engine._voice_regions',return_value=[(0,3_000_000),(4_000_000,8_000_000)]):
                with self.assertRaises(CaptionsNotRecognized):
                    obtain_captions(a,12_000_000)

    def test_no_placeholder_without_vad_and_no_long_music_false_positive(self):
        rows=[(500000,1400000,'слова')]
        self.assertEqual(fill_unrecognized_vocals(rows,[],6_000_000),rows)
        self.assertEqual(fill_unrecognized_vocals(rows,[(0,14000000)],15_000_000),rows)

if __name__=='__main__':unittest.main()
