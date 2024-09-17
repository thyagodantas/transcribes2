from flask import Flask, render_template, request, jsonify, Response
from moviepy.editor import VideoFileClip
import whisper
import re
import os
import yt_dlp
import moviepy.config as mp_conf
import subprocess
import time
from flask_cors import CORS
import threading
from celery import Celery
import uuid

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://altekweb.com.br"}})

# Configurando FFMPEG
mp_conf.change_settings({"FFMPEG_BINARY": "/usr/bin/ffmpeg"})

# Carregar o modelo Whisper
model = whisper.load_model("base")

# Configurar Celery com Redis
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config['CELERY_RESULT_BACKEND'],
        broker=app.config['CELERY_BROKER_URL']
    )
    celery.conf.update(app.config)
    return celery

celery = make_celery(app)

progress_status = {}

@app.route('/')
def index():
    return render_template('index.html')

def is_valid_youtube_url(url):
    pattern = r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$"
    return re.match(pattern, url) is not None

def download_video_with_cookies(url, resolution, cookies_file):
    try:
        ydl_opts = {
            'format': f'bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]',
            'cookiefile': cookies_file,
            'outtmpl': '%(title)s.%(ext)s',
            'continuedl': False,
            'noprogress': True,
            'retries': 10,
            'verbose': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            video_file = ydl.prepare_filename(result)
            print(f"Vídeo baixado com sucesso: {video_file}")
            return video_file, None
    except Exception as e:
        print(f"Erro ao baixar vídeo com yt-dlp: {str(e)}")
        return None, str(e)

def convert_to_wav(video_path):
    try:
        if video_path.endswith('.mkv'):
            audio_path = video_path.replace('.mkv', '.wav')
        elif video_path.endswith('.mp4'):
            audio_path = video_path.replace('.mp4', '.wav')
        elif video_path.endswith('.webm'):
            audio_path = video_path.replace('.webm', '.wav')
        else:
            raise ValueError("Formato de vídeo não suportado. Use MP4, MKV ou WEBM.")
        
        command = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s24le', '-ar', '48000', '-ac', '2', audio_path]
        subprocess.run(command, check=True)
        
        print(f"Conversão concluída: {audio_path}")
        return audio_path, None
    except subprocess.CalledProcessError as e:
        print(f"Erro ao converter para WAV com ffmpeg: {str(e)}")
        return None, str(e)
    except ValueError as ve:
        print(str(ve))
        return None, str(ve)

def transcribe_audio(audio_path):
    try:
        print(f"Iniciando transcrição do arquivo {audio_path}...")
        result = model.transcribe(audio_path)
        print("Transcrição concluída.")
        return result['text'], None
    except Exception as e:
        print(f"Erro na transcrição: {str(e)}")
        return None, str(e)

@celery.task
def process_transcription_task(video_path, task_id):
    global progress_status
    try:
        progress_status[task_id] = {"message": "Convertendo vídeo para WAV...", "completed": False}
        audio_path, error_message = convert_to_wav(video_path)
        if not audio_path:
            progress_status[task_id] = {"message": f"Erro ao converter vídeo: {error_message}", "completed": True}
            return
        
        progress_status[task_id]["message"] = "Transcrevendo áudio..."
        transcription, error_message = transcribe_audio(audio_path)
        if transcription:
            os.remove(audio_path)
            progress_status[task_id] = {
                "message": "Transcrição concluída.",
                "transcription": transcription,
                "completed": True
            }
        else:
            progress_status[task_id] = {"message": f"Erro na transcrição: {error_message}", "completed": True}
    except Exception as e:
        progress_status[task_id] = {"message": f"Erro no processamento: {str(e)}", "completed": True}

@app.route('/baixar_video', methods=['POST'])
def baixar_video():
    youtube_url = request.json.get('youtube_url')

    if not youtube_url:
        return jsonify({"error": "URL do vídeo do YouTube é necessária."}), 400

    if not is_valid_youtube_url(youtube_url):
        return jsonify({"error": "URL do vídeo do YouTube inválida."}), 400

    resolution = '360'
    cookies_file = 'cookies.txt'

    video_path, error_message = download_video_with_cookies(youtube_url, resolution, cookies_file)
    
    if not video_path:
        return jsonify({"error": error_message}), 500
    
    # Gera um ID único no formato generate-xxxxxx
    task_id = f"generate-{uuid.uuid4().hex[:6]}"
    progress_status[task_id] = {"message": "Vídeo baixado com sucesso! Iniciando transcrição...", "completed": False}

    # Iniciar o processo de transcrição como uma tarefa em segundo plano
    process_transcription_task.apply_async(args=[video_path, task_id])

    print(f"Task ID gerado: {task_id}")
    print(f"Status atual: {progress_status}")

    return jsonify({"message": "Processo de transcrição iniciado.", "task_id": task_id}), 200

@app.route('/progress/<task_id>')
def progress(task_id):
    def generate():
        # Verificar se o task_id existe no dicionário progress_status
        if task_id not in progress_status:
            yield f"data: Tarefa {task_id} não encontrada.\n\n"
            return

        while not progress_status[task_id]["completed"]:
            yield f"data: {progress_status[task_id]['message']}\n\n"
            time.sleep(5)

        yield f"data: Transcrição finalizada: {progress_status[task_id]['transcription']}\n\n"

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
