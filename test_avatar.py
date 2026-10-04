import io,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from PIL import Image
import app

class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.original=app.DATA;app.DATA=Path(self.temp.name)
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();app.DATA=self.original;self.temp.cleanup()
    def upload(self,data,token=app.token):
        req=urllib.request.Request(self.url+'/api/avatar',data=data,headers={'X-Assistant-Token':token},method='POST')
        return urllib.request.urlopen(req)
    def test_upload_persists_normalized_image_and_serves_after_reopen(self):
        data=io.BytesIO();Image.new('RGB',(1200,600),'red').save(data,format='JPEG')
        with self.upload(data.getvalue()) as r:self.assertEqual(r.status,200)
        with Image.open(app.DATA/'自訂頭像.png') as image:self.assertEqual(image.size,(512,256));self.assertEqual(image.format,'PNG')
        self.assertEqual(urllib.request.urlopen(self.url+'/avatar.png').read(),(app.DATA/'自訂頭像.png').read_bytes())
        with self.assertRaises(urllib.error.HTTPError):self.upload(b'not an image')
        with Image.open(app.DATA/'自訂頭像.png') as image:self.assertEqual(image.size,(512,256))
    def test_upload_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as result:self.upload(b'x',token='wrong')
        self.assertEqual(result.exception.code,403);self.assertFalse((app.DATA/'自訂頭像.png').exists())

    def test_gallery_switches_default_and_preserves_previous_uploads(self):
        import json
        keys=[]
        for color in ['red','blue']:
            data=io.BytesIO();Image.new('RGB',(64,64),color).save(data,format='PNG')
            with self.upload(data.getvalue()):pass
            keys.append(app.avatar_library()[0])
        self.assertEqual(len(app.avatar_library()[1]),3)
        for key in ['default',keys[0],keys[1]]:
            request=urllib.request.Request(self.url+'/api/avatar/select',data=json.dumps({'id':key}).encode(),headers={'X-Assistant-Token':app.token},method='POST')
            with urllib.request.urlopen(request) as response:self.assertEqual(response.status,200)
            self.assertEqual(app.avatar_library()[0],key)
            expected=(app.ASSETS/'avatar-default.png') if key=='default' else app.DATA/'圖片收藏'/(key+'.png')
            self.assertEqual(urllib.request.urlopen(self.url+'/avatar.png').read(),expected.read_bytes())
        self.assertEqual(len(app.avatar_library()[1]),3)

    def test_existing_avatar_migrates_and_invalid_selection_does_not_change_it(self):
        import json
        Image.new('RGB',(64,64),'green').save(app.DATA/'自訂頭像.png')
        selected,images=app.avatar_library();self.assertNotEqual(selected,'default');self.assertEqual(len(images),2)
        request=urllib.request.Request(self.url+'/api/avatar/select',data=json.dumps({'id':'../../outside'}).encode(),headers={'X-Assistant-Token':app.token},method='POST')
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(request)
        self.assertEqual(app.avatar_library()[0],selected)

    def test_delete_current_image_returns_to_cat_and_does_not_remigrate(self):
        import json
        data=io.BytesIO();Image.new('RGB',(64,64),'red').save(data,format='PNG')
        with self.upload(data.getvalue()):pass
        key=app.avatar_library()[0]
        def delete(value):
            return urllib.request.urlopen(urllib.request.Request(self.url+'/api/avatar/delete',data=json.dumps({'id':value}).encode(),headers={'X-Assistant-Token':app.token},method='POST'))
        with self.assertRaises(urllib.error.HTTPError):delete('default')
        with delete(key) as response:self.assertEqual(response.status,200)
        self.assertEqual(app.avatar_library(),('default',[{'id':'default','name':'預設貓咪','url':'/avatar-default.png'}]))
        self.assertFalse((app.DATA/'自訂頭像.png').exists())

if __name__=='__main__':unittest.main()
