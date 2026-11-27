import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
import remotion_export as r

def fixture(path,family,weight,italic):
    chars='АБВабвЁёABCabc012'
    glyphs=['.notdef']+['uni%04X'%ord(c) for c in chars]
    fb=FontBuilder(1000,isTTF=True)
    fb.setupGlyphOrder(glyphs)
    fb.setupCharacterMap({ord(c):'uni%04X'%ord(c) for c in chars})
    fb.setupGlyf({g:TTGlyphPen(None).glyph() for g in glyphs})
    fb.setupHorizontalMetrics({g:(500,0) for g in glyphs})
    fb.setupHorizontalHeader(ascent=800,descent=-200)
    fb.setupNameTable({'familyName':family,'styleName':'SemiBold Italic' if italic else 'SemiBold',
                      'uniqueFontIdentifier':family+str(italic),'fullName':family+' SemiBold','psName':family.replace(' ','')+'-SemiBold'})
    fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200,
                usWeightClass=weight,fsSelection=1 if italic else 0)
    fb.setupPost(italicAngle=-10 if italic else 0)
    fb.font['head'].macStyle=2 if italic else 0
    fb.save(path)

class FontTests(unittest.TestCase):
    def test_exact_profile_and_local_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);good=root/'original.ttf';wrong=root/'wrong.ttf';normal=root/'normal.ttf'
            fixture(good,'Inter Tight',600,True);fixture(wrong,'Inter Tight',400,True);fixture(normal,'Inter Tight',600,False)
            with patch.object(r,'FONT_DIR',root/'local'):
                saved=r.import_caption_font('1',good);good.unlink()
                self.assertTrue(saved.is_file())
                self.assertEqual(r.find_font(r.CAPTION_FONTS['1'][0],'АБВ'),saved)
                with self.assertRaises(r.ExportError):r.import_caption_font('1',wrong)
                with self.assertRaises(r.ExportError):r.import_caption_font('1',normal)
                with self.assertRaises(r.ExportError):r.import_caption_font('2',normal)
    def test_content_addressed_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);one=root/'one.ttf';two=root/'two.ttf'
            fixture(one,'Inter Tight',600,True);fixture(two,'Onest',600,False)
            first,a=r.stage_caption_font(one,r.CAPTION_FONTS['1'][0],root)
            second,b=r.stage_caption_font(two,r.CAPTION_FONTS['2'][0],root)
            again,c=r.stage_caption_font(one,r.CAPTION_FONTS['1'][0],root)
            self.assertEqual(a['family'],'Inter Tight')
            self.assertEqual(b['family'],'Onest')
            self.assertNotEqual(a['sha256'],b['sha256'])
            self.assertEqual(first,again)
            self.assertEqual(a['sha256'],c['sha256'])
    def test_onest_and_missing_cyrillic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'onest.ttf';fixture(p,'Onest',600,False)
            self.assertEqual(r._validate_font(p,r.CAPTION_FONTS['2'][0],'АБВ'),p)
            with self.assertRaises(r.ExportError):r._validate_font(p,r.CAPTION_FONTS['2'][0],'Я')

if __name__=='__main__':unittest.main()
