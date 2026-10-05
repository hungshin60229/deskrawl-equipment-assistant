import copy,json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
import app
from loadouts import Library,scope

class LoadoutApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.original_library=app.library;self.original_state=copy.deepcopy(app.state)
        app.library=Library(Path(self.tmp.name));self.char={'key':'test-character','mode':1}
        app.state.update(status='connected',character=self.char,items=[{'uid':'one','slot':'Chest','name':'胸甲','primary':[],'secondary':[],'other':[]}])
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}/api/loadouts'
    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();app.library=self.original_library;app.state.clear();app.state.update(self.original_state);self.tmp.cleanup()
    def request(self,data=None,token=app.token):
        req=urllib.request.Request(self.url,data=json.dumps(data).encode() if data is not None else None,headers={'X-Assistant-Token':token})
        with urllib.request.urlopen(req) as response:return json.load(response)
    def test_token_required_for_read_and_write(self):
        for data in [None,{'action':'favorite','uid':'one','scope':scope(self.char)}]:
            with self.assertRaises(urllib.error.HTTPError) as e:self.request(data,token='wrong')
            self.assertEqual(e.exception.code,403)
        self.assertFalse(app.library.path.exists())
    def test_character_switch_and_offline_changes_rejected(self):
        for status,requested_scope in [('connected','old-character'),('offline',scope(self.char))]:
            app.state['status']=status
            with self.assertRaises(urllib.error.HTTPError) as e:self.request({'action':'favorite','uid':'one','scope':requested_scope})
            self.assertEqual(e.exception.code,400)
        self.assertFalse(app.library.path.exists())
    def test_save_reload_and_invalid_identifiers(self):
        result=self.request({'action':'save','scope':scope(self.char),'name':'刷寶','equipment':{'Chest':'one'}})
        self.assertEqual(self.request()['builds'][0]['id'],result['builds'][0]['id'])
        with self.assertRaises(urllib.error.HTTPError) as e:self.request({'action':'favorite','scope':scope(self.char),'uid':[]})
        self.assertEqual(e.exception.code,400)

if __name__=='__main__':unittest.main()
