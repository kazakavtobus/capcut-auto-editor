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
