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

app = Flask(__name__)
CORS(app)

mp_conf.change_settings({"FFMPEG_BINARY": "/usr/bin/ffmpeg"})

model = whisper.load_model("base")

progress_status = {
    "message": "Esperando para iniciar...",
    "completed": False
}

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
        audio_path = video_path.replace('.webm', '.wav')
        command = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '2', audio_path]
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

def process_transcription(video_path):
    global progress_status

    # Etapa 1: Converter vídeo para WAV
    progress_status['message'] = "Convertendo vídeo para WAV..."
    audio_path, error_message = convert_to_wav(video_path)

    if not audio_path:
        progress_status['message'] = f"Erro ao converter vídeo: {error_message}"
        progress_status['completed'] = True
        return

    # Etapa 2: Transcrever o áudio
    progress_status['message'] = "Transcrevendo áudio..."
    transcription, error_message = transcribe_audio(audio_path)

    if transcription:
        os.remove(audio_path)
        progress_status['message'] = "Transcrição concluída."
        progress_status['transcription'] = transcription
        progress_status['completed'] = True
    else:
        progress_status['message'] = f"Erro na transcrição: {error_message}"
        progress_status['completed'] = True

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

    video_path, error_message = download_video_with_cookies(youtube_url, resolution, cookies_file)
    
    if not video_path:
        return jsonify({"error": error_message}), 500
    
    global progress_status
    progress_status['message'] = "Vídeo baixado com sucesso! Iniciando transcrição..."
    progress_status['completed'] = False

    # Iniciar o processo de transcrição em uma thread separada
    threading.Thread(target=process_transcription, args=(video_path,)).start()

    return jsonify({"message": "Processo de transcrição iniciado."}), 200

# Rota SSE para enviar progresso ao frontend a cada 10 segundos
@app.route('/progress')
def progress():
    def generate():
        while not progress_status['completed']:
            yield f"data: {progress_status['message']}\n\n"
            time.sleep(10)

        yield f"data: Transcrição finalizada: {progress_status['transcription']}\n\n"

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=8000)
