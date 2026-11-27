import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import remotion_export as r
import updater as u

class PreviewTests(unittest.TestCase):
    def test_lut_copy_survives_source_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'Sample.CUBE'
            source.write_text('TITLE "Sample"\nLUT_3D_SIZE 2\n'+'0.0 0.0 0.0\n'*8,encoding='utf-8')
            with patch.object(r,'LUT_DIR',root/'local'):
                saved=r.import_lut(source);source.unlink()
                self.assertTrue(saved.is_file())
                self.assertEqual(r.find_lut({'remotion_lut':str(saved)}),saved)
                self.assertIn('Sample.CUBE',r.lut_label({'remotion_lut':str(saved)}))
                invalid=root/'bad.cube';invalid.write_text('LUT_3D_SIZE 2\n0 0 0\n')
                with self.assertRaises(r.ExportError):r.import_lut(invalid)
    def test_preview_channel_does_not_select_stable_release(self):
        def release(tag,pre):
            prefix='https://github.com/'+u.REPOSITORY+'/releases/download/'+tag+'/'
            return {'tag_name':tag,'prerelease':pre,'draft':False,'assets':[
                {'name':name,'browser_download_url':prefix+name} for name in (u.INSTALLER_NAME,u.CHECKSUM_NAME)]}
        releases=[release('v99.0.0',False),release('preview-v9.0.2',True),release('preview-v9.0.1',True)]
        with patch.object(u,'_download',return_value=json.dumps(releases).encode()),patch.object(u,'VERSION','9.0.1'):
            self.assertEqual(u.check_release()['tag'],'preview-v9.0.2')

if __name__=='__main__':unittest.main()
