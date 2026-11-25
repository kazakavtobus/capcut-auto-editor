"""Visual regression checks: actual Qt raster output, controls and navigation.
Screenshots use generated sample assets only, never a user's library.
"""
import os,sys,tempfile,json,unittest
from unittest.mock import patch
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
# Isolate every profile, library and settings write before importing application.
ROOT=tempfile.TemporaryDirectory()
os.environ['LOCALAPPDATA']=ROOT.name
from PySide6.QtWidgets import QApplication,QComboBox,QAbstractSpinBox,QAbstractItemView,QStyleOptionViewItem,QStyle
from PySide6.QtCore import Qt,QRect
from PySide6.QtGui import QColor,QImage,QPalette,QPainter
from app import MainWindow,SETTINGS
from desktop_ui import apply_appearance,asset_colors
from studio_media import MediaLibrary

def rgb(pixel):
    return (pixel.red(),pixel.green(),pixel.blue())

def near(a,b,tolerance=12):
    return max(abs(x-y) for x,y in zip(a,b))<=tolerance

def count_color(img,hex_color,tolerance=20):
    target=rgb(QColor(hex_color))
    return sum(near(rgb(img.pixelColor(x,y)),target,tolerance)
               for y in range(img.height()) for x in range(img.width()))

class VisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q=QApplication.instance() or QApplication([])
        cls.q.setStyle('Fusion')
        SETTINGS['media_root']=str(Path(ROOT.name)/'media')
        SETTINGS['projects_folder']=ROOT.name
        cls.library=MediaLibrary(SETTINGS['media_root'])
        for i in range(6):
            k=f'sample{i}';preview=cls.library.root/'previews'/(k+'.jpg')
            # Uniform mid-gray proves the cover fills its frame: no bars.
            image=QImage(180,320,QImage.Format_RGB32);image.fill(QColor('#999999'));image.save(str(preview))
            path=cls.library.root/'clips'/(k+'.mp4');path.write_bytes(b'fixture')
            with cls.library.connect() as c:
                c.execute('INSERT INTO sources VALUES(?,?,?,?)',(k,'Ночной город '+str(i+1),str(path),'Город'))
                c.execute('INSERT INTO clips(id,source,idx,path,preview) VALUES(?,?,?,?,?)',(k,k,i,str(path),str(preview)))
        from song_library import SongLibrary
        sl=SongLibrary();sl.directory.mkdir(parents=True,exist_ok=True)
        (sl.directory/('a'*64+'.json')).write_text(json.dumps({'sha256':'a'*64,'filename':'Тестовая песня.mp3','verified':True,'captions':[{'start':0,'end':1,'text':'Текст'}]},ensure_ascii=False),encoding='utf-8')
        cls.out=Path(os.environ.get('STUDIO_VISUAL_DIR','visual-results'));cls.out.mkdir(parents=True,exist_ok=True)
    def settle(self):
        for _ in range(4):self.q.processEvents()
    def test_render_all_pages_both_themes_and_sizes(self):
        # Replace before construction: QTimer captures the callback at startup.
        with patch.object(MainWindow,'initial_check',lambda self:None):
            w=MainWindow()
        w.show();self.settle()
        w.change_page(1)
        w.account_inputs['1'].setText('Ночной Хулиган')
        w.account_inputs['2'].setText('Второй канал')
        self.assertTrue(w.store_settings())
        self.assertEqual(w.account_titles['1'].text(),'Ночной Хулиган')
        self.assertEqual(w.account_titles['2'].text(),'Второй канал')
        w.change_page(6)
        self.assertEqual(w.profiles_page.titles['2'].text(),'Второй канал')
        for dark in (False,True):
            theme='dark' if dark else 'light'
            w.theme.setCurrentIndex(int(dark));apply_appearance(dark)
            for width,height in ((820,620),(1150,760),(1536,900)):
                w.resize(width,height);self.settle()
                self.assertEqual(w.width(),width)
                w.change_page(0);self.settle()
                # Read and inspect real drawn digits, not just the backing number.
                for account in ('1','2'):
                    control=w.counts[account]
                    for value in (0,1,9,10,20):
                        control.setValue(value);self.settle()
                        self.assertEqual(control.number.text(),str(value))
                        self.assertEqual(control.minus.isEnabled(),value>0)
                        self.assertEqual(control.plus.isEnabled(),value<20)
                        img=control.number.grab().toImage()
                        self.assertGreater(count_color(img,'#eef0f4' if dark else '#20242c'),12,(theme,width,value))
                    control.setValue(1 if account=='1' else 0)
                w.counts['1'].plus.click();self.assertEqual(w.counts['1'].value(),2)
                self.assertIn('2',w.build_btn.text());w.counts['1'].minus.click()
                for page in (0,3,4,5,6,7,8,9,1,2):
                    w.change_page(page);self.settle()
                    self.assertEqual(w.pages.currentIndex(),page)
                    self.assertTrue(w.pages.currentWidget().isVisible())
                    img=w.grab();self.assertTrue(img.save(str(self.out/f'{theme}-{width}-{page}.png')))
                    if page==3:
                        grid=w.media_page.grid
                        self.assertEqual(grid.count(),6)
                        grid.clearSelection();self.settle()
                        grid.scrollToItem(grid.item(0),QAbstractItemView.ScrollHint.PositionAtTop);self.settle()
                        rect=grid.visualItemRect(grid.item(0))
                        self.assertTrue(rect.isValid(),(theme,width,rect))
                        # Real viewport snapshot: assert that the first cover is visible,
                        # sampling only coordinates that are inside the viewport.
                        im=grid.viewport().grab().toImage();dpr=im.devicePixelRatio()
                        for x in (rect.left()+22,rect.right()-22):
                            px,py=round(x*dpr),round((rect.top()+55)*dpr)
                            self.assertTrue(0<=px<im.width() and 0<=py<im.height(),(theme,width,rect))
                            self.assertTrue(near(rgb(im.pixelColor(px,py)),(153,153,153),25),(theme,width,rect))
                        # Also render the complete card independently of scroll clipping.
                        # Use the exact delegate and item model from the visible gallery.
                        def check_full_card(selected=False):
                            card=QImage(rect.width(),rect.height(),QImage.Format.Format_RGB32)
                            card.fill(QColor('#ff00ff'))
                            opt=QStyleOptionViewItem()
                            opt.rect=QRect(0,0,rect.width(),rect.height())
                            opt.font=grid.font();opt.palette=grid.palette()
                            opt.state=QStyle.StateFlag.State_Selected if selected else QStyle.StateFlag.State_None
                            painter=QPainter(card)
                            try:grid.itemDelegate().paint(painter,opt,grid.indexFromItem(grid.item(0)))
                            finally:painter.end()
                            for x in (22,card.width()-22):
                                self.assertTrue(near(rgb(card.pixelColor(x,55)),(153,153,153),25),(theme,width,selected))
                            footer=rgb(card.pixelColor(10,card.height()-19))
                            self.assertTrue(near(footer,rgb(QColor(asset_colors(dark,selected)['surface'])),25),(theme,width,selected,footer))
                            self.assertTrue(card.save(str(self.out/f'{theme}-{width}-card-{selected}.png')))
                        check_full_card()
                        grid.setCurrentRow(0);self.settle()
                        self.assertTrue(grid.item(0).isSelected())
                        grid.viewport().grab().save(str(self.out/f'{theme}-{width}-selected.png'))
                        check_full_card(True)
                        # Search and empty state must also render correctly.
                        w.media_page.search.setText('не существует');self.settle()
                        self.assertEqual(grid.count(),0);self.assertTrue(w.media_page.empty.isVisible())
                        w.media_page.search.clear();self.settle()
                    if page==1:
                        w.model.showPopup();self.settle()
                        self.assertTrue(w.model.view().isVisible())
                        w.model.view().grab().save(str(self.out/f'{theme}-{width}-combo.png'))
                        w.model.hidePopup();self.settle()
                w.open_manual();self.settle()
                self.assertIsNotNone(w.manual_page)
                self.assertTrue(w.manual_page.isVisible())
                w.grab().save(str(self.out/f'{theme}-{width}-manual.png'))
                w.manual_page.reject();self.settle()
        w.close();self.settle()

if __name__=='__main__':
    unittest.main(verbosity=2)
