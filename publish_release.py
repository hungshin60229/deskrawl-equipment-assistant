"""Prepare clean portable/source packages and content-addressed update assets.

python publish_release.py --exe release_v1_4/桌面破壞神小助手.exe --output ../github_publish_v1_4
Upload every file in output/release_assets to the SAME GitHub release. Publish
only when all files have uploaded. The updater refuses incomplete releases.
"""
import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
import maintenance as m


def prepare(executable, output):
    source = Path(__file__).resolve().parent
    output = Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    assets = output/'release_assets';assets.mkdir(exist_ok=True)
    repo = output/'repository';repo.mkdir(exist_ok=True)
    allow = ['app.py','reader.py','model.py','maintenance.py','desktop_icons.py','loadouts.py','test_loadouts.py','test_icons.py','publish_release.py',
             'test_core.py','test_avatar.py','test_maintenance.py','test_loadout_api.py','test_build_math.cjs','requirements.txt','使用說明.txt','桌面破壞神小助手.spec']
    for name in allow:shutil.copy2(source/name,repo/name)
    prior_docs = source
    for name in ['README.md','THIRD_PARTY_NOTICES.md','.gitignore']:
        shutil.copy2(prior_docs/name,repo/name)
    readme=(repo/'README.md').read_text(encoding='utf-8').replace('{VERSION}',m.VERSION)
    readme+='''
## 一鍵更新與完全移除（v1.2.0 起）

右上角「小助手設定」提供以下功能：

- **一鍵更新**：檢查本專案 GitHub 最新正式版，重用本機已存在的內容區塊，只下載缺少區塊；校驗完整檔案後自動重新啟動。圖片、篩選條件及裝備紀錄會保留。
- 顯示實際下載量及重用比例。網路中斷、校驗失敗或無法替換時，保留或復原原有程式；下載時可取消。程式不會下載整個 portable ZIP 作為回退。
- **一鍵刪除**：確認後關閉並移除本資料夾內的小助手執行檔、說明、資料（包含圖片、設定、紀錄及瀏覽器快取），以及本工具的原始碼／版本備份。資料夾為空時一起移除；非小助手檔案保留。不搜尋或刪除其他位置的下載包／手動複本，也不移除共用 WebView2 與 .NET。
- 如果放在遊戲資料夾或包含連結／junction，會拒絕移除，請先移至獨立資料夾。

**v1.1.0 沒有更新按鈕，需手動下載 v1.2.0 一次。** 從 v1.2.0 起可使用增量更新。節省比例取決於兩個版本的差異；Python 或相依元件大幅更換時，下載量也可能接近完整程式。

發布包包含使用者指定的預設人像圖示，不包含私人圖片收藏、遊戲資訊或權杖。更新只向 GitHub 下載版本資訊及區塊，不上傳本機資料。更新信任本 GitHub 專案的發布者，並依 GitHub 回傳的 SHA-256 與版本清單驗證；校驗不代表第三方程式碼簽章。

### 發布新的增量版本

1. 修改 `maintenance.py` 的 `VERSION`，建置單檔執行檔。
2. 執行 `python publish_release.py --exe dist/桌面破壞神小助手.exe --output release_publish`。
3. 建立對應 GitHub 標籤（例如 v1.2.0），上傳 `release_assets` 中的所有檔案，包含 `update-manifest.json` 與所有 `chunk-*.bin`，全部完成才按發布。
4. 一般使用者下載 portable.zip。`chunk-*.bin` 是自動更新用，無須手動下載。每個新版均附完整區塊組，所以可跨版本更新，不需逐版升級。

目前只更新小助手程式及說明。遊戲的讀取仍為唯讀，不會修改遊戲檔案。
'''
    (repo/'README.md').write_text(readme,encoding='utf-8')
    with zipfile.ZipFile(repo/'assets.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((source/'assets').rglob('*')):
            if not path.is_file():continue
            name=path.relative_to(source).as_posix()
            if path.name=='reader_config.json':
                config=json.loads(path.read_text(encoding='utf-8'));config.pop('game_path',None)
                archive.writestr(name,json.dumps(config,ensure_ascii=False,indent=2))
            else:archive.write(path,name)
    files={m.EXE:Path(executable).read_bytes(),'使用說明.txt':(source/'使用說明.txt').read_bytes()}
    manifest={'schema':1,'product':m.PRODUCT,'version':m.VERSION,'chunking':'gear-v1','files':[]}
    for name,raw in files.items():
        parts=[]
        for key,block in m.chunks(raw):
            (assets/('chunk-'+key+'.bin')).write_bytes(block)
            parts.append({'sha256':key,'size':len(block)})
        manifest['files'].append({'path':name,'sha256':m.digest(raw),'size':len(raw),'chunks':parts})
    m.validate_manifest(manifest,'v'+m.VERSION)
    (assets/'update-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    portable=assets/f'DeskrawlAssistant-v{m.VERSION}-win-x64-portable.zip'
    with zipfile.ZipFile(portable,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in files.items():archive.writestr('桌面破壞神小助手/'+name,raw)
    source_zip=assets/f'DeskrawlAssistant-v{m.VERSION}-source.zip'
    with zipfile.ZipFile(source_zip,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(repo.iterdir()):
            if path.name!='assets.zip':archive.write(path,path.name)
        with zipfile.ZipFile(repo/'assets.zip') as nested:
            for name in nested.namelist():archive.writestr(name,nested.read(name))
    (assets/'SHA256SUMS.txt').write_text(''.join(m.digest(p.read_bytes())+'  '+p.name+'\n' for p in [portable,source_zip,assets/'update-manifest.json']),encoding='utf-8')
    for path in [portable,source_zip]:
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert not any(name.startswith('資料/') or '/資料/' in name for name in archive.namelist())
    # A release must not accidentally pick up obsolete chunks after a rebuild.
    active={'chunk-'+p['sha256']+'.bin' for f in manifest['files'] for p in f['chunks']}
    for path in assets.glob('chunk-*.bin'):
        if path.name not in active:path.unlink()
    print(json.dumps({'version':m.VERSION,'assets':len(list(assets.iterdir())),'chunks':len(active),'portable_bytes':portable.stat().st_size,'output':str(output)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();prepare(args.exe,args.output)
