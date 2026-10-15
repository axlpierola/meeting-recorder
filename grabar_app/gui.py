"""Interfaz gráfica moderna (ttkbootstrap sobre tkinter)."""
from __future__ import annotations

import os
import queue
import re
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import ttkbootstrap as ttk
from ttkbootstrap.tooltip import ToolTip

from . import core, library, resumen, settings

THEMES = {"light": "flatly", "dark": "darkly"}
SUMMARY_LANGS = ["Español", "English", "Português", "Français", "Deutsch", "Italiano"]
TRANSCRIBE_LANGS = ["es", "en", "pt", "fr", "de", "it"]
CHIP_NAMES = {"python": "Python", "ffmpeg": "ffmpeg", "pyaudio": "Captura", "loopback": "Audio del sistema",
              "mic": "Micrófono", "platform": "Sistema", "whisperx": "WhisperX", "gpu": "GPU", "hf": "Token HF"}
FONT = "Segoe UI"


class App(ttk.Window):
    def __init__(self) -> None:
        self.cfg = settings.load()
        self.dark = self.cfg.get("theme", "light") == "dark"
        super().__init__(themename=THEMES["dark" if self.dark else "light"])
        self.title("Grabador + Transcriptor de reuniones")
        self.geometry("1040x860")
        self.minsize(980, 740)
        self.q: queue.Queue = queue.Queue()
        self.rec: core.Recorder | None = None
        self.transcription: core.Transcription | None = None
        self.devs: dict | None = None
        self.files: list[Path] = []
        self._sent_ok: set[str] = set()
        self.busy = False
        self._act = {"running": False, "t0": 0.0, "text": "", "bar": ""}
        self._loading = True
        self._build()
        self._loading = False
        self._apply_theme_colors()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(100, self._pump)
        self.after(300, self.refresh_env)
        threading.Thread(target=lambda: core.migrate_legacy(self.log), daemon=True).start()
        self.after(600, self.refresh_files)

    # ------------------------------------------------------- preferencias
    def _var(self, kind, key: str, default):
        """Variable de tk enlazada a config.json (se guarda al cambiar)."""
        v = kind(value=self.cfg.get(key, default))
        v.trace_add("write", lambda *_: self._save_cfg())
        return v

    def _save_cfg(self) -> None:
        if self._loading:
            return
        c = self.cfg
        c.update({
            "theme": "dark" if self.dark else "light",
            "loop_dev": self.loop_var.get(), "mic_dev": self.mic_var.get(),
            "model": self.model_var.get(), "lang": self.lang_var.get(), "device": self.dev_var.get(),
            "diarize": bool(self.diar_var.get()), "provider": self.prov_var.get(),
            "sum_lang": self.sum_lang_var.get(),
        })
        c.setdefault("sum_models", {})[self._prov()["id"]] = self.sum_model_var.get()
        try:
            c["tab"] = self.nb.index(self.nb.select())
        except tk.TclError:
            pass
        settings.save(c)

    # ---------------------------------------------------------------- UI
    def _build(self) -> None:
        root = ttk.Frame(self, padding=(16, 12, 16, 12))
        root.pack(fill="both", expand=True)

        # Cabecera
        head = ttk.Frame(root)
        head.pack(fill="x")
        ttk.Label(head, text="Grabador + Transcriptor", font=(FONT, 18, "bold")).pack(side="left")
        ttk.Label(head, text="  reuniones · WhisperX · resumen con IA", bootstyle="secondary").pack(side="left", pady=(6, 0))
        self.theme_var = tk.BooleanVar(value=self.dark)
        ttk.Checkbutton(head, text="Modo oscuro", variable=self.theme_var, bootstyle="round-toggle",
                        command=self.toggle_theme).pack(side="right")

        # Entorno (chips)
        env = ttk.Labelframe(root, text=" Entorno ", padding=(10, 6))
        env.pack(fill="x", pady=(10, 6))
        self.chips = ttk.Frame(env)
        self.chips.pack(fill="x")
        brow = ttk.Frame(env)
        brow.pack(fill="x", pady=(8, 0))
        ttk.Button(brow, text="↻ Verificar", bootstyle="primary-outline", command=self.refresh_env).pack(side="left")
        self.btn_audio = ttk.Button(brow, text="Instalar audio/ffmpeg", bootstyle="primary-outline",
                                    command=lambda: self._install("audio"))
        self.btn_audio.pack(side="left", padx=6)
        self.btn_wx = ttk.Button(brow, text="Instalar WhisperX", bootstyle="primary-outline",
                                 command=lambda: self._install("whisperx"))
        self.btn_wx.pack(side="left")
        ttk.Button(brow, text="Detalles", bootstyle="link", command=self.show_env_details).pack(side="left", padx=6)
        ttk.Button(brow, text="Carpeta de logs", bootstyle="link",
                   command=lambda: core.open_folder(core.LOG_DIR)).pack(side="right")
        self._checks: list[core.Check] = []

        # Actividad (siempre al final de la ventana)
        act = ttk.Labelframe(root, text=" Actividad ", padding=(10, 6))
        act.pack(side="bottom", fill="both", pady=(6, 0))
        top = ttk.Frame(act)
        top.pack(fill="x")
        self.act_label = ttk.Label(top, text="Listo.", anchor="w")
        self.act_label.pack(side="left", fill="x", expand=True)
        self.btn_toggle_log = ttk.Button(top, text="Ocultar registro", bootstyle="link", command=self.toggle_log)
        self.btn_toggle_log.pack(side="right")
        self.act_bar = ttk.Progressbar(act, mode="determinate", maximum=100, value=0, bootstyle="success")
        self.act_bar.pack(fill="x", pady=(4, 6))
        self.log_wrap = ttk.Frame(act)
        self.log_wrap.pack(fill="both", expand=True)
        self.log_box = tk.Text(self.log_wrap, height=7, wrap="word", state="disabled", relief="flat",
                               font=("Consolas", 9), padx=8, pady=6)
        sb = ttk.Scrollbar(self.log_wrap, command=self.log_box.yview)
        self.log_box.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

        # Cuerpo: lista de reuniones + pestañas
        body = ttk.Frame(root)
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=11, minsize=520)
        body.columnconfigure(1, weight=8, minsize=430)
        self.style.configure("Treeview", rowheight=30)
        left = ttk.Labelframe(body, text=" Reuniones ", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        search = ttk.Frame(left)
        search.pack(fill="x", pady=(0, 10))
        search.columnconfigure(0, weight=1)
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(search, textvariable=self.filter_var)
        self.filter_entry.grid(row=0, column=0, sticky="ew")
        self.btn_clear = ttk.Button(search, text="✕", width=3, bootstyle="primary-outline", command=self.clear_filter)
        self.btn_clear.grid(row=0, column=1, padx=(6, 0))
        self.filter_count = ttk.Label(search, text="", bootstyle="secondary")
        self.filter_count.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        self._filter_job = None
        self.filter_var.trace_add("write", lambda *_: self._filter_changed())
        self.filter_entry.bind("<Escape>", lambda _e: self.clear_filter())
        self.bind_all("<Control-f>", lambda _e: (self.filter_entry.focus_set(), self.filter_entry.select_range(0, "end")))
        ToolTip(self.filter_entry, text="Buscar por nombre de reunión o cliente (Ctrl+F). Escape limpia.", bootstyle="secondary")
        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(wrap, columns=("cli", "t", "r"), height=5, selectmode="browse")
        self.tree.heading("#0", text="Reunión", anchor="w")
        self.tree.heading("cli", text="Cliente", anchor="w")
        self.tree.heading("t", text="Trans.")
        self.tree.heading("r", text="Resumen")
        self.tree.column("#0", width=250, stretch=True)
        self.tree.column("cli", width=120, anchor="w", stretch=False)
        self.tree.column("t", width=48, anchor="center", stretch=False)
        self.tree.column("r", width=78, anchor="center", stretch=False)
        tsb = ttk.Scrollbar(wrap, command=self.tree.yview)
        self.tree.config(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_meeting_info())
        self.tree.bind("<Double-1>", lambda _e: self.edit_meeting())
        self.tree.bind("<Delete>", lambda _e: self.delete_meeting())
        self.tree.bind("<Button-3>", self._tree_menu)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Editar datos…", command=self.edit_meeting)
        self.menu.add_command(label="Abrir carpeta", command=self.open_selected_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Borrar…", command=self.delete_meeting)

        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(10, 0))
        btns.columnconfigure((0, 1), weight=1, uniform="lb")
        for r, c, text, style, cmd in [
            (0, 0, "✏  Editar datos", "primary-outline", self.edit_meeting),
            (0, 1, "🗑  Borrar", "danger-outline", self.delete_meeting),
            (1, 0, "↻  Actualizar", "primary-outline", self.refresh_files),
            (1, 1, "📂  Carpeta", "primary-outline", self.open_selected_folder),
        ]:
            ttk.Button(btns, text=text, bootstyle=style, command=cmd).grid(
                row=r, column=c, sticky="ew", padx=(0, 4) if c == 0 else (4, 0), pady=3)
        ttk.Button(btns, text="⤓  Importar video/audio…", bootstyle="primary-outline", command=self.import_file).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=3)

        self.nb = ttk.Notebook(body, width=420)
        self.nb.grid(row=0, column=1, sticky="nsew")
        self._build_record_tab()
        self._build_transcribe_tab()
        self._build_summary_tab()
        try:
            self.nb.select(int(self.cfg.get("tab", 0)))
        except (tk.TclError, ValueError):
            pass
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._save_cfg())

    # --- piezas comunes de las pestañas (mismo patrón en las tres)
    def _tab(self, title: str, subtitle: str, label: str) -> ttk.Frame:
        tab = ttk.Frame(self.nb, padding=20)
        self.nb.add(tab, text=label)
        tab.columnconfigure(0, minsize=140)
        tab.columnconfigure(1, weight=1)
        ttk.Label(tab, text=title, font=(FONT, 14, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(tab, text=subtitle, bootstyle="secondary", wraplength=400, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(2, 14))
        return tab

    def _field(self, tab, row: int, label: str, widget_factory=None, **grid):
        lab = ttk.Label(tab, text=label)
        lab.grid(row=row, column=0, sticky="nw", pady=7, padx=(0, 10))
        if widget_factory:
            w = widget_factory(tab)
            w.grid(row=row, column=1, sticky="ew", pady=7, **grid)
            return lab, w
        return lab, None

    def _actions(self, tab, row: int) -> ttk.Frame:
        ttk.Separator(tab).grid(row=row, column=0, columnspan=3, sticky="ew", pady=(18, 16))
        bar = ttk.Frame(tab)
        bar.grid(row=row + 1, column=0, columnspan=3, sticky="w")
        return bar

    def _build_record_tab(self) -> None:
        tab = self._tab("Grabar reunión", "Captura el audio de la salida activa (la reunión) y tu micrófono, y los "
                        "mezcla en un MP3 dentro de grabaciones/AAAA/MM/DD.", "  ●  Grabar  ")
        self.name_var, self.cli_var, self.part_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._field(tab, 2, "Nombre", lambda p: ttk.Entry(p, textvariable=self.name_var))
        self._field(tab, 3, "Cliente (opcional)", lambda p: ttk.Entry(p, textvariable=self.cli_var))
        self._field(tab, 4, "Participantes (opc.)", lambda p: ttk.Entry(p, textvariable=self.part_var))
        self.loop_var = self._var(tk.StringVar, "loop_dev", "")
        _, self.loop_cb = self._field(tab, 5, "Audio del sistema",
                                      lambda p: ttk.Combobox(p, textvariable=self.loop_var, state="readonly"))
        self.mic_var = self._var(tk.StringVar, "mic_dev", "")
        _, self.mic_cb = self._field(tab, 6, "Micrófono",
                                     lambda p: ttk.Combobox(p, textvariable=self.mic_var, state="readonly"))
        bar = self._actions(tab, 7)
        self.btn_rec = ttk.Button(bar, text="●  Grabar", bootstyle="danger", width=13, command=self.start_rec)
        self.btn_rec.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="■  Parar", bootstyle="primary-outline", width=10, command=self.stop_rec,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=10)
        self.timer = ttk.Label(bar, text="00:00", font=(FONT, 22, "bold"))
        self.timer.pack(side="left", padx=(16, 8))
        self.rec_dot = ttk.Label(bar, text="", bootstyle="danger", font=(FONT, 11, "bold"))
        self.rec_dot.pack(side="left")

    def _build_transcribe_tab(self) -> None:
        tab = self._tab("Transcribir con WhisperX", "Convierte la reunión seleccionada (lista de la izquierda) en texto, "
                        "con marcas de tiempo y, opcionalmente, quién habla.", "  📝  Transcribir  ")
        self.model_var = self._var(tk.StringVar, "model", "medium")
        self._field(tab, 2, "Modelo", lambda p: ttk.Combobox(p, textvariable=self.model_var, values=list(core.MODELS),
                                                              state="readonly"))
        self.model_hint = ttk.Label(tab, text="", bootstyle="secondary")
        self.model_hint.grid(row=3, column=1, sticky="w")
        self.model_var.trace_add("write", lambda *_: self.model_hint.config(text=core.MODELS.get(self.model_var.get(), "")))
        self.model_hint.config(text=core.MODELS.get(self.model_var.get(), ""))
        self.lang_var = self._var(tk.StringVar, "lang", os.environ.get("GRABAR_LANG", "es"))
        self._field(tab, 4, "Idioma del audio", lambda p: ttk.Combobox(p, textvariable=self.lang_var, values=TRANSCRIBE_LANGS))
        self.dev_var = self._var(tk.StringVar, "device", "auto")
        self._field(tab, 5, "Cómputo", lambda p: ttk.Combobox(p, textvariable=self.dev_var, values=["auto", "gpu", "cpu"],
                                                               state="readonly"))
        self.diar_var = self._var(tk.BooleanVar, "diarize", False)
        self._field(tab, 6, "Identificar hablantes", lambda p: ttk.Checkbutton(
            p, variable=self.diar_var, bootstyle="round-toggle", text="requiere token de Hugging Face"))
        self.token_var = tk.StringVar(value=core.load_hf_token())

        def token_row(p):
            f = ttk.Frame(p)
            f.columnconfigure(0, weight=1)
            self.token_entry = ttk.Entry(f, textvariable=self.token_var, show="•")
            self.token_entry.grid(row=0, column=0, sticky="ew")
            self.btn_token = ttk.Button(f, width=9, bootstyle="primary-outline", command=self.toggle_token)
            self.btn_token.grid(row=0, column=1, padx=(8, 0))
            ttk.Button(f, text="¿Qué es?", bootstyle="link", command=self.explain_token).grid(row=0, column=2)
            return f

        self._field(tab, 7, "Token HF", token_row)
        self._token_locked(bool(self.token_var.get()))
        bar = self._actions(tab, 8)
        self.btn_tr = ttk.Button(bar, text="Transcribir", bootstyle="primary", width=13, command=self.start_transcribe)
        self.btn_tr.pack(side="left")
        self.btn_cancel = ttk.Button(bar, text="Cancelar", bootstyle="danger-outline", width=10,
                                     command=self.cancel_transcribe, state="disabled")
        self.btn_cancel.pack(side="left", padx=10)
        ttk.Button(bar, text="Ver", bootstyle="primary-outline", width=6, command=self.open_md).pack(side="left")

    def _build_summary_tab(self) -> None:
        tab = self._tab("Resumen con IA", "Genera resumen, key discussion points, decisiones y action items de la reunión "
                        "seleccionada, usando el cliente y los participantes que hayas indicado.", "  ✨  Resumen  ")
        prov = self.cfg.get("provider", next(iter(resumen.PROVIDERS)))
        if prov not in resumen.PROVIDERS:
            prov = next(iter(resumen.PROVIDERS))
        self.prov_var = tk.StringVar(value=prov)
        _, pc = self._field(tab, 2, "Proveedor", lambda p: ttk.Combobox(p, textvariable=self.prov_var,
                                                                        values=list(resumen.PROVIDERS), state="readonly"))
        pc.bind("<<ComboboxSelected>>", lambda _e: self._provider_changed())
        self.sum_model_var = tk.StringVar()
        self.sum_model_var.trace_add("write", lambda *_: self._save_cfg())
        _, self.sum_model_cb = self._field(tab, 3, "Modelo", lambda p: ttk.Combobox(p, textvariable=self.sum_model_var))
        self.sum_lang_var = self._var(tk.StringVar, "sum_lang", "Español")
        self._field(tab, 4, "Idioma resumen", lambda p: ttk.Combobox(p, textvariable=self.sum_lang_var,
                                                                          values=SUMMARY_LANGS, state="readonly"))
        self.key_var = tk.StringVar()

        def key_row(p):
            f = self.key_row = ttk.Frame(p)
            f.columnconfigure(0, weight=1)
            self.key_entry = ttk.Entry(f, textvariable=self.key_var, show="•")
            self.key_entry.grid(row=0, column=0, sticky="ew")
            self.btn_key = ttk.Button(f, width=9, bootstyle="primary-outline", command=self.toggle_key)
            self.btn_key.grid(row=0, column=1, padx=(8, 0))
            ttk.Button(f, text="Obtener key", bootstyle="link", command=self.open_key_page).grid(row=0, column=2)
            return f

        self.key_label, _ = self._field(tab, 5, "API key", key_row)
        self.sum_hint = ttk.Label(tab, text="", bootstyle="secondary", wraplength=330, justify="left")
        self.sum_hint.grid(row=6, column=1, sticky="w")
        self._field(tab, 7, "Reunión", None)
        info = ttk.Frame(tab)
        info.grid(row=7, column=1, columnspan=2, sticky="ew", pady=7)
        info.columnconfigure(0, weight=1)
        self.meeting_info = ttk.Label(info, text="—", justify="left", wraplength=190)
        self.meeting_info.grid(row=0, column=0, sticky="w")
        ttk.Button(info, text="Editar", bootstyle="link", command=self.edit_meeting).grid(row=0, column=1, sticky="e")
        bar = self._actions(tab, 8)
        self.btn_sum = ttk.Button(bar, text="Generar resumen", bootstyle="primary", width=15, command=self.start_summary)
        self.btn_sum.pack(side="left")
        ttk.Button(bar, text="Ver", bootstyle="primary-outline", width=6, command=self.open_summary).pack(side="left", padx=10)
        self.btn_ollama = ttk.Button(bar, text="Instalar Ollama", bootstyle="primary-outline",
                                     command=lambda: self.start_summary(setup_only=True))
        self._provider_changed(initial=True)

    # ------------------------------------------------------------ tema
    def _apply_theme_colors(self) -> None:
        c = self.style.colors
        self.log_box.config(bg=c.inputbg, fg=c.inputfg, insertbackground=c.fg)
        self.log_box.tag_config("err", foreground=c.danger)
        self.log_box.tag_config("ok", foreground=c.success)
        self.log_box.tag_config("stage", foreground=c.info)
        self.log_box.tag_config("time", foreground=c.secondary)
        # en el tema oscuro los colores 'primary'/'secondary' del tema tienen poco contraste: se aclaran
        accent, muted = ("#8ab4f8", "#9aa0a6") if self.dark else (c.primary, c.secondary)
        self.style.configure("primary.Outline.TButton", foreground=accent, bordercolor=accent)
        self.style.configure("secondary.TLabel", foreground=muted)
        self.style.configure("Link.TButton", foreground=accent if self.dark else c.primary)

    def toggle_theme(self) -> None:
        self.dark = bool(self.theme_var.get())
        self.style.theme_use(THEMES["dark" if self.dark else "light"])
        self._apply_theme_colors()
        self._save_cfg()

    def toggle_log(self) -> None:
        if self.log_wrap.winfo_ismapped():
            self.log_wrap.pack_forget()
            self.btn_toggle_log.config(text="Mostrar registro")
        else:
            self.log_wrap.pack(fill="both", expand=True)
            self.btn_toggle_log.config(text="Ocultar registro")

    # ----------------------------------------------------------- helpers
    def log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def ui(self, fn) -> None:
        self.q.put(("call", fn))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    low = payload.lower()
                    tag = ("err" if payload.startswith(("[ERROR]", "✘")) or "error:" in low or "traceback" in low
                           else "ok" if payload.startswith("✔") else "stage" if payload.startswith("▶") else "")
                    self.log_box.config(state="normal")
                    self.log_box.insert("end", f"{datetime.now():%H:%M:%S}  ", "time")
                    self.log_box.insert("end", payload + "\n", tag)
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        if self.rec and self.rec.active:
            s = int(self.rec.elapsed())
            self.timer.config(text=f"{s // 60:02d}:{s % 60:02d}")
            self.rec_dot.config(text="● REC" if s % 2 == 0 else "")
        else:
            self.rec_dot.config(text="")
        self.after(150, self._pump)

    def _bg(self, fn, done=None) -> None:
        def run() -> None:
            try:
                res, err = fn(), None
            except Exception as e:  # noqa: BLE001
                res, err = None, e

            def finish() -> None:
                if err:
                    self.log(f"[ERROR] {err}")
                    messagebox.showerror("Error", str(err))
                if done:
                    done(res, err)
            self.ui(finish)
        threading.Thread(target=run, daemon=True).start()

    # --- panel de actividad (una tarea larga a la vez)
    def act_begin(self, text: str) -> bool:
        if self.busy:
            messagebox.showinfo("Tarea en curso", "Espera a que termine la tarea actual (ver panel Actividad).")
            return False
        self.busy = True
        self._act.update(running=True, t0=time.monotonic(), text=text, bar="")
        self.act_bar.config(mode="indeterminate", value=0)
        self.act_bar.start(12)
        self._act_tick()
        return True

    def _act_tick(self) -> None:
        if not self._act["running"]:
            return
        m, s = divmod(int(time.monotonic() - self._act["t0"]), 60)
        self.act_label.config(text=f"{self._act['text']}{self._act['bar']}   ·   {m:02d}:{s:02d}")
        self.after(500, self._act_tick)

    def act_text(self, text: str) -> None:
        self._act["text"] = text

    def act_pct(self, pct: int, detail: str = "") -> None:
        if str(self.act_bar.cget("mode")) != "determinate":
            self.act_bar.stop()
            self.act_bar.config(mode="determinate", maximum=100)
        self.act_bar.config(value=pct)
        self._act["bar"] = f"  {pct}%" + (f" ({detail})" if detail else "")

    def act_indeterminate(self) -> None:
        self._act["bar"] = ""
        self.act_bar.config(mode="indeterminate")
        self.act_bar.start(12)

    def act_end(self, text: str = "Listo.") -> None:
        self._act["running"] = False
        self.busy = False
        self.act_bar.stop()
        self.act_bar.config(mode="determinate", value=0)
        self.act_label.config(text=text)

    # --------------------------------------------------------------- env
    def refresh_env(self) -> None:
        def done(checks, err):
            if err or checks is None:
                return
            self._checks = checks
            for w in self.chips.winfo_children():
                w.destroy()
            for c in checks:
                style = "success" if c.ok else ("danger" if c.required else "warning")
                icon = "✔" if c.ok else ("✘" if c.required else "!")
                lab = ttk.Label(self.chips, text=f"{icon} {CHIP_NAMES.get(c.key, c.label)}", bootstyle=f"inverse-{style}",
                                padding=(8, 3))
                lab.pack(side="left", padx=(0, 5))
                tip = f"{c.label}: {c.detail}" + (f"\n→ {c.fix}" if not c.ok and c.fix else "")
                ToolTip(lab, text=tip, bootstyle="secondary", wraplength=420)
            self._load_devices(checks)
            ready = not core.missing_required(checks)
            self.btn_rec.config(state="normal" if ready and core.IS_WIN else "disabled")

        self._bg(core.check_environment, done)

    def show_env_details(self) -> None:
        lines = []
        for c in self._checks:
            lines.append(f"{'✔' if c.ok else '✘' if c.required else '!'} {c.label}: {c.detail}")
            if not c.ok and c.fix:
                lines.append(f"      → {c.fix}")
        messagebox.showinfo("Estado del entorno", "\n".join(lines) or "Verificando ...")

    def _load_devices(self, checks) -> None:
        if not core.IS_WIN or not any(c.key == "pyaudio" and c.ok for c in checks):
            return
        try:
            self.devs = core.list_audio_devices()
        except Exception as e:  # noqa: BLE001
            self.log(f"[ERROR] No se pudieron listar dispositivos: {e}")
            return
        d = self.devs
        loops = [x["name"] for x in d["loopbacks"]]
        mics = ["(sin micrófono)"] + [x["name"] for x in d["inputs"]]
        self.loop_cb["values"], self.mic_cb["values"] = loops, mics
        saved_l, saved_m = self.cfg.get("loop_dev"), self.cfg.get("mic_dev")
        self.loop_var.set(saved_l if saved_l in loops else (d["default_loopback"]["name"] if d["default_loopback"] else ""))
        self.mic_var.set(saved_m if saved_m in mics else (d["default_input"]["name"] if d["default_input"] else "(sin micrófono)"))

    def _install(self, what: str) -> None:
        fn = core.install_audio_deps if what == "audio" else core.install_whisperx
        if not self.act_begin(f"Instalando {what} ..."):
            return
        self.log(f"▶ Instalando {what}")
        self.log(f"(salida completa en {core.LOG_FILE})")
        for b in (self.btn_audio, self.btn_wx):
            b.config(state="disabled")

        def on_line(line: str) -> None:
            if line.strip() and not line.startswith(("  ", "Requirement already")):
                self.ui(lambda: self.act_text(f"Instalando {what}: {line.strip()[:70]}"))

        def on_progress(cur: int, total: int) -> None:
            if total > 0:
                self.ui(lambda: self.act_pct(int(cur * 100 / total), f"{cur / 1e6:.0f} / {total / 1e6:.0f} MB"))

        def done(ok, err):
            self.act_end("Instalación terminada." if ok else "La instalación falló.")
            for b in (self.btn_audio, self.btn_wx):
                b.config(state="normal")
            if ok:
                self.log("✔ Instalación terminada correctamente.")
                if what == "audio":
                    messagebox.showinfo("Reiniciar", "Cierra y vuelve a abrir la aplicación para usar los componentes nuevos.")
            else:
                self.log("✘ La instalación falló: causa y solución en el mensaje de error.")
            self.refresh_env()

        self._bg(lambda: fn(self.log, on_progress, on_line), done)

    # -------------------------------------------------------------- token
    def _token_locked(self, locked: bool) -> None:
        self.token_entry.config(state="disabled" if locked else "normal")
        self.btn_token.config(text="Editar" if locked else "Guardar")

    def toggle_token(self) -> None:
        if str(self.token_entry.cget("state")) == "disabled":
            self._token_locked(False)
            self.token_entry.focus_set()
        else:
            core.save_hf_token(self.token_var.get())
            self.token_var.set(self.token_var.get().strip())
            self._token_locked(bool(self.token_var.get()))
            self.log("✔ Token de Hugging Face guardado." if self.token_var.get() else "Token de Hugging Face borrado.")
            self.refresh_env()

    def explain_token(self) -> None:
        if messagebox.askyesno("Token de Hugging Face", core.HF_HELP + "\n\n¿Abrir la página para crear el token?"):
            webbrowser.open("https://huggingface.co/settings/tokens")

    # ---------------------------------------------------------- grabar
    def _index_for(self, name: str, items: list[dict]) -> int | None:
        return next((x["index"] for x in items if x["name"] == name), None)

    def start_rec(self) -> None:
        if not self.devs:
            messagebox.showwarning("Grabar", "No hay dispositivos de audio disponibles.")
            return
        loop = self._index_for(self.loop_var.get(), self.devs["loopbacks"])
        mic = self._index_for(self.mic_var.get(), self.devs["inputs"])
        try:
            self.rec = core.Recorder(loop, mic)
            out = self.rec.start(self.name_var.get())
            library.save_meta(out, self.cli_var.get(), self.part_var.get())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Grabar", str(e))
            return
        self.log(f"▶ Grabando → {out.name}" + ("" if mic is not None else " (sin micrófono)"))
        self.btn_rec.config(state="disabled")
        self.btn_stop.config(state="normal", bootstyle="danger")

    def stop_rec(self) -> None:
        rec = self.rec
        self.btn_stop.config(state="disabled", bootstyle="primary-outline")

        def done(out, err):
            self.btn_rec.config(state="normal")
            self.timer.config(text="00:00")
            for v in (self.name_var, self.cli_var, self.part_var):
                v.set("")
            if out:
                self.log(f"✔ Guardado: {out}")
                self.refresh_files(select=out)

        self._bg(lambda: rec.stop(self.log) if rec else None, done)

    # ------------------------------------------------------ grabaciones
    _NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_(\d{2})-(\d{2})-\d{2}_?(.*)$")

    @staticmethod
    def _norm(text: str) -> str:
        """Minúsculas y sin tildes, para buscar 'reunion' y encontrar 'Reunión'."""
        return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()

    def _filter_changed(self) -> None:
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(150, lambda: self.refresh_files(select=self._selected()))

    def clear_filter(self) -> None:
        self.filter_var.set("")

    def _matches(self, f: Path, meta: dict, words: list[str]) -> bool:
        hay = self._norm(f"{library.display_name(f)} {f.stem} {meta['cliente']}")
        return all(w in hay for w in words)

    def refresh_files(self, select: Path | None = None) -> None:
        self.files = core.list_recordings()
        self.tree.delete(*self.tree.get_children())
        words = self._norm(self.filter_var.get()).split()
        visible: list[int] = []
        for i, f in enumerate(self.files):
            meta = library.load_meta(f)
            if words and not self._matches(f, meta, words):
                continue
            visible.append(i)
            try:
                rel = f.parent.relative_to(core.OUTPUT_DIR).as_posix()
            except ValueError:
                rel = "(otras)"
            parent = f"d:{rel}"
            if not self.tree.exists(parent):
                self.tree.insert("", "end", iid=parent, text=f"📅  {rel.replace('/', '-') or 'raíz'}", open=True)
            m = self._NAME_RE.match(f.stem)
            name = library.display_name(f) or f.suffix[1:]
            label = f"{m[1]}:{m[2]}   {name}" if m else f.name
            md = f.with_suffix(".md")
            self.tree.insert(parent, "end", iid=str(i), text=label, values=(
                meta["cliente"], "✔" if md.exists() else "",
                "✔" if resumen.summary_path(md).exists() else ""))
        total = len(self.files)
        if words:
            self.filter_count.config(text=f"{len(visible)} de {total} reuniones" if visible
                                     else "Sin resultados para esa búsqueda")
        else:
            self.filter_count.config(text=f"{total} reuniones" if total else "Aún no hay reuniones")
        target = next((str(i) for i in visible if self.files[i] == select), None) or (str(visible[0]) if visible else None)
        if target is not None:
            self.tree.selection_set(target)
            self.tree.see(target)
        self._update_meeting_info()

    def _selected(self) -> Path | None:
        sel = self.tree.selection()
        return self.files[int(sel[0])] if sel and sel[0].isdigit() else None

    def _tree_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and row.isdigit():
            self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)

    def _update_meeting_info(self) -> None:
        if not hasattr(self, "meeting_info"):
            return
        f = self._selected()
        if not f:
            self.meeting_info.config(text="— (elige una reunión de la lista)")
            return
        meta = library.load_meta(f)
        self.meeting_info.config(text=(
            f"{library.display_name(f) or f.stem}\n"
            f"Cliente: {meta['cliente'] or '—'}   ·   Participantes: {meta['participantes'] or '—'}"))

    def _can_change_meeting(self) -> Path | None:
        f = self._selected()
        if not f:
            messagebox.showinfo("Reunión", "Elige una reunión de la lista de la izquierda.")
            return None
        if self.busy or (self.rec and self.rec.active):
            messagebox.showinfo("Reunión", "Espera a que termine la grabación o la tarea en curso (panel Actividad).")
            return None
        return f

    def edit_meeting(self) -> None:
        f = self._can_change_meeting()
        if not f:
            return
        meta = library.load_meta(f)
        dlg = ttk.Toplevel(self)
        dlg.title("Editar datos de la reunión")
        dlg.transient(self)
        dlg.resizable(False, False)
        body = ttk.Frame(dlg, padding=24)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Datos de la reunión", font=(FONT, 14, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        stamp, _ = library.split_stem(f.stem)
        when = f"{stamp.split('_')[0]} {stamp.split('_')[1].replace('-', ':')}" if stamp else f.name
        ttk.Label(body, text=f"Grabada: {when}",
                  bootstyle="secondary").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))
        vars_ = {"name": tk.StringVar(value=library.display_name(f)), "cli": tk.StringVar(value=meta["cliente"]),
                 "part": tk.StringVar(value=meta["participantes"])}
        for r, (label, key) in enumerate([("Nombre", "name"), ("Cliente  (opcional)", "cli"),
                                          ("Participantes  (opcional)", "part")], start=2):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=7, padx=(0, 14))
            e = ttk.Entry(body, textvariable=vars_[key], width=44)
            e.grid(row=r, column=1, sticky="ew", pady=7)
            if key == "name":
                e.focus_set()
        ttk.Label(body, text="El cliente y los participantes se incluyen al generar el resumen.",
                  bootstyle="secondary").grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        bar = ttk.Frame(body)
        bar.grid(row=6, column=0, columnspan=2, sticky="e", pady=(18, 0))

        def save() -> None:
            try:
                new = library.rename_recording(f, vars_["name"].get())
                library.save_meta(new, vars_["cli"].get(), vars_["part"].get())
            except (library.LibraryError, OSError) as e:
                messagebox.showerror("Editar reunión", str(e), parent=dlg)
                return
            dlg.destroy()
            self.log(f"✔ Reunión actualizada: {new.name}")
            self.refresh_files(select=new)

        ttk.Button(bar, text="Cancelar", bootstyle="primary-outline", width=12, command=dlg.destroy).pack(side="right")
        ttk.Button(bar, text="Guardar", bootstyle="primary", width=12, command=save).pack(side="right", padx=(0, 10))
        dlg.bind("<Return>", lambda _e: save())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.grab_set()

    def delete_meeting(self) -> None:
        f = self._can_change_meeting()
        if not f:
            return
        n = len(library.companions(f))
        if not messagebox.askyesno(
                "Borrar reunión",
                f"¿Borrar la reunión «{library.display_name(f) or f.name}»?\n\n"
                f"Se enviarán a la Papelera de reciclaje {n} archivo(s): audio, transcripción, resumen y datos.\n"
                "Podrás recuperarlos desde la Papelera.", icon="warning", default="no"):
            return

        def done(res, err):
            if res:
                count, recycled = res
                library.prune_empty_dirs()
                self.log(f"✔ Reunión borrada ({count} archivos" + (", enviados a la Papelera)" if recycled else ", eliminados)")
                         )
            self.refresh_files()

        self._bg(lambda: library.delete_recording(f), done)

    def open_selected_folder(self) -> None:
        f = self._selected()
        core.open_folder(f.parent if f else core.OUTPUT_DIR)

    def import_file(self) -> None:
        path = filedialog.askopenfilename(title="Elige un video o audio",
                                          filetypes=[("Audio/Video", "*.mp4 *.m4a *.mp3 *.wav *.webm *.mkv *.flac *.ogg"),
                                                     ("Todos", "*.*")])
        if not path:
            return
        self._bg(lambda: core.convert_to_wav(Path(path), self.log),
                 lambda out, err: (self.log(f"✔ Creado: {out}"), self.refresh_files(select=out)) if out else None)

    # ------------------------------------------------------ transcribir
    def start_transcribe(self) -> None:
        f = self._selected()
        if not f:
            messagebox.showinfo("Transcribir", "Elige una grabación de la lista de la izquierda.")
            return
        if not core._has_module("whisperx"):
            messagebox.showwarning("Transcribir", "WhisperX no está instalado. Usa el botón 'Instalar WhisperX'.")
            return
        dev = {"auto": None, "gpu": "cuda", "cpu": "cpu"}[self.dev_var.get()]
        if dev == "cuda" and not core.cuda_available():
            messagebox.showwarning("Transcribir", "Tu PyTorch no tiene soporte de GPU (CUDA). Usa 'cpu' o 'auto', "
                                   "o pulsa 'Instalar WhisperX' para reinstalar PyTorch con GPU.")
            return
        if not self.act_begin("Iniciando transcripción ..."):
            return
        t = self.transcription = core.Transcription(f, self.model_var.get(), self.lang_var.get().strip() or "es",
                                                    self.diar_var.get(), self.token_var.get().strip(), dev)
        self.btn_tr.config(state="disabled")
        self.btn_cancel.config(state="normal")

        def on_line(line: str) -> None:
            prog = core.parse_progress(line)
            if prog:
                label, pct, detail = prog
                if detail.split("/")[-1][-1:] in ("k", "M", "G", "B"):
                    self.ui(lambda: self.act_text(f"Descargando modelo{': ' + label if label else ''} (solo la primera vez)"))
                self.ui(lambda: self.act_pct(pct, detail))
                return
            stage = core.stage_of(line)
            if stage:
                def go() -> None:
                    self.act_text(stage)
                    self.act_indeterminate()
                self.ui(go)
                self.log(f"▶ {stage}")
            # el resto de la salida de WhisperX solo va a logs/transcripcion.log

        def done(res, err):
            self.act_end("Transcripción lista." if res else "Transcripción terminada con errores o cancelada.")
            self.btn_tr.config(state="normal")
            self.btn_cancel.config(state="disabled")
            self.refresh_files(select=f)
            if err and core.DIAR_MODEL in str(err):
                webbrowser.open(f"https://huggingface.co/{core.DIAR_MODEL}")
            if res:
                self.log(f"✔ Transcripción lista: {res}")
                messagebox.showinfo("Transcripción lista", str(res))

        self._bg(lambda: t.run(self.log, on_line), done)

    def cancel_transcribe(self) -> None:
        if self.transcription:
            self.transcription.cancel()

    def open_md(self) -> None:
        f = self._selected()
        md = f.with_suffix(".md") if f else None
        if not md or not md.exists():
            messagebox.showinfo("Transcripción", "Esta grabación todavía no tiene transcripción.")
            return
        self._open(md)

    @staticmethod
    def _open(path: Path) -> None:
        if core.IS_WIN:
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            core.open_folder(path.parent)

    # ----------------------------------------------------------- resumen
    def _prov(self) -> dict:
        return resumen.PROVIDERS[self.prov_var.get()]

    def _provider_changed(self, initial: bool = False) -> None:
        p = self._prov()
        self.sum_model_cb.config(values=p["models"])
        saved = self.cfg.get("sum_models", {}).get(p["id"])
        was, self._loading = self._loading, True
        self.sum_model_var.set(saved or p["models"][0])
        self._loading = was
        if p["needs_key"]:
            self.key_label.grid()
            self.key_row.grid()
            self.key_var.set(resumen.load_key(p["id"]))
            self.btn_ollama.pack_forget()
            self._key_locked(bool(self.key_var.get()))
            self.sum_hint.config(text="La transcripción se envía a ese proveedor para generar el resumen. "
                                      "La key se guarda solo en esta PC (.api_keys.json). Gemini ofrece un plan gratuito.")
        else:
            self.key_var.set("")
            self.key_label.grid_remove()
            self.key_row.grid_remove()
            self.btn_ollama.pack(side="left")
            self.sum_hint.config(text="100% local y gratis: nada sale de tu PC. 'Instalar Ollama' descarga e "
                                      "instala Ollama (~1.6 GB) y el modelo (~5 GB) solo, con barra de progreso.")
        if not initial:
            self._save_cfg()

    def _key_locked(self, locked: bool) -> None:
        self.key_entry.config(state="disabled" if locked else "normal")
        self.btn_key.config(state="normal", text="Editar" if locked else "Guardar")

    def toggle_key(self) -> None:
        if str(self.key_entry.cget("state")) == "disabled":
            self._key_locked(False)
            self.key_entry.focus_set()
        else:
            resumen.save_key(self._prov()["id"], self.key_var.get())
            self.key_var.set(self.key_var.get().strip())
            self._key_locked(bool(self.key_var.get()))
            self.log("✔ API key guardada." if self.key_var.get() else "API key borrada.")

    def open_key_page(self) -> None:
        webbrowser.open(self._prov()["key_url"])

    def start_summary(self, setup_only: bool = False) -> None:
        f = self._selected()
        md = f.with_suffix(".md") if f else None
        if not setup_only and (not md or not md.exists()):
            messagebox.showinfo("Resumen", "Primero transcribe la grabación seleccionada (hace falta el .md).")
            return
        p = self._prov()
        pid, model, key = p["id"], self.sum_model_var.get().strip(), self.key_var.get().strip()
        lang = self.sum_lang_var.get() or "Español"
        if p["needs_key"]:
            if not key:
                messagebox.showwarning("Resumen", "Pega la API key y pulsa Guardar (el botón 'Obtener key' abre la página).")
                return
            if pid not in self._sent_ok and not messagebox.askokcancel(
                    "Enviar transcripción", f"La transcripción se enviará a {self.prov_var.get()} para resumirla.\n\n"
                    "¿Continuar? (Para que no salga de tu PC usa Ollama.)"):
                return
            self._sent_ok.add(pid)
        else:
            installed = resumen.ollama_models()
            todo = []
            if installed is None and not resumen.ollama_installed():
                todo.append("instalar Ollama (~1.6 GB)")
            if installed is None or not any(m == model or m == f"{model}:latest" for m in installed):
                todo.append(f"descargar el modelo '{model}' (~5 GB)")
            if todo and not messagebox.askyesno(
                    "Preparar Ollama", "Primero hay que " + " y ".join(todo) + ", solo la primera vez y sin que "
                    "hagas nada manual (puede tardar según tu internet).\n\n¿Continuar?"):
                return
        meta = library.load_meta(f) if f else None
        if not self.act_begin("Preparando ..."):
            return
        self.btn_sum.config(state="disabled")
        self.btn_ollama.config(state="disabled")
        self.log("▶ Preparando Ollama" if setup_only else f"▶ Generando resumen en {lang}")

        def on_pull(status: str, pct: int, detail: str) -> None:
            if pct >= 0:
                self.ui(lambda: (self.act_text(status or "Descargando"), self.act_pct(pct, detail)))
            else:
                self.ui(lambda: (self.act_text(status or "Ollama ..."), self.act_indeterminate()))

        def work():
            if pid == "ollama":
                resumen.setup_ollama(model, on_pull, self.log)
                if setup_only:
                    return None
            self.ui(lambda: (self.act_text(f"Generando resumen con {self.prov_var.get()} ..."), self.act_indeterminate()))
            return resumen.summarize(md, pid, model, key, self.log, lang, meta)

        def done(out, err):
            self.act_end("Resumen listo." if out else "Listo." if setup_only and not err else "No se generó el resumen.")
            self.btn_sum.config(state="normal")
            self.btn_ollama.config(state="normal")
            self.refresh_files(select=f)
            if setup_only and not err:
                self.log("✔ Ollama y el modelo están listos. Ya puedes generar el resumen.")
                messagebox.showinfo("Ollama", "Ollama y el modelo están listos.")
            if out:
                self.log(f"✔ Resumen guardado: {out}")
                self._open(out)

        self._bg(work, done)

    def open_summary(self) -> None:
        f = self._selected()
        out = resumen.summary_path(f.with_suffix(".md")) if f else None
        if not out or not out.exists():
            messagebox.showinfo("Resumen", "Esta grabación todavía no tiene resumen.")
            return
        self._open(out)

    # ------------------------------------------------------------ cierre
    def destroy(self) -> None:
        self._save_cfg()
        if self.rec and self.rec.active:
            try:
                self.rec.stop(self.log)
            except Exception:
                pass
        if self.transcription:
            self.transcription.cancel()
        super().destroy()


def main() -> None:
    App().mainloop()
