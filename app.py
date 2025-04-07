from flask import Flask, request, render_template, jsonify, send_file
import os
import shutil
import pandas as pd
import cv2
import xlsxwriter
import zipfile
import io
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
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=30.0))

    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()

    cutlist = []
    for i, (start_time, end_time) in enumerate(scene_list):
        cutlist.append({
            "Start(sec)": round(start_time.get_seconds(), 1),
            "End(sec)": round(end_time.get_seconds(), 1),
            "Transcript": ""
        })

    video_manager.release()
    return cutlist

# -----------------------------
# Whisperでトランスクリプト生成

# def generate_transcripts(cutlist, video_path=VIDEO_PATH):
    #model = whisper.load_model("small")  # 他に tiny / small / medium / large もOK
    #result = model.transcribe(video_path, language='ja')

    #segments = result.get("segments", [])
    #for cut in cutlist:
     #   start = cut["Start(sec)"]
      #  end = cut["End(sec)"]
       # texts = [seg["text"] for seg in segments if seg["start"] < end and seg["end"] > start]
        #cut["Transcript"] = "".join(texts).strip()

    #return cutlist

# -----------------------------
# メインページ
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global cutlist_data, frame_paths

    if request.method == "POST":
        file = request.files["video"]
        if file:
            # 保存フォルダ初期化
            shutil.rmtree(FRAME_FOLDER, ignore_errors=True)
            os.makedirs(FRAME_FOLDER, exist_ok=True)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)

            # 動画保存
            file.save(VIDEO_PATH)

            # カット検出＋トランスクリプト
            cutlist_data = detect_cuts(VIDEO_PATH)
            #cutlist_data = generate_transcripts(cutlist_data, VIDEO_PATH)

            # フレーム・Excel生成
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
        data = request.get_json()
        cutlist = data.get("cutlist", [])

        validated = []
        for cut in cutlist:
            start = cut.get("Start(sec)")
            end = cut.get("End(sec)")
            text = cut.get("Transcript", "")
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

        # 開始秒数でソート
        validated.sort(key=lambda x: x["Start(sec)"])
        cutlist_data = validated

        # フレーム再生成
        frame_paths = generate_frames(cutlist_data)
        frame_paths = [f"static/{fp.replace('static/', '').replace(os.sep, '/')}" for fp in frame_paths]
        save_to_excel(cutlist_data)

        return jsonify({
            "status": "success",
            "cutlist": cutlist_data,
            "frames": frame_paths
        })

    except Exception as e:
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
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        # Excelファイルを追加
        if os.path.exists(EXCEL_PATH):
            zipf.write(EXCEL_PATH, arcname="cutlist.xlsx")

        # フレーム画像を追加
        if os.path.exists(FRAME_FOLDER):
            for filename in sorted(os.listdir(FRAME_FOLDER)):
                filepath = os.path.join(FRAME_FOLDER, filename)
                arcname = f"frames/{filename}"
                zipf.write(filepath, arcname=arcname)

    zip_buffer.seek(0)
    return send_file(zip_buffer, as_attachment=True, download_name="cutlist_and_frames.zip", mimetype="application/zip")

# -----------------------------
# アプリ起動
# -----------------------------
if __name__ == "__main__":
    # 初期化
    if os.path.exists(VIDEO_PATH):
        os.remove(VIDEO_PATH)
    if os.path.exists(EXCEL_PATH):
        os.remove(EXCEL_PATH)
    if os.path.exists(FRAME_FOLDER):
        shutil.rmtree(FRAME_FOLDER)

    port = int(os.environ.get("PORT", 10000))  # ←ここ！Render用にポート取得
    app.run(host="0.0.0.0", port=port)
