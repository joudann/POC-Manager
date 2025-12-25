import os
import sqlite3
import customtkinter as ctk
from tkinter import messagebox
from pathlib import Path
import threading
import math
import requests
import zipfile
import io
import webbrowser  # [新增] 用于跳转网页

# 全局样式
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# --- 1. 通用删除/重置选项弹窗 (升级版) ---
class DeleteDialog(ctk.CTkToplevel):
    def __init__(self, parent, count, callback_index, callback_physical, title="删除确认", prefix="已选中"):
        super().__init__(parent)
        self.title(title)
        self.geometry("500x280")
        self.attributes("-topmost", True)
        self.callback_index = callback_index
        self.callback_physical = callback_physical

        self.grid_columnconfigure(0, weight=1)

        # 标题 (支持自定义前缀)
        msg = f"{prefix} {count} 个 POC 文件"
        ctk.CTkLabel(self, text=msg, font=("微软雅黑", 20, "bold")).grid(row=0, column=0, pady=(25, 10))
        ctk.CTkLabel(self, text="请选择操作方式：", font=("微软雅黑", 14), text_color="gray70").grid(row=1, column=0,
                                                                                                    pady=(0, 20))

        # 按钮区
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, pady=10)

        # 按钮1: 仅删索引
        ctk.CTkButton(btn_frame, text="仅移除索引 (保留文件)", width=180, height=45, corner_radius=10,
                      fg_color="#2e86c1", font=("微软雅黑", 13, "bold"),
                      command=self.do_index_delete).pack(side="left", padx=15)

        # 按钮2: 物理删除
        ctk.CTkButton(btn_frame, text="彻底物理删除 (不可恢复)", width=180, height=45, corner_radius=10,
                      fg_color="#c0392b", hover_color="#922b21", font=("微软雅黑", 13, "bold"),
                      command=self.do_physical_delete).pack(side="left", padx=15)

    def do_index_delete(self):
        self.callback_index()
        self.destroy()

    def do_physical_delete(self):
        # 二次确认，防止误触
        if messagebox.askyesno("高危操作", "确定要从硬盘上彻底粉碎这些文件吗？\n此操作绝对无法撤销！", parent=self):
            self.callback_physical()
            self.destroy()


# --- 2. 更新弹窗 ---
class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, parent, default_url, download_func):
        super().__init__(parent)
        self.title("在线更新 POC 库")
        self.geometry("620x380")
        self.attributes("-topmost", True)
        self.download_func = download_func
        self.default_url = default_url

        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="正在准备更新", font=("微软雅黑", 22, "bold")).grid(row=0, column=0, pady=(20, 10))

        info_frame = ctk.CTkFrame(self, fg_color="#2b2b2b")
        info_frame.grid(row=1, column=0, padx=30, pady=5, sticky="ew")
        ctk.CTkLabel(info_frame, text="默认下载源地址：", font=("微软雅黑", 12, "bold"), text_color="#3498db").pack(
            anchor="w", padx=10, pady=(10, 0))

        self.url_text = ctk.CTkTextbox(info_frame, height=50, font=("Consolas", 11), fg_color="transparent",
                                       text_color="gray80")
        self.url_text.pack(fill="x", padx=5, pady=5)
        self.url_text.insert("0.0", self.default_url)
        self.url_text.configure(state="disabled")

        self.btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.btn_frame.grid(row=2, column=0, pady=25)

        ctk.CTkButton(self.btn_frame, text="使用默认地址下载", width=160, height=40, corner_radius=20,
                      command=self.do_default).pack(side="left", padx=15)
        ctk.CTkButton(self.btn_frame, text="输入自选链接", width=160, height=40, corner_radius=20,
                      fg_color="#2e86c1", command=self.do_custom).pack(side="left", padx=15)

        self.status_label = ctk.CTkLabel(self, text="", font=("微软雅黑", 14), text_color="#2ecc71")
        self.prog_bar = ctk.CTkProgressBar(self, width=550, height=15)
        self.prog_bar.set(0)

    def switch_to_progress(self):
        self.btn_frame.grid_forget()
        self.status_label.grid(row=2, column=0, pady=(20, 5))
        self.prog_bar.grid(row=3, column=0, pady=10)
        self.update()

    def do_default(self):
        self.switch_to_progress()
        self.download_func(self.default_url, self)

    def do_custom(self):
        dialog = ctk.CTkInputDialog(text="请粘贴 ZIP 下载链接:", title="自定义源")
        url = dialog.get_input()
        if url and url.strip().lower().endswith(".zip"):
            self.switch_to_progress()
            self.download_func(url.strip(), self)

    def update_view(self, text, val):
        self.status_label.configure(text=text)
        self.prog_bar.set(val)
        self.update()


