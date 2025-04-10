
import os
import shutil
import zipfile
import tempfile
from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import cv2
from moviepy.editor import VideoFileClip
# import subprocess
import gdown

app = Flask(__name__)

UPLOAD_FOLDER = 'static/uploads'
FRAME_FOLDER = 'static/frames'
EXCEL_PATH = 'static/cutlist.xlsx'
ZIP_PATH = 'static/output.zip'
VIDEO_PATH = os.path.join(UPLOAD_FOLDER, 'input.mp4')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FRAME_FOLDER, exist_ok=True)

# コメントアウトで無効化されたリサイズ機能
# def resize_video(input_path, output_path, width=640):
#     cmd = [
#         'ffmpeg', '-i', input_path, '-vf',
#         f'scale={width}:-2', '-c:a', 'copy', output_path
#     ]
#     subprocess.run(cmd, check=True)
#     return output_path

def download_video_from_drive(drive_url):
    file_id = drive_url.split('/')[-2]
    download_url = f'https://drive.google.com/uc?id={file_id}'
    gdown.download(download_url, VIDEO_PATH, quiet=False)

def detect_cuts(video_path):
    cap = cv2.VideoCapture(video_path)
    cuts = []
    prev_frame = None
    prev_time = 0
    frame_rate = cap.get(cv2.CAP_PROP_FPS)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        current_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        if prev_frame is not None:
            diff = cv2.absdiff(prev_frame, frame)
            non_zero_count = cv2.countNonZero(cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY))
            if non_zero_count > 500000:
                cuts.append((round(prev_time, 1), round(current_time, 1)))
                prev_time = current_time
        prev_frame = frame
    cap.release()
    return cuts

def generate_frames(video_path, cutlist):
    clip = VideoFileClip(video_path)
    frame_paths = []
    cache = {}
    for i, cut in enumerate(cutlist):
        start = cut['start']
        if start in cache:
            frame = cache[start]
        else:
            frame = clip.get_frame(start)
            cache[start] = frame
        img_path = f"{FRAME_FOLDER}/frame_{i:03d}.jpg"
        cv2.imwrite(img_path, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        frame_paths.append(img_path)
    return frame_paths

def save_to_excel(cutlist):
    df = pd.DataFrame(cutlist)
    df.to_excel(EXCEL_PATH, index=False)

@app.route('/')
def index():
    return render_template('index.html', cutlist=[], frames=[])

@app.route('/process', methods=['POST'])
def process():
    drive_url = request.form.get('drive_url')
    if drive_url:
        print('🌐 Google Drive URLモード')
        download_video_from_drive(drive_url)
    else:
        return 'No drive_url provided', 400

    print(f"📁 動画ファイルパス: {VIDEO_PATH}")
    print(f"📦 ファイルサイズ: {os.path.getsize(VIDEO_PATH) / 1024 / 1024:.2f} MB")

    print("📹 detect_cuts(): OpenCVでカット検出開始")
    cuts = detect_cuts(VIDEO_PATH)

    cutlist = [{'start': round(start, 1), 'end': round(end, 1), 'transcript': ''} for start, end in cuts]
    frame_paths = generate_frames(VIDEO_PATH, cutlist)
    save_to_excel(cutlist)

    return render_template('index.html', cutlist=cutlist, frames=frame_paths)

@app.route('/download_excel')
def download_excel():
    return send_file(EXCEL_PATH, as_attachment=True)

@app.route('/download_zip')
def download_zip():
    with zipfile.ZipFile(ZIP_PATH, 'w') as zipf:
        zipf.write(EXCEL_PATH, os.path.basename(EXCEL_PATH))
        for fname in os.listdir(FRAME_FOLDER):
            zipf.write(os.path.join(FRAME_FOLDER, fname), f'frames/{fname}')
    return send_file(ZIP_PATH, as_attachment=True)

@app.route('/api/update-cutlist', methods=['POST'])
def update_cutlist():
    cutlist = request.json.get('cutlist', [])
    save_to_excel(cutlist)
    frame_paths = generate_frames(VIDEO_PATH, cutlist)
    return jsonify({'frames': frame_paths})

if __name__ == '__main__':
    app.run(debug=True, port=10000)
