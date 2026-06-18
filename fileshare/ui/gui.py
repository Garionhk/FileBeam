"""Native desktop admin GUI (CustomTkinter, dark theme).

Replaces the browser-based admin page. Talks directly to the in-process
AppState (DB + TunnelManager) — no HTTP round-trips. The public file server is
still a web server (downloaders use a browser), but the host's control panel is
now this window.

Language is switchable live (English / Traditional Chinese) via i18n.py and
persisted in the user's prefs.
"""
from __future__ import annotations

import shutil
import threading
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from pathlib import Path

import customtkinter as ctk

from ..auth.tokens import hash_passcode
from ..tunnels.registry import backend_choices
from .i18n import LANGUAGES, I18n

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#2563eb"
GOOD = "#10b981"
WARN = "#f59e0b"
BAD = "#ef4444"
CARD = "#1c1f26"


class AdminGUI(ctk.CTk):
    def __init__(self, runtime):
        super().__init__()
        self.runtime = runtime
        self.app_state = runtime.state
        self.db = self.app_state.db
        self.tunnel = self.app_state.tunnel
        self.cfg = self.app_state.config
        self.i18n = I18n(self.cfg.ui_language)

        self._last_url = None
        self._warn_dismissed = False
        self._backend_label_to_name = {b["label"]: b["name"] for b in backend_choices()}
        self._name_to_backend_label = {v: k for k, v in self._backend_label_to_name.items()}

        self.title("FileShare")
        self.geometry("960x720")
        self.minsize(840, 600)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self.after(1000, self._poll)

    # ------------------------------------------------------------------ utils
    def t(self, key: str) -> str:
        return self.i18n.t(key)

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _rebuild(self):
        self._clear()
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_status()
        self._build_tabs()

    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 4))
        bar.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(bar, text="📁  " + self.t("app_title"),
                             font=ctk.CTkFont(size=24, weight="bold"))
        title.grid(row=0, column=0, sticky="w")
        sub = ctk.CTkLabel(bar, text=self.t("subtitle"), text_color="#9aa0aa",
                           font=ctk.CTkFont(size=12))
        sub.grid(row=1, column=0, sticky="w")

        lang_box = ctk.CTkFrame(bar, fg_color="transparent")
        lang_box.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkLabel(lang_box, text="🌐 " + self.t("language") + ":").pack(side="left", padx=(0, 6))
        self.lang_menu = ctk.CTkOptionMenu(
            lang_box, values=list(LANGUAGES.values()),
            command=self._on_language_change, width=130,
        )
        self.lang_menu.set(LANGUAGES.get(self.i18n.lang, "English"))
        self.lang_menu.pack(side="left")

    def _build_status(self):
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14)
        card.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        card.grid_columnconfigure(0, weight=1)

        self.state_label = ctk.CTkLabel(card, text="● " + self.t("state_stopped"),
                                        font=ctk.CTkFont(size=13, weight="bold"))
        self.state_label.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))

        url_row = ctk.CTkFrame(card, fg_color="transparent")
        url_row.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16, pady=4)
        url_row.grid_columnconfigure(0, weight=1)
        self.url_label = ctk.CTkLabel(
            url_row, text="—", font=ctk.CTkFont(size=18, weight="bold"),
            text_color=ACCENT, anchor="w",
        )
        self.url_label.grid(row=0, column=0, sticky="ew")
        self.copy_btn = ctk.CTkButton(url_row, text=self.t("copy_url"), width=110,
                                      command=self._copy_url, state="disabled")
        self.copy_btn.grid(row=0, column=1, padx=(8, 0))

        # URL-change warning (hidden until needed)
        self.warn_frame = ctk.CTkFrame(card, fg_color="#3a2d12", corner_radius=10)
        self.warn_label = ctk.CTkLabel(self.warn_frame, text=self.t("url_changed"),
                                       text_color=WARN, wraplength=720, justify="left")
        self.warn_label.pack(side="left", padx=12, pady=8)
        ctk.CTkButton(self.warn_frame, text=self.t("dismiss"), width=80,
                      fg_color=WARN, hover_color="#b45309",
                      command=self._dismiss_warn).pack(side="right", padx=10, pady=8)

        controls = ctk.CTkFrame(card, fg_color="transparent")
        controls.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(6, 14))
        ctk.CTkLabel(controls, text=self.t("tunnel") + ":").pack(side="left")
        self.backend_menu = ctk.CTkOptionMenu(
            controls, values=list(self._backend_label_to_name.keys()), width=280,
        )
        cur = self.tunnel.backend_name or self.cfg.backend_name
        self.backend_menu.set(self._name_to_backend_label.get(cur, list(self._backend_label_to_name)[0]))
        self.backend_menu.pack(side="left", padx=8)
        self.start_btn = ctk.CTkButton(controls, text=self.t("start_sharing"),
                                       fg_color=GOOD, hover_color="#0e9f6e",
                                       command=self._start)
        self.start_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(controls, text=self.t("stop_sharing"),
                                      fg_color="transparent", border_width=1,
                                      command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self, fg_color=CARD)
        self.tabs.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 18))
        self.tab_folders = self.tabs.add(self.t("tab_folders"))
        self.tab_groups = self.tabs.add(self.t("tab_groups"))
        self.tab_links = self.tabs.add(self.t("tab_links"))
        self._render_folders()
        self._render_groups()
        self._render_links()

    # --------------------------------------------------------------- folders
    def _render_folders(self):
        for w in self.tab_folders.winfo_children():
            w.destroy()
        self.tab_folders.grid_columnconfigure(0, weight=1)
        self.tab_folders.grid_rowconfigure(0, weight=1)

        lst = ctk.CTkScrollableFrame(self.tab_folders, fg_color="transparent")
        lst.grid(row=0, column=0, sticky="nsew", pady=(6, 6))
        lst.grid_columnconfigure(0, weight=1)

        folders = self.db.folders()
        if not folders:
            ctk.CTkLabel(lst, text=self.t("no_folders"), text_color="#9aa0aa").pack(pady=20)
        for f in folders:
            self._folder_row(lst, f)

        # add-folder form
        form = ctk.CTkFrame(self.tab_folders, fg_color="#23272f", corner_radius=10)
        form.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(form, text=self.t("add_folder"),
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 2))

        self.f_name = ctk.CTkEntry(form, placeholder_text=self.t("folder_name"))
        self.f_name.grid(row=1, column=0, sticky="ew", padx=(12, 6), pady=4)

        path_row = ctk.CTkFrame(form, fg_color="transparent")
        path_row.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6, pady=4)
        path_row.grid_columnconfigure(0, weight=1)
        self.f_path = ctk.CTkEntry(path_row, placeholder_text=self.t("folder_path"))
        self.f_path.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(path_row, text=self.t("browse"), width=90,
                      command=self._pick_folder).grid(row=0, column=1, padx=(6, 0))

        self.f_access = ctk.CTkOptionMenu(form, values=[self.t("access_public"), self.t("access_group")])
        self.f_access.grid(row=2, column=0, sticky="ew", padx=(12, 6), pady=4)
        self.f_watch = ctk.CTkCheckBox(form, text=self.t("watch_files"))
        self.f_watch.grid(row=2, column=1, sticky="w", padx=6, pady=4)
        ctk.CTkButton(form, text=self.t("save"), fg_color=ACCENT,
                      command=self._save_folder).grid(row=2, column=2, sticky="e", padx=12, pady=4)

    def _folder_row(self, parent, f):
        row = ctk.CTkFrame(parent, fg_color="#23272f", corner_radius=10)
        row.pack(fill="x", pady=4)
        row.grid_columnconfigure(1, weight=1)

        is_pub = f["access_level"] == "PUBLIC"
        badge = ctk.CTkLabel(row, text=("PUBLIC" if is_pub else "GROUP"), width=70,
                             fg_color=(GOOD if is_pub else WARN), corner_radius=8,
                             text_color="#0b0d10", font=ctk.CTkFont(size=11, weight="bold"))
        badge.grid(row=0, column=0, rowspan=2, padx=12, pady=12)

        ctk.CTkLabel(row, text=f["name"], font=ctk.CTkFont(size=15, weight="bold"),
                     anchor="w").grid(row=0, column=1, sticky="w", pady=(10, 0))
        watch = "  👁" if f["watched"] else ""
        ctk.CTkLabel(row, text=f["abs_path"] + watch, text_color="#9aa0aa",
                     anchor="w").grid(row=1, column=1, sticky="w", pady=(0, 10))

        ctk.CTkButton(row, text=self.t("add_files"), width=110, fg_color=ACCENT,
                      command=lambda fid=f["id"], p=f["abs_path"]: self._add_files(fid, p)
                      ).grid(row=0, column=2, rowspan=2, padx=6)
        ctk.CTkButton(row, text=self.t("delete"), width=80, fg_color="transparent",
                      border_width=1, text_color=BAD, hover_color="#3a1d1d",
                      command=lambda fid=f["id"]: self._delete_folder(fid)
                      ).grid(row=0, column=3, rowspan=2, padx=(0, 12))

    def _pick_folder(self):
        d = fd.askdirectory()
        if d:
            self.f_path.delete(0, "end")
            self.f_path.insert(0, d)
            if not self.f_name.get().strip():
                self.f_name.insert(0, Path(d).name)

    def _save_folder(self):
        name = self.f_name.get().strip()
        path = self.f_path.get().strip()
        if not name or not path:
            mb.showerror(self.t("error_title"), self.t("need_name_path"))
            return
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        access = "PUBLIC" if self.f_access.get() == self.t("access_public") else "GROUP"
        self.db.create_folder(name, str(p.resolve()), access, None, bool(self.f_watch.get()))
        self.app_state.start_watcher()
        self._render_folders()
        self._render_groups()  # permission grid includes folders

    def _delete_folder(self, fid):
        if mb.askyesno(self.t("app_title"), self.t("confirm_delete_folder")):
            self.db.delete_folder(fid)
            self.app_state.start_watcher()
            self._render_folders()
            self._render_groups()

    def _add_files(self, folder_id, abs_path):
        files = fd.askopenfilenames()
        if not files:
            return
        dest_dir = Path(abs_path)
        for src in files:
            try:
                shutil.copy2(src, dest_dir / Path(src).name)
            except Exception as e:  # noqa: BLE001
                mb.showerror(self.t("error_title"), str(e))
        mb.showinfo(self.t("app_title"), f"{self.t('files_added')}: {len(files)}")

    # ---------------------------------------------------------------- groups
    def _render_groups(self):
        for w in self.tab_groups.winfo_children():
            w.destroy()
        self.tab_groups.grid_columnconfigure(0, weight=1)
        self.tab_groups.grid_rowconfigure(1, weight=1)

        # add-group form
        form = ctk.CTkFrame(self.tab_groups, fg_color="#23272f", corner_radius=10)
        form.grid(row=0, column=0, sticky="ew", pady=(6, 8))
        form.grid_columnconfigure(0, weight=1)
        form.grid_columnconfigure(1, weight=1)
        self.g_name = ctk.CTkEntry(form, placeholder_text=self.t("group_name"))
        self.g_name.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=10)
        self.g_pass = ctk.CTkEntry(form, placeholder_text=self.t("passcode"), show="•")
        self.g_pass.grid(row=0, column=1, sticky="ew", padx=6, pady=10)
        ctk.CTkButton(form, text=self.t("add_group"), fg_color=ACCENT,
                      command=self._save_group).grid(row=0, column=2, padx=12, pady=10)

        # permission grid
        grid = ctk.CTkScrollableFrame(self.tab_groups, fg_color="transparent",
                                      label_text=self.t("permissions"))
        grid.grid(row=1, column=0, sticky="nsew")
        groups = self.db.groups()
        folders = self.db.folders()

        header = ctk.CTkFrame(grid, fg_color="transparent")
        header.pack(fill="x", pady=(2, 6))
        ctk.CTkLabel(header, text=self.t("folder_col"), width=160, anchor="w",
                     font=ctk.CTkFont(weight="bold")).pack(side="left", padx=4)
        for g in groups:
            gbox = ctk.CTkFrame(header, fg_color="transparent")
            gbox.pack(side="left", padx=4)
            ctk.CTkLabel(gbox, text=g["name"], font=ctk.CTkFont(weight="bold")).pack(side="left")
            ctk.CTkButton(gbox, text="✕", width=22, height=22, fg_color="transparent",
                          text_color=BAD, hover_color="#3a1d1d",
                          command=lambda gid=g["id"]: self._delete_group(gid)).pack(side="left")

        if not folders:
            ctk.CTkLabel(grid, text=self.t("no_folders"), text_color="#9aa0aa").pack(pady=14)
        perm_vals = [self.t("perm_none"), self.t("perm_download"), self.t("perm_upload")]
        self._perm_map = {self.t("perm_none"): "none", self.t("perm_download"): "download",
                          self.t("perm_upload"): "upload"}
        rev_perm = {v: k for k, v in self._perm_map.items()}
        for f in folders:
            r = ctk.CTkFrame(grid, fg_color="#23272f", corner_radius=8)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=f["name"], width=160, anchor="w").pack(side="left", padx=4, pady=6)
            for g in groups:
                cur = self.db.grant(f["id"], g["id"])
                cur_perm = cur["permission"] if cur else "none"
                om = ctk.CTkOptionMenu(
                    r, values=perm_vals, width=120,
                    command=lambda val, fid=f["id"], gid=g["id"]: self._set_grant(fid, gid, val),
                )
                om.set(rev_perm[cur_perm])
                om.pack(side="left", padx=4, pady=4)

    def _save_group(self):
        name = self.g_name.get().strip()
        if not name:
            return
        pw = self.g_pass.get()
        try:
            self.db.create_group(name, hash_passcode(pw) if pw else None)
        except Exception as e:  # noqa: BLE001
            mb.showerror(self.t("error_title"), str(e))
            return
        self._render_groups()

    def _delete_group(self, gid):
        if mb.askyesno(self.t("app_title"), self.t("confirm_delete_group")):
            self.db.delete_group(gid)
            self._render_groups()

    def _set_grant(self, folder_id, group_id, label):
        self.db.set_grant(folder_id, group_id, self._perm_map[label])

    # ----------------------------------------------------------------- links
    def _render_links(self):
        for w in self.tab_links.winfo_children():
            w.destroy()
        self.tab_links.grid_columnconfigure(0, weight=1)
        self.tab_links.grid_rowconfigure(1, weight=1)

        # create-link form
        form = ctk.CTkFrame(self.tab_links, fg_color="#23272f", corner_radius=10)
        form.grid(row=0, column=0, sticky="ew", pady=(6, 8))
        for i in range(4):
            form.grid_columnconfigure(i, weight=1)
        folders = self.db.folders()
        groups = self.db.groups()
        self._link_folder_opts = {self.t("all_folders"): None}
        for f in folders:
            self._link_folder_opts[f["name"]] = f["id"]
        self._link_group_opts = {self.t("no_group_opt"): None}
        for g in groups:
            self._link_group_opts[g["name"]] = g["id"]

        self.l_folder = ctk.CTkOptionMenu(form, values=list(self._link_folder_opts.keys()))
        self.l_folder.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=10)
        self.l_group = ctk.CTkOptionMenu(form, values=list(self._link_group_opts.keys()))
        self.l_group.grid(row=0, column=1, sticky="ew", padx=6, pady=10)
        self.l_exp = ctk.CTkEntry(form, placeholder_text=self.t("expires_hours"))
        self.l_exp.grid(row=0, column=2, sticky="ew", padx=6, pady=10)
        self.l_cap = ctk.CTkEntry(form, placeholder_text=self.t("max_downloads"))
        self.l_cap.grid(row=0, column=3, sticky="ew", padx=6, pady=10)
        ctk.CTkButton(form, text=self.t("create_link"), fg_color=ACCENT,
                      command=self._save_link).grid(row=0, column=4, padx=12, pady=10)

        lst = ctk.CTkScrollableFrame(self.tab_links, fg_color="transparent")
        lst.grid(row=1, column=0, sticky="nsew")
        links = self.db.links()
        if not links:
            ctk.CTkLabel(lst, text=self.t("no_links"), text_color="#9aa0aa").pack(pady=14)
        import time as _t
        for l in links:
            self._link_row(lst, l, _t.time())

    def _link_row(self, parent, l, now):
        row = ctk.CTkFrame(parent, fg_color="#23272f", corner_radius=8)
        row.pack(fill="x", pady=3)
        row.grid_columnconfigure(0, weight=1)
        revoked = bool(l["revoked"])
        scope = ("#%s" % l["folder_id"]) if l["folder_id"] else self.t("all_folders")
        exp = ("%.0fh" % ((l["expires_at"] - now) / 3600)) if l["expires_at"] else "∞"
        cap = str(l["max_downloads"]) if l["max_downloads"] else "∞"
        info = f"…{l['token'][-8:]}   ·   {scope}   ·   {self.t('expires')}: {exp}   ·   {self.t('cap')}: {cap}   ·   {self.t('used')}: {l['download_count']}"
        ctk.CTkLabel(row, text=info, anchor="w",
                     text_color="#9aa0aa" if revoked else "#e6e8ec").grid(row=0, column=0, sticky="w", padx=12, pady=8)
        if revoked:
            ctk.CTkLabel(row, text=self.t("revoked"), text_color=BAD).grid(row=0, column=1, padx=12)
        else:
            ctk.CTkButton(row, text=self.t("copy_link"), width=100, fg_color=ACCENT,
                          command=lambda tok=l["token"]: self._copy_link(tok)).grid(row=0, column=1, padx=4)
            ctk.CTkButton(row, text=self.t("revoke"), width=80, fg_color="transparent",
                          border_width=1, text_color=BAD,
                          command=lambda lid=l["id"]: self._revoke_link(lid)).grid(row=0, column=2, padx=(0, 12))

    def _save_link(self):
        fid = self._link_folder_opts.get(self.l_folder.get())
        gid = self._link_group_opts.get(self.l_group.get())
        import time as _t
        exp = _t.time() + float(self.l_exp.get()) * 3600 if self.l_exp.get().strip() else None
        cap = int(self.l_cap.get()) if self.l_cap.get().strip() else None
        self.db.create_link(fid, gid, exp, cap)
        self._render_links()

    def _revoke_link(self, lid):
        self.db.revoke_link(lid)
        self._render_links()

    def _copy_link(self, token):
        url = self.tunnel.public_url
        if not url:
            mb.showinfo(self.t("app_title"), self.t("link_needs_url"))
            return
        self._to_clipboard(url.rstrip("/") + "/l/" + token)

    # ------------------------------------------------------------- tunnel ops
    def _start(self):
        self.start_btn.configure(state="disabled")
        self.state_label.configure(text="● " + self.t("starting"), text_color=WARN)
        backend = self._backend_label_to_name[self.backend_menu.get()]
        threading.Thread(target=self._start_worker, args=(backend,), daemon=True).start()

    def _start_worker(self, backend):
        try:
            self.tunnel.start(backend)
        except Exception:
            pass  # poll() will surface the error from tunnel.status()

    def _stop(self):
        self.tunnel.stop()
        self._last_url = None
        self._warn_dismissed = False

    def _copy_url(self):
        if self.tunnel.public_url:
            self._to_clipboard(self.tunnel.public_url)
            self.copy_btn.configure(text=self.t("copied"))
            self.after(1200, lambda: self.copy_btn.configure(text=self.t("copy_url")))

    def _to_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    # ------------------------------------------------------------- live poll
    def _poll(self):
        st = self.tunnel.status()
        url = self.tunnel.public_url
        state = st.state.value

        if url:
            self.url_label.configure(text=url)
            self.copy_btn.configure(state="normal")
            self.state_label.configure(text="● " + self.t("state_running"), text_color=GOOD)
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            if self._last_url and url != self._last_url and not self._warn_dismissed:
                self._show_warn()
            self._last_url = url
        else:
            self.copy_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")
            self.start_btn.configure(state="normal")
            if state == "ERROR":
                self.url_label.configure(text=self.t("state_error") + ": " + (st.error or ""))
                self.state_label.configure(text="● " + self.t("state_error"), text_color=BAD)
            elif state in ("STARTING", "RECONNECTING"):
                self.state_label.configure(text="● " + self.t("starting"), text_color=WARN)
            else:
                self.url_label.configure(text="—")
                self.state_label.configure(text="● " + self.t("state_stopped"), text_color="#9aa0aa")

        # server-detected change (e.g. reconnect)
        if self.tunnel.previous_url and not self._warn_dismissed:
            self._show_warn()

        self.after(1000, self._poll)

    def _show_warn(self):
        self.warn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8))

    def _dismiss_warn(self):
        self._warn_dismissed = True
        self.tunnel.ack_url_change()
        self.warn_frame.grid_forget()

    # --------------------------------------------------------------- language
    def _on_language_change(self, display_name):
        code = self.i18n.code_for_name(display_name)
        self.i18n.set_language(code)
        self.cfg.set_ui_language(code)
        self._rebuild()

    # -------------------------------------------------------------- shutdown
    def _on_close(self):
        try:
            self.runtime.stop()
        finally:
            self.destroy()


def run_gui(runtime) -> None:
    app = AdminGUI(runtime)
    app.mainloop()
