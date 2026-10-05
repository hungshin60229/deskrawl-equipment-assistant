import copy
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import maintenance as m


def release_for(files, version='1.3.0'):
    blocks = {}
    manifest = {'schema': 1, 'product': m.PRODUCT, 'chunking': 'gear-v1', 'version': version, 'files': []}
    for name, raw in files.items():
        parts = list(m.chunks(raw));blocks.update(parts)
        manifest['files'].append({'path': name, 'size': len(raw), 'sha256': m.digest(raw),
                                  'chunks': [{'sha256': k, 'size': len(v)} for k, v in parts]})
    return manifest, blocks


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / '小助手';self.home.mkdir()
        self.old = random.Random(8).randbytes(3 * 1024 * 1024)
        (self.home / m.EXE).write_bytes(self.old)
        (self.home / '使用說明.txt').write_bytes(b'old instructions')
        (self.home / '資料').mkdir()
        self.personal = self.home / '資料' / '照片.png';self.personal.write_bytes(b'personal photo')
        self.files = {m.EXE: self.old[:500000] + b'new compiled code' + self.old[500000:], '使用說明.txt': b'new instructions'}
        self.manifest, self.blocks = release_for(self.files)
    def tearDown(self):self.temp.cleanup()

    def test_insertion_reuses_existing_content_and_reconstructs_exact_bytes(self):
        available = m.local_blocks(self.home)
        missing = m.missing_blocks(self.manifest, available)
        self.assertLess(sum(missing.values()), len(self.old) * .6)
        available.update({key: self.blocks[key] for key in missing})
        stage = Path(self.temp.name) / 'stage'
        m.reconstruct(self.manifest, available, stage)
        for name, raw in self.files.items():self.assertEqual((stage / name).read_bytes(), raw)

    def test_same_content_needs_zero_download(self):
        manifest, _ = release_for({n: (self.home/n).read_bytes() for n in m.MANAGED_FILES})
        self.assertEqual(m.missing_blocks(manifest, m.local_blocks(self.home)), {})

    def test_manifest_rejects_path_traversal_foreign_paths_duplicates_and_bad_size(self):
        for path in ['../outside.exe', '資料/照片.png', 'C:/Windows/explorer.exe', m.EXE]:
            manifest = copy.deepcopy(self.manifest);manifest['files'][1]['path'] = path
            with self.assertRaises(ValueError):m.validate_manifest(manifest)
        for field, value in [('schema', 99), ('product', 'other'), ('chunking', 'other')]:
            manifest = copy.deepcopy(self.manifest);manifest[field] = value
            with self.assertRaises(ValueError):m.validate_manifest(manifest)
        manifest = copy.deepcopy(self.manifest);manifest['files'][0]['chunks'][0]['size'] += 1
        with self.assertRaises(ValueError):m.validate_manifest(manifest)
        with self.assertRaises(ValueError):m.validate_manifest(self.manifest, 'v9.0.0')

    def test_corrupt_block_and_corrupt_full_hash_rejected(self):
        blocks = dict(self.blocks);blocks[next(iter(blocks))] = b'corrupt'
        with self.assertRaises(ValueError):m.reconstruct(self.manifest, blocks, Path(self.temp.name)/'bad')
        bad = copy.deepcopy(self.manifest);bad['files'][0]['sha256'] = '0'*64
        with self.assertRaises(ValueError):m.reconstruct(bad, self.blocks, Path(self.temp.name)/'bad2')
        self.assertEqual((self.home/m.EXE).read_bytes(), self.old)

    def test_apply_update_preserves_photos_settings_and_removes_backup(self):
        stage = Path(self.temp.name)/'stage';m.reconstruct(self.manifest,self.blocks,stage)
        m.apply_update(self.home,stage,self.manifest)
        for name, raw in self.files.items():self.assertEqual((self.home/name).read_bytes(),raw)
        self.assertEqual(self.personal.read_bytes(),b'personal photo')
        self.assertFalse((self.home/m.JOURNAL).exists())
        self.assertFalse((self.home/'資料'/'.更新復原').exists())

    def test_locked_second_file_rolls_back_first_file(self):
        stage = Path(self.temp.name)/'stage';m.reconstruct(self.manifest,self.blocks,stage)
        original = m.os.replace
        def locked(source,target):
            if Path(source).name == 'new-使用說明.txt':raise PermissionError('locked')
            return original(source,target)
        with patch.object(m.os,'replace',side_effect=locked):
            with self.assertRaises(PermissionError):m.apply_update(self.home,stage,self.manifest)
        self.assertEqual((self.home/m.EXE).read_bytes(),self.old)
        self.assertEqual((self.home/'使用說明.txt').read_bytes(),b'old instructions')
        self.assertEqual(self.personal.read_bytes(),b'personal photo')

    def test_power_loss_journal_restores_original_files(self):
        backup = self.home/'資料'/'.更新復原';backup.mkdir()
        for name in m.MANAGED_FILES:(backup/name).write_bytes((self.home/name).read_bytes())
        (self.home/m.EXE).write_bytes(b'incomplete new version')
        m.write_json(self.home/m.JOURNAL,{'product':m.PRODUCT,'files':list(m.MANAGED_FILES),'phase':'prepared','created':[]})
        m.recover(self.home)
        self.assertEqual((self.home/m.EXE).read_bytes(),self.old)
        self.assertFalse((self.home/m.JOURNAL).exists())

    def test_corrupt_stage_does_not_replace_old_version(self):
        stage = Path(self.temp.name)/'stage';m.reconstruct(self.manifest,self.blocks,stage)
        (stage/m.EXE).write_bytes(b'changed after download')
        with self.assertRaises(ValueError):m.apply_update(self.home,stage,self.manifest)
        self.assertEqual((self.home/m.EXE).read_bytes(),self.old)

    def test_uninstall_removes_entire_owned_folder(self):
        (self.home/'版本備份').mkdir();(self.home/'版本備份'/'old.exe').write_bytes(b'old')
        (self.home/'原始碼').mkdir();(self.home/'原始碼'/'app.py').write_text('example')
        self.assertEqual(m.remove_installation(self.home),[])
        self.assertFalse(self.home.exists())

    def test_uninstall_preserves_foreign_files_and_game(self):
        foreign = self.home/'朋友文件.txt';foreign.write_text('keep')
        game = Path(self.temp.name)/'game';game.mkdir();(game/'Deskrawl.exe').write_bytes(b'game')
        self.assertEqual(m.remove_installation(self.home),['朋友文件.txt'])
        self.assertEqual(foreign.read_text(),'keep')
        self.assertEqual((game/'Deskrawl.exe').read_bytes(),b'game')

    def test_uninstall_refuses_game_directory_before_deleting_anything(self):
        (self.home/'Deskrawl.exe').write_bytes(b'game')
        with self.assertRaises(ValueError):m.remove_installation(self.home)
        self.assertTrue(self.personal.exists());self.assertTrue((self.home/m.EXE).exists())

    def test_uninstall_refuses_reparse_points_before_deleting_anything(self):
        original = m.no_links
        def reject(path):
            if Path(path) == self.personal:raise ValueError('junction')
            return original(path)
        with patch.object(m,'no_links',side_effect=reject):
            with self.assertRaises(ValueError):m.remove_installation(self.home)
        self.assertTrue(self.personal.exists());self.assertTrue((self.home/m.EXE).exists())

    def client(self, corrupt=False, cancel=False):
        tests=self
        class FakeClient:
            def __init__(self,cancelled):self.calls=[];self.cancelled=cancelled;tests.fake=self
            def latest(self):return {'tag_name':'v1.3.0'}
            def manifest(self,release):return tests.manifest
            def asset_url(self,tag,name):return name
            def read(self,url,limit,progress):
                self.calls.append(url);raw=tests.blocks[url.removeprefix('chunk-').removesuffix('.bin')]
                if cancel:raise InterruptedError('cancel')
                progress(len(raw));return b'bad' if corrupt else raw
        return FakeClient

    def test_manager_downloads_only_missing_blocks_no_full_zip(self):
        missing=m.missing_blocks(self.manifest,m.local_blocks(self.home));jobs=[]
        manager=m.Manager(self.home,True,jobs.append,client_factory=self.client())
        manager.run('update')
        self.assertEqual(manager.snapshot()['status'],'restarting')
        self.assertEqual(len(self.fake.calls),len(missing))
        self.assertEqual(manager.snapshot()['downloaded'],sum(missing.values()))
        self.assertEqual(len(jobs),1)
        self.assertTrue(all(name.startswith('chunk-') for name in self.fake.calls))
        self.assertEqual(self.personal.read_bytes(),b'personal photo')

    def test_download_corruption_or_cancellation_never_applies(self):
        for corrupt,cancel,status in [(True,False,'error'),(False,True,'cancelled')]:
            manager=m.Manager(self.home,True,lambda _:self.fail('must not apply'),client_factory=self.client(corrupt,cancel))
            manager.run('update');self.assertEqual(manager.snapshot()['status'],status)
            self.assertEqual((self.home/m.EXE).read_bytes(),self.old)

    def test_current_or_older_release_does_not_download(self):
        manager=m.Manager(self.home,True,current='1.3.0',client_factory=self.client())
        manager.run('update');self.assertEqual(manager.snapshot()['status'],'current');self.assertEqual(self.fake.calls,[])

    def test_busy_or_source_mode_cannot_launch_second_operation(self):
        manager=m.Manager(self.home,False)
        with self.assertRaises(ValueError):manager.start('update')
        manager.frozen=True;manager.report(status='downloading')
        with self.assertRaises(ValueError):manager.start('uninstall')

    def test_github_manifest_checks_server_digest_before_parsing(self):
        raw=json.dumps(self.manifest).encode()
        release={'tag_name':'v1.3.0','assets':[{'name':'update-manifest.json','state':'uploaded','digest':'sha256:'+'0'*64}]}
        client=m.GitHub()
        with patch.object(client,'read',return_value=raw):
            with self.assertRaises(ValueError):client.manifest(release)


if __name__=='__main__':unittest.main()
