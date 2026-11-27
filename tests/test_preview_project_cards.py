import tempfile,unittest
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
from studio_media import MediaLibrary
from studio_ui import ProjectsDialog
from desktop_ui import apply_appearance

class ProjectCardsTests(unittest.TestCase):
    def test_search_and_account_filter(self):
        app=QApplication.instance() or QApplication([])
        apply_appearance(False)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lib=MediaLibrary(root/'media')
            p1=root/'First song';p1.mkdir()
            p2=root/'Second song';p2.mkdir()
            lib.record('1',p1,[],'first');lib.record('2',p2,[],'second')
            host=QWidget()
            dialog=ProjectsDialog(host,root/'media')
            self.assertEqual(len(dialog.cards),2)
            dialog.search.setText('Second')
            self.assertEqual(len(dialog.cards),1)
            dialog.account_filter.setCurrentIndex(1)
            self.assertEqual(len(dialog.cards),0)
            dialog.search.clear()
            self.assertEqual(len(dialog.cards),1)
            apply_appearance(True)
            dialog.close();host.close()
if __name__=='__main__':unittest.main()
