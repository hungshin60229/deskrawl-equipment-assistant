"""Portable lifecycle: content-defined GitHub updates and scoped removal.

No game paths or process handles are used by this module. Release chunks are
verified before any installed file is changed; helper mode runs outside HOME.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = '1.4.0'
PRODUCT = 'deskrawl-equipment-assistant'
REPO = 'hungshin60229/' + PRODUCT
EXE = '桌面破壞神小助手.exe'
MANAGED_FILES = (EXE, '使用說明.txt')
MIN_CHUNK, MAX_CHUNK = 128 * 1024, 2 * 1024 * 1024
MASK = (1 << 19) - 1
GEAR = [int.from_bytes(hashlib.sha256(bytes([i])).digest()[:8], 'little') for i in range(256)]
MAX_TOTAL = 256 * 1024 * 1024
SHA = re.compile(r'[0-9a-f]{64}')
JOURNAL = '.小助手維護.json'
OWNED = {*MANAGED_FILES, '資料', '原始碼', '版本備份', '小助手版本.json',
         '位置顯示更新.txt', '第一版介面.jpg', '測試紀錄.txt', '數值修正說明.txt'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def chunks(raw):
    """Gear hash boundaries survive insertions, unlike fixed byte offsets."""
    start = 0
    rolling = 0
    for end, byte in enumerate(raw, 1):
        rolling = ((rolling << 1) + GEAR[byte]) & 0xffffffffffffffff
        length = end - start
        if length >= MAX_CHUNK or (length >= MIN_CHUNK and rolling & MASK == 0):
            block = raw[start:end]
            yield digest(block), block
            start, rolling = end, 0
    if start < len(raw):
        block = raw[start:]
        yield digest(block), block


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', value):
        raise ValueError('版本編號格式不正確')
    return tuple(map(int, value.lstrip('v').split('.')))


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def no_links(path):
    """Reject junctions/symlinks, including Windows mount-point reparse tags."""
    path = Path(path)
    if path.is_symlink() or (path.exists() and getattr(path.lstat(), 'st_file_attributes', 0) & 1024):
        raise ValueError('資料夾含有連結，無法安全操作：' + path.name)


def validate_home(home):
    home = Path(home).absolute()
    for parent in [home, *home.parents]:
        no_links(parent)
    home = home.resolve(strict=True)
    if home == Path(home.anchor) or home == Path.home().resolve():
        raise ValueError('小助手需要放在獨立資料夾內')
    if not (home / EXE).is_file():
        raise ValueError('找不到小助手執行檔')
    if any((home / name).exists() for name in ['Deskrawl.exe', 'GameAssembly.dll', 'Deskrawl_Data']):
        raise ValueError('請先將小助手移到獨立資料夾，避免在遊戲資料夾內操作')
    no_links(home / EXE)
    return home


def removal_plan(home):
    home = validate_home(home)
    if (home / JOURNAL).exists():
        raise ValueError('尚有未完成的更新，請重新開啟小助手完成復原')
    paths, unknown = [], []
    for entry in home.iterdir():
        if entry.name not in OWNED:
            unknown.append(entry.name)
            continue
        no_links(entry)
        if entry.is_dir():
            for descendant in entry.rglob('*'):
                no_links(descendant)
        paths.append(entry)
    return paths, unknown


def remove_installation(home):
    home = validate_home(home)
    paths, unknown = removal_plan(home)  # validate the entire tree BEFORE deleting
    # Remove the executable last so a locked browser cache never leaves a
    # partially removed installation that cannot retry removal.
    paths.sort(key=lambda path: path.name == EXE)
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    if not any(home.iterdir()):
        home.rmdir()
    return unknown


class GitHub:
    def __init__(self, cancelled=lambda: False):
        self.cancelled = cancelled

    def read(self, url, limit, progress=None):
        if self.cancelled():
            raise InterruptedError('已取消更新')
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('api.github.com', 'github.com'):
            raise ValueError('更新來源不正確')
        request = urllib.request.Request(url, headers={
            'User-Agent': PRODUCT + '/' + VERSION,
            'Accept': 'application/vnd.github+json' if parsed.hostname == 'api.github.com' else 'application/octet-stream',
            'X-GitHub-Api-Version': '2022-11-28',
        })
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                redirected = urllib.parse.urlsplit(response.url)
                if redirected.scheme != 'https' or redirected.hostname not in (
                    'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'
                ):
                    raise ValueError('下載來源不正確')
                if int(response.headers.get('Content-Length', '0')) > limit:
                    raise ValueError('更新檔案超過大小限制')
                parts, size = [], 0
                while True:
                    if self.cancelled():
                        raise InterruptedError('已取消更新')
                    block = response.read(65536)
                    if not block:
                        return b''.join(parts)
                    size += len(block)
                    if size > limit:
                        raise ValueError('更新檔案超過大小限制')
                    parts.append(block)
                    if progress:
                        progress(len(block))
        except urllib.error.HTTPError as error:
            if error.code == 403 or error.code == 429:
                raise RuntimeError('GitHub 暫時限制請求，請稍後再試') from error
            if error.code == 404:
                raise RuntimeError('最新版本尚未提供完整更新檔，請稍後再試') from error
            raise RuntimeError('GitHub 下載失敗，請稍後重試') from error

    def latest(self):
        release = json.loads(self.read('https://api.github.com/repos/' + REPO + '/releases/latest', 2 * 1024 * 1024))
        version(release['tag_name'])
        if release.get('draft') or release.get('prerelease'):
            raise ValueError('更新版本尚未正式發布')
        if not isinstance(release.get('id'), int):
            raise ValueError('版本資訊不正確')
        if len(release.get('assets', [])) >= 100:
            all_assets = []
            for page in range(1, 11):
                page_assets = json.loads(self.read(
                    f'https://api.github.com/repos/{REPO}/releases/{release["id"]}/assets?per_page=100&page={page}',
                    2 * 1024 * 1024))
                all_assets.extend(page_assets)
                if len(page_assets) < 100:
                    break
            release['assets'] = all_assets
        return release

    def manifest(self, release):
        assets = {a['name']: a for a in release['assets'] if a.get('state') == 'uploaded'}
        asset = assets.get('update-manifest.json')
        if not asset:
            raise RuntimeError('這個版本尚未提供增量更新，請從下載頁取得新版')
        expected = asset.get('digest', '').removeprefix('sha256:')
        if not SHA.fullmatch(expected):
            raise ValueError('GitHub 尚未完成更新檔校驗，請稍後重試')
        raw = self.read(self.asset_url(release['tag_name'], asset['name']), 2 * 1024 * 1024)
        if digest(raw) != expected:
            raise ValueError('更新資訊校驗失敗，未變更任何檔案')
        manifest = json.loads(raw)
        validate_manifest(manifest, release['tag_name'])
        for file in manifest['files']:
            for chunk in file['chunks']:
                asset = assets.get('chunk-' + chunk['sha256'] + '.bin')
                if not asset or asset['size'] != chunk['size']:
                    raise ValueError('版本缺少更新區塊，請稍後重試')
                if asset.get('digest') != 'sha256:' + chunk['sha256']:
                    raise ValueError('更新區塊校驗資訊不正確')
        return manifest

    @staticmethod
    def asset_url(tag, name):
        return f'https://github.com/{REPO}/releases/download/{urllib.parse.quote(tag, safe="")}/{urllib.parse.quote(name, safe="")}'


def validate_manifest(manifest, tag=None):
    if manifest.get('schema') != 1 or manifest.get('product') != PRODUCT or manifest.get('chunking') != 'gear-v1':
        raise ValueError('更新格式不支援')
    version(manifest.get('version'))
    if tag is not None and version(manifest['version']) != version(tag):
        raise ValueError('更新版本與發布版本不符')
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) != len(MANAGED_FILES):
        raise ValueError('更新檔案清單不完整')
    if {f.get('path') for f in files} != set(MANAGED_FILES):
        raise ValueError('更新只能替換小助手程式與使用說明')
    total = 0
    for file in files:
        if not SHA.fullmatch(str(file.get('sha256'))) or type(file.get('size')) is not int or not 0 < file['size'] <= MAX_TOTAL:
            raise ValueError('更新檔案校驗格式不正確')
        blocks = file.get('chunks')
        if not isinstance(blocks, list) or not 0 < len(blocks) <= 1024:
            raise ValueError('更新區塊清單不正確')
        for block in blocks:
            if not SHA.fullmatch(str(block.get('sha256'))) or type(block.get('size')) is not int or not 0 < block['size'] <= MAX_CHUNK:
                raise ValueError('更新區塊格式不正確')
        if sum(c['size'] for c in blocks) != file['size']:
            raise ValueError('更新區塊大小不符')
        total += file['size']
    if total > MAX_TOTAL:
        raise ValueError('更新檔案過大')


def local_blocks(home):
    blocks = {}
    for name in MANAGED_FILES:
        path = Path(home) / name
        no_links(path)
        if path.is_file():
            if path.stat().st_size > MAX_TOTAL:
                raise ValueError('本機檔案過大')
            blocks.update(chunks(path.read_bytes()))
    return blocks


def missing_blocks(manifest, available):
    wanted = {c['sha256']: c['size'] for f in manifest['files'] for c in f['chunks']}
    return {key: size for key, size in wanted.items() if key not in available or len(available[key]) != size}


def reconstruct(manifest, available, stage):
    validate_manifest(manifest)
    stage = Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    for file in manifest['files']:
        target = stage / file['path']
        with target.open('wb') as stream:
            for part in file['chunks']:
                raw = available[part['sha256']]
                if len(raw) != part['size'] or digest(raw) != part['sha256']:
                    raise ValueError('更新區塊校驗失敗')
                stream.write(raw)
        if digest(target.read_bytes()) != file['sha256']:
            raise ValueError('完整更新檔校驗失敗')


def verify_stage(stage, manifest):
    validate_manifest(manifest)
    stage = Path(stage)
    for file in manifest['files']:
        path = stage / file['path']
        no_links(path)
        if path.stat().st_size != file['size'] or digest(path.read_bytes()) != file['sha256']:
            raise ValueError('更新檔已變更，未套用更新')


def recover(home):
    home = validate_home(home)
    path = home / JOURNAL
    if not path.exists():
        return
    no_links(path)
    job = json.loads(path.read_text(encoding='utf-8'))
    if job.get('product') != PRODUCT or job.get('files') != list(MANAGED_FILES):
        raise ValueError('更新復原資訊不正確')
    backup = home / '資料' / '.更新復原'
    for parent in (home / '資料', backup):
        no_links(parent)
    if job.get('phase') != 'committed':
        for name in MANAGED_FILES:
            saved = backup / name
            no_links(saved)
            if saved.exists():
                os.replace(saved, home / name)
            elif name in job.get('created', []):
                (home / name).unlink(missing_ok=True)
    if backup.exists():
        shutil.rmtree(backup)
    path.unlink()


def apply_update(home, stage, manifest):
    home = validate_home(home)
    recover(home)
    verify_stage(stage, manifest)
    backup = home / '資料' / '.更新復原'
    no_links(home / '資料')
    no_links(backup)
    backup.mkdir(parents=True, exist_ok=False)
    journal = {'product': PRODUCT, 'files': list(MANAGED_FILES), 'phase': 'prepared',
               'created': [n for n in MANAGED_FILES if not (home / n).exists()]}
    # Copy all originals before moving the first file. A crash during this copy
    # has not changed installed files, so recovery simply restores available ones.
    write_json(home / JOURNAL, journal)
    try:
        for name in MANAGED_FILES:
            no_links(home / name)
            if (home / name).exists():
                shutil.copy2(home / name, backup / name)
            shutil.copy2(Path(stage) / name, backup / ('new-' + name))
        for name in MANAGED_FILES:
            os.replace(backup / ('new-' + name), home / name)
        write_json(home / '小助手版本.json', {'product': PRODUCT, 'version': manifest['version']})
        journal['phase'] = 'committed'
        write_json(home / JOURNAL, journal)
    except Exception:
        recover(home)
        raise
    recover(home)


class Manager:
    def __init__(self, home, frozen=False, on_ready=lambda job: None, current=VERSION, client_factory=GitHub):
        self.home, self.frozen, self.on_ready = Path(home), frozen, on_ready
        self.current, self.client_factory = current, client_factory
        self.mutex, self.cancelled = threading.Lock(), threading.Event()
        self.state = {'status': 'idle', 'version': current, 'message': '按一鍵更新檢查 GitHub 最新版本',
                      'downloaded': 0, 'download_bytes': 0, 'total_bytes': 0, 'can_manage': frozen}

    def snapshot(self):
        with self.mutex:
            return dict(self.state)

    def report(self, **fields):
        with self.mutex:
            self.state.update(fields)

    def start(self, action):
        if not self.frozen:
            raise ValueError('請從免安裝版執行檔使用這個功能')
        validate_home(self.home)
        with self.mutex:
            if self.state['status'] in ('checking', 'downloading', 'preparing', 'restarting', 'removing'):
                raise ValueError('正在處理上一個操作，請稍候')
            self.state.update(status='checking' if action == 'update' else 'removing', message='正在檢查最新版本…' if action == 'update' else '正在準備完全移除…', downloaded=0, download_bytes=0, total_bytes=0)
            self.cancelled.clear()
        threading.Thread(target=self.run, args=(action,), daemon=True).start()

    def run(self, action):
        stage = None
        handed_off = False
        try:
            if action == 'uninstall':
                _, unknown = removal_plan(self.home)
                self.on_ready({'action': action, 'unknown': unknown})
                handed_off = True
                return
            client = self.client_factory(self.cancelled.is_set)
            release = client.latest()
            if version(release['tag_name']) <= version(self.current):
                self.report(status='current', message='目前已是最新版本 v' + self.current)
                return
            manifest = client.manifest(release)
            available = local_blocks(self.home)
            missing = missing_blocks(manifest, available)
            download_bytes = sum(missing.values())
            total_bytes = sum(f['size'] for f in manifest['files'])
            self.report(status='downloading', latest_version=manifest['version'], download_bytes=download_bytes, total_bytes=total_bytes,
                        message='只下載缺少的更新區塊，圖片與篩選條件會保留')
            received = 0
            def progress(count):
                nonlocal received
                received += count
                self.report(downloaded=received)
            for key, size in missing.items():
                raw = client.read(client.asset_url(release['tag_name'], 'chunk-' + key + '.bin'), size, progress)
                if len(raw) != size or digest(raw) != key:
                    raise ValueError('下載檔案校驗失敗，未變更任何檔案')
                available[key] = raw
            if self.cancelled.is_set():
                raise InterruptedError('已取消更新')
            self.report(status='preparing', message='下載完成，正在驗證與準備重新啟動…')
            stage = self.home / '資料' / '.更新暫存'
            no_links(self.home / '資料')
            no_links(stage)
            if stage.exists():
                shutil.rmtree(stage)
            reconstruct(manifest, available, stage)
            if self.cancelled.is_set():
                raise InterruptedError('已取消更新')
            self.report(status='restarting', message='正在套用更新，小助手即將重新開啟…')
            self.on_ready({'action': action, 'manifest': manifest, 'stage': str(stage)})
            handed_off = True
        except InterruptedError:
            self.report(status='cancelled', message='已取消更新，原有版本仍可使用')
        except Exception as error:
            self.report(status='error', message='操作未完成：' + str(error))
        finally:
            if stage and stage.exists() and not handed_off:
                shutil.rmtree(stage)


def wait_for_parent(pid, timeout=60):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return
        raise OSError('無法等待原有小助手結束')
    try:
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise RuntimeError('原有小助手尚未結束，未修改檔案')
    finally:
        kernel.CloseHandle(handle)


def handoff(home, payload):
    home = validate_home(home)
    folder = Path(tempfile.mkdtemp(prefix='DeskrawlAssistant-maintenance-'))
    helper = folder / EXE
    shutil.copy2(sys.executable, helper)
    job = {'product': PRODUCT, 'home': str(home), 'pid': os.getpid(), 'testing': '--test-instance' in sys.argv, **payload}
    write_json(folder / 'job.json', job)
    # Helper runs a copied executable outside HOME; running file can then be
    # replaced/deleted. It writes ready only after validating the job and itself.
    process = subprocess.Popen([str(helper), '--maintenance', str(folder / 'job.json')], cwd=folder)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if (folder / 'ready').exists():
            return
        if process.poll() is not None:
            break
        time.sleep(.1)
    raise RuntimeError('維護程序無法啟動，保留原有版本')


CLEANUP_SCRIPT = r'''param([string]$Folder, [int]$HelperId)
$ErrorActionPreference = 'Stop'
$resolved = [IO.Path]::GetFullPath($Folder).TrimEnd('\')
$temporary = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
if ([IO.Path]::GetDirectoryName($resolved) -ne $temporary) { exit 1 }
if ([IO.Path]::GetFileName($resolved) -notmatch '^DeskrawlAssistant-maintenance-[a-z0-9_]+$') { exit 1 }
if (-not (Test-Path -LiteralPath (Join-Path $resolved 'job.json'))) { exit 1 }
Wait-Process -Id $HelperId -ErrorAction SilentlyContinue
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try { Remove-Item -LiteralPath $resolved -Recurse -Force; exit 0 }
    catch { Start-Sleep -Milliseconds 500 }
}
'''


def schedule_cleanup(folder):
    path = folder / 'cleanup.ps1'
    path.write_text(CLEANUP_SCRIPT, encoding='utf-8-sig')
    powershell = Path(os.environ['SystemRoot']) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(path),
                      '-Folder', str(folder), '-HelperId', str(os.getpid())], cwd=Path(tempfile.gettempdir()),
                     creationflags=subprocess.CREATE_NO_WINDOW)


def helper_main(job_path):
    job={};home=None
    folder = Path(sys.executable).resolve().parent
    job_path = Path(job_path).resolve()
    try:
        if folder.parent != Path(tempfile.gettempdir()).resolve() or not folder.name.startswith('DeskrawlAssistant-maintenance-') or job_path != folder / 'job.json':
            raise ValueError('維護程序必須從專用暫存資料夾執行')
        job = json.loads(job_path.read_text(encoding='utf-8'))
        if job.get('product') != PRODUCT or job.get('action') not in ('update', 'uninstall', 'recover', 'icon') or type(job.get('pid')) is not int:
            raise ValueError('維護操作不正確')
        home = validate_home(job['home'])
        if digest(Path(sys.executable).read_bytes()) != digest((home / EXE).read_bytes()):
            raise ValueError('維護程序與原有版本不同')
        if job['action'] == 'update':
            stage = home / '資料' / '.更新暫存'
            if Path(job['stage']).resolve() != stage.resolve():
                raise ValueError('更新暫存位置不正確')
            no_links(home / '資料')
            no_links(stage)
            verify_stage(stage, job['manifest'])
        elif job['action'] == 'uninstall':
            removal_plan(home)
        elif job['action']=='icon':
            if not SHA.fullmatch(str(job.get('icon_sha256'))):raise ValueError('圖示校驗格式不正確')
        (folder / 'ready').write_text('ready', encoding='ascii')
        wait_for_parent(job['pid'])
        # PyInstaller's one-file parent may retain the original EXE briefly.
        time.sleep(1)
        if job['action']=='icon':
            from desktop_icons import apply_exe_icon
            apply_exe_icon(home,folder,job['icon_sha256'])
        elif job['action'] in ('update', 'recover'):
            for attempt in range(20):
                try:
                    if job['action'] == 'recover':recover(home)
                    else:apply_update(home, stage, job['manifest'])
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(.5)
            if job['action'] == 'update' and stage.exists():
                shutil.rmtree(stage)
            subprocess.Popen([str(home / EXE), *(['--test-instance'] if job.get('testing') else [])], cwd=home)
        else:
            for attempt in range(20):
                try:
                    unknown = remove_installation(home)
                    break
                except PermissionError:
                    if attempt == 19:raise
                    time.sleep(.5)
            text = '小助手、圖片收藏、設定及紀錄已移除。'
            if unknown:
                text += '\n資料夾內另有非小助手檔案，因此保留資料夾與這些檔案。'
            if not job.get('testing'):ctypes.windll.user32.MessageBoxW(None, text, '桌面破壞神小助手', 64)
    except Exception as error:
        if job.get('action')=='icon':
            (home/'資料'/'圖示同步錯誤.txt').write_text(str(error),encoding='utf-8')
        else:ctypes.windll.user32.MessageBoxW(None, '操作未完成：' + str(error) + '\n原有檔案已保留或復原；請重新開啟小助手。', '桌面破壞神小助手', 16)
        return 1
    finally:
        if folder.parent == Path(tempfile.gettempdir()).resolve() and folder.name.startswith('DeskrawlAssistant-maintenance-') and (folder / 'job.json').is_file():
            schedule_cleanup(folder)
    return 0
