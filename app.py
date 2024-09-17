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
import redis

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "https://altekweb.com.br"}})

mp_conf.change_settings({"FFMPEG_BINARY": "/usr/bin/ffmpeg"})

model = whisper.load_model("base")
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

@app.route('/')
def index():
    return render_template('index.html')

def is_valid_youtube_url(url):
    pattern = r"^(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+$"
    return re.match(pattern, url) is not None

def download_video_with_cookies(url, resolution, cookies_file, task_id):
    try:
        ydl_opts = {
            'format': f'bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]',
            'cookiefile': cookies_file,
            'outtmpl': f'{task_id}.%(ext)s',  # Nome do arquivo baseado no task_id
            'continuedl': False,
            'noprogress': True,
            'retries': 10,
            'verbose': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=True)
            video_file = f"{task_id}.mp4"  # Assume que o vídeo baixado será .mp4
            print(f"Vídeo baixado com sucesso: {video_file}")
            return video_file, None
    except Exception as e:
        print(f"Erro ao baixar vídeo com yt-dlp: {str(e)}")
        return None, str(e)

def convert_to_wav(video_path, task_id):
    try:
        audio_path = f"{task_id}.wav"  # Nome do arquivo WAV baseado no task_id
        
        # Ajuste da taxa de amostragem para 48kHz e profundidade de bits para 24 bits para melhorar a qualidade
        command = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s24le', '-ar', '48000', '-ac', '2', audio_path]
        subprocess.run(command, check=True)
        
        print(f"Conversão concluída: {audio_path}")
        return audio_path, None
    except subprocess.CalledProcessError as e:
        print(f"Erro ao converter para WAV com ffmpeg: {str(e)}")
        return None, str(e)

def transcribe_audio(audio_path):
    try:
        print(f"Iniciando transcrição do arquivo {audio_path}...")
        result = model.transcribe(audio_path)
        print("Transcrição concluída.")
        return result['text'], None
    except Exception as e:
        print(f"Erro na transcrição: {str(e)}")
        return None, str(e)

def process_transcription(video_path, task_id):
    # Etapa 1: Converter vídeo para WAV
    redis_client.hset(task_id, "message", "Convertendo vídeo para WAV...")
    audio_path, error_message = convert_to_wav(video_path, task_id)

    if not audio_path:
        redis_client.hset(task_id, mapping={
            "message": f"Erro ao converter vídeo: {error_message}",
            "completed": "True"  # Armazenar como string
        })
        return

    # Etapa 2: Transcrever o áudio
    redis_client.hset(task_id, "message", "Transcrevendo áudio...")
    transcription, error_message = transcribe_audio(audio_path)

    if transcription:
        os.remove(audio_path)  # Remove o áudio depois da transcrição
        redis_client.hset(task_id, mapping={
            "message": "Transcrição concluída.",
            "transcription": transcription,
            "completed": "True"  # Armazenar como string
        })
    else:
        redis_client.hset(task_id, mapping={
            "message": f"Erro na transcrição: {error_message}",
            "completed": "True"  # Armazenar como string
        })

# Rota para baixar o vídeo e iniciar o processo de transcrição
@app.route('/baixar_video', methods=['POST'])
def baixar_video():
    youtube_url = request.json.get('youtube_url')

    if not youtube_url:
        return jsonify({"error": "URL do vídeo do YouTube é necessária."}), 400

    if not is_valid_youtube_url(youtube_url):
        return jsonify({"error": "URL do vídeo do YouTube inválida."}), 400

    resolution = '360'
    cookies_file = 'cookies.txt'

    # Gerar um ID único para a tarefa de transcrição
    task_id = str(time.time())  # Você pode usar outro método para gerar um ID único

    video_path, error_message = download_video_with_cookies(youtube_url, resolution, cookies_file, task_id)

    if not video_path:
        return jsonify({"error": error_message}), 500

    # Armazena o status no Redis com a chave do vídeo
    redis_client.hset(task_id, mapping={
        "message": "Vídeo baixado com sucesso! Iniciando transcrição...",
        "completed": "False",  # Armazenar como string
        "transcription": ""
    })

    # Iniciar o processo de transcrição em uma thread separada
    threading.Thread(target=process_transcription, args=(video_path, task_id)).start()

    return jsonify({"message": "Processo de transcrição iniciado.", "task_id": task_id}), 200

# Rota SSE para enviar progresso ao frontend
@app.route('/progress/<task_id>')
def progress(task_id):
    def generate():
        while True:
            progress_status = redis_client.hgetall(task_id)
            if not progress_status.get("completed") == "True":
                yield f"data: {progress_status.get('message')}\n\n"
                time.sleep(10)
            else:
                yield f"data: Transcrição finalizada: {progress_status.get('transcription')}\n\n"
                break

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