# --- 3. 阅览窗口 ---
class TextViewer(ctk.CTkToplevel):
    def __init__(self, title, content):
        super().__init__()
        self.title(f"预览 - {title}")
        self.geometry("900x700")
        self.attributes("-topmost", True)
        self.textbox = ctk.CTkTextbox(self, font=("Consolas", 14), corner_radius=0)
        self.textbox.pack(fill="both", expand=True)
        self.textbox.insert("0.0", content)
        self.textbox.configure(state="disabled")


# --- 4. 主程序 ---
class POCApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("POC 管理助手v1.1 - by 冗談")
        self.geometry("1150x900")
        self.poc_dir = "my_pocs"
        self.db_name = "poc_library.db"
        self.default_url = "https://github.com/eeeeeeeeee-code/POC/archive/refs/heads/main.zip"
        # 目标 GitHub 地址
        self.github_url = "https://github.com/joudann/POC-Manager"

        if not os.path.exists(self.poc_dir): os.makedirs(self.poc_dir)
        self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('CREATE TABLE IF NOT EXISTS pocs (name TEXT, path TEXT UNIQUE, parent_dir TEXT)')
        self.conn.commit()

        self.current_page = 1
        self.total_pages = 1
        self.checkboxes = []
        self.current_font_size = 13
        self.font_timer = None
        self.scroll_frame = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # === 左侧边栏 ===
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#1a1a1a")
        self.sidebar.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(self.sidebar, text="POC 管理助手", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(30, 20))

        ctk.CTkButton(self.sidebar, text="🔄 同步本地库", height=40, command=self.start_refresh_thread).pack(padx=20,
                                                                                                            pady=10)
        ctk.CTkButton(self.sidebar, text="🌐 在线更新 POC", height=40, fg_color="#2e86c1",
                      command=lambda: UpdateDialog(self, self.default_url, self.run_download_task)).pack(padx=20,
                                                                                                         pady=10)

        # [新增] 跳转到 GitHub 按钮
        ctk.CTkButton(self.sidebar, text="🚀 下载最新版 (GitHub)", height=40, fg_color="#6c3483", hover_color="#512E5F",
                      command=lambda: webbrowser.open(self.github_url)).pack(padx=20, pady=10)

        ctk.CTkButton(self.sidebar, text="📂 浏览文件夹", height=40, fg_color="transparent", border_width=1,
                      command=self.open_folder).pack(padx=20, pady=10)

        # 修改：重置按钮现在触发高级逻辑
        ctk.CTkButton(self.sidebar, text="⚠️ 重置全库", height=40, fg_color="#922b21",
                      command=self.reset_all_request).pack(padx=20, pady=10)

        self.author_label = ctk.CTkLabel(self.sidebar, text="Designed by 冗談", font=("微软雅黑", 12, "bold"),
                                         text_color="#555555")
        self.author_label.pack(side="bottom", pady=20)

        self.font_slider = ctk.CTkSlider(self.sidebar, from_=10, to=18, command=self.change_font_size)
        self.font_slider.set(self.current_font_size)
        self.font_slider.pack(side="bottom", padx=20, pady=(0, 10))
        ctk.CTkLabel(self.sidebar, text="列表字号调节").pack(side="bottom", pady=(0, 5))

        # === 右侧主内容区 ===
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_rowconfigure(2, weight=1)

        # 1. 顶部搜索栏
        self.top_bar = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        self.search_entry = ctk.CTkEntry(self.top_bar, placeholder_text="搜索资产...", height=35)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.search_entry.bind("<Return>", lambda e: self.reset_and_search())
        self.limit_option = ctk.CTkOptionMenu(self.top_bar, values=["20", "50", "100"], width=80)
        self.limit_option.set("50")
        self.limit_option.pack(side="left", padx=5)
        ctk.CTkButton(self.top_bar, text="查询", width=80, command=self.reset_and_search).pack(side="left", padx=5)

        # 2. 批量操作栏
        self.action_bar = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.action_bar.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.select_all_var = ctk.BooleanVar()
        ctk.CTkCheckBox(self.action_bar, text="全选", variable=self.select_all_var, command=self.toggle_all).pack(
            side="left", padx=5)

        ctk.CTkButton(self.action_bar, text="批量删除", fg_color="#cb4335", width=100,
                      command=self.batch_delete_request).pack(side="right", padx=5)
        ctk.CTkButton(self.action_bar, text="批量外部打开", fg_color="#28b463", width=120,
                      command=self.batch_open).pack(side="right", padx=5)

        # 3. 列表容器
        self.init_scroll_container()

        # 4. 分页栏
        self.page_frame = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.page_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        ctk.CTkButton(self.page_frame, text="<", width=40, command=self.prev_page).pack(side="left")
        self.page_lbl = ctk.CTkLabel(self.page_frame, text="1 / 1")
        self.page_lbl.pack(side="left", expand=True)
        ctk.CTkButton(self.page_frame, text=">", width=40, command=self.next_page).pack(side="right")

        # 5. 底部提示
        ctk.CTkLabel(self.main_area, text="💡 提示：双击列表行内容，可直接预览代码", font=("微软雅黑", 12),
                     text_color="gray60").grid(row=4, column=0, pady=5)

        self.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))

    def init_scroll_container(self):
        """强制重构容器以防重影"""
        if self.scroll_frame is not None:
            for widget in self.scroll_frame.winfo_children():
                widget.destroy()
            self.scroll_frame.destroy()
        self.update_idletasks()
        self.scroll_frame = ctk.CTkScrollableFrame(self.main_area, fg_color="transparent")
        self.scroll_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=(0, 5))

    # --- 下载逻辑 ---
    def run_download_task(self, url, dialog):
        threading.Thread(target=self._download_worker, args=(url, dialog), daemon=True).start()

    def _download_worker(self, url, dialog):
        try:
            self.after(0, lambda: dialog.update_view("正在连接服务器...", 0.1))
            res = requests.get(url, stream=True, timeout=20)
            res.raise_for_status()
            total_size = int(res.headers.get('content-length', 0))
            data_io = io.BytesIO()
            downloaded = 0
            for chunk in res.iter_content(chunk_size=65536):
                if chunk:
                    data_io.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = downloaded / total_size
                        self.after(0, lambda v=percent: dialog.update_view(f"正在下载: {int(v * 100)}%", v))

            self.after(0, lambda: dialog.update_view("正在解压...", 0.95))
            ignore_files = ["README.MD", "LICENSE", "README.ZH.MD", ".GITIGNORE"]
            with zipfile.ZipFile(data_io) as z:
                for member in z.infolist():
                    parts = member.filename.split('/')
                    if len(parts) > 1 and os.path.basename(member.filename):
                        fname = os.path.basename(member.filename).upper()
                        if fname in ignore_files: continue
                        target_path = os.path.join(self.poc_dir, *parts[1:])
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with z.open(member) as s, open(target_path, "wb") as t:
                            t.write(s.read())
            self.after(0, lambda: (dialog.destroy(), messagebox.showinfo("完成", "更新已完成！"),
                                   self.start_refresh_thread()))
        except Exception as e:
            self.after(0, lambda: (dialog.destroy(), messagebox.showerror("失败", str(e))))

    # --- 列表渲染 ---
    def search_poc(self):
        self.init_scroll_container()
        self.checkboxes = []
        key = self.search_entry.get()
        limit = int(self.limit_option.get())
        offset = (self.current_page - 1) * limit
        self.cursor.execute("SELECT COUNT(*) FROM pocs WHERE name LIKE ? OR parent_dir LIKE ?",
                            (f"%{key}%", f"%{key}%"))
        total = self.cursor.fetchone()[0]
        self.total_pages = math.ceil(total / limit) if total > 0 else 1
        self.page_lbl.configure(text=f"{self.current_page} / {self.total_pages} (共 {total} 条)")
        self.cursor.execute("SELECT * FROM pocs WHERE name LIKE ? OR parent_dir LIKE ? LIMIT ? OFFSET ?",
                            (f"%{key}%", f"%{key}%", limit, offset))
        for name, path, parent in self.cursor.fetchall():
            cb = ctk.CTkCheckBox(self.scroll_frame, text=f"[{parent}] {name}  ({path})",
                                 font=("Consolas", self.current_font_size), border_width=2)
            cb.path = path
            cb.pack(fill="x", padx=10, pady=3, anchor="w")
            cb.bind("<Double-Button-1>", lambda e, p=path, n=name: self.show_content(p, n))
            self.checkboxes.append(cb)

    # --- 批量删除逻辑 ---
    def batch_delete_request(self):
        selected = [cb for cb in self.checkboxes if cb.get()]
        if not selected:
            return
        DeleteDialog(self, len(selected),
                     lambda: self._execute_delete(selected, physical=False),
                     lambda: self._execute_delete(selected, physical=True),
                     title="批量删除", prefix="已选中")

    def _execute_delete(self, selected_cbs, physical=False):
        try:
            for cb in selected_cbs:
                if physical and os.path.exists(cb.path):
                    os.remove(cb.path)
                self.cursor.execute("DELETE FROM pocs WHERE path = ?", (cb.path,))
            self.conn.commit()
            messagebox.showinfo("成功", f"已{'物理' if physical else '从索引'}移除 {len(selected_cbs)} 个项目")
            self.search_poc()
        except Exception as e:
            messagebox.showerror("错误", str(e))

    # --- 重置全库逻辑 (新增) ---
    def reset_all_request(self):
        self.cursor.execute("SELECT COUNT(*) FROM pocs")
        count = self.cursor.fetchone()[0]
        if count == 0:
            messagebox.showinfo("提示", "库已经是空的了。")
            return

        # 复用 DeleteDialog
        DeleteDialog(self, count,
                     self._do_reset_index,
                     self._do_reset_physical,
                     title="重置全库", prefix="库中共有")

    def _do_reset_index(self):
        self.cursor.execute("DELETE FROM pocs")
        self.conn.commit()
        self.reset_and_search()
        messagebox.showinfo("成功", "索引已重置 (文件已保留)")

    def _do_reset_physical(self):
        # 先查出所有路径
        self.cursor.execute("SELECT path FROM pocs")
        rows = self.cursor.fetchall()
        for (path,) in rows:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

        self._do_reset_index()  # 删除文件后清空索引并刷新

    # --- 辅助功能 ---
    def change_font_size(self, size):
        self.current_font_size = int(size)
        if self.font_timer: self.after_cancel(self.font_timer)
        self.font_timer = self.after(300, self.search_poc)

    def show_content(self, path, name):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            TextViewer(name, content)
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def start_refresh_thread(self):
        threading.Thread(target=self.refresh_lib, daemon=True).start()

    def refresh_lib(self):
        self.cursor.execute("DELETE FROM pocs")
        exts = ['*.py', '*.yaml', '*.json', '*.txt', '*.md']
        for ext in exts:
            for p in Path(self.poc_dir).rglob(ext):
                self.cursor.execute("INSERT OR IGNORE INTO pocs VALUES (?, ?, ?)",
                                    (p.name, str(p.absolute()), p.parent.name))
        self.conn.commit()
        self.after(0, self.reset_and_search)

    def reset_and_search(self):
        self.current_page = 1;
        self.search_poc()

    def next_page(self):
        if self.current_page < self.total_pages: self.current_page += 1; self.search_poc()

    def prev_page(self):
        if self.current_page > 1: self.current_page -= 1; self.search_poc()

    def toggle_all(self):
        v = self.select_all_var.get()
        for cb in self.checkboxes: cb.select() if v else cb.deselect()

    def batch_open(self):
        for cb in self.checkboxes:
            if cb.get() and os.path.exists(cb.path): os.startfile(cb.path)

    def open_folder(self):
        os.startfile(os.path.abspath(self.poc_dir))


if __name__ == "__main__":
    app = POCApp()
    app.mainloop()
