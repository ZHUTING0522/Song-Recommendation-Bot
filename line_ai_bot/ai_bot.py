import os
import sys
import random
import requests
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.webhooks import MessageEvent, TextMessageContent, UserSource
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, TextMessage, ReplyMessageRequest
from linebot.v3.exceptions import InvalidSignatureError
from openai import AzureOpenAI

# YouTube API Key
youtube_api_key = os.getenv("YOUTUBE_API_KEY")

# LINE Messaging API credentials
channel_access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
channel_secret = os.getenv("LINE_CHANNEL_SECRET")
if channel_access_token is None or channel_secret is None:
    print("Specify LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET as environment variable.")
    sys.exit(1)

# Azure OpenAI API credentials
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION")
azure_openai_model = os.getenv("AZURE_OPENAI_MODEL")
if azure_openai_endpoint is None or azure_openai_api_key is None or azure_openai_api_version is None:
    raise Exception("Please set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, and AZURE_OPENAI_API_VERSION.")

# Flask app and LINE WebhookHandler setup
app = Flask(__name__)
handler = WebhookHandler(channel_secret)
configuration = Configuration(access_token=channel_access_token)
ai = AzureOpenAI(
    azure_endpoint=azure_openai_endpoint, api_key=azure_openai_api_key, api_version=azure_openai_api_version
)

chat_history = []
recent_songs = []  # 用于存储最近推荐的歌曲，避免重复

# Chat history initialization
def init_chat_history():
    chat_history.clear()
    system_role = {
        "role": "system",
        "content": "あなたは創造的で親切なアシスタントです。関西弁を使って、相手を元気づける会話をします。",
    }
    chat_history.append(system_role)
    recent_songs.clear()  # 重置推荐歌曲的缓存

# YouTube曲検索関数
def search_youtube(query, max_results=5):
    if youtube_api_key is None:
        raise Exception("YouTube APIキーが設定されていません。")

    youtube_api_url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": query,
        "maxResults": max_results,
        "type": "video",
        "key": youtube_api_key,
    }

    response = requests.get(youtube_api_url, params=params)
    if response.status_code != 200:
        raise Exception(f"YouTube API リクエストエラー: {response.status_code}, {response.text}")

    search_results = response.json().get("items", [])
    if not search_results:
        return []

    results = []
    for item in search_results:
        video_id = item["id"]["videoId"]
        video_title = item["snippet"]["title"]
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        results.append({"title": video_title, "url": video_url})

    return results

# メッセージの分析
def analyze_message(message):
    if "疲れた" in message:
        return "リラックス"
    elif "楽しい" in message:
        return "楽しい"
    elif "悲しい" in message:
        return "元気づける"
    elif "雨" in message:
        return "雨の日の曲"
    else:
        return "人気の曲"

# 励ましのメッセージ生成
def generate_encouragement(analysis):
    encouragements = {
        "リラックス": ["深呼吸してね！🍃", "今日は自分を甘やかそう🎵", "心をゆるめて☺️"],
        "楽しい": ["笑顔が一番やで！😁", "楽しんでこそ人生や！🎉", "気分アゲアゲやね！😆"],
        "元気づける": ["負けへんで！🔥", "まだまだこれからや💪", "頑張るあんた、カッコええで！✨"],
        "雨の日の曲": ["雨の日も心晴れやかに☔️", "雨上がりを楽しみに🌈", "静かに過ごすんもええやろ🌧️"],
        "人気の曲": ["音楽で元気チャージ🎧", "気分転換しよう🎶", "良い曲で笑顔に！😊"]
    }
    return random.choice(encouragements.get(analysis, ["今日も素敵な一日を！🌟"]))

# 動的な曲のおすすめ
def recommend_song_dynamic(text):
    analysis = analyze_message(text)
    search_query = f"{analysis} 曲"
    search_results = search_youtube(query=search_query)

    # 从搜索结果中选择一个未推荐过的歌曲
    available_songs = [song for song in search_results if song["title"] not in recent_songs]
    if available_songs:
        selected_song = random.choice(available_songs)
        recent_songs.append(selected_song["title"])
        if len(recent_songs) > 20:
            recent_songs.pop(0)  # 保持最近20首歌的缓存
    else:
        selected_song = None

    encouragement = generate_encouragement(analysis)

    if selected_song:
        return f"🎵 おすすめの曲: {selected_song['title']}\nリンク: {selected_song['url']}\n\n✨ 応援メッセージ: {encouragement}"
    else:
        return f"申し訳ありませんが、適切な曲を見つけることができませんでした。\n\n✨ 応援メッセージ: {encouragement}"

# AI応答を生成する関数
def generate_response(from_user, text):
    if text in ["リセット", "初期化", "クリア", "reset", "clear"]:
        init_chat_history()
        return [TextMessage(text="チャットがリセットされました。")]
    else:
        reply_text = recommend_song_dynamic(text)
        return [TextMessage(text=reply_text)]

# LINEメッセージを受け取った際の処理
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    text = event.message.text
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        res = generate_response(event.source.user_id, text)
        line_bot_api.reply_message(
            ReplyMessageRequest(reply_token=event.reply_token, messages=res)
        )

# Flaskエンドポイント設定
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)

