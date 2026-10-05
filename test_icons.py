import io,json,tempfile,unittest,shutil
from pathlib import Path
from PIL import Image
from desktop_icons import make_icon,icon_source,replace_resources,pe_end

class IconTests(unittest.TestCase):
    def test_ico_contains_small_tray_and_large_explorer_sizes(self):
        source=io.BytesIO();Image.new('RGB',(300,200),'red').save(source,format='PNG');source.seek(0)
        raw=make_icon(source)
        with Image.open(io.BytesIO(raw)) as icon:
            self.assertTrue({(16,16),(32,32),(256,256)}.issubset(icon.ico.sizes()))
    def test_default_custom_cat_and_deleted_image_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);assets=data/'assets';assets.mkdir();(data/'圖片收藏').mkdir()
            key='a'*64;custom=data/'圖片收藏'/(key+'.png');custom.write_bytes(b'image')
            self.assertEqual(icon_source(data,assets,'default'),assets/'product-default.png')
            self.assertEqual(icon_source(data,assets,key),custom)
            (data/'圖示設定.json').write_text(json.dumps({'selected':'default'}))
            self.assertEqual(icon_source(data,assets,'default'),assets/'avatar-default.png')
            (data/'圖示設定.json').write_text(json.dumps({'selected':key}))
            custom.unlink();self.assertEqual(icon_source(data,assets,'default'),assets/'product-default.png')
    def test_exe_icon_change_preserves_entire_runtime_archive(self):
        source=Path(__file__).parent/'release_v1_2'/'桌面破壞神小助手.exe'
        if not source.exists():self.skipTest('needs local baseline executable')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'copy.exe';shutil.copy2(source,path)
            raw=path.read_bytes();overlay=raw[pe_end(raw):]
            replace_resources(path,(Path(__file__).parent/'assets'/'product-default.ico').read_bytes())
            changed=path.read_bytes();self.assertEqual(changed[pe_end(changed):],overlay)
            from PyInstaller.archive.readers import CArchiveReader
            self.assertIn('app',CArchiveReader(str(path)).toc)

if __name__=='__main__':unittest.main()
