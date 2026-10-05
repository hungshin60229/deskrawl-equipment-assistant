import copy,json,tempfile,unittest
from pathlib import Path
from loadouts import Library,scope

class LoadoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.home=Path(self.tmp.name);self.lib=Library(self.home)
        self.char={'key':'hero-one','mode':1}
        self.items=[{'uid':'a','slot':'Ring','name':'戒指','level':800,'location':'inventory','position':1,'primary':[],'secondary':[],'other':[]},
                    {'uid':'b','slot':'Chest','name':'胸甲','level':820,'location':'inventory','position':2,'primary':[],'secondary':[],'other':[]}]
    def tearDown(self):self.tmp.cleanup()
    def save(self,equipment,name='刷寶',bid=None):return self.lib.change(self.char,self.items,{'action':'save','equipment':equipment,'name':name,'id':bid})
    def test_favorite_survives_move_and_reload_but_not_character_or_mode_change(self):
        self.lib.change(self.char,self.items,{'action':'favorite','uid':'a'});self.items[0]['location']='storage';self.items[0]['position']=90
        self.assertEqual(Library(self.home).view(self.char,self.items)['favorites'],['a'])
        self.assertEqual(self.lib.view({'key':'other','mode':1},self.items)['favorites'],[])
        self.assertNotEqual(scope(self.char),scope({'key':'hero-one','mode':0}))
    def test_invalid_slot_duplicate_instance_and_unknown_uid_leave_file_unchanged(self):
        self.save({'Chest':'b'});before=self.lib.path.read_bytes()
        for equipment in [{'Helm':'b'},{'Ring1':'a','Ring2':'a'},{'Chest':'missing'},{'Bogus':'b'}]:
            with self.assertRaises(ValueError):self.save(equipment)
            self.assertEqual(self.lib.path.read_bytes(),before)
    def test_live_updates_and_missing_snapshot_retained_without_deleting_build(self):
        first=self.save({'Chest':'b'});bid=first['builds'][0]['id'];self.items[1]['level']=830
        self.assertEqual(self.lib.view(self.char,self.items)['builds'][0]['equipment']['Chest']['level'],830)
        self.lib.observe(self.char,self.items)
        self.assertEqual(Library(self.home).view(self.char,[])['builds'][0]['equipment']['Chest']['level'],830)
        self.items=[];view=self.lib.view(self.char,self.items);self.assertTrue(view['builds'][0]['equipment']['Chest']['missing'])
        self.save({'Chest':'b'},'改名',bid);self.assertEqual(self.lib.view(self.char,[])['builds'][0]['name'],'改名')
    def test_duplicate_delete_and_two_distinct_ring_instances(self):
        ring=copy.deepcopy(self.items[0]);ring['uid']='c';self.items.append(ring)
        first=self.save({'Ring1':'a','Ring2':'c'});bid=first['builds'][0]['id']
        self.lib.change(self.char,self.items,{'action':'duplicate','id':bid});self.assertEqual(len(self.lib.view(self.char,self.items)['builds']),2)
        self.lib.change(self.char,self.items,{'action':'delete','id':bid});self.assertEqual(len(self.lib.view(self.char,self.items)['builds']),1)
        self.assertEqual(len(self.items),3)
    def test_damaged_collection_preserved(self):
        self.lib.path.write_text('broken',encoding='utf-8');lib=Library(self.home)
        with self.assertRaises(ValueError):lib.change(self.char,self.items,{'action':'favorite','uid':'a'})
        self.assertEqual(lib.path.read_text(),'broken')

    def test_preferences_migrate_persist_deduplicate_and_do_not_change_builds(self):
        self.save({'Chest':'b'});before=copy.deepcopy(self.lib.records(self.char)['builds'])
        lib=Library(self.home,['MagicFind','Intelligence'])
        self.assertEqual(lib.view(self.char,self.items)['preferred_stats'],[])
        result=lib.change(self.char,self.items,{'action':'preferences','stats':['MagicFind','MagicFind','Intelligence']})
        self.assertEqual(result['preferred_stats'],['MagicFind','Intelligence']);self.assertEqual(result['builds'][0]['id'],before[0]['id'])
        self.assertEqual(Library(self.home).view(self.char,self.items)['preferred_stats'],result['preferred_stats'])
        self.assertEqual(lib.view({'key':'other','mode':1},self.items)['preferred_stats'],[])
        with self.assertRaises(ValueError):lib.change(self.char,self.items,{'action':'preferences','stats':['UnknownStat']})
        self.assertEqual(lib.records(self.char)['builds'],before)
        lib.change(self.char,self.items,{'action':'preferences','stats':[]})
        self.assertEqual(lib.view(self.char,self.items)['preferred_stats'],[])

if __name__=='__main__':unittest.main()
