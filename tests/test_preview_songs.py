import tempfile, unittest
from pathlib import Path
from song_library import SongLibrary,song_hash
from studio_media import MediaLibrary

class PreviewSongTests(unittest.TestCase):
    def test_audio_only_and_caption_title_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'Original song.mp3';source.write_bytes(b'example')
            media=MediaLibrary(root/'media');lib=SongLibrary(root/'metadata')
            saved=media.store_song(source);key=song_hash(source)
            lib.register_audio(saved,source.name);source.unlink()
            self.assertEqual(media.find_song(key),saved)
            self.assertEqual(lib.load(saved)['filename'],'Original song.mp3')
            self.assertFalse(lib.load(saved)['verified'])
            lib.save(saved,[(0,1000000,'Текст')],verified=True,source='manual')
            lib.register_audio(saved,'Other name')
            self.assertEqual(lib.load(saved)['filename'],'Original song.mp3')
            self.assertTrue(lib.load(saved)['verified'])
    def test_restore_audio_from_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);media=MediaLibrary(root/'media')
            project=root/'old';assets=project/'AutoAssets';assets.mkdir(parents=True)
            source=assets/'song.mp3';source.write_bytes(b'old song');key=song_hash(source)
            media.record('1',project,[],key)
            saved=media.find_song(key)
            self.assertIsNotNone(saved)
            self.assertEqual(saved.read_bytes(),source.read_bytes())

if __name__=='__main__':unittest.main()
