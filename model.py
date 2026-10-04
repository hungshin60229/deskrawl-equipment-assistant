"""Filtering uses actual instance modifiers, never merely possible affixes."""
SLOT_NAMES={'Weapon':'武器','Helm':'頭盔','Chest':'胸甲','Pants':'褲子','Boots':'鞋子','Belt':'腰帶','Ring':'戒指','Necklace':'項鍊','Shoulder':'肩甲','Gloves':'手套','Back':'背部'}
EQUIP_NAMES=['武器','頭盔','胸甲','褲子','鞋子','腰帶','戒指一','戒指二','項鍊','肩甲','手套','背部']
RARITIES=['普通','不常見','稀有','傳奇','神聖','符文套裝']

def position_label(location,position):
    if location=='equipped':
        return EQUIP_NAMES[position] if 0<=position<len(EQUIP_NAMES) else '穿戴欄'
    if position<1:return '位置同步中'
    # Current game scene: SlotGrid width 640, cell 64, spacing -2 => 10 columns.
    # Storage.Capacity is the per-page constant 50; total pages = 5.
    index=position-1
    if location=='storage':
        page,index=divmod(index,50)
        row,column=divmod(index,10)
        return f'第 {page+1} 頁\n第 {row+1} 排第 {column+1} 格'
    row,column=divmod(index,10)
    return f'第 {row+1} 排第 {column+1} 格'

def enrich(snapshot,catalog):
    result=[]
    for source in snapshot['items']:
        # Version 1 is the requested legendary equipment filter.
        if source['rarity']!=3:continue
        row=dict(source);base=catalog['items'].get(row['base_name'],{})
        row['name']=base.get('name') or row['base_name'] or '未對應裝備'
        row['icon']=base.get('icon');row['slot_name']=SLOT_NAMES.get(row['slot'],row['slot'])
        row['position_label']=position_label(row['location'],row['position'])
        row['primary']=[];row['secondary']=[];row['other']=[]
        pool=catalog['pools'].get(row['slot'],{'primary':[],'secondary':[]})
        for index,mod in enumerate(row['modifiers']):
            stat=mod['stat'];value=mod['value'];kind=mod['type']
            percent=stat in catalog['pct_stats'] or kind in [1,2]
            number=value*100 if percent else value
            formatted=f'{number:.1f}' if percent else f'{number:.2f}'.rstrip('0').rstrip('.')
            mod={**mod,'name':catalog['stat_names'].get(stat,stat),'display':('+' if number>=0 else '')+formatted+('%' if percent else '')}
            group='primary' if stat in pool['primary'] else 'secondary' if stat in pool['secondary'] else 'other'
            # Generator prepends the intrinsic armor roll before its affix draws.
            if index==0 and stat=='Armor' and row['slot'] in ['Helm','Chest','Pants','Boots','Gloves','Shoulder']:
                group='other'
            row[group].append(mod)
        result.append(row)
    return sorted(result,key=lambda x:(-x['level'],x['name'],x['uid']))

def filter_items(items,slot='',primary=(),secondary=()):
    return [row for row in items if (not slot or row['slot']==slot)
        and set(primary)<={m['stat'] for m in row['primary']}
        and set(secondary)<={m['stat'] for m in row['secondary']}]
