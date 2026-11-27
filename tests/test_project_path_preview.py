import unittest
from unittest.mock import patch
from app import accessible_project_folder

class ProjectPathTests(unittest.TestCase):
    def test_empty_path_is_not_project_folder(self):
        self.assertFalse(accessible_project_folder(''))
    def test_windows_untrusted_mount_does_not_escape_to_gui(self):
        with patch('app.Path.is_dir',side_effect=OSError(448,'Untrusted mount point')):
            self.assertFalse(accessible_project_folder('C:/CapCut/Projects'))
    def test_normal_path(self):
        with patch('app.Path.is_dir',return_value=True):
            self.assertTrue(accessible_project_folder('D:/CapCut/Projects'))

if __name__=='__main__':unittest.main()
