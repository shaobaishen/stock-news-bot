import os
import feedparser
import logging
import anthropic
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

TW_TZ = timezone(timedelta(hours=8))

SYSTEM_PROMPT = """你是一位專業的股票新聞分析師。
用戶會提供股票代號與今日新聞，請用繁體中文整理出重點摘要。

格式要求：
- 每點以 • 開頭
- 每點結尾加上【來源｜時間】，例如：【經濟日報｜05/20 14:30】
- 簡潔明瞭，每點不超過 40 字
- 聚焦對投資人最重要的資訊（法說會、財報、重大消息、市場趨勢）
- 若無重大消息，請如實說明"""


def fetch_today_news(query: str, max_results: int = 10) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(url)
    today = datetime.now(TW_TZ).date()
    results = []
    for entry in feed.entries[:max_results]:
        published_str = entry.get("published", "")
        try:
            pub_dt = parsedate_to_datetime(published_str).astimezone(TW_TZ)
            if pub_dt.date() != today:
                continue
            pub_display = pub_dt.strftime("%m/%d %H:%M")
        except Exception:
            pub_display = ""

        source = getattr(getattr(entry, "source", None), "title", "")

        results.append({
            "title": entry.title,
            "published": pub_display,
            "source": source,
        })
    return results


def summarize_news(stock_code: str, news: list[dict]) -> str:
    lines = []
    for item in news:
        meta = f"[{item['source']} | {item['published']}]" if item["source"] else f"[{item['published']}]"
        lines.append(f"- {item['title']} {meta}")
    news_text = "\n".join(lines)

    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=600,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": f"股票代號：{stock_code}\n\n今日新聞：\n{news_text}",
        }],
    )
    return response.content[0].text


def is_stock_code(text: str) -> bool:
    text = text.strip()
    return (text.isdigit() and 4 <= len(text) <= 5) or (text.isalpha() and 1 <= len(text) <= 5)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not is_stock_code(text):
        await update.message.reply_text("請輸入股票代號，例如：\n台股：2330\n美股：TSLA")
        return

    await update.message.reply_text(f"🔍 查詢 {text.upper()} 今日新聞中...")

    news = fetch_today_news(text)

    if not news:
        today_str = datetime.now(TW_TZ).strftime("%m/%d")
        await update.message.reply_text(f"今日（{today_str}）尚無 {text.upper()} 相關新聞。")
        return

    await update.message.reply_text("🤖 AI 整理重點中...")

    try:
        summary = summarize_news(text.upper(), news)
        today_str = datetime.now(TW_TZ).strftime("%m/%d")
        await update.message.reply_text(
            f"📊 <b>{text.upper()} 今日新聞重點（{today_str}）</b>\n\n{summary}",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"AI summarization failed: {e}")
        await update.message.reply_text("AI 整理失敗，請稍後再試。")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    webhook_url = os.environ.get("WEBHOOK_URL")
    if webhook_url:
        port = int(os.environ.get("PORT", 8080))
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            webhook_url=f"{webhook_url}/webhook",
            url_path="webhook",
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
