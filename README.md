# 桌面破壞神小助手

Deskrawl 傳奇裝備篩選器，Windows x64 免安裝桌面工具。

## 下載與使用

請到 [Releases](https://github.com/hungshin60229/deskrawl-equipment-assistant/releases/latest) 下載 `DeskrawlAssistant-v1.2.0-win-x64-portable.zip`，解壓縮後開啟「桌面破壞神小助手.exe」。一般使用者不需要安裝 Python。

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
python -m unittest test_core test_avatar test_maintenance -v
python app.py
python -m pip install PyInstaller==6.20.0
python -m PyInstaller --noconfirm --onefile --windowed --name 桌面破壞神小助手 --add-data "assets;assets" --collect-all webview --hidden-import pythonnet --hidden-import clr app.py
```

Release 另提供完整原始碼 ZIP。請勿將「資料」資料夾加入 Git 或分享給他人。

## 資料來源

裝備名稱與詞條分類參考 [X1X 桌面破壞神物品圖鑑](https://x1x.tw/deskrawl/items/)。遊戲圖示來自 Deskrawl，相關遊戲名稱、圖像及資料權利屬原權利人。本工具非官方作品。本倉庫未指定涵蓋第三方素材的再授權。

預設頭像依使用者提供的貓咪圖像以 imagegen 整理；介面標語「自私的人永遠得不到滿足，或許我也是」由使用者提供，署名許至均。

## 一鍵更新與完全移除（v1.2.0 起）

右上角「小助手設定」提供以下功能：

- **一鍵更新**：檢查本專案 GitHub 最新正式版，重用本機已存在的內容區塊，只下載缺少區塊；校驗完整檔案後自動重新啟動。圖片、篩選條件及裝備紀錄會保留。
- 顯示實際下載量及重用比例。網路中斷、校驗失敗或無法替換時，保留或復原原有程式；下載時可取消。程式不會下載整個 portable ZIP 作為回退。
- **一鍵刪除**：確認後關閉並移除本資料夾內的小助手執行檔、說明、資料（包含圖片、設定、紀錄及瀏覽器快取），以及本工具的原始碼／版本備份。資料夾為空時一起移除；非小助手檔案保留。不搜尋或刪除其他位置的下載包／手動複本，也不移除共用 WebView2 與 .NET。
- 如果放在遊戲資料夾或包含連結／junction，會拒絕移除，請先移至獨立資料夾。

**v1.1.0 沒有更新按鈕，需手動下載 v1.2.0 一次。** 從 v1.2.0 起可使用增量更新。節省比例取決於兩個版本的差異；Python 或相依元件大幅更換時，下載量也可能接近完整程式。

發布包內沒有個人照片、遊戲資訊或權杖。更新只向 GitHub 下載版本資訊及區塊，不上傳本機資料。更新信任本 GitHub 專案的發布者，並依 GitHub 回傳的 SHA-256 與版本清單驗證；校驗不代表第三方程式碼簽章。

### 發布新的增量版本

1. 修改 `maintenance.py` 的 `VERSION`，建置單檔執行檔。
2. 執行 `python publish_release.py --exe dist/桌面破壞神小助手.exe --output release_publish`。
3. 建立對應 GitHub 標籤（例如 v1.2.0），上傳 `release_assets` 中的所有檔案，包含 `update-manifest.json` 與所有 `chunk-*.bin`，全部完成才按發布。
4. 一般使用者下載 portable.zip。`chunk-*.bin` 是自動更新用，無須手動下載。每個新版均附完整區塊組，所以可跨版本更新，不需逐版升級。

目前只更新小助手程式及說明。遊戲的讀取仍為唯讀，不會修改遊戲檔案。
