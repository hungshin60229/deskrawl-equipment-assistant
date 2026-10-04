# 桌面破壞神小助手

Deskrawl 傳奇裝備篩選器，Windows x64 免安裝桌面工具。

## 下載與使用

請到 [Releases](https://github.com/hungshin60229/deskrawl-equipment-assistant/releases/latest) 下載 `DeskrawlAssistant-v1.1.0-win-x64-portable.zip`，解壓縮後開啟「桌面破壞神小助手.exe」。一般使用者不需要安裝 Python。

1. 將整個資料夾放在可寫入的位置，不要直接在 ZIP 內執行。
2. 開啟 Deskrawl 並進入角色，小助手會自動連接本機遊戲。
3. 選擇部位、主要／次要詞條，按「篩選裝備」。所選條件需全部符合，結果按物品等級由高到低排列。
4. 裝備位置顯示穿戴欄、背包排與格，或倉庫頁、排與格。
5. 點頭像或「更換圖片」可上傳、收藏、切換及刪除圖片；預設貓咪固定保留。
6. 按右上角 × 結束小助手。重複啟動會帶回既有視窗。

## 環境與相容性

- Windows x64，需要 Microsoft Edge WebView2 Runtime 與 .NET Framework；若系統缺少 WebView2，請從 [Microsoft 官方頁面](https://developer.microsoft.com/microsoft-edge/webview2/) 安裝 Evergreen Runtime。
- 以 2026-10-05 本機 Deskrawl 遊戲檔案驗證。遊戲更新後，檔案雜湊不同時會停止讀取並提示更新，無法保證其他遊戲版本相容。
- 不要求固定的遊戲安裝路徑：從執行中的 Deskrawl.exe 與 GameAssembly.dll 自動取得位置。
- 目前讀取選定角色的穿戴裝備、背包及已載入倉庫；未涵蓋所有未載入角色或離線存檔。
- 已在開發者 Windows 電腦驗證，尚未在另一台沒有 Python 的電腦上驗證；首次公開提供朋友測試。

## 唯讀方式與本機資料

程式僅透過 `PROCESS_VM_READ`、`PROCESS_QUERY_LIMITED_INFORMATION` 與 `ReadProcessMemory` 讀取本機遊戲程序，不呼叫寫入程序記憶體、注入或修改存檔功能。無須提供遊戲帳密。

介面服務只綁定 `127.0.0.1`，使用每次啟動的新權杖。裝備快照、篩選條件、圖片收藏及紀錄保存在執行檔旁的「資料」資料夾，不會自動上傳到 GitHub 或其他伺服器。發布包不包含開發者的角色資料、照片、圖片收藏、連線權杖或紀錄。

## 原始碼與建置

本倉庫提供可閱讀的 Python 原始碼；`assets.zip` 包含 `assets/` 介面、讀取設定及圖片。請先將它解壓縮到倉庫根目錄，再以 Windows x64 Python 3.12 建置：

```powershell
python -m pip install -r requirements.txt
python -m unittest test_core test_avatar -v
python app.py
python -m pip install PyInstaller==6.20.0
python -m PyInstaller --noconfirm --onefile --windowed --name 桌面破壞神小助手 --add-data "assets;assets" --collect-all webview --hidden-import pythonnet --hidden-import clr app.py
```

Release 另提供完整原始碼 ZIP。請勿將「資料」資料夾加入 Git 或分享給他人。

## 資料來源

裝備名稱與詞條分類參考 [X1X 桌面破壞神物品圖鑑](https://x1x.tw/deskrawl/items/)。遊戲圖示來自 Deskrawl，相關遊戲名稱、圖像及資料權利屬原權利人。本工具非官方作品。本倉庫未指定涵蓋第三方素材的再授權。

預設頭像依使用者提供的貓咪圖像以 imagegen 整理；介面標語「自私的人永遠得不到滿足，或許我也是」由使用者提供，署名許至均。
