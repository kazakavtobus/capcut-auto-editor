import tempfile, unittest
from pathlib import Path
from studio_media import MediaLibrary,LibraryShortage
from studio_pipeline import bounded_cuts

class StudioTests(unittest.TestCase):
    def test_no_repeat_across_four_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            l=MediaLibrary(tmp)
            with l.connect() as c:
                for i in range(20):
                    k=str(i);p=Path(tmp)/(k+'.mp4');p.write_bytes(b'test')
                    c.execute('INSERT INTO sources VALUES(?,?,?,?)',(k,k,str(p),'Город'))
                    c.execute('INSERT INTO clips(id,source,idx,path,preview) VALUES(?,?,?,?,?)',(k,k,0,str(p),''))
            used=[]
            for i in range(5):
                rows=l.choose(4);ids={r['id'] for r in rows}
                self.assertFalse(ids.intersection(set().union(*used[-4:])))
                l.record(str(i%2+1),str(i),rows,'song');used.append(ids)
            self.assertEqual(len(l.projects()),5)
            self.assertFalse(set(r['id'] for r in l.choose(4)).intersection(set().union(*used[-4:])))
    def test_shortage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LibraryShortage):MediaLibrary(tmp).choose(1)
    def test_cut_lengths(self):
        cuts=bounded_cuts([2_000_000,10_000_000],23_000_000,[])
        self.assertEqual(cuts[-1],23_000_000)
        self.assertTrue(all(0<b-a<=4_950_000 for a,b in zip([0]+cuts,cuts)))

    def test_srt_millisecond_precision(self):
        from builder import parse_srt
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'lyrics.srt'
            p.write_text('1\n00:00:00,005 --> 00:00:01,020\nТест\n',encoding='utf-8')
            self.assertEqual(parse_srt(p),[(5000,1020000,'Тест')])

    def test_real_import_and_native_builder(self):
        import copy,json,zipfile
        from builder import build,media_info
        from studio_media import ffmpeg
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lib=MediaLibrary(root/'база')
            raw=root/'исходник.mp4'
            ffmpeg(['-f','lavfi','-i','testsrc2=size=160x240:rate=30:duration=10.2','-c:v','libx264','-pix_fmt','yuv420p',raw])
            self.assertEqual(lib.import_video(raw,'Город'),2)
            self.assertEqual(lib.import_video(raw,'Город'),0)
            clips=lib.clips()
            self.assertEqual(len(clips),2)
            for row in clips:
                d=media_info(Path(row['path']),'video')
                self.assertEqual((d['width'],d['height']),(720,1280))
                self.assertTrue(4_950_000<=d['duration']<=5_050_000)
                self.assertTrue(Path(row['preview']).exists())
                # Confirm grayscale pixels in the encoded material.
                import av
                with av.open(row['path']) as c:
                    frame=next(c.decode(video=0)).to_ndarray(format='rgb24')
                    self.assertLessEqual(abs(frame[:,:,0].astype('int16')-frame[:,:,1].astype('int16')).max(),3)
            audio=root/'песня.mp3'
            ffmpeg(['-f','lavfi','-i','sine=frequency=440:duration=6','-c:a','libmp3lame',audio])
            dur=media_info(audio,'audio')['duration']
            tracks=[{'type':'video','segments':[{'id':'v','material_id':'V','extra_material_refs':['T'],'target_timerange':{'start':0,'duration':3_000_000},'clip':{'flip':{'horizontal':True,'vertical':False}}}]},
                {'type':'text','segments':[{'id':'t','material_id':'TEXT','extra_material_refs':[],'target_timerange':{'start':0,'duration':1_000_000}}]},
                {'type':'audio','segments':[{'id':'a','material_id':'A','target_timerange':{'start':0,'duration':6_000_000}}]}]
            data={'id':'OLD','duration':6_000_000,'tracks':tracks,'materials':{'videos':[{'id':'V','path':'old.mp4'}],'texts':[{'id':'TEXT','content':json.dumps({'text':'Слова','styles':[{'range':[0,5]}]})}],'audios':[{'id':'A','path':'old.mp3'}],'transitions':[{'id':'T','duration':100_000}],'beats':[],'time_marks':[]}}
            meta={'draft_id':'DRAFT','draft_materials':[{'value':[{'id':'old','file_Path':'old.mp4'},{'file_Path':'old.mp3'}]}]}
            template=root/'template.zip'
            with zipfile.ZipFile(template,'w') as z:
                for name,value in [('draft_content.json',data),('draft_meta_info.json',meta),('Timelines/project.json',{'timelines':[{}]}),('Timelines/OLD/attachment_editing.json',{})]:
                    z.writestr('test/'+name,json.dumps(value))
            srt=root/'lyrics.srt';srt.write_text('1\n00:00:00,005 --> 00:00:01,020\nФраза\n',encoding='utf-8')
            out=root/'projects';out.mkdir()
            project,info=build(str(audio),[r['path'] for r in clips],str(out),'test',srt_file=str(srt),
                beats_override=[],local_boundaries=[3_000_000,dur],template_path=template)
            draft=json.loads((project/'draft_content.json').read_text(encoding='utf-8'))
            segments=draft['tracks'][0]['segments']
            self.assertEqual(len(segments),2)
            self.assertEqual(len({s['material_id'] for s in segments}),2)
            self.assertTrue(all(not s['clip']['flip']['horizontal'] for s in segments))
            self.assertEqual(info['captions'],1)
            self.assertEqual(len(list((project/'AutoAssets').glob('video_*.mp4'))),2)
            from studio_profiles import install_template,active_template,versions,create_reference
            profile_dir=root/'profiles'
            install_template('1',project,profile_dir)
            self.assertTrue(active_template('1',profile_dir).is_file())
            original=active_template('1',profile_dir).read_bytes()
            copy_project=create_reference('2',out,profile_dir)
            self.assertTrue((copy_project/'draft_content.json').is_file())
            doc=json.loads((copy_project/'draft_content.json').read_text(encoding='utf-8'))
            text=doc['materials']['texts'][0]
            style=json.loads(text['content'])
            style['styles'][0]['font']={'id':'new-font','path':'local-font'}
            text['content']=json.dumps(style)
            (copy_project/'draft_content.json').write_text(json.dumps(doc),encoding='utf-8')
            install_template('2',copy_project,profile_dir)
            self.assertEqual(active_template('1',profile_dir).read_bytes(),original)
            install_template('1',copy_project,profile_dir)
            self.assertEqual(len(versions('1',profile_dir)),1)
            install_template('1',versions('1',profile_dir)[0],profile_dir)
            self.assertEqual(active_template('1',profile_dir).read_bytes(),original)
