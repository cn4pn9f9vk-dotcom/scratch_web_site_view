import os
import time
import threading
import urllib.parse
import cv2
import numpy as np
from flask import Flask
import scratchattach as sa

USERNAME = os.environ.get("SCRATCH_USERNAME")
PASSWORD = os.environ.get("SCRATCH_PASSWORD")
PROJECT_ID = os.environ.get("SCRATCH_PROJECT_ID")

CHAR_LIST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!?%:/_-,+=&#"

def digits_to_url(digits):
    """2桁の数字の羅列を文字列に戻す"""
    result = ""
    for i in range(0, len(digits), 2):
        chunk = digits[i:i+2]
        if chunk.isdigit():
            idx = int(chunk)
            if 0 <= idx < len(CHAR_LIST):
                result += CHAR_LIST[idx]
    return result

class BrowserTVState:
    def __init__(self):
        self.current_url = "https://www.google.com"
        self.target_x = 0
        self.target_y = 0
        self.target_size = 1
        self.is_running = True

state = BrowserTVState()

app = Flask(__name__)

@app.route('/')
def home():
    return f"Scratch Browser Bridge Running | URL: {state.current_url} | X:{state.target_x} Y:{state.target_y} Size:{state.target_size}", 200

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def frame_to_digits(frame):
    """44×25ピクセルのドット絵に変換"""
    resized = cv2.resize(frame, (44, 25), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    digits = ""
    
    for y in range(25):
        for x in range(44):
            h, s, v = hsv[y, x]
            
            if v <= 128:
                b = int(round((v / 128.0) * 5))
            else:
                b = 5 + int(round(((v - 128.0) / 127.0) * 4))
            b = max(0, min(9, b))

            # 色相 c (0-9)
            if s < 40 or v < 30: 
                c = 9
            else:
                if h < 6 or h >= 170:      c = 0
                elif h < 18:          c = 1
                elif h < 33:          c = 2
                elif h < 53:          c = 3
                elif h < 78:          c = 4
                elif h < 100:         c = 5
                elif h < 125:         c = 6
                elif h < 140:         c = 7
                else:                 c = 8
            digits += f"{c}{b}"
    return digits

def watch_scratch_commands(cloud_connection):
    global state
    print("Scratchからの指令監視システムを起動しました。")
    
    while state.is_running:
        try:
            raw_data = cloud_connection.get_var("データ10")
            if raw_data and len(raw_data) >= 5:
                # 末尾5文字から x(2桁), y(2桁), size(1桁) を抽出
                size_str = raw_data[-1]
                y_str = raw_data[-3:-1]
                x_str = raw_data[-5:-3]
                
                url_digits = raw_data[:-5]
                input_text = digits_to_url(url_digits)
                
                x = int(x_str)
                y = int(y_str)
                size = int(size_str)
                
                # URLかキーワードか
                if input_text.startswith("http://") or input_text.startswith("https://"):
                    target_url = input_text
                elif "." in input_text and " " not in input_text:
                    target_url = "https://" + input_text
                elif len(input_text) > 0:
                    encoded_query = urllib.parse.quote(input_text)
                    target_url = f"https://www.google.com/search?q={encoded_query}"
                else:
                    target_url = state.current_url
                
                # 状態を更新
                if target_url != state.current_url:
                    print(f"移動先変更: {target_url}")
                    state.current_url = target_url
                
                state.target_x = x
                state.target_y = y
                state.target_size = size

        except Exception as e:
            pass
            
        time.sleep(1.0)

def browser_streaming_loop():
    INTERVAL = 1.0 / 5.0  # 5FPS
    
    print(f"Scratchアカウント [{USERNAME}] でログインしています")
    try:
        session = sa.login(USERNAME, PASSWORD)
        cloud = session.connect_cloud(PROJECT_ID)
        print("クラウド変数サーバーへの接続が完了しました")
    except Exception as e:
        print(f"接続エラー: {e}")
        time.sleep(10)
        return browser_streaming_loop()

    threading.Thread(target=watch_scratch_commands, args=(cloud,), daemon=True).start()

    print("ループを開始します。")
    var_turn = 0
    frame_count = 0

    while state.is_running:
        start_time = time.time()
        
        try:
            # ※ここに将来Playwright等のブラウザキャプチャを組み込みます
            dummy_frame = np.zeros((25, 44, 3), dtype=np.uint8)
            t = frame_count * 0.1
            for y in range(25):
                for x in range(44):
                    val = int((np.sin(x*0.3 + t) + np.cos(y*0.3 + t)) * 127 + 128)
                    dummy_frame[y, x] = [val, 200, 200]
            
            data = frame_to_digits(dummy_frame)
            
            # データ1 〜 データ9 に分割してローテーション送信
            var_name = f"データ{var_turn + 1}"
            chunk = data[var_turn * 256 : (var_turn + 1) * 256]
            if chunk:
                cloud.set_var(var_name, chunk)
                
            var_turn = (var_turn + 1) % 9
            frame_count += 1

        except Exception as e:
            print(f"送信エラー: {e}")

        # FPS（フレームレート）調整
        elapsed = time.time() - start_time
        if elapsed < INTERVAL:
            time.sleep(INTERVAL - elapsed)

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    browser_streaming_loop()
