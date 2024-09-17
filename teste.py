# Instalação das dependências necessárias
!pip install youtube_transcript_api requests

import re
import os
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from google.colab import files
from IPython.display import display, Markdown

# Definindo a nova chave API do Groq
os.environ['GROQ_API_KEY'] = "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"

def extract_video_id(url):
    match = re.search(r"v=([^&]+)", url)
    return match.group(1) if match else None

def save_transcription_to_file(text, filename="transcricao.txt"):
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(text)
    files.download(filename)

def send_data_to_webhook(transcription, summary):
    webhook_url = "https://conector.ancoraebarros.com/webhook/transcsricao"
    payload = {
        "transcricao": transcription,
        "resumo": summary
    }
    try:
        response = requests.post(webhook_url, json=payload)
        response.raise_for_status()
        display(Markdown("*Transcrição e resumo enviados com sucesso para o webhook.*"))
    except Exception as e:
        display(Markdown(f"*Erro ao enviar os dados para o webhook*: {e}"))

def format_transcription(transcript, max_line_length=500):
    formatted_text = ""
    for entry in transcript:
        text = entry['text'].strip()
        if text:
            while len(text) > max_line_length:
                split_index = text.rfind(' ', 0, max_line_length)
                if split_index == -1:
                    split_index = max_line_length
                formatted_text += text[:split_index] + ' '
                text = text[split_index:].lstrip()
            formatted_text += text + ' '
    formatted_text = re.sub(r'\s+', ' ', formatted_text).strip()
    formatted_text = formatted_text[0].upper() + formatted_text[1:] if formatted_text else ""
    return formatted_text

def summarize_transcription(text):
    try:
        cleaned_text = text.replace('\n', ' ').replace('\r', ' ')
        headers = {
            "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
            "Content-Type": "application/json"
        }
        data = {
            "messages": [{"role": "user", "content": f"Resuma o seguinte texto: {cleaned_text}"}],
            "model": "llama-3.1-70b-versatile"
        }
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        summary = result['choices'][0]['message']['content']
        return summary
    except requests.exceptions.RequestException as e:
        error_message = f"Erro ao processar o resumo: {e}"
        if hasattr(e.response, 'text'):
            error_message += f"\nDetalhes da resposta: {e.response.text}"
        display(Markdown(f"{error_message}"))
        return "Não foi possível gerar um resumo devido a um erro na API."

def process_video_transcription(video_url):
    video_id = extract_video_id(video_url)
    if video_id:
        try:
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['pt'])
        except Exception as e:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id)
            except Exception as e:
                display(Markdown(f"*Erro ao obter a transcrição*: {e}"))
                return
        if transcript:
            formatted_text = format_transcription(transcript)
            display(Markdown("### Transcrição do vídeo:"))
            display(Markdown(formatted_text))
            save_transcription_to_file(formatted_text)

            summary = summarize_transcription(formatted_text)
            display(Markdown("### Resumo da transcrição:"))
            display(Markdown(summary))

            send_data_to_webhook(formatted_text, summary)
        else:
            display(Markdown("*Nenhuma transcrição disponível para este vídeo.*"))
    else:
        display(Markdown("*ID do vídeo não encontrado. Certifique-se de que o link é válido.*"))

def restart_process():
    video_url = input("Insira o link do vídeo do YouTube: ")
    process_video_transcription(video_url)

restart_process()