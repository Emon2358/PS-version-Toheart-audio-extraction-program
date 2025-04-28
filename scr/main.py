"""
PS版ToHeart CD-XA 音声抽出・デコード GUIツール
・.binファイルからMode2 Form2セクタをパース
・サブヘッダ(byte16-23)解析でファイル番号・チャンネル別に分割
・抽出データをそれぞれffmpegへパイプしWAVにデコード
・大きめチャンクでバッファリングし高速化
・Tkinter GUIで操作完結
・ログ出力機能付き

依存：
 - Python 3.7+
 - ffmpeg が PATH にあること

使い方：
 1. python extractor.py
 2. GUIで BIN と出力フォルダを選択
 3. 「開始」ボタンで抽出／デコード開始
"""
import os
import threading
import subprocess
import logging
import struct
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# 定数
SECTOR_SIZE = 2352
XA_DATA_OFFSET = 24
XA_DATA_SIZE = 2324
SAMPLE_RATE = 37800
CHANNELS = 2
LOG_FILENAME = 'extractor.log'

# ロガー設定
logger = logging.getLogger('ToHeartExtractor')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
ch = logging.StreamHandler()
ch.setFormatter(formatter)
logger.addHandler(ch)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ToHeart Audio Extractor")
        self.geometry("520x260")
        self.bin_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self._build_ui()
        logger.info("アプリ起動")

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="BINファイル:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(frm, textvariable=self.bin_path, width=50).grid(row=0, column=1)
        ttk.Button(frm, text="参照...", command=self.select_bin).grid(row=0, column=2)
        ttk.Label(frm, text="出力フォルダ:").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(frm, textvariable=self.out_dir, width=50).grid(row=1, column=1)
        ttk.Button(frm, text="参照...", command=self.select_out).grid(row=1, column=2)
        self.progress = ttk.Progressbar(frm, mode='determinate')
        self.progress.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=10)
        ttk.Label(frm, text=f"ログ: {LOG_FILENAME}").grid(row=3, column=0, columnspan=3, sticky=tk.W)
        self.btn = ttk.Button(frm, text="開始", command=self.start)
        self.btn.grid(row=4, column=1, pady=10)

    def select_bin(self):
        path = filedialog.askopenfilename(filetypes=[('BIN files','*.bin')])
        if path:
            self.bin_path.set(path)
            logger.info(f"BINファイル選択: {path}")

    def select_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out_dir.set(d)
            logger.info(f"出力フォルダ選択: {d}")

    def start(self):
        bin_path = self.bin_path.get()
        out_dir = self.out_dir.get()
        if not os.path.isfile(bin_path):
            messagebox.showerror("エラー", "BINファイルを選択してください")
            logger.error("BINファイル未選択")
            return
        if not os.path.isdir(out_dir):
            messagebox.showerror("エラー", "出力フォルダを選択してください")
            logger.error("出力フォルダ未選択")
            return
        logger.info("抽出開始")
        self.btn.config(state=tk.DISABLED)
        fh = logging.FileHandler(os.path.join(out_dir, LOG_FILENAME), mode='w')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        threading.Thread(target=self.extract_and_decode, daemon=True).start()

    def extract_and_decode(self):
        bin_path = self.bin_path.get()
        out_base = self.out_dir.get()
        file_size = os.path.getsize(bin_path)
        total_sectors = file_size // SECTOR_SIZE
        processed = 0
        CHUNK_SECTORS = 4096
        CHUNK_BYTES = SECTOR_SIZE * CHUNK_SECTORS

        # ffmpeg プロセス管理辞書: (file,channel)->proc
        procs = {}

        with open(bin_path, 'rb') as f:
            while True:
                buf = f.read(CHUNK_BYTES)
                if not buf:
                    break
                mv = memoryview(buf)
                for i in range(0, len(buf), SECTOR_SIZE):
                    sector = mv[i:i+SECTOR_SIZE]
                    if len(sector) < SECTOR_SIZE:
                        break
                    if sector[15] != 2:
                        processed += 1
                        continue
                    subhdr = sector[16:24]
                    # subhdr: file_num, channel, submode, codinginfo...
                    file_num, ch_num = subhdr[0], subhdr[1]
                    key = (file_num, ch_num)
                    if key not in procs:
                        wav_name = os.path.join(out_base, f"file{file_num:02}_ch{ch_num:02}.wav")
                        cmd = ['ffmpeg', '-y', '-f', 'psx_str', '-ar', str(SAMPLE_RATE), '-ac', str(CHANNELS), '-i', 'pipe:0', '-c:a', 'pcm_s16le', wav_name]
                        logger.debug(f"Start ffmpeg for file{file_num:02}_ch{ch_num:02}")
                        procs[key] = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    # データ部を書き込む
                    procs[key].stdin.write(sector[XA_DATA_OFFSET:XA_DATA_OFFSET+XA_DATA_SIZE])
                    processed += 1
                self.progress['value'] = (processed / total_sectors) * 100

        # 全プロセス終了
        for key, proc in procs.items():
            proc.stdin.close()
            proc.wait()
            logger.info(f"Decoded file{key[0]:02}_ch{key[1]:02}.wav")
        messagebox.showinfo("完了", "すべての音声ファイルを出力しました。")
        self.btn.config(state=tk.NORMAL)

if __name__ == '__main__':
    App().mainloop()
