"""
PS版ToHeart 音声抽出・デコード GUIツール
対応音源:
 1. CD-DA（Red Book オーディオトラック）
 2. CD-XA ADPCM（Mode2 Form2）

・BIN/CUEからCD-DAトラックを自動リッピング
・.binファイルからMode2 Form2セクタをパース
・サブヘッダ解析でファイル番号・チャンネル別に分割
・抽出データをそれぞれffmpegへパイプしWAVにデコード
・大きめチャンクでバッファリングし高速化
・Tkinter GUIで操作完結
・ログ出力機能付き

依存：
 - Python 3.7+
 - ffmpeg が PATH にあること

使い方：
 1. python extractor.py
 2. GUIで BIN/CUE と出力フォルダを選択
 3. 「開始」ボタンでCD-DA→WAV、CD-XA→WAVを自動実行
"""
import os
import threading
import subprocess
import logging
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
        self.geometry("520x300")
        self.bin_path = tk.StringVar()
        self.cue_path = tk.StringVar()
        self.out_dir = tk.StringVar()
        self._build_ui()
        logger.info("アプリ起動")

    def _build_ui(self):
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill=tk.BOTH, expand=True)
        # BIN
        ttk.Label(frm, text="BINファイル:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(frm, textvariable=self.bin_path, width=40).grid(row=0, column=1)
        ttk.Button(frm, text="参照...", command=self.select_bin).grid(row=0, column=2)
        # CUE
        ttk.Label(frm, text="CUEファイル:").grid(row=1, column=0, sticky=tk.W)
        ttk.Entry(frm, textvariable=self.cue_path, width=40).grid(row=1, column=1)
        ttk.Button(frm, text="参照...", command=self.select_cue).grid(row=1, column=2)
        # 出力フォルダ
        ttk.Label(frm, text="出力フォルダ:").grid(row=2, column=0, sticky=tk.W)
        ttk.Entry(frm, textvariable=self.out_dir, width=40).grid(row=2, column=1)
        ttk.Button(frm, text="参照...", command=self.select_out).grid(row=2, column=2)
        # 進捗バー
        self.progress = ttk.Progressbar(frm, mode='determinate')
        self.progress.grid(row=3, column=0, columnspan=3, sticky=tk.EW, pady=10)
        ttk.Label(frm, text=f"ログ: {LOG_FILENAME}").grid(row=4, column=0, columnspan=3, sticky=tk.W)
        self.btn = ttk.Button(frm, text="開始", command=self.start)
        self.btn.grid(row=5, column=1, pady=10)

    def select_bin(self):
        path = filedialog.askopenfilename(filetypes=[('BIN files','*.bin')])
        if path:
            self.bin_path.set(path)
            logger.info(f"BIN選択: {path}")
    def select_cue(self):
        path = filedialog.askopenfilename(filetypes=[('CUE files','*.cue')])
        if path:
            self.cue_path.set(path)
            logger.info(f"CUE選択: {path}")
    def select_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out_dir.set(d)
            logger.info(f"出力先選択: {d}")

    def start(self):
        bin_path = self.bin_path.get()
        cue_path = self.cue_path.get()
        out_dir = self.out_dir.get()
        if not os.path.isfile(bin_path): messagebox.showerror("エラー","BINを選択してください"); return
        if not os.path.isdir(out_dir): messagebox.showerror("エラー","出力先を選択してください"); return
        logger.info("抽出開始")
        self.btn.config(state=tk.DISABLED)
        fh = logging.FileHandler(os.path.join(out_dir, LOG_FILENAME), mode='w')
        fh.setFormatter(formatter); logger.addHandler(fh)
        threading.Thread(target=self.process_all, args=(bin_path, cue_path, out_dir), daemon=True).start()

    def process_all(self, bin_path, cue_path, out_dir):
        # 1. CD-DA リッピング
        if cue_path and os.path.isfile(cue_path):
            logger.info("CD-DA リッピング開始")
            cmd = ['ffmpeg','-f','cdda','-i',cue_path,'-vn','-c:a','pcm_s16le',os.path.join(out_dir,'cd_da_track%02d.wav')]
            subprocess.run(cmd, check=True)
            logger.info("CD-DA リッピング完了")
        # 2. CD-XA 抽出 & デコード
        self.extract_xa(bin_path, out_dir)
        messagebox.showinfo("完了","CD-DA & CD-XA の WAV 出力が完了しました。")
        self.btn.config(state=tk.NORMAL)

    def extract_xa(self, bin_path, out_dir):
        file_size = os.path.getsize(bin_path)
        total = file_size // SECTOR_SIZE
        processed = 0
        CHUNK = 4096 * SECTOR_SIZE
        procs = {}
        with open(bin_path,'rb') as f:
            while True:
                buf = f.read(CHUNK)
                if not buf: break
                mv = memoryview(buf)
                for i in range(0,len(buf),SECTOR_SIZE):
                    sec = mv[i:i+SECTOR_SIZE]
                    if len(sec)<SECTOR_SIZE: break
                    if sec[15]==2:
                        file_num,ch = sec[16],sec[17]
                        key=(file_num,ch)
                        if key not in procs:
                            out_wav=os.path.join(out_dir,f"file{file_num:02}_ch{ch:02}.wav")
                            cmd=['ffmpeg','-y','-f','psx_str','-ar',str(SAMPLE_RATE),'-ac',str(CHANNELS),'-i','pipe:0','-c:a','pcm_s16le',out_wav]
                            procs[key]=subprocess.Popen(cmd,stdin=subprocess.PIPE)
                            logger.debug(f"Start XA decode {key}")
                        procs[key].stdin.write(sec[XA_DATA_OFFSET:XA_DATA_OFFSET+XA_DATA_SIZE])
                    processed+=1
                self.progress['value']=processed/total*100
        for key,proc in procs.items(): proc.stdin.close(); proc.wait(); logger.info(f"Decoded XA file{key[0]:02}_ch{key[1]:02}.wav")

if __name__=='__main__': App().mainloop()
