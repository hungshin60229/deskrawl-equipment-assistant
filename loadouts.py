"""Local per-character favorites and loadouts. Never writes game memory."""
import copy
import hashlib
import json
import uuid
from pathlib import Path

SLOTS = [('Weapon','武器'),('Helm','頭盔'),('Chest','胸甲'),('Pants','褲子'),
         ('Boots','鞋子'),('Belt','腰帶'),('Ring1','戒指一'),('Ring2','戒指二'),
         ('Necklace','項鍊'),('Shoulder','肩甲'),('Gloves','手套'),('Back','背部')]

def scope(character):
    if not character or not character.get('key'):raise ValueError('請先進入遊戲角色')
    return hashlib.sha256(json.dumps([character.get('mode'),character['key']],ensure_ascii=False).encode()).hexdigest()

def compatible(slot,item):
    return item['slot']==('Ring' if slot in ('Ring1','Ring2') else slot)

class Library:
    def __init__(self,data,allowed_stats=None):
        self.allowed_stats=set(allowed_stats) if allowed_stats is not None else None
        self.path=Path(data)/'配裝收藏.json'
        try:self.data=json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:self.data={}
        # Preserve a damaged file rather than silently overwriting collections.
        except (ValueError,OSError):self.data={};self.damaged=True
        if not isinstance(self.data,dict) or any(not isinstance(r,dict) or not isinstance(r.get('favorites'),list) or not isinstance(r.get('builds'),list) for r in self.data.values()):
            self.data={};self.damaged=True

    def records(self,character):
        return self.data.get(scope(character),{'favorites':[], 'builds':[]})

    def save(self,key,records):
        if getattr(self,'damaged',False):raise ValueError('收藏資料無法讀取，請先備份並檢查配裝收藏.json')
        updated={**self.data,key:records}
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(updated,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(self.path);self.data=updated

    def view(self,character,items):
        if not character:return {'favorites':[], 'builds':[], 'preferred_stats':[], 'slots':SLOTS, 'ready':False}
        records=copy.deepcopy(self.records(character));live={i['uid']:i for i in items}
        records.setdefault('preferred_stats',[])
        for build in records['builds']:
            for slot,item in build['equipment'].items():
                if item['uid'] in live:build['equipment'][slot]=copy.deepcopy(live[item['uid']]);build['equipment'][slot]['missing']=False
                else:item['missing']=True
        return {**records,'slots':SLOTS,'ready':True,'scope':scope(character)}

    def observe(self,character,items):
        """Persist last successful values so missing items retain recent rolls."""
        key=scope(character)
        if key not in self.data:return
        records=copy.deepcopy(self.records(character));live={i['uid']:i for i in items};changed=False
        for build in records['builds']:
            for slot,item in build['equipment'].items():
                row=live.get(item['uid'])
                if row is not None and row!=item:build['equipment'][slot]=copy.deepcopy(row);changed=True
        if changed:self.save(key,records)

    def change(self,character,items,command):
        key=scope(character);records=copy.deepcopy(self.records(character));action=command.get('action')
        live={i['uid']:i for i in items}
        if action=='preferences':
            preferred=command.get('stats')
            if not isinstance(preferred,list) or len(preferred)>200 or any(not isinstance(s,str) or len(s)>100 or (self.allowed_stats is not None and s not in self.allowed_stats) for s in preferred):
                raise ValueError('偏愛詞條選擇不正確')
            records['preferred_stats']=list(dict.fromkeys(preferred))
        elif action=='favorite':
            uid=command.get('uid')
            if not isinstance(uid,str):raise ValueError('裝備識別碼不正確')
            if uid in records['favorites']:records['favorites'].remove(uid)
            elif uid in live:records['favorites'].append(uid)
            else:raise ValueError('找不到此裝備，請等待同步')
        elif action=='save':
            name=command.get('name');equipment=command.get('equipment');bid=command.get('id')
            if not isinstance(name,str) or not 1<=len(name.strip())<=40:raise ValueError('名稱需為 1 至 40 字')
            if not isinstance(equipment,dict) or any(s not in dict(SLOTS) for s in equipment):raise ValueError('配裝部位不正確')
            old=next((b for b in records['builds'] if b['id']==bid),None)
            if bid and not old:raise ValueError('找不到 Build，請重新載入')
            selected={};seen=set()
            for slot,uid in equipment.items():
                if not isinstance(uid,str) or uid in seen:raise ValueError('同一件裝備不能配置兩次')
                seen.add(uid);item=live.get(uid)
                if item is None and old:item=old['equipment'].get(slot)
                if not item or item['uid']!=uid or not compatible(slot,item):raise ValueError('裝備已變更或部位不符，請重新選擇')
                selected[slot]=copy.deepcopy(item)
            build={'id':bid or uuid.uuid4().hex,'name':name.strip(),'equipment':selected}
            if old:records['builds'][records['builds'].index(old)]=build
            else:
                if len(records['builds'])>=100:raise ValueError('最多可保存 100 套 Build')
                records['builds'].append(build)
        elif action in ('delete','duplicate'):
            old=next((b for b in records['builds'] if b['id']==command.get('id')),None)
            if not old:raise ValueError('找不到 Build')
            if action=='delete':records['builds'].remove(old)
            else:
                if len(records['builds'])>=100:raise ValueError('最多可保存 100 套 Build')
                new=copy.deepcopy(old);new['id']=uuid.uuid4().hex;new['name']=old['name'][:35]+'（副本）';records['builds'].append(new)
        else:raise ValueError('操作不正確')
        self.save(key,records)
        return self.view(character,items)
