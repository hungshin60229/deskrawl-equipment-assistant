"""Windows tray and live window icons; EXE resources update after exit."""
import ctypes as C
import hashlib
import io
import json
import logging
import os
import struct
import threading
from pathlib import Path
from PIL import Image, ImageOps

SIZES = [(n,n) for n in (16,24,32,48,64,128,256)]


def make_icon(source):
    with Image.open(source) as image:
        image = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGBA'),(256,256),method=Image.Resampling.LANCZOS)
        stream=io.BytesIO();image.save(stream,format='ICO',sizes=SIZES)
    return stream.getvalue()


def icon_source(data, assets, selected):
    try:
        choice=json.loads((data/'圖示設定.json').read_text(encoding='utf-8'))['selected']
    except (OSError,ValueError,KeyError):choice=selected if selected!='default' else 'product'
    if choice=='default':return assets/'avatar-default.png'
    if choice==selected and selected!='default':
        import re
        if re.fullmatch('[0-9a-f]{64}',str(selected)) and (data/'圖片收藏'/(selected+'.png')).is_file():
            return data/'圖片收藏'/(selected+'.png')
    # Deleted/stale selections fall back to the product portrait.
    return assets/'product-default.png'


def pe_end(raw):
    if raw[:2]!=b'MZ':raise ValueError('不是小助手執行檔')
    offset=struct.unpack_from('<I',raw,60)[0]
    if raw[offset:offset+4]!=b'PE\0\0':raise ValueError('執行檔格式不正確')
    count=struct.unpack_from('<H',raw,offset+6)[0]
    opt=struct.unpack_from('<H',raw,offset+20)[0]
    table=offset+24+opt
    end=table+count*40
    for i in range(count):
        length,start=struct.unpack_from('<II',raw,table+i*40+16)
        end=max(end,start+length)
    if end>len(raw):raise ValueError('執行檔內容不完整')
    return end


def replace_resources(path, ico):
    """Operate on a COPY, preserving the PyInstaller package byte-for-byte.

    Resource editing APIs can discard PE overlays. Detach the archive first,
    update only RT_ICON/RT_GROUP_ICON, then append the exact original archive.
    """
    path=Path(path);original=path.read_bytes();end=pe_end(original);overlay=original[end:]
    if len(overlay)<88 or overlay[-88:-80]!=b'MEI\x0c\x0b\x0a\x0b\x0e':
        raise ValueError('找不到完整的小助手封裝，未修改檔案')
    reserved,kind,count=struct.unpack_from('<HHH',ico)
    if reserved or kind!=1 or not 1<=count<=16:raise ValueError('圖示格式不正確')
    group=ico[:6];parts=[]
    for i in range(count):
        offset=6+i*16
        width,height,colors,zero,planes,bits,size,start=struct.unpack_from('<BBBBHHII',ico,offset)
        data=ico[start:start+size]
        if len(data)!=size:raise ValueError('圖示資料不完整')
        parts.append(data)
        group+=struct.pack('<BBBBHHIH',width,height,colors,zero,planes,bits,size,i+1)
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.BeginUpdateResourceW.argtypes=[C.c_wchar_p,C.c_int];kernel.BeginUpdateResourceW.restype=C.c_void_p
    kernel.UpdateResourceW.argtypes=[C.c_void_p,C.c_void_p,C.c_void_p,C.c_ushort,C.c_void_p,C.c_uint32]
    kernel.EndUpdateResourceW.argtypes=[C.c_void_p,C.c_int]
    path.write_bytes(original[:end])
    handle=kernel.BeginUpdateResourceW(str(path),False)
    if not handle:raise C.WinError(C.get_last_error())
    try:
        for resource_id,data in enumerate(parts,1):
            buffer=C.create_string_buffer(data)
            if not kernel.UpdateResourceW(handle,C.c_void_p(3),C.c_void_p(resource_id),0,buffer,len(data)):
                raise C.WinError(C.get_last_error())
        buffer=C.create_string_buffer(group)
        if not kernel.UpdateResourceW(handle,C.c_void_p(14),C.c_void_p(1),0,buffer,len(group)):
            raise C.WinError(C.get_last_error())
        if not kernel.EndUpdateResourceW(handle,False):raise C.WinError(C.get_last_error())
        handle=None
    finally:
        if handle:kernel.EndUpdateResourceW(handle,True)
    changed=path.read_bytes();path.write_bytes(changed[:pe_end(changed)]+overlay)
    if path.read_bytes()[-len(overlay):]!=overlay:raise ValueError('封裝驗證失敗')


