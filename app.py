from flask import Flask, render_template, request, jsonify
from moviepy.editor import VideoFileClip
import whisper
import re
import os
import yt_dlp
import moviepy.config as mp_conf
import subprocess

app = Flask(__name__)

# Definir o caminho do ffmpeg manualmente
mp_conf.change_settings({"FFMPEG_BINARY": "/usr/bin/ffmpeg"})

# Carregar o modelo Whisper
model = whisper.load_model("base")

# Função para validar o formato da URL do YouTube
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
        command = ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '44100', '-ac', '2', audio_path]
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

# Rota para exibir e processar a transcrição na mesma página
@app.route('/', methods=['GET', 'POST'])
def index():
    transcricao = None

    if request.method == 'POST':
        youtube_url = request.form.get('youtube_url')

        if not youtube_url:
            return jsonify({"error": "URL do vídeo do YouTube é necessária."}), 400

        print(f"Recebendo URL: {youtube_url}")

        # Verificar se a URL é válida
        if not is_valid_youtube_url(youtube_url):
            return jsonify({"error": "URL do vídeo do YouTube inválida."}), 400

        # Definir uma resolução padrão
        resolution = '360'

        # Caminho do arquivo de cookies
        cookies_file = 'cookies.txt'

        # Download do vídeo
        video_path, error_message = download_video_with_cookies(youtube_url, resolution, cookies_file)
        if not video_path:
            return jsonify({"error": error_message}), 500

        # Converter para WAV
        audio_path, error_message = convert_to_wav(video_path)
        if not audio_path:
            return jsonify({"error": error_message}), 500

        # Transcrição do áudio
        transcricao, error_message = transcribe_audio(audio_path)
        if transcricao:
            # Apagar os arquivos temporários após a transcrição
            os.remove(video_path)
            os.remove(audio_path)
        else:
            return jsonify({"error": error_message}), 500

    return render_template('index.html', transcricao=transcricao)

if __name__ == '__main__':
    app.run(debug=True, port=8000)
