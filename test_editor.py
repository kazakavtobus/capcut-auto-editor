"""Synthetic local tests: no personal CapCut template or internet required."""
import json
import tempfile
import unittest
from pathlib import Path

from subtitle_editor import _project_data, apply_changes
from updater import _version, UpdateError

class EditorTests(unittest.TestCase):
    def test_can_add_edit_and_delete_real_segments(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            material={'id':'M1','content':json.dumps({'text':'Старая строка',
                  'styles':[{'range':[0,13]}]},ensure_ascii=False)}
            seg={'id':'S1','material_id':'M1','extra_material_refs':[],
                 'target_timerange':{'start':0,'duration':900000}}
            d={'materials':{'texts':[material]},'tracks':[{'type':'text','segments':[seg]},
                {'type':'video','segments':[{'id':'VIDEO'}]}]}
            copies=[root/'draft_content.json',root/'Timelines'/'uid'/'draft_content.json']
            for f in copies:
                f.parent.mkdir(parents=True,exist_ok=True)
                f.write_text(json.dumps(d),encoding='utf-8')
            rows,_=_project_data(root)
            self.assertEqual(len(rows),1)
            rows[0]['text']='Исправленная строка,'
            rows.append({'id':'SUB-2','start':1.0,'end':2.0,'text':'Новая строка,'})
            self.assertEqual(apply_changes(root,rows),2)
            new,_=_project_data(root)
            self.assertEqual(len(new),2)
            self.assertEqual(new[0]['text'],'Исправленная строка')
            self.assertEqual(new[1]['text'],'Новая строка')
            for f in copies:
                data=json.loads(f.read_text(encoding='utf-8'))
                self.assertEqual(len(data['materials']['texts']),2)
                self.assertEqual(data['tracks'][1]['segments'][0]['id'],'VIDEO')
                ids={m['id'] for m in data['materials']['texts']}
                self.assertTrue(all(x['material_id'] in ids for x in data['tracks'][0]['segments']))
            self.assertEqual(apply_changes(root,new[1:]),2)
            self.assertEqual(len(_project_data(root)[0]),1)
            self.assertTrue((root/'AutoAssets'/'lyrics.srt').is_file())

    def test_does_not_write_anything_on_invalid_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'draft_content.json').write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):
                apply_changes(root,[{'id':'1','start':0,'end':1,'text':'первый'},
                                    {'id':'2','start':0.5,'end':2,'text':'второй'}])
            self.assertEqual((root/'draft_content.json').read_text(),'{}')

    def test_release_version_comparison(self):
        self.assertGreater(_version('v7.4.0'),_version('v7.3.0'))
        with self.assertRaises(UpdateError):_version('latest')

if __name__=='__main__':unittest.main()
