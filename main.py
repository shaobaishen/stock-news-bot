import os
import feedparser
import logging
import anthropic
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

load_dotenv()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

# 系統提示穩定不變，適合 prompt caching
SYSTEM_PROMPT = """你是一位專業的股票新聞分析師。
用戶會提供股票代號與相關新聞標題，請用繁體中文整理出 3~5 個重點摘要。

格式要求：
- 每點以 • 開頭
- 簡潔明瞭，每點不超過 30 字
- 聚焦對投資人最重要的資訊（法說會、財報、重大消息、市場趨勢）
- 若無重大消息，請如實說明"""


def fetch_news(query: str, max_results: int = 5) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries[:max_results]:
        results.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.get("published", ""),
        })
    return results


def summarize_news(stock_code: str, news: list[dict]) -> str:
    news_text = "\n".join([f"{i+1}. {item['title']}" for i, item in enumerate(news)])

    response = claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=512,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},  # 系統提示快取，重複查詢省費用
        }],
        messages=[{
            "role": "user",
            "content": f"股票代號：{stock_code}\n\n近期新聞標題：\n{news_text}",
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

    await update.message.reply_text(f"🔍 查詢 {text.upper()} 近期新聞中...")

    news = fetch_news(text)

    if not news:
        await update.message.reply_text(f"找不到 {text} 的相關新聞。")
        return

    lines = [f"📰 <b>{text.upper()} 近期新聞</b>\n"]
    for i, item in enumerate(news, 1):
        lines.append(f'{i}. <a href="{item["link"]}">{item["title"]}</a>')
        if item["published"]:
            lines.append(f'   🕐 {item["published"][:16]}\n')

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    await update.message.reply_text("🤖 AI 整理重點中...")

    try:
        summary = summarize_news(text.upper(), news)
        await update.message.reply_text(
            f"📊 <b>{text.upper()} 新聞重點</b>\n\n{summary}",
            parse_mode="HTML",
        )
    except Exception as e:
        logging.error(f"AI summarization failed: {e}")
        await update.message.reply_text("AI 整理失敗，請稍後再試。")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
