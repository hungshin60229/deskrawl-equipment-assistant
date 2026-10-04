"""Version-pinned, read-only IL2CPP inventory reader. No game writes or calls."""
import ctypes as C
from ctypes import wintypes as W
import struct,hashlib,math,time
from pathlib import Path

class NotReady(Exception):pass
class VersionMismatch(Exception):pass
class GameClosed(Exception):pass

def decode_obscured_float(checksum,hidden,key):
    # ACTk.Runtime.dll 0x180454810 / 0x180454b1f: undo the byte-1/byte-2
    # permutation BEFORE XOR. XOR alone produces plausible but incorrect floats.
    restored=(hidden&0xff0000ff)|((hidden&0x0000ff00)<<8)|((hidden&0x00ff0000)>>8)
    bits=restored^key
    if checksum==hidden==key==0:return 0.0
    # Exact per-byte hash used by this game build, 0x180454b55..0x180454b99.
    h=0x811c9dc6
    for byte in bits.to_bytes(4,'little'):h=((h^byte)*0x1000192)&0xffffffff
    if (h|1)!=checksum:raise NotReady('詞條數值尚未穩定，等待同步')
    value=struct.unpack('<f',struct.pack('<I',bits))[0]
    if not math.isfinite(value):raise NotReady('等待詞條數值')
    return value

class PROCESSENTRY32(C.Structure):
    _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),('th32DefaultHeapID',C.c_size_t),('th32ModuleID',W.DWORD),('cntThreads',W.DWORD),('th32ParentProcessID',W.DWORD),('pcPriClassBase',W.LONG),('dwFlags',W.DWORD),('szExeFile',W.WCHAR*260)]
class MODULEENTRY32(C.Structure):
    _fields_=[('dwSize',W.DWORD),('th32ModuleID',W.DWORD),('th32ProcessID',W.DWORD),('GlblcntUsage',W.DWORD),('ProccntUsage',W.DWORD),('modBaseAddr',C.c_void_p),('modBaseSize',W.DWORD),('hModule',W.HMODULE),('szModule',W.WCHAR*256),('szExePath',W.WCHAR*260)]

