import json,unittest
from pathlib import Path
from unittest.mock import patch
from model import enrich,filter_items,position_label
from reader import stable_capture,NotReady,decode_obscured_float

CATALOG=json.loads((Path(__file__).parent/'assets/catalog.json').read_text(encoding='utf-8'))
def item(uid,level,mods,slot='Ring',location='storage',rarity=3):
    return {'uid':uid,'level':level,'base_name':'LegendaryRing7','slot':slot,'rarity':rarity,
        'location':location,'position':0,'upgrade':0,'ancient':False,'black_mist':False,
        'modifiers':[{'stat':s,'type':0,'value':v} for s,v in mods]}
class Tests(unittest.TestCase):
    def test_inventory_rows(self):
        for index,expected in [(1,'第 1 排第 1 格'),(10,'第 1 排第 10 格'),(11,'第 2 排第 1 格'),(40,'第 4 排第 10 格')]:
            with self.subTest(index=index):self.assertEqual(position_label('inventory',index),expected)
    def test_storage_pages_and_rows(self):
        for index,expected in [(1,'第 1 頁\n第 1 排第 1 格'),(50,'第 1 頁\n第 5 排第 10 格'),(51,'第 2 頁\n第 1 排第 1 格'),(120,'第 3 頁\n第 2 排第 10 格'),(250,'第 5 頁\n第 5 排第 10 格')]:
            with self.subTest(index=index):self.assertEqual(position_label('storage',index),expected)
        self.assertEqual(position_label('equipped',6),'戒指一')
    def test_obscured_float_known_bytes(self):
        # Plain IEEE754 12.5 = 0x41480000, key=0x12345678. ACTk swaps
        # middle ciphertext bytes, storing 0x53567c78 (not 0x537c5678).
        self.assertEqual(decode_obscured_float(0x4caf9553,0x53567c78,0x12345678),12.5)
        with self.assertRaises(NotReady):decode_obscured_float(0x4caf9553,0x537c5678,0x12345678)
        self.assertEqual(decode_obscured_float(0,0,0),0)
    def test_all_conditions_and_category(self):
        rows=enrich({'items':[item('a',800,[('CritChance',.08),('CritDamage',.5),('MagicFind',.2)]),item('b',900,[('CritChance',.08),('GoldFind',.2)]),item('c',950,[('CritChance',.08),('CritDamage',.5),('MagicFind',.2)],slot='Weapon')]},CATALOG)
        self.assertEqual([x['uid'] for x in filter_items(rows,'Ring',['CritChance','CritDamage'],['MagicFind'])],['a'])
        self.assertEqual(filter_items(rows,'Ring',[],['CritChance']),[])
        self.assertEqual(rows[0]['level'],950)
        self.assertEqual(next(x for x in rows if x['uid']=='a')['primary'][0]['display'],'+8.0%')
    def test_user_chest_screenshot(self):
        chest=item('screenshot',820,[('Armor',706),('Thorns',119),('Dodge',.071),('Intelligence',73),('MaxHealth',595),('MagicFind',.3)],slot='Chest',location='equipped')
        chest['base_name']='LegendaryChestArmor5';chest['position']=2
        row=enrich({'items':[chest]},CATALOG)[0]
        self.assertEqual({m['stat']:m['display'] for m in row['primary']},{'Thorns':'+119','Dodge':'+7.1%','Intelligence':'+73','MaxHealth':'+595'})
        self.assertEqual(row['secondary'][0]['display'],'+30.0%')
        self.assertEqual(row['other'][0]['display'],'+706')
    def test_actual_not_possible(self):
        rows=enrich({'items':[item('a',800,[('Intelligence',50),('GoldFind',.2)])]},CATALOG)
        self.assertEqual(filter_items(rows,'Ring',['CritChance']),[])
    def test_intrinsic_armor_is_not_random_primary(self):
        rows=enrich({'items':[item('a',800,[('Armor',600),('Intelligence',50),('MagicFind',.2)],slot='Helm')]},CATALOG)
        self.assertEqual(filter_items(rows,'Helm',['Armor']),[])
        self.assertEqual(rows[0]['other'][0]['stat'],'Armor')
    def test_duplicate_names_keep_independent_instances_and_position(self):
        rows=enrich({'items':[item('a',800,[('CritChance',.08)]),item('b',900,[('CritChance',.08)],location='inventory')]},CATALOG)
        self.assertEqual([r['uid'] for r in rows],['b','a'])
        moved=item('b',900,[('CritChance',.08)],location='equipped');moved['position']=6
        self.assertEqual(enrich({'items':[moved]},CATALOG)[0]['position_label'],'戒指一')
    def test_only_legendary(self):
        self.assertEqual(enrich({'items':[item('a',800,[],rarity=2)]},CATALOG),[])
    def test_stable_capture_rejects_transition(self):
        class Fake:
            def __init__(self,values):self.values=iter(values)
            def capture(self):return next(self.values)
        with patch('reader.time.sleep'):
            with self.assertRaises(NotReady):stable_capture(Fake([{'position':1},{'position':2}]))
            self.assertEqual(stable_capture(Fake([{'position':2},{'position':2}])),{'position':2})
    def test_catalog_ring_classification(self):
        self.assertIn('CritChance',CATALOG['pools']['Ring']['primary'])
        self.assertIn('MagicFind',CATALOG['pools']['Ring']['secondary'])
        self.assertNotIn('CooldownReduction',CATALOG['pools']['Ring']['secondary'])
if __name__=='__main__':unittest.main()
