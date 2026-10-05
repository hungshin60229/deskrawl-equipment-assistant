import json,threading,time,sys,os,secrets,logging,hashlib,re
import maintenance
if __name__=='__main__' and '--maintenance' in sys.argv:
    sys.exit(maintenance.helper_main(sys.argv[sys.argv.index('--maintenance')+1]))
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from datetime import datetime
from reader import LiveReader,stable_capture,GameClosed,NotReady,VersionMismatch
from model import enrich,SLOT_NAMES

BUNDLE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
HOME=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
DATA=HOME/'資料';DATA.mkdir(exist_ok=True)
ASSETS=BUNDLE/'assets'
CATALOG=json.loads((ASSETS/'catalog.json').read_text(encoding='utf-8'))
CONFIG=json.loads((ASSETS/'reader_config.json').read_text(encoding='utf-8'))
try:filters=json.loads((DATA/'篩選條件.json').read_text(encoding='utf-8'))
except (OSError,ValueError):filters={'slot':'','primary':[],'secondary':[]}
state={'status':'waiting','message':'正在連接遊戲','items':[],'character':None,'updated_at':None,'revision':0}
lock=threading.Lock();stop=threading.Event();token=secrets.token_urlsafe(24)
logging.basicConfig(filename=DATA/'小助手.log',encoding='utf-8',level=logging.INFO,format='%(asctime)s %(message)s')

def prepare_maintenance(job):
    maintenance.handoff(HOME,job)
    stop.set()

manager=maintenance.Manager(HOME,getattr(sys,'frozen',False),prepare_maintenance)

