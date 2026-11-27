import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import native_export as n

class NativeExportTests(unittest.TestCase):
    def test_visual_fallback_only_before_export_actions(self):
        self.assertTrue(n.visual_fallback_allowed('start','STAGE: open exact project | missing'))
        self.assertTrue(n.visual_fallback_allowed('start','STAGE: find editor export button | missing'))
        self.assertFalse(n.visual_fallback_allowed('start','STAGE: confirm native export | error'))
        self.assertFalse(n.visual_fallback_allowed('start','STAGE: output folder | error'))
        self.assertFalse(n.visual_fallback_allowed('close','STAGE: open exact project | missing'))
        self.assertTrue(n.visual_fallback_allowed('close','STAGE: close exact project | missing'))
    def test_partial_batch_keeps_completed(self):
        def export(p,s):
            if p=='b':raise n.ExportError('UIA unavailable')
            return {'path':p}
        closed=[]
        result=n.export_batch(['a','b','c'],{},exporter=export,close=lambda p,**kw:closed.append(p))
        self.assertEqual(result['rows'],[{'path':'a'}])
        self.assertEqual(result['remaining'],['b','c'])
        self.assertEqual(closed,['a'])
    def test_verified_real_mp4(self):
        from studio_media import ffmpeg
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'good.mp4'
            ffmpeg(['-f','lavfi','-i','color=c=black:s=1080x1920:r=30:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',p])
            self.assertEqual(n.verify_mp4(p,1_000_000),p)
            with self.assertRaises(n.ExportError):n.verify_mp4(p,2_000_000)
            bad=Path(tmp)/'bad.mp4'
            ffmpeg(['-f','lavfi','-i','color=c=black:s=720x1280:r=25:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',bad])
            with self.assertRaises(n.ExportError):n.verify_mp4(bad,1_000_000)
    def test_receipt_written_only_after_verified_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp)/'project';(project/'AutoAssets').mkdir(parents=True)
            (project/'draft_content.json').write_text('{}',encoding='utf-8')
            row={'project':str(project),'account':'1','song':'Song','duration':1000000}
            with patch.object(n,'project_info',return_value=row),patch.object(n,'verify_mp4',side_effect=n.ExportError('invalid')):
                def start(p,folder):(folder/'video.mp4').write_bytes(b'fake')
                with self.assertRaises(n.ExportError):n.export_one(project,{'export_root':tmp},start=start,wait=lambda p,d:p)
            self.assertIsNone(n.receipt(project))
            with patch.object(n,'project_info',return_value=row),patch.object(n,'verify_mp4',side_effect=lambda p,d:Path(p)):
                result=n.export_one(project,{'export_root':tmp},start=start,wait=lambda p,d:p)
                self.assertEqual(n.receipt(project),result)
                # Windows may spell the same temp directory with an 8.3 short path.
                self.assertTrue(Path(result['path']).parent.samefile(Path(tmp)))
                self.assertEqual(Path(result['path']).name,'Аккаунт 1 — Song.mp4')
                (project/'draft_content.json').write_text('{"changed":true}',encoding='utf-8')
                self.assertEqual(n.receipt(project),result)
