"""Interfaz gráfica (tkinter, incluido con Python: no requiere instalar nada)."""
from __future__ import annotations

import os
import queue
import threading
import time
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import core, resumen


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Grabador + Transcriptor de reuniones")
        self.geometry("860x930")
        self.minsize(760, 800)
        self.q: queue.Queue = queue.Queue()
        self.rec: core.Recorder | None = None
        self.transcription: core.Transcription | None = None
        self.devs: dict | None = None
        self.files: list[Path] = []
        self._sent_ok: set[str] = set()
        self._build()
        self.after(100, self._pump)
        self.after(300, self.refresh_env)
        threading.Thread(target=lambda: core.migrate_legacy(self.log), daemon=True).start()
        self.after(600, self.refresh_files)

    # ---------------------------------------------------------------- UI
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 5}

        env = ttk.LabelFrame(self, text="1. Estado del entorno")
        env.pack(fill="x", **pad)
        self.env_text = tk.Text(env, height=8, wrap="word", state="disabled", relief="flat",
                                background=self.cget("background"))
        self.env_text.pack(fill="x", padx=6, pady=4)
        self.env_text.tag_config("ok", foreground="#1a7f37")
        self.env_text.tag_config("bad", foreground="#c62828")
        self.env_text.tag_config("warn", foreground="#b26a00")
        row = ttk.Frame(env)
        row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(row, text="Volver a verificar", command=self.refresh_env).pack(side="left")
        self.btn_audio = ttk.Button(row, text="Instalar audio/ffmpeg", command=lambda: self._install("audio"))
        self.btn_audio.pack(side="left", padx=6)
        self.btn_wx = ttk.Button(row, text="Instalar WhisperX", command=lambda: self._install("whisperx"))
        self.btn_wx.pack(side="left")
        ttk.Button(row, text="Abrir carpeta de logs",
                   command=lambda: core.open_folder(core.LOG_DIR)).pack(side="left", padx=6)
        self.prog_frame = ttk.Frame(env)
        self.prog_label = ttk.Label(self.prog_frame, text="", anchor="w")
        self.prog_label.pack(fill="x")
        self.prog = ttk.Progressbar(self.prog_frame, mode="indeterminate")
        self.prog.pack(fill="x", pady=(2, 0))

        rec = ttk.LabelFrame(self, text="2. Grabar")
        rec.pack(fill="x", **pad)
        g = ttk.Frame(rec)
        g.pack(fill="x", padx=6, pady=4)
        g.columnconfigure(1, weight=1)
        ttk.Label(g, text="Nombre:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        ttk.Entry(g, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(g, text="Audio del sistema:").grid(row=1, column=0, sticky="w")
        self.loop_var = tk.StringVar()
        self.loop_cb = ttk.Combobox(g, textvariable=self.loop_var, state="readonly")
        self.loop_cb.grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(g, text="Micrófono:").grid(row=2, column=0, sticky="w")
        self.mic_var = tk.StringVar()
        self.mic_cb = ttk.Combobox(g, textvariable=self.mic_var, state="readonly")
        self.mic_cb.grid(row=2, column=1, sticky="ew", pady=2)
        r = ttk.Frame(rec)
        r.pack(fill="x", padx=6, pady=(0, 6))
        self.btn_rec = ttk.Button(r, text="● Grabar", command=self.start_rec)
        self.btn_rec.pack(side="left")
        self.btn_stop = ttk.Button(r, text="■ Parar", command=self.stop_rec, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.timer = ttk.Label(r, text="00:00", font=("Segoe UI", 14, "bold"))
        self.timer.pack(side="left", padx=12)

        tr = ttk.LabelFrame(self, text="3. Transcribir")
        tr.pack(fill="both", expand=True, **pad)
        top = ttk.Frame(tr)
        top.pack(fill="both", expand=True, padx=6, pady=4)
        self.listbox = tk.Listbox(top, height=6, exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(top, command=self.listbox.yview)
        sb.pack(side="left", fill="y")
        self.listbox.config(yscrollcommand=sb.set)
        side = ttk.Frame(top)
        side.pack(side="left", padx=8, fill="y")
        ttk.Button(side, text="Actualizar lista", command=self.refresh_files).pack(fill="x", pady=1)
        ttk.Button(side, text="Importar video/audio…", command=self.import_file).pack(fill="x", pady=1)
        ttk.Button(side, text="Abrir carpeta", command=self.open_selected_folder).pack(fill="x", pady=1)
        ttk.Button(side, text="Ver transcripción", command=self.open_md).pack(fill="x", pady=1)

        opt = ttk.Frame(tr)
        opt.pack(fill="x", padx=6)
        ttk.Label(opt, text="Modelo:").pack(side="left")
        self.model_var = tk.StringVar(value="medium")
        ttk.Combobox(opt, textvariable=self.model_var, values=list(core.MODELS), width=10,
                     state="readonly").pack(side="left", padx=4)
        ttk.Label(opt, text="Idioma:").pack(side="left", padx=(10, 0))
        self.lang_var = tk.StringVar(value=os.environ.get("GRABAR_LANG", "es"))
        ttk.Entry(opt, textvariable=self.lang_var, width=4).pack(side="left", padx=4)
        ttk.Label(opt, text="Cómputo:").pack(side="left", padx=(10, 0))
        self.dev_var = tk.StringVar(value="auto")
        ttk.Combobox(opt, textvariable=self.dev_var, values=["auto", "gpu", "cpu"], width=6,
                     state="readonly").pack(side="left", padx=4)
        self.diar_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Identificar hablantes", variable=self.diar_var).pack(side="left", padx=10)
        tk_row = ttk.Frame(tr)
        tk_row.pack(fill="x", padx=6, pady=4)
        ttk.Label(tk_row, text="Token HF:").pack(side="left")
        self.token_var = tk.StringVar(value=core.load_hf_token())
        self.token_entry = ttk.Entry(tk_row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_token = ttk.Button(tk_row, width=8, command=self.toggle_token)
        self.btn_token.pack(side="left", padx=(0, 4))
        self._token_locked(bool(self.token_var.get()))
        self.btn_tr = ttk.Button(tk_row, text="Transcribir", command=self.start_transcribe)
        ttk.Button(tk_row, text="¿Qué es?", width=8, command=self.explain_token).pack(side="left", padx=(0, 4))
        self.btn_tr.pack(side="left", padx=4)
        self.btn_cancel = ttk.Button(tk_row, text="Cancelar", command=self.cancel_transcribe, state="disabled")
        self.btn_cancel.pack(side="left")

        self.tprog_frame = ttk.Frame(tr)
        self.tprog_label = ttk.Label(self.tprog_frame, text="", anchor="w")
        self.tprog_label.pack(fill="x")
        self.tprog = ttk.Progressbar(self.tprog_frame, mode="indeterminate")
        self.tprog.pack(fill="x", pady=(2, 0))
        self.log_box = tk.Text(tr, height=9, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.log_box.tag_config("err", foreground="#c62828")

        sm = ttk.LabelFrame(self, text="4. Resumen (resumen · key discussion points · action items)")
        sm.pack(fill="x", **pad)
        r1 = ttk.Frame(sm)
        r1.pack(fill="x", padx=6, pady=(4, 2))
        ttk.Label(r1, text="Proveedor:").pack(side="left")
        self.prov_var = tk.StringVar(value=next(iter(resumen.PROVIDERS)))
        pc = ttk.Combobox(r1, textvariable=self.prov_var, values=list(resumen.PROVIDERS), width=22, state="readonly")
        pc.pack(side="left", padx=4)
        pc.bind("<<ComboboxSelected>>", lambda _e: self._provider_changed())
        ttk.Label(r1, text="Modelo:").pack(side="left", padx=(10, 0))
        self.sum_model_var = tk.StringVar()
        self.sum_model_cb = ttk.Combobox(r1, textvariable=self.sum_model_var, width=24)
        self.sum_model_cb.pack(side="left", padx=4)
        r2 = ttk.Frame(sm)
        r2.pack(fill="x", padx=6, pady=2)
        ttk.Label(r2, text="API key:").pack(side="left")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(r2, textvariable=self.key_var, show="•")
        self.key_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.btn_key = ttk.Button(r2, width=8, command=self.toggle_key)
        self.btn_key.pack(side="left", padx=(0, 4))
        self.btn_getkey = ttk.Button(r2, text="Obtener key", command=self.open_key_page)
        self.btn_getkey.pack(side="left")
        self.sum_hint = ttk.Label(sm, text="", foreground="#666666", wraplength=780, justify="left")
        self.sum_hint.pack(fill="x", padx=6)
        r3 = ttk.Frame(sm)
        r3.pack(fill="x", padx=6, pady=(2, 6))
        self.btn_sum = ttk.Button(r3, text="Resumen", command=self.start_summary)
        self.btn_sum.pack(side="left")
        ttk.Button(r3, text="Ver resumen", command=self.open_summary).pack(side="left", padx=6)
        self.sprog_label = ttk.Label(r3, text="")
        self.sprog = ttk.Progressbar(r3, mode="indeterminate", length=220)
        self._provider_changed()

    # ----------------------------------------------------------- helpers
    def log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log_box.config(state="normal")
                    low = payload.lower()
                    bad = payload.startswith(("[ERROR]", "✘")) or "error:" in low or "traceback" in low
                    self.log_box.insert("end", payload + "\n", "err" if bad else "")
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "call":
                    payload()
        except queue.Empty:
            pass
        if self.rec and self.rec.active:
            s = int(self.rec.elapsed())
            self.timer.config(text=f"{s // 60:02d}:{s % 60:02d}")
        self.after(150, self._pump)

    def _bg(self, fn, done=None) -> None:
        def run() -> None:
            try:
                res = fn()
                err = None
            except Exception as e:  # noqa: BLE001
                res, err = None, e
            def finish() -> None:
                if err:
                    self.log(f"[ERROR] {err}")
                    messagebox.showerror("Error", str(err))
                if done:
                    done(res, err)
            self.q.put(("call", finish))
        threading.Thread(target=run, daemon=True).start()

    # --------------------------------------------------------------- env
    def refresh_env(self) -> None:
        def work():
            return core.check_environment()

        def done(checks, err):
            if err or checks is None:
                return
            t = self.env_text
            t.config(state="normal")
            t.delete("1.0", "end")
            for c in checks:
                tag = "ok" if c.ok else ("bad" if c.required else "warn")
                t.insert("end", ("✔ " if c.ok else ("✘ " if c.required else "! ")), tag)
                t.insert("end", f"{c.label}: {c.detail}\n")
                if not c.ok and c.fix:
                    t.insert("end", f"     → {c.fix}\n", "warn")
            t.config(state="disabled")
            self._load_devices(checks)
            ready = not core.missing_required(checks)
            can_rec = ready and core.IS_WIN
            self.btn_rec.config(state="normal" if can_rec else "disabled")

        self._bg(work, done)

    def _load_devices(self, checks) -> None:
        if not core.IS_WIN or not any(c.key == "pyaudio" and c.ok for c in checks):
            return
        try:
            self.devs = core.list_audio_devices()
        except Exception as e:  # noqa: BLE001
            self.log(f"[ERROR] No se pudieron listar dispositivos: {e}")
            return
        d = self.devs
        self.loop_cb["values"] = [x["name"] for x in d["loopbacks"]]
        self.mic_cb["values"] = ["(sin micrófono)"] + [x["name"] for x in d["inputs"]]
        if d["default_loopback"]:
            self.loop_var.set(d["default_loopback"]["name"])
        self.mic_var.set(d["default_input"]["name"] if d["default_input"] else "(sin micrófono)")

    def _install(self, what: str) -> None:
        fn = core.install_audio_deps if what == "audio" else core.install_whisperx
        self.log(f"--- Instalando {what} ---")
        self.log(f"(Log completo en {core.LOG_FILE})")
        for b in (self.btn_audio, self.btn_wx):
            b.config(state="disabled")
        t0 = time.monotonic()
        state = {"running": True, "msg": "Preparando ...", "mb": ""}
        self.prog_frame.pack(fill="x", padx=6, pady=(0, 6))
        self.prog.config(mode="indeterminate", value=0)
        self.prog.start(12)

        def tick() -> None:
            if not state["running"]:
                return
            m, s = divmod(int(time.monotonic() - t0), 60)
            extra = f" · {state['mb']}" if state["mb"] else ""
            self.prog_label.config(text=f"Instalando {what}… {m:02d}:{s:02d}{extra}  |  {state['msg']}")
            self.after(500, tick)

        def on_line(line: str) -> None:
            # la salida de pip va solo a logs/instalacion.log; aquí solo se muestra como estado
            if line.strip() and not line.startswith(("  ", "Requirement already")):
                state["msg"] = line.strip()[:80]

        def on_progress(cur: int, total: int) -> None:
            def upd() -> None:
                if total > 0:
                    if str(self.prog.cget("mode")) != "determinate":
                        self.prog.stop()
                        self.prog.config(mode="determinate", maximum=100)
                    self.prog.config(value=cur * 100 / total)
                    state["mb"] = f"descarga {cur / 1e6:.0f} / {total / 1e6:.0f} MB"
            self.q.put(("call", upd))

        def done(ok, err):
            state["running"] = False
            self.prog.stop()
            self.prog_frame.pack_forget()
            for b in (self.btn_audio, self.btn_wx):
                b.config(state="normal")
            if ok:
                self.log("✔ Instalación terminada correctamente.")
                if what == "audio":
                    messagebox.showinfo("Reiniciar", "Cerrá y volvé a abrir la aplicación para usar los componentes nuevos.")
            else:
                self.log("✘ La instalación falló: causa y solución en el mensaje de error.")
            self.refresh_env()

        tick()
        self._bg(lambda: fn(self.log, on_progress, on_line), done)

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
            self.log("Token de Hugging Face guardado." if self.token_var.get() else "Token de Hugging Face borrado.")
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
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Grabar", str(e))
            return
        self.log(f"Grabando → {out.name}" + ("" if mic is not None else " (sin micrófono)"))
        self.btn_rec.config(state="disabled")
        self.btn_stop.config(state="normal")

    def stop_rec(self) -> None:
        rec = self.rec
        self.btn_stop.config(state="disabled")

        def done(out, err):
            self.btn_rec.config(state="normal")
            if out:
                self.log(f"Guardado: {out}")
                self.refresh_files(select=out)

        self._bg(lambda: rec.stop(self.log) if rec else None, done)

    # ------------------------------------------------------ transcribir
    def refresh_files(self, select: Path | None = None) -> None:
        self.files = core.list_recordings()
        self.listbox.delete(0, "end")
        for f in self.files:
            marks = ("   ✔ transcrito" if f.with_suffix(".md").exists() else "") + (
                "   ✔ resumen" if resumen.summary_path(f.with_suffix(".md")).exists() else "")
            self.listbox.insert("end", f"{f.relative_to(core.OUTPUT_DIR).as_posix()}{marks}")
        if self.files:
            idx = self.files.index(select) if select in self.files else 0
            self.listbox.selection_set(idx)

    def _selected(self) -> Path | None:
        sel = self.listbox.curselection()
        return self.files[sel[0]] if sel else None

    def import_file(self) -> None:
        path = filedialog.askopenfilename(title="Elegí un video o audio",
                                          filetypes=[("Audio/Video", "*.mp4 *.m4a *.mp3 *.wav *.webm *.mkv *.flac *.ogg"),
                                                     ("Todos", "*.*")])
        if not path:
            return
        self._bg(lambda: core.convert_to_wav(Path(path), self.log),
                 lambda out, err: (self.log(f"Creado: {out}"), self.refresh_files(select=out)) if out else None)

    def start_transcribe(self) -> None:
        f = self._selected()
        if not f:
            messagebox.showinfo("Transcribir", "Elegí una grabación de la lista.")
            return
        if not core._has_module("whisperx"):
            messagebox.showwarning("Transcribir", "WhisperX no está instalado. Usá el botón 'Instalar WhisperX'.")
            return
        dev = {"auto": None, "gpu": "cuda", "cpu": "cpu"}[self.dev_var.get()]
        if dev == "cuda" and not core.cuda_available():
            messagebox.showwarning("Transcribir", "Tu PyTorch no tiene soporte de GPU (CUDA). Usá 'cpu' o 'auto', "
                                   "o pulsá 'Instalar WhisperX' para reinstalar PyTorch con GPU.")
            return
        self.transcription = core.Transcription(f, self.model_var.get(), self.lang_var.get().strip() or "es",
                                                self.diar_var.get(), self.token_var.get().strip(), dev)
        t = self.transcription
        self.btn_tr.config(state="disabled")
        self.btn_cancel.config(state="normal")
        t0 = time.monotonic()
        st = {"running": True, "stage": "Iniciando ...", "bar": ""}
        self.tprog_frame.pack(fill="x", padx=6, pady=(0, 4), before=self.log_box)
        self.tprog.config(mode="indeterminate", value=0)
        self.tprog.start(12)

        def tick() -> None:
            if st["running"]:
                m, s = divmod(int(time.monotonic() - t0), 60)
                self.tprog_label.config(text=f"{st['stage']}{st['bar']}   ·   {m:02d}:{s:02d}")
                self.after(500, tick)

        def set_bar(label: str, pct: int, detail: str) -> None:
            if str(self.tprog.cget("mode")) != "determinate":
                self.tprog.stop()
                self.tprog.config(mode="determinate", maximum=100)
            self.tprog.config(value=pct)
            st["bar"] = f"  {pct}% ({detail})"

        def on_line(line: str) -> None:
            prog = core.parse_progress(line)
            if prog:
                label, pct, detail = prog
                is_dl = detail.split("/")[-1][-1:] in ("k", "M", "G", "B")
                self.q.put(("call", lambda: set_bar(label, pct, detail)))
                if is_dl:
                    st["stage"] = f"Descargando modelo{': ' + label if label else ''} (solo la primera vez)"
                return  # las barras no se vuelcan al log
            stage = core.stage_of(line)
            if stage:
                st["stage"], st["bar"] = stage, ""
                def reset() -> None:
                    self.tprog.config(mode="indeterminate")
                    self.tprog.start(12)
                self.q.put(("call", reset))
                self.log(f"▶ {stage}")
            # el resto de la salida de WhisperX (avisos, trazas) solo va a logs/transcripcion.log

        def done(res, err):
            st["running"] = False
            self.tprog.stop()
            self.tprog_frame.pack_forget()
            self.btn_tr.config(state="normal")
            self.btn_cancel.config(state="disabled")
            self.refresh_files(select=f)
            if err and core.DIAR_MODEL in str(err):
                webbrowser.open(f"https://huggingface.co/{core.DIAR_MODEL}")
            if res:
                messagebox.showinfo("Transcripción lista", str(res))

        tick()
        self._bg(lambda: t.run(self.log, on_line), done)

    def cancel_transcribe(self) -> None:
        if self.transcription:
            self.transcription.cancel()

    # ----------------------------------------------------------- resumen
    def _prov(self) -> dict:
        return resumen.PROVIDERS[self.prov_var.get()]

    def _provider_changed(self) -> None:
        p = self._prov()
        self.sum_model_cb.config(values=p["models"])
        self.sum_model_var.set(p["models"][0])
        if p["needs_key"]:
            self.key_var.set(resumen.load_key(p["id"]))
            self.btn_getkey.config(state="normal")
            self._key_locked(bool(self.key_var.get()))
            self.sum_hint.config(text="La transcripción se envía a ese proveedor para generar el resumen. "
                                      "La key se guarda solo en esta PC (.api_keys.json). Gemini ofrece un plan gratuito.")
        else:
            self.key_var.set("")
            self.key_entry.config(state="disabled")
            self.btn_key.config(state="disabled", text="Guardar")
            self.btn_getkey.config(text="Instalar Ollama + modelo", state="normal")
            self.sum_hint.config(text="100% local y gratis: nada sale de tu PC. Con 'Instalar Ollama + modelo' la app "
                                      "descarga e instala Ollama (~1.6 GB) y el modelo (~5 GB) sola, con barra de progreso.")
        if p["needs_key"]:
            self.btn_getkey.config(text="Obtener key")

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
            self.log("API key guardada." if self.key_var.get() else "API key borrada.")

    def open_key_page(self) -> None:
        if self._prov()["id"] == "ollama":
            self.start_summary(setup_only=True)
        else:
            webbrowser.open(self._prov()["key_url"])

    def start_summary(self, setup_only: bool = False) -> None:
        f = self._selected()
        md = f.with_suffix(".md") if f else None
        if not setup_only and (not md or not md.exists()):
            messagebox.showinfo("Resumen", "Primero transcribí la grabación seleccionada (hace falta el .md).")
            return
        p = self._prov()
        pid, model, key = p["id"], self.sum_model_var.get().strip(), self.key_var.get().strip()
        if p["needs_key"]:
            if not key:
                messagebox.showwarning("Resumen", "Pegá la API key y pulsá Guardar (botón 'Obtener key' abre la página).")
                return
            if pid not in self._sent_ok and not messagebox.askokcancel(
                    "Enviar transcripción", f"La transcripción se enviará a {self.prov_var.get()} para resumirla.\n\n"
                    "¿Continuar? (Para que no salga de tu PC usá Ollama.)"):
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
        self.btn_sum.config(state="disabled")
        t0 = time.monotonic()
        st = {"running": True, "text": "Preparando ..."}
        self.sprog_label.pack(side="left", padx=(12, 4))
        self.sprog.pack(side="left")
        self.sprog.config(mode="indeterminate", value=0)
        self.sprog.start(12)

        def tick() -> None:
            if st["running"]:
                m, s = divmod(int(time.monotonic() - t0), 60)
                self.sprog_label.config(text=f"{st['text']}  ·  {m:02d}:{s:02d}")
                self.after(500, tick)

        def on_pull(status: str, pct: int, detail: str) -> None:
            def upd() -> None:
                if pct >= 0:
                    if str(self.sprog.cget("mode")) != "determinate":
                        self.sprog.stop()
                        self.sprog.config(mode="determinate", maximum=100)
                    self.sprog.config(value=pct)
                    st["text"] = f"{status or 'Descargando'}: {pct}% ({detail})"
                else:
                    st["text"] = status or "Ollama ..."
                    self.sprog.config(mode="indeterminate")
                    self.sprog.start(12)
            self.q.put(("call", upd))

        def work():
            if pid == "ollama":
                resumen.setup_ollama(model, on_pull, self.log)
                if setup_only:
                    return None
                def to_indet() -> None:
                    self.sprog.config(mode="indeterminate")
                    self.sprog.start(12)
                self.q.put(("call", to_indet))
            st["text"] = f"Generando resumen con {self.prov_var.get()} ..."
            return resumen.summarize(md, pid, model, key, self.log)

        def done(out, err):
            st["running"] = False
            self.sprog.stop()
            self.sprog.pack_forget()
            self.sprog_label.pack_forget()
            self.btn_sum.config(state="normal")
            self.refresh_files(select=f)
            if setup_only and not err:
                self.log("✔ Ollama y el modelo están listos. Ya puedes pulsar Resumen.")
                messagebox.showinfo("Ollama", "Ollama y el modelo están listos.")
            if out:
                self.log(f"✔ Resumen guardado: {out}")
                os.startfile(str(out)) if core.IS_WIN else core.open_folder(out.parent)

        tick()
        self._bg(work, done)

    def open_summary(self) -> None:
        f = self._selected()
        out = resumen.summary_path(f.with_suffix(".md")) if f else None
        if not out or not out.exists():
            messagebox.showinfo("Resumen", "Esta grabación todavía no tiene resumen.")
            return
        if core.IS_WIN:
            os.startfile(str(out))  # type: ignore[attr-defined]
        else:
            core.open_folder(out.parent)

    def open_selected_folder(self) -> None:
        f = self._selected()
        core.open_folder(f.parent if f else core.OUTPUT_DIR)

    def open_md(self) -> None:
        f = self._selected()
        md = f.with_suffix(".md") if f else None
        if not md or not md.exists():
            messagebox.showinfo("Transcripción", "Esta grabación todavía no tiene transcripción.")
            return
        if core.IS_WIN:
            os.startfile(str(md))  # type: ignore[attr-defined]
        else:
            core.open_folder(md.parent)

    def destroy(self) -> None:
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