def apply_exe_icon(home, folder, expected):
    import maintenance as m
    home=m.validate_home(home);icon=home/'資料'/'小助手圖示.ico'
    m.no_links(home/'資料');m.no_links(icon)
    raw=icon.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('圖示已變更，略過這次套用')
    executable=home/m.EXE
    # Stage beside the EXE so atomic replacement also works across C:/D:.
    staged=home/'資料'/'icon-ready.exe'
    m.no_links(staged)
    import shutil
    shutil.copy2(executable,staged)
    replace_resources(staged,raw)
    # os.replace is atomic. Never edit the installed file in-place.
    for attempt in range(20):
        try:os.replace(staged,executable);break
        except PermissionError:
            if attempt==19:raise
            import time
            time.sleep(.5)
    m.write_json(home/'資料'/'圖示同步.json',{'icon_sha256':expected,'exe_sha256':hashlib.sha256(executable.read_bytes()).hexdigest()})
    shell=C.WinDLL('shell32');shell.SHChangeNotify.argtypes=[C.c_long,C.c_uint,C.c_void_p,C.c_void_p]
    filename=C.c_wchar_p(str(executable))
    shell.SHChangeNotify(0x2000,0x0005,C.cast(filename,C.c_void_p),None)


class DesktopShell:
    def __init__(self,window,data,assets,stop,get_selected,frozen=False,home=None):
        self.window,self.data,self.assets,self.stop=window,Path(data),Path(assets),stop
        self.get_selected,self.frozen,self.home=get_selected,frozen,home
        self.tray=None;self.drawing_icon=None;self.icon_hash=None;self.mutex=threading.Lock()

    def ui(self,callback):
        from System import Action
        form=self.window.native
        if form and not form.IsDisposed:
            if form.InvokeRequired:form.Invoke(Action(callback))
            else:callback()

    def start(self):
        try:
            from System.Windows.Forms import NotifyIcon,ContextMenuStrip,ToolStripMenuItem,MouseButtons
            def setup():
                self.tray=NotifyIcon();self.tray.Text='桌面破壞神小助手'
                menu=ContextMenuStrip()
                for title,callback in [('開啟小助手',self.show),('收到右下角',self.hide),('結束小助手',self.stop.set)]:
                    item=ToolStripMenuItem(title)
                    item.Click+=lambda sender,args,fn=callback:fn()
                    menu.Items.Add(item)
                self.tray.ContextMenuStrip=menu
                self.tray.MouseClick+=lambda sender,args:self.show() if args.Button==MouseButtons.Left else None
            self.ui(setup);self.refresh()
            self.ui(lambda:setattr(self.tray,'Visible',True))
        except Exception:logging.exception('常駐圖示啟動失敗')

    def refresh(self):
        if self.stop.is_set():return
        with self.mutex:
            try:
                raw=make_icon(icon_source(self.data,self.assets,self.get_selected()))
                key=hashlib.sha256(raw).hexdigest()
                if key==self.icon_hash:return
                path=self.data/'小助手圖示.ico';temp=path.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(path)
                from System.Drawing import Icon
                drawing=Icon(str(path))
                old=self.drawing_icon
                def apply():
                    self.window.native.Icon=drawing
                    if self.tray:self.tray.Icon=drawing
                self.ui(apply)
                self.drawing_icon=drawing;self.icon_hash=key
                if old:old.Dispose()
            except Exception:logging.exception('圖示切換失敗')

    def show(self):
        self.window.show();self.window.restore()

    def hide(self):self.window.hide()

    def closing(self):
        if not self.stop.is_set():
            self.hide();return False
        self.dispose()

    def dispose(self):
        def clean():
            if self.tray:self.tray.Visible=False;self.tray.Dispose();self.tray=None
        try:
            if self.window.native and not self.window.native.IsDisposed:self.ui(clean)
            elif self.tray:self.tray.Visible=False;self.tray.Dispose();self.tray=None
        except Exception:logging.exception('常駐圖示清理失敗')
        if self.drawing_icon:self.drawing_icon.Dispose();self.drawing_icon=None

    def pending_exe_icon(self):
        if not self.frozen or not self.icon_hash:return None
        path=self.data/'圖示同步.json'
        try:
            applied=json.loads(path.read_text(encoding='utf-8'))
            if applied['icon_sha256']==self.icon_hash and applied['exe_sha256']==hashlib.sha256((Path(self.home)/'桌面破壞神小助手.exe').read_bytes()).hexdigest():return None
        except (OSError,KeyError,ValueError):pass
        return {'action':'icon','icon_sha256':self.icon_hash}