def atomic_json(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def avatar_library():
    folder=DATA/'圖片收藏';folder.mkdir(exist_ok=True)
    legacy=DATA/'自訂頭像.png'
    if legacy.is_file():
        raw=legacy.read_bytes();key=hashlib.sha256(raw).hexdigest()
        if not (folder/(key+'.png')).exists():(folder/(key+'.png')).write_bytes(raw)
    try:selected=json.loads((DATA/'頭像設定.json').read_text(encoding='utf-8'))['selected']
    except (OSError,ValueError,KeyError):selected=key if legacy.is_file() else 'default'
    if selected!='default' and not (re.fullmatch('[0-9a-f]{64}',str(selected)) and (folder/(selected+'.png')).is_file()):selected='default'
    entries=[{'id':'default','name':'預設貓咪','url':'/avatar-default.png'}]
    entries.extend({'id':p.stem,'name':f'收藏圖片 {i+1}','url':'/avatars/'+p.name} for i,p in enumerate(sorted(folder.glob('*.png'),key=lambda p:p.stat().st_mtime)))
    return selected,entries

def monitor():
    reader=LiveReader(CONFIG);previous=None;last_error=None
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                snapshot=stable_capture(reader);rows=enrich(snapshot,CATALOG)
                changed=snapshot!=previous
                now=datetime.now().isoformat(timespec='seconds')
                if changed:
                    atomic_json(DATA/'最新裝備.json',{'captured_at':now,**snapshot})
                    previous=snapshot
                with lock:
                    state.update(status='connected',message='已連接遊戲',items=rows,character=snapshot['character'],updated_at=now)
                    if changed:state['revision']+=1
                last_error=None
            except Exception as e:
                if isinstance(e,GameClosed):status,message='offline','遊戲未啟動，開啟遊戲並進入角色後會自動連接'
                elif isinstance(e,VersionMismatch):status,message='version',str(e)
                elif isinstance(e,NotReady):status,message='waiting',str(e)
                elif isinstance(e,PermissionError) or getattr(e,'winerror',None)==5:status,message='error','無法讀取遊戲，請讓遊戲與小助手使用相同的權限啟動'
                else:status,message='error','讀取暫時失敗，正在重試；詳細資訊已寫入小助手.log'
                if str(e)!=last_error:
                    logging.info('%s: %s',status,e);last_error=str(e)
                with lock:state.update(status=status,message=message)
                if status in ['offline','error']:reader.close()
            stop.wait(max(.05,1-(time.monotonic()-started)))
    finally:reader.close()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,body,typ):
        self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        parsed=urlsplit(self.path);path=parsed.path
        # Only localhost requests, no remote website access to inventory data.
        if self.headers.get('Host') not in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']:
            self.send(403,b'Forbidden','text/plain');return
        if path.startswith('/api/'):
            if self.headers.get('X-Assistant-Token')!=token:self.send(403,b'Forbidden','text/plain');return
            if path=='/api/state':
                with lock:body=json.dumps(state,ensure_ascii=False).encode('utf-8')
            elif path=='/api/catalog':body=json.dumps({'pools':CATALOG['pools'],'stat_names':CATALOG['stat_names'],'slots':SLOT_NAMES},ensure_ascii=False).encode('utf-8')
            elif path=='/api/filters':
                with lock:body=json.dumps(filters,ensure_ascii=False).encode('utf-8')
            elif path=='/api/avatars':
                with lock:selected,entries=avatar_library();body=json.dumps({'selected':selected,'images':entries},ensure_ascii=False).encode('utf-8')
            elif path=='/api/maintenance':body=json.dumps(manager.snapshot(),ensure_ascii=False).encode('utf-8')
            else:self.send(404,b'Not found','text/plain');return
            self.send(200,body,'application/json; charset=utf-8');return
        if path=='/':filename=ASSETS/'index.html'
        elif path=='/avatar.png':
            with lock:selected,_=avatar_library()
            filename=ASSETS/'avatar-default.png' if selected=='default' else DATA/'圖片收藏'/(selected+'.png')
        elif path=='/avatar-default.png':filename=ASSETS/'avatar-default.png'
        elif re.fullmatch(r'/avatars/[0-9a-f]{64}\.png',path):filename=DATA/'圖片收藏'/path.rsplit('/',1)[1]
        elif path in ['/app.js','/style.css']:filename=ASSETS/path[1:]
        elif path.startswith('/icons/') and '/' not in path[7:] and '..' not in path:filename=ASSETS/path[1:]
        else:self.send(404,b'Not found','text/plain');return
        if not filename.is_file():self.send(404,b'Not found','text/plain');return
        typ={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png'}[filename.suffix]
        self.send(200,filename.read_bytes(),typ)
    def do_POST(self):
        if self.headers.get('Host') not in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']:
            self.send(403,b'Forbidden','text/plain');return
        if self.headers.get('X-Assistant-Token')!=token:self.send(403,b'Forbidden','text/plain');return
        if self.path in ['/api/update','/api/uninstall','/api/update/cancel']:
            try:
                if self.path=='/api/update/cancel':
                    if manager.snapshot()['status'] not in ['checking','downloading','preparing']:raise ValueError('目前無法取消操作')
                    manager.cancelled.set()
                else:manager.start('update' if self.path=='/api/update' else 'uninstall')
                self.send(200,b'{}','application/json')
            except (ValueError,OSError) as error:
                self.send(400,json.dumps({'error':str(error)},ensure_ascii=False).encode('utf-8'),'application/json; charset=utf-8')
            return
        if self.path=='/api/avatar/delete':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<1024:raise ValueError()
                key=json.loads(self.rfile.read(length))['id']
                if not isinstance(key,str) or not re.fullmatch('[0-9a-f]{64}',key):raise ValueError()
                with lock:
                    selected,_=avatar_library();path=DATA/'圖片收藏'/(key+'.png')
                    if not path.is_file():raise ValueError()
                    if selected==key:atomic_json(DATA/'頭像設定.json',{'selected':'default'})
                    legacy=DATA/'自訂頭像.png'
                    if legacy.is_file() and hashlib.sha256(legacy.read_bytes()).hexdigest()==key:legacy.unlink()
                    path.unlink()
                self.send(200,b'{}','application/json')
            except (ValueError,KeyError):self.send(400,b'Invalid image','text/plain')
            return
        if self.path=='/api/avatar/select':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<1024:raise ValueError()
                selected=json.loads(self.rfile.read(length))['id']
                with lock:
                    _,entries=avatar_library()
                    if selected not in [entry['id'] for entry in entries]:raise ValueError()
                    atomic_json(DATA/'頭像設定.json',{'selected':selected})
                self.send(200,b'{}','application/json')
            except (ValueError,KeyError):self.send(400,b'Invalid image','text/plain')
            return
        if self.path=='/api/avatar':
            try:
                from PIL import Image,ImageOps,UnidentifiedImageError
                import io
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=8*1024*1024:raise ValueError('圖片大小需在 8 MB 以內')
                raw=self.rfile.read(length)
                with Image.open(io.BytesIO(raw)) as source:
                    if source.width*source.height>16000000:raise ValueError('圖片尺寸過大')
                    image=ImageOps.exif_transpose(source).convert('RGBA');image.thumbnail((512,512))
                    output=io.BytesIO();image.save(output,format='PNG')
                with lock:
                    avatar_library()
                    raw=output.getvalue();key=hashlib.sha256(raw).hexdigest()
                    (DATA/'圖片收藏'/(key+'.png')).write_bytes(raw)
                    atomic_json(DATA/'頭像設定.json',{'selected':key})
                    temp=DATA/'自訂頭像.tmp';temp.write_bytes(output.getvalue());temp.replace(DATA/'自訂頭像.png')
                self.send(200,b'{}','application/json')
            except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError) as error:
                self.send(400,json.dumps({'error':str(error)},ensure_ascii=False).encode('utf-8'),'application/json; charset=utf-8')
            return
        if self.path=='/api/filters':
            global filters
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<8192:raise ValueError()
                f=json.loads(self.rfile.read(length))
                if f.get('slot') not in ['',*SLOT_NAMES] or not all(isinstance(f.get(g),list) and len(f[g])<=100 and all(isinstance(x,str) and x in CATALOG['stat_names'] for x in f[g]) for g in ['primary','secondary']):raise ValueError()
                with lock:filters={k:f[k] for k in ['slot','primary','secondary']};atomic_json(DATA/'篩選條件.json',filters)
                self.send(200,b'{}','application/json')
            except (ValueError,KeyError):self.send(400,b'Invalid filters','text/plain')
            return
        if self.path!='/api/quit':self.send(404,b'Not found','text/plain');return
        self.send(200,b'{}','application/json');stop.set();threading.Thread(target=self.server.shutdown,daemon=True).start()

