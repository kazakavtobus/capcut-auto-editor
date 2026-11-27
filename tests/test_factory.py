import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from studio_pipeline import build_factory,reference_style,factory_project_root
from remotion_export import timeline,raster_caption
from PIL import Image

class FactoryTests(unittest.TestCase):
    def test_build_without_external_editor_or_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);audio=root/'song.mp3';audio.write_bytes(b'music')
            clips=[]
            for i in range(5):
                p=root/f'v{i}.mp4';p.write_bytes(b'video');clips.append(p)
            with patch('studio_pipeline.profile_template',side_effect=FileNotFoundError),patch('studio_pipeline.media_info',return_value={'duration':5000000}):
                style=reference_style('1')
                project,info=build_factory(audio,clips,root,'factory',[1000000,2000000,3000000,4000000,5000000],[(0,1000000,'Тест')],'1',style)
            (project/'AutoAssets'/'sources.json').write_text(json.dumps({'account':'1'}))
            plan=timeline(project)
            self.assertEqual(plan['fontName'],'InterTight-SemiBoldItalic.ttf')
            self.assertEqual(plan['durationFrames'],150)
            self.assertEqual(len(plan['videos']),5)
            self.assertEqual(info['captions'],1)
            self.assertTrue((project/'AutoAssets'/'song.mp3').is_file())
    def test_raster_font_pixels_differ(self):
        import os
        fonts=Path(os.environ['WINDIR'])/'Fonts'
        with tempfile.TemporaryDirectory() as temp:
            a=Path(temp)/'a.png';b=Path(temp)/'b.png'
            cap={'fontSize':69,'text':'Съешь ещё этих мягких булок','color':'#ffffff'}
            raster_caption(cap,fonts/'arial.ttf',a);raster_caption(cap,fonts/'times.ttf',b)
            self.assertNotEqual(a.read_bytes(),b.read_bytes())
            with Image.open(a) as im:self.assertIsNotNone(im.getbbox())
    def test_timeline_move_and_trim(self):
        from waveform_editor import retime
        self.assertEqual(retime(2,4,'move',1,0,7),(3,5))
        self.assertEqual(retime(2,4,'move',10,0,7),(5,7))
        self.assertEqual(retime(2,4,'start',-.97,0,7,(1,),.05),(1,4))
        self.assertEqual(retime(2,4,'end',10,0,7),(2,7))
if __name__=='__main__':unittest.main()
