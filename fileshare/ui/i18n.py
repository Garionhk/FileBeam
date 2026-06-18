"""Tiny i18n layer for the desktop GUI.

Strings live in TRANSLATIONS keyed by language code. ``t(key)`` returns the
string for the active language, falling back to English. The chosen language is
persisted in the settings file so it survives restarts.

To add a language: add a new code -> {key: text} block to TRANSLATIONS and add
its display name to LANGUAGES.
"""
from __future__ import annotations

LANGUAGES = {
    "en": "English",
    "zh-Hant": "繁體中文",
}

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "FileShare",
        "subtitle": "Share files publicly — no account, no setup",
        "language": "Language",
        # status / tunnel
        "public_url": "Public URL",
        "not_sharing": "Not sharing",
        "starting": "Starting…",
        "tunnel": "Tunnel",
        "start_sharing": "▶  Start sharing",
        "stop_sharing": "■  Stop",
        "copy_url": "Copy URL",
        "copied": "✓ Copied",
        "state_running": "Sharing is live",
        "state_stopped": "Stopped",
        "state_error": "Error",
        "url_changed": "⚠  The public URL changed — previously shared links no longer work. Share the new one.",
        "dismiss": "Got it",
        # tabs
        "tab_folders": "Folders",
        "tab_groups": "Groups & Access",
        "tab_links": "Share Links",
        # folders
        "add_folder": "Add folder",
        "folder_name": "Display name",
        "folder_path": "Folder on this computer",
        "browse": "Browse…",
        "access_level": "Access",
        "access_public": "PUBLIC — anyone with the link",
        "access_group": "GROUP — passcode / link required",
        "watch_files": "Watch for new files",
        "add_files": "＋ Add files",
        "delete": "Delete",
        "no_folders": "No shared folders yet. Add one below.",
        "quota_mb": "Quota MB (optional)",
        "save": "Save",
        "cancel": "Cancel",
        # groups
        "add_group": "Add group",
        "group_name": "Group name",
        "passcode": "Passcode (optional)",
        "permissions": "Permissions",
        "perm_none": "none",
        "perm_download": "download",
        "perm_upload": "upload",
        "no_groups": "No groups yet.",
        "folder_col": "Folder",
        # links
        "create_link": "Create link",
        "all_folders": "All visible folders",
        "no_group_opt": "No group",
        "expires_hours": "Expires in hours (optional)",
        "max_downloads": "Max downloads (optional)",
        "copy_link": "Copy link",
        "revoke": "Revoke",
        "revoked": "revoked",
        "scope": "Scope",
        "group": "Group",
        "expires": "Expires",
        "cap": "Cap",
        "used": "Used",
        "no_links": "No share links yet.",
        "link_needs_url": "Start sharing first to get a public URL for links.",
        # dialogs / messages
        "confirm_delete_folder": "Remove this folder from sharing? Files on disk are kept.",
        "confirm_delete_group": "Delete this group?",
        "error_title": "Error",
        "need_name_path": "Please enter a name and pick a folder.",
        "tunnel_failed": "Tunnel failed to start",
        "files_added": "Files added",
    },
    "zh-Hant": {
        "app_title": "FileShare 檔案分享",
        "subtitle": "公開分享檔案 — 免註冊、免設定",
        "language": "語言",
        "public_url": "公開網址",
        "not_sharing": "尚未分享",
        "starting": "啟動中…",
        "tunnel": "通道",
        "start_sharing": "▶  開始分享",
        "stop_sharing": "■  停止",
        "copy_url": "複製網址",
        "copied": "✓ 已複製",
        "state_running": "分享進行中",
        "state_stopped": "已停止",
        "state_error": "錯誤",
        "url_changed": "⚠  公開網址已變更 — 先前分享的連結已失效，請改用新網址。",
        "dismiss": "知道了",
        "tab_folders": "資料夾",
        "tab_groups": "群組與權限",
        "tab_links": "分享連結",
        "add_folder": "新增資料夾",
        "folder_name": "顯示名稱",
        "folder_path": "本機資料夾路徑",
        "browse": "瀏覽…",
        "access_level": "存取權",
        "access_public": "公開 — 任何取得連結者皆可下載",
        "access_group": "群組 — 需通行碼或連結",
        "watch_files": "自動監看新檔案",
        "add_files": "＋ 加入檔案",
        "delete": "刪除",
        "no_folders": "尚未有共享資料夾，請於下方新增。",
        "quota_mb": "容量上限 MB（選填）",
        "save": "儲存",
        "cancel": "取消",
        "add_group": "新增群組",
        "group_name": "群組名稱",
        "passcode": "通行碼（選填）",
        "permissions": "權限",
        "perm_none": "無",
        "perm_download": "下載",
        "perm_upload": "上傳",
        "no_groups": "尚未有群組。",
        "folder_col": "資料夾",
        "create_link": "建立連結",
        "all_folders": "所有可見資料夾",
        "no_group_opt": "不指定群組",
        "expires_hours": "幾小時後到期（選填）",
        "max_downloads": "下載次數上限（選填）",
        "copy_link": "複製連結",
        "revoke": "撤銷",
        "revoked": "已撤銷",
        "scope": "範圍",
        "group": "群組",
        "expires": "到期",
        "cap": "上限",
        "used": "已使用",
        "no_links": "尚未有分享連結。",
        "link_needs_url": "請先開始分享以取得公開網址，連結才能使用。",
        "confirm_delete_folder": "要將此資料夾移出分享嗎？磁碟上的檔案會保留。",
        "confirm_delete_group": "確定刪除此群組？",
        "error_title": "錯誤",
        "need_name_path": "請輸入名稱並選擇資料夾。",
        "tunnel_failed": "通道啟動失敗",
        "files_added": "檔案已加入",
    },
}


class I18n:
    def __init__(self, lang: str = "en"):
        self.lang = lang if lang in TRANSLATIONS else "en"

    def set_language(self, lang: str) -> None:
        if lang in TRANSLATIONS:
            self.lang = lang

    def code_for_name(self, name: str) -> str:
        for code, disp in LANGUAGES.items():
            if disp == name:
                return code
        return "en"

    def t(self, key: str) -> str:
        return TRANSLATIONS.get(self.lang, {}).get(key) or TRANSLATIONS["en"].get(key, key)