def main():
    import ctypes as C
    import webview
    testing='--test-instance' in sys.argv
    if getattr(sys,'frozen',False) and (HOME/maintenance.JOURNAL).exists():
        maintenance.handoff(HOME,{'action':'recover'});return
    title='桌面破壞神小助手 — 裝備篩選器'+('（測試）' if testing else '')
    k=C.WinDLL('kernel32',use_last_error=True)
    k.CreateMutexW.argtypes=[C.c_void_p,C.c_int,C.c_wchar_p];k.CreateMutexW.restype=C.c_void_p
    k.CloseHandle.argtypes=[C.c_void_p]
    mutex=k.CreateMutexW(None,False,'Local\\DeskrawlEquipmentAssistantV1'+('Test' if testing else ''))
    if C.get_last_error()==183:
        u=C.WinDLL('user32');u.FindWindowW.argtypes=[C.c_wchar_p,C.c_wchar_p];u.FindWindowW.restype=C.c_void_p
        u.ShowWindow.argtypes=[C.c_void_p,C.c_int];u.SetForegroundWindow.argtypes=[C.c_void_p]
        window=u.FindWindowW(None,title)
        if window:u.ShowWindow(window,9);u.SetForegroundWindow(window)
        k.CloseHandle(mutex);return
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}/#token={token}'
    atomic_json(DATA/'連線.json',{'mode':'desktop','url':url,'pid':os.getpid(),'window_title':title})
    worker=threading.Thread(target=monitor,daemon=True);worker.start()
    serving=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.25},daemon=True);serving.start()
    window=webview.create_window(title,url,width=1360,height=900,min_size=(1000,680),background_color='#10171b',text_select=True)
    def wait_for_exit():
        stop.wait();window.destroy()
    def close():stop.set()
    window.events.closed+=close
    try:webview.start(wait_for_exit,gui='edgechromium',private_mode=True,storage_path=str(DATA/'瀏覽器快取'))
    finally:
        manager.cancelled.set();stop.set();worker.join(timeout=3);server.shutdown();serving.join(timeout=2);server.server_close();k.CloseHandle(mutex)

if __name__=='__main__':
    try:main()
    except Exception:
        logging.exception('桌面視窗啟動失敗')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'啟動失敗，請查看資料資料夾中的小助手.log。','桌面破壞神小助手',16)