class LiveReader:
    def __init__(self,config):
        self.config=config;self.handle=None;self.pid=None;self.base=None;self.verified={}
        self.k=C.WinDLL('kernel32',use_last_error=True)
        for name,args,ret in [
            ('OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE),
            ('CloseHandle',[W.HANDLE],W.BOOL),
            ('ReadProcessMemory',[W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)],W.BOOL),
            ('CreateToolhelp32Snapshot',[W.DWORD,W.DWORD],W.HANDLE),
            ('Process32FirstW',[W.HANDLE,C.POINTER(PROCESSENTRY32)],W.BOOL),
            ('Process32NextW',[W.HANDLE,C.POINTER(PROCESSENTRY32)],W.BOOL),
            ('Module32FirstW',[W.HANDLE,C.POINTER(MODULEENTRY32)],W.BOOL),
            ('Module32NextW',[W.HANDLE,C.POINTER(MODULEENTRY32)],W.BOOL),
            ('GetExitCodeProcess',[W.HANDLE,C.POINTER(W.DWORD)],W.BOOL)]:
            fn=getattr(self.k,name);fn.argtypes=args;fn.restype=ret
        self.stat_names={v:k for k,v in config['enums']['StatType'].items()}

    def close(self):
        if self.handle:self.k.CloseHandle(self.handle)
        self.handle=None;self.pid=None

    def snapshot_handle(self,flags,pid=0):
        h=self.k.CreateToolhelp32Snapshot(flags,pid)
        if h==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
        return h

    def connect(self):
        if self.handle:
            code=W.DWORD()
            if self.k.GetExitCodeProcess(self.handle,C.byref(code)) and code.value==259:return
            self.close()
        h=self.snapshot_handle(2);entry=PROCESSENTRY32();entry.dwSize=C.sizeof(entry);pids=[]
        try:
            more=self.k.Process32FirstW(h,C.byref(entry))
            while more:
                if entry.szExeFile.lower()=='deskrawl.exe':pids.append(entry.th32ProcessID)
                more=self.k.Process32NextW(h,C.byref(entry))
        finally:self.k.CloseHandle(h)
        if not pids:raise GameClosed('遊戲未啟動')
        if len(pids)!=1:raise NotReady('偵測到多個遊戲，請保留一個遊戲視窗')
        pid=pids[0];h=self.snapshot_handle(0x18,pid);module=MODULEENTRY32();module.dwSize=C.sizeof(module);found=None
        try:
            more=self.k.Module32FirstW(h,C.byref(module))
            while more:
                if module.szModule.lower()=='gameassembly.dll':found=(module.modBaseAddr,Path(module.szExePath));break
                more=self.k.Module32NextW(h,C.byref(module))
        finally:self.k.CloseHandle(h)
        if not found:raise NotReady('等待遊戲載入')
        base,path=found
        metadata=path.parent/'Deskrawl_Data/il2cpp_data/Metadata/global-metadata.dat'
        signature=(str(path),path.stat().st_mtime_ns,path.stat().st_size,metadata.stat().st_mtime_ns)
        if signature not in self.verified:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=self.config['assembly_sha256'] or hashlib.sha256(metadata.read_bytes()).hexdigest()!=self.config['metadata_sha256']:
                raise VersionMismatch('遊戲版本已變更，需要更新小助手的讀取資料')
            self.verified[signature]=True
        handle=self.k.OpenProcess(0x10|0x1000,False,pid)
        if not handle:raise C.WinError(C.get_last_error())
        self.handle=handle;self.pid=pid;self.base=base

    def read(self,address,size):
        if not address or not 0<=size<=1048576:raise NotReady('等待角色資料')
        buf=C.create_string_buffer(size);got=C.c_size_t()
        if not self.k.ReadProcessMemory(self.handle,C.c_void_p(address),buf,size,C.byref(got)) or got.value!=size:
            raise NotReady('等待遊戲資料穩定')
        return buf.raw
    def num(self,a,fmt='<i'):return struct.unpack(fmt,self.read(a,struct.calcsize(fmt)))[0]
    def ptr(self,a):return self.num(a,'<Q')
    def string(self,a):
        if not a:return ''
        n=self.num(a+16)
        if not 0<=n<=100000:raise NotReady('等待字串資料')
        return self.read(a+20,n*2).decode('utf-16-le') if n else ''
    def static(self,name):
        candidates=set()
        for rva in self.config['type_rvas'][name]:
            try:
                cls=self.ptr(self.base+rva)
                if cls<0x10000:continue
                fields=self.ptr(cls+0xb8);instance=self.ptr(fields)
                if instance:candidates.add(instance)
            except NotReady:continue
        if len(candidates)!=1:raise NotReady('等待角色載入')
        return candidates.pop()
    def dictionary(self,a,key='string',value='pointer'):
        if not a:return {}
        entries=self.ptr(a+24);count=self.num(a+32);version=self.num(a+36)
        if not 0<=count<=10000:raise NotReady('等待物品清單')
        result={}
        if count:
            data=self.read(entries+32,count*24)
            for i in range(count):
                pos=i*24
                if struct.unpack_from('<i',data,pos)[0]<0:continue
                k=self.string(struct.unpack_from('<Q',data,pos+8)[0]) if key=='string' else struct.unpack_from('<i',data,pos+8)[0]
                v=struct.unpack_from('<Q',data,pos+16)[0]
                result[k]=self.string(v) if value=='string' else v
        if version!=self.num(a+36) or count!=self.num(a+32):raise NotReady('裝備移動中')
        return result
    def generated(self,a):
        if not a:raise NotReady('等待裝備屬性')
        result={}
        for f in self.config['generated_fields']:
            p=a+f['offset'];typ=f['type'];name=f['name']
            if typ in ['int','ItemRarity']:result[name]=self.num(p)
            elif typ=='bool':result[name]=self.num(p,'<?')
            elif name=='Modifiers':
                arr=self.ptr(p);mods=[]
                if arr:
                    n=self.num(arr+24,'<Q')
                    if n>100:raise NotReady('等待詞條')
                    data=self.read(arr+32,n*28)
                    for j in range(n):
                        stat,kind=struct.unpack_from('<ii',data,j*28)
                        checksum,hidden,key=struct.unpack_from('<III',data,j*28+8)
                        v=decode_obscured_float(checksum,hidden,key)
                        mods.append({'stat':self.stat_names.get(stat,str(stat)),'type':kind,'value':v})
                result['Modifiers']=mods
        return result
    def slots(self,arr,location):
        if not arr:return []
        n=self.num(arr+24,'<Q')
        if n>10000:raise NotReady('等待背包資料')
        pointers=struct.unpack('<'+'Q'*n,self.read(arr+32,n*8)) if n else []
        result=[]
        for i,a in enumerate(pointers):
            if not a:continue
            item=self.ptr(a+16)
            if not item or self.num(item+32)!=3:continue
            uid=self.string(self.ptr(a+32))
            if not uid:raise NotReady('等待裝備識別碼')
            result.append({'uid':uid,'item':item,'location':location,'position':i+1})
        return result
    def capture(self):
        self.connect()
        game=self.static('GameManager')
        playing=self.config['enums']['GameState']['Playing']
        if self.num(game+168)!=playing:raise NotReady('等待進入角色')
        save=self.static('SaveSystem');mode=self.num(save+32);selected=self.num(save+36);container=self.ptr(save+40)
        records=self.ptr(container+(32 if mode==1 else 24))
        if not records or not 0<=selected<self.num(records+24):raise NotReady('等待角色載入')
        record=self.ptr(self.ptr(records+16)+32+selected*8)
        character={'key':self.string(self.ptr(record+24)),'level':self.num(record+40),'hero':self.string(self.ptr(record+48)),'mode':mode}
        inv=self.static('Inventory');storage=self.static('Storage');equip=self.static('EquipmentManager')
        registry=self.dictionary(self.static('gi'))
        names={p:name for name,p in self.dictionary(self.ptr(save+112)).items()}
        rows=self.slots(self.ptr(inv+56),'inventory')+self.slots(self.ptr(storage+48),'storage')
        eq=self.dictionary(self.ptr(equip+40),'int');uids=self.dictionary(self.ptr(equip+48),'int','string')
        for slot,item in eq.items():
            if item:rows.append({'uid':uids.get(slot),'item':item,'location':'equipped','position':slot})
        seen=set()
        for row in rows:
            uid=row['uid'];item=row.pop('item')
            if not uid or uid in seen or uid not in registry:raise NotReady('裝備移動中，等待同步')
            seen.add(uid)
            g=self.generated(registry[uid]);slot=self.num(item+144)
            row.update({'base_name':names.get(item,''),'slot':next((k for k,v in self.config['enums']['EquipSlotType'].items() if v==slot),'Unknown'),
                'rarity':g['Rarity'],'level':g['ItemLevel'],'upgrade':g['UpgradeLevel'],'ancient':g['IsAncient'],
                'black_mist':g['IsBlackMist'],'modifiers':g['Modifiers']})
        if selected!=self.num(save+36) or mode!=self.num(save+32) or self.num(game+168)!=playing:raise NotReady('角色切換中')
        return {'character':character,'items':sorted(rows,key=lambda x:x['uid'])}

def stable_capture(reader):
    first=reader.capture()
    time.sleep(.08)
    second=reader.capture()
    if first!=second:raise NotReady('裝備變動中，等待同步')
    return second
