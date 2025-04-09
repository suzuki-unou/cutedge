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
# import whisper  # Whisperの追加

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
FRAME_FOLDER = 'static/frames'
VIDEO_PATH = os.path.join(UPLOAD_FOLDER, 'input.mp4')
EXCEL_PATH = 'static/cutlist.xlsx'

cutlist_data = []
frame_paths = []

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

def save_to_excel(cutlist, path=EXCEL_PATH):
    df = pd.DataFrame(cutlist)
    df.to_excel(path, index=False)

def detect_cuts(video_path):
    print("📹 detect_cuts(): 処理開始")
    
    video_manager = VideoManager([video_path])
    
    # ✅ 高速化：解像度を下げて処理（品質は少し落ちるけどかなり速くなる）
    video_manager.set_downscale_factor(2)  # 1 = オリジナル, 2 = 半分, 4 = 1/4
    
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=30.0))

    print("⏳ video_manager.start() 実行前")
    video_manager.start()
    print("✅ video_manager.start() 実行後")

    print("🔍 シーン検出 開始")
    scene_manager.detect_scenes(frame_source=video_manager)
    print("✅ detect_scenes 実行後")

    scene_list = scene_manager.get_scene_list()
    print(f"🎞 検出されたシーン数: {len(scene_list)}")

    cutlist = []
    for i, (start_time, end_time) in enumerate(scene_list):
        cutlist.append({
            "Start(sec)": round(start_time.get_seconds(), 1),
            "End(sec)": round(end_time.get_seconds(), 1),
            "Transcript": ""
        })

    video_manager.release()
    print("✅ video_manager.release() 実行完了")
    
    return cutlist


# def generate_transcripts(cutlist, video_path=VIDEO_PATH):
#     model = whisper.load_model("small")
#     result = model.transcribe(video_path, language='ja')
#     segments = result.get("segments", [])
#     for cut in cutlist:
#         start = cut["Start(sec)"]
#         end = cut["End(sec)"]
#         texts = [seg["text"] for seg in segments if seg["start"] < end and seg["end"] > start]
#         cut["Transcript"] = "".join(texts).strip()
#     return cutlist

@app.route("/", methods=["GET", "POST"])
def index():
    global cutlist_data, frame_paths

    if request.method == "POST":
        drive_url = request.form.get("drive_url")
        if drive_url:
            shutil.rmtree(FRAME_FOLDER, ignore_errors=True)
            os.makedirs(FRAME_FOLDER, exist_ok=True)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)

            # Google Drive URL → ID だけ抽出
            if "id=" in drive_url:
                file_id = drive_url.split("id=")[-1].split("&")[0]
            elif "file/d/" in drive_url:
                file_id = drive_url.split("file/d/")[-1].split("/")[0]
            else:
                return render_template("index.html", error="URLの形式が正しくありません")

            gdown.download(f"https://drive.google.com/uc?id={file_id}", VIDEO_PATH, quiet=False)

            cutlist_data = detect_cuts(VIDEO_PATH)
            # cutlist_data = generate_transcripts(cutlist_data, VIDEO_PATH)
            frame_paths = generate_frames(cutlist_data)
            save_to_excel(cutlist_data)

    return render_template("index.html",
                           video_url="input.mp4" if os.path.exists(VIDEO_PATH) else None,
                           cutlist=cutlist_data,
                           frames=frame_paths)

@app.route("/api/update-cutlist", methods=["POST"])
def update_cutlist():
    global cutlist_data, frame_paths
    try:
        data = request.get_json(force=True)
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
        return jsonify({
            "status": "error",
            "message": str(e)
        })

@app.route("/download_excel")
def download_excel():
    return send_file(EXCEL_PATH, as_attachment=True)

@app.route("/download_zip")
def download_zip():
    save_to_excel(cutlist_data)
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
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name="cutlist_and_frames.zip",
        mimetype="application/zip"
    )

if __name__ == "__main__":
    if os.path.exists(VIDEO_PATH):
        os.remove(VIDEO_PATH)
    if os.path.exists(EXCEL_PATH):
        os.remove(EXCEL_PATH)
    if os.path.exists(FRAME_FOLDER):
        shutil.rmtree(FRAME_FOLDER)

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
