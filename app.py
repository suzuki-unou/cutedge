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
# import whisper  # Whisperは未使用

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
FRAME_FOLDER = 'static/frames'
VIDEO_PATH = os.path.join(UPLOAD_FOLDER, 'input.mp4')
EXCEL_PATH = 'static/cutlist.xlsx'

cutlist_data = []
frame_paths = []

# ----------------------------------------
# フレーム画像生成
# ----------------------------------------
def generate_frames(cutlist, video_path=VIDEO_PATH, output_dir=FRAME_FOLDER):
    print("🖼️ フレーム生成開始")
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
    print(f"✅ フレーム生成完了: {len(frame_paths)} 枚")
    return frame_paths

# ----------------------------------------
# Excel書き出し
# ----------------------------------------
def save_to_excel(cutlist, path=EXCEL_PATH):
    print("📁 Excel書き出し")
    df = pd.DataFrame(cutlist)
    df.to_excel(path, index=False)

# ----------------------------------------
# カット検出
# ----------------------------------------
def detect_cuts(video_path):
    print("🧪 OpenCVで動画オープンテスト")
    cap = cv2.VideoCapture("static/uploads/input.mp4")
    if not cap.isOpened():
        print("❌ 動画ファイルを開けません")
    else:
        print("✅ 動画ファイルオープン成功")
    print("📹 detect_cuts(): カット検出処理開始")
    video_manager = VideoManager([video_path])
    video_manager.set_downscale_factor(2)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=30.0))

    print("📦 video_manager.start() 実行中...")
    video_manager.start()
    print("✅ video_manager.start() 完了")
    scene_manager.detect_scenes(frame_source=video_manager)
    scene_list = scene_manager.get_scene_list()
    video_manager.release()

    cutlist = []
    for i, (start_time, end_time) in enumerate(scene_list):
        cutlist.append({
            "Start(sec)": round(start_time.get_seconds(), 1),
            "End(sec)": round(end_time.get_seconds(), 1),
            "Transcript": ""
        })

    print(f"✅ カット検出完了: {len(cutlist)} カット")
    return cutlist

# ----------------------------------------
# メイン画面
# ----------------------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    global cutlist_data, frame_paths

    if request.method == "POST":
        result = None

        # ファイルアップロードモード
        if 'video' in request.files and request.files['video'].filename != '':
            print("📤 ファイルアップロードモード")
            file = request.files["video"]
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file.save(VIDEO_PATH)
            result = VIDEO_PATH

        # Google Drive URLモード
        elif 'drive_url' in request.form and request.form.get("drive_url", "").strip():
            print("🌐 Google Drive URLモード")
            url = request.form.get("drive_url", "").strip()
            try:
                file_id = url.split("/d/")[-1].split("/")[0]
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                download_url = f"https://drive.google.com/uc?id={file_id}"
                output_path = VIDEO_PATH
                result = gdown.download(download_url, output_path, quiet=False)
            import time

            # Driveダウンロード後の確認処理
            if result is None or not os.path.exists(VIDEO_PATH):
                print("❌ 動画ファイルの取得に失敗")
                return render_template("index.html", error="動画の取得に失敗しました。")
            
            # 確実に書き込み完了するまで少し待つ
            for i in range(5):
                if os.path.exists(VIDEO_PATH) and os.path.getsize(VIDEO_PATH) > 10_000_000:
                    print(f"✅ 動画ファイル確認: {os.path.getsize(VIDEO_PATH)} bytes")
                    break
                print("⌛ ファイルがまだ書き込み中？待機中...")
                time.sleep(1)
            else:
                return render_template("index.html", error="動画ファイルのサイズ確認に失敗しました。")
            
            # OpenCVで本当に開けるか確認
            cap = cv2.VideoCapture(VIDEO_PATH)
            if not cap.isOpened():
                print("❌ OpenCVで動画を開けませんでした")
                return render_template("index.html", error="動画ファイルが壊れているか、対応していません。")
            else:
                print("🎉 OpenCVでの読み込み成功")
            cap.release()

            except Exception as e:
                print("❌ Driveダウンロード中の例外:", e)
                return render_template("index.html", error="Google DriveのURL処理に失敗しました。")

        # ▼ ここでファイル確認
        if result is None or not os.path.exists(VIDEO_PATH):
            print("❌ 動画ファイルが存在しません")
            return render_template("index.html", error="動画の取得に失敗しました。ファイルかURLをご確認ください。")
        else:
            print("📁 動画ファイルパス:", VIDEO_PATH)
            print("📦 ファイルサイズ:", round(os.path.getsize(VIDEO_PATH) / 1024**2, 2), "MB")

        try:
            print("🚀 detect_cuts を呼び出す直前")
            cutlist_data = detect_cuts(VIDEO_PATH)
            # cutlist_data = generate_transcripts(cutlist_data, VIDEO_PATH)
            frame_paths = generate_frames(cutlist_data)
            save_to_excel(cutlist_data)
        except Exception as e:
            print("❌ detect_cuts() 呼び出し中に例外:", str(e))
            return render_template("index.html", error="カット検出中にエラーが発生しました。")

    return render_template("index.html",
                           video_url="input.mp4" if os.path.exists(VIDEO_PATH) else None,
                           cutlist=cutlist_data,
                           frames=frame_paths)

# ----------------------------------------
# カットリスト更新API
# ----------------------------------------
@app.route("/api/update-cutlist", methods=["POST"])
def update_cutlist():
    global cutlist_data, frame_paths
    try:
        print("🔄 カットリスト更新リクエスト")
        data = request.get_json(force=True)
        cutlist = data.get("cutlist", [])
        validated = []

        for cut in cutlist:
            start = round(float(cut.get("Start(sec)", 0)), 1)
            end = round(float(cut.get("End(sec)", 0)), 1)
            transcript = cut.get("Transcript", "")
            if end > start:
                validated.append({
                    "Start(sec)": start,
                    "End(sec)": end,
                    "Transcript": transcript
                })

        validated.sort(key=lambda x: x["Start(sec)"])
        cutlist_data = validated
        frame_paths = generate_frames(cutlist_data)
        frame_paths = [f"static/{fp.replace('static/', '').replace(os.sep, '/')}" for fp in frame_paths]
        save_to_excel(cutlist_data)

        return jsonify({"status": "success", "cutlist": cutlist_data, "frames": frame_paths})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

# ----------------------------------------
# ダウンロード系
# ----------------------------------------
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
    return send_file(zip_buffer, as_attachment=True, download_name="cutlist_and_frames.zip", mimetype="application/zip")

# ----------------------------------------
# 起動前の初期化
# ----------------------------------------
if __name__ == "__main__":
    if os.path.exists(VIDEO_PATH): os.remove(VIDEO_PATH)
    if os.path.exists(EXCEL_PATH): os.remove(EXCEL_PATH)
    if os.path.exists(FRAME_FOLDER): shutil.rmtree(FRAME_FOLDER)

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
