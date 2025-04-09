from flask import Flask, request, render_template, jsonify, send_file
import os
import shutil
import pandas as pd
import cv2
import xlsxwriter
import zipfile
import io
import gdown
from scenedetect import VideoManager, SceneManager
from scenedetect.detectors import ContentDetector
#import whisper  # Whisperの追加

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
FRAME_FOLDER = 'static/frames'
VIDEO_PATH = os.path.join(UPLOAD_FOLDER, 'input.mp4')
EXCEL_PATH = 'static/cutlist.xlsx'

# グローバル変数
cutlist_data = []
frame_paths = []

# -----------------------------
# フレーム画像をカットごとに生成
# -----------------------------
def generate_frames(cutlist, video_path=VIDEO_PATH, output_dir=FRAME_FOLDER):
    print("🖼 フレーム生成開始")
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    frame_paths = []

    for i, cut in enumerate(cutlist):
        t = cut["Start(sec)"]
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ret, frame = cap.read()
        if ret:
            frame_path = os.path.join(output_dir, f"frame_{i}.jpg")
            cv2.imwrite(frame_path, frame)
            frame_paths.append(frame_path)
        else:
            frame_paths.append("")

    cap.release()
    print("🖼 フレーム生成完了")
    return frame_paths

# -----------------------------
# Excelとして保存
# -----------------------------
def save_to_excel(cutlist, path=EXCEL_PATH):
    df = pd.DataFrame(cutlist)
    df.to_excel(path, index=False)

# -----------------------------
# PySceneDetectによるカット検出
# -----------------------------
def detect_cuts(video_path):
    print("📹 detect_cuts(): 処理開始")
    video_manager = VideoManager([video_path])
    video_manager.set_downscale_factor(2)  # ✅ 処理高速化
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=30.0))

    video_manager.start()
    print("⏳ Scene検出開始")
    scene_manager.detect_scenes(frame_source=video_manager)
    print("✅ Scene検出完了")

    scene_list = scene_manager.get_scene_list()
    cutlist = []
    for i, (start_time, end_time) in enumerate(scene_list):
        cutlist.append({
            "Start(sec)": round(start_time.get_seconds(), 1),
            "End(sec)": round(end_time.get_seconds(), 1),
            "Transcript": ""
        })

    video_manager.release()
    print("📹 detect_cuts(): 完了")
    return cutlist

# -----------------------------
# メインページ
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global cutlist_data, frame_paths

    if request.method == "POST":
        if 'video' in request.files:
            print("📤 ファイルアップロードモード")
            file = request.files["video"]
            if file:
                shutil.rmtree(FRAME_FOLDER, ignore_errors=True)
                os.makedirs(FRAME_FOLDER, exist_ok=True)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                file.save(VIDEO_PATH)

        elif 'drive_url' in request.form:
    print("🌐 Google Drive URLモード")
    url = request.form.get("drive_url", "")
    file_id = url.split("/d/")[-1].split("/")[0]
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    download_url = f"https://drive.google.com/uc?id={file_id}"
    output_path = VIDEO_PATH
    result = gdown.download(download_url, output_path, quiet=False)

    if result is None or not os.path.exists(output_path):
        return render_template("index.html", error="Google Driveから動画のダウンロードに失敗しました。リンクの共有設定をご確認ください。")


        else:
            return render_template("index.html", error="ファイルが選択されていません")

        cutlist_data = detect_cuts(VIDEO_PATH)
        #cutlist_data = generate_transcripts(cutlist_data, VIDEO_PATH)
        frame_paths = generate_frames(cutlist_data)
        save_to_excel(cutlist_data)

    return render_template("index.html",
                           video_url="input.mp4" if os.path.exists(VIDEO_PATH) else None,
                           cutlist=cutlist_data,
                           frames=frame_paths)

# -----------------------------
# カットリスト更新API
# -----------------------------
@app.route("/api/update-cutlist", methods=["POST"])
def update_cutlist():
    global cutlist_data, frame_paths
    try:
        print("✅ /api/update-cutlist にアクセスされた")

        data = request.get_json(force=True)
        print("📥 受信データ:", data)

        cutlist = data.get("cutlist", [])
        validated = []
        for i, cut in enumerate(cutlist):
            start = cut.get("Start(sec)")
            end = cut.get("End(sec)")
            text = cut.get("Transcript", "")
            print(f"🔹 Cut {i}: Start={start}, End={end}, Transcript={text}")
            if start is None or end is None:
                raise ValueError("Start/End missing")
            start = round(float(start), 1)
            end = round(float(end), 1)
            if end <= start:
                continue
            validated.append({
                "Start(sec)": start,
                "End(sec)": end,
                "Transcript": text
            })

        validated.sort(key=lambda x: x["Start(sec)"])
        cutlist_data = validated
        frame_paths = generate_frames(cutlist_data)
        frame_paths = [f"static/{fp.replace('static/', '').replace(os.sep, '/')}" for fp in frame_paths]
        save_to_excel(cutlist_data)

        return jsonify({
            "status": "success",
            "cutlist": cutlist_data,
            "frames": frame_paths
        })

    except Exception as e:
        print("❌ エラー発生:", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        })

# -----------------------------
# Excel ダウンロード
# -----------------------------
@app.route("/download_excel")
def download_excel():
    return send_file(EXCEL_PATH, as_attachment=True)

@app.route("/download_zip")
def download_zip():
    save_to_excel(cutlist_data)  # 念のためここでも保存する

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        if os.path.exists(EXCEL_PATH):
            zipf.write(EXCEL_PATH, arcname="cutlist.xlsx")
        if os.path.exists(FRAME_FOLDER):
            for filename in sorted(os.listdir(FRAME_FOLDER)):
                filepath = os.path.join(FRAME_FOLDER, filename)
                arcname = f"frames/{filename}"
                zipf.write(filepath, arcname=arcname)

    zip_buffer.seek(0)
    return send_file(zip_buffer, as_attachment=True,
                     download_name="cutlist_and_frames.zip", mimetype="application/zip")

# -----------------------------
# アプリ起動
# -----------------------------
if __name__ == "__main__":
    if os.path.exists(VIDEO_PATH):
        os.remove(VIDEO_PATH)
    if os.path.exists(EXCEL_PATH):
        os.remove(EXCEL_PATH)
    if os.path.exists(FRAME_FOLDER):
        shutil.rmtree(FRAME_FOLDER)

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
