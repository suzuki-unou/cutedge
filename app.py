from flask import Flask, request, render_template, jsonify, send_file
import os
import shutil
import pandas as pd
import cv2
import zipfile
import io
import gdown
# from scenedetect import VideoManager, SceneManager
# from scenedetect.detectors import ContentDetector

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
# カット検出（OpenCVでの簡易実装）
# ----------------------------------------
def detect_cuts(video_path):
    print("📹 detect_cuts(OpenCV) 開始")
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    threshold = 30.0

    last_frame = None
    cutlist = []
    current_time = 0.0
    last_cut = 0.0

    frame_count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        current_time = frame_count / fps

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if last_frame is not None:
            diff = cv2.absdiff(gray, last_frame)
            score = diff.mean()
            if score > threshold and current_time - last_cut > 0.5:
                cutlist.append({
                    "Start(sec)": round(last_cut, 1),
                    "End(sec)": round(current_time - 0.1, 1),
                    "Transcript": ""
                })
                last_cut = current_time

        last_frame = gray

    # 最後のカットを追加
    total_duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    if not cutlist or cutlist[-1]["End(sec)"] < total_duration:
        cutlist.append({
            "Start(sec)": round(last_cut, 1),
            "End(sec)": round(total_duration, 1),
            "Transcript": ""
        })

    cap.release()
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
            except Exception as e:
                print("❌ Driveダウンロード中の例外:", e)
                return render_template("index.html", error="Google DriveのURL処理に失敗しました。")

        if result is None or not os.path.exists(VIDEO_PATH):
            print("❌ 動画ファイルが存在しません")
            return render_template("index.html", error="動画の取得に失敗しました。ファイルかURLをご確認ください。")
        else:
            print("📁 動画ファイルパス:", VIDEO_PATH)
            print("📦 ファイルサイズ:", round(os.path.getsize(VIDEO_PATH) / 1024**2, 2), "MB")

        try:
            cutlist_data = detect_cuts(VIDEO_PATH)
            frame_paths = generate_frames(cutlist_data, VIDEO_PATH)
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
