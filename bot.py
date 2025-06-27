# bot.py
import os
import requests
import re
from db import get_twitter_handle
from db import get_twitter_handle, get_recent_approved_posts, get_user_stats
from db import (
    add_user,
    get_user,
    get_user_slots,
    get_user_stats,
    save_post,
    get_pending_posts,
    set_post_status,
    deduct_slot_by_admin,
    expire_old_posts,
    set_twitter_handle,
    get_post_link_by_id,
    has_completed_post,
    mark_post_completed,
    add_task_slot,
)
from db import get_user
from twitter_api import has_liked_post_user_token
import pytz
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
load_dotenv()


AUTH_SERVER_URL = os.getenv("AUTH_SERVER_URL")

TWITTER_BEARER_TOKEN = "AAAAAAAAAAAAAAAAAAAAAB%2B%2B2gEAAAAA88pOPepF8nIceHn9310R%2Fy1zoEk%3DeimB2IvJnLmnf74nkrGWKw68daIo7YXhJGs95CUvPidXybofgH"

# ────────────────────────── CONFIG ──────────────────────────
API_KEY = "7673608151:AAEOpR9o19HwBTNw_RwdMl6jyPb966QTdtQ"   # BotFather token
CHANNEL_URL = "https://t.me/Damitechinfo"                      # Raid channel
SUPPORT_URL = "https://t.me/web3kaijun"                        # Support link
# Telegram IDs of admins
ADMINS = [6229232611]


# ──────────────────────── UTILITIES ─────────────────────────
def run_background_jobs():
    """Runs hourly job that expires approved posts >24 h old."""
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(expire_old_posts, "interval", hours=1)
    scheduler.start()
    print("🕒 Background job started to expire old posts every hour.")


def extract_tweet_id(link: str) -> str | None:
    match = re.search(r"twitter\.com\/[^\/]+\/status\/(\d+)", link)
    return match.group(1) if match else None


def has_liked_tweet(handle: str, tweet_id: str) -> bool:
    url = f"https://api.twitter.com/2/tweets/{tweet_id}/liking_users"
    headers = {
        "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"
    }

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print("[Twitter API Error]", response.status_code, response.text)
        return False

    users = response.json().get("data", [])
    return any(user["username"].lower() == handle.lower() for user in users)


def main_kbd(user_id: int | None = None) -> ReplyKeyboardMarkup:
    keyboard = [
        ["🔥 Ongoing Raids"],
        ["🎯 Slots", "📤 Post", "📨 Invite Friends"],
        ["🎧 Support", "📱 Contacts", "👤 Profile"],
    ]
    if user_id in ADMINS:
        keyboard.append(["🛠️ Review Posts"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_kbd() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["🚫 Cancel"]], resize_keyboard=True)


# ────────────────────────── COMMANDS ────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref_by = int(args[0]) if args and args[0].isdigit() else None

    added = add_user(user.id, user.full_name, ref_by)

    if added:
        welcome = (
            f"*Welcome {user.first_name}!*\n\n"
            "🎉 You’ve been registered with *2 engagement slots*.\n"
            "🔗 Share your referral link to earn more slots.\n\n"
            f"`https://t.me/{context.bot.username}?start={user.id}`"
        )
    else:
        welcome = (
            f"*Welcome back, {user.first_name}!* 👋\n\n"
            "Here’s your referral link again:\n"
            f"`https://t.me/{context.bot.username}?start={user.id}`"
        )

    await update.message.reply_text(welcome, parse_mode="Markdown")
    await update.message.reply_text("🔘 Choose an option:", reply_markup=main_kbd(user.id))


# ──────────────────────── ADMIN REVIEW ─────────────────────
async def review_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("⛔ You’re not authorized.")
        return

    posts = get_pending_posts()
    if not posts:
        await update.message.reply_text("✅ No pending posts.")
        return

    for post_id, link, name, tg_id in posts:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Approve", callback_data=f"approve|{post_id}|{tg_id}"),
            InlineKeyboardButton(
                "❌ Reject",  callback_data=f"reject|{post_id}|{tg_id}")
        ]])
        await update.message.reply_text(f"👤 {name}\n🔗 {link}", reply_markup=kb)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, post_id, user_id = query.data.split("|")
    post_id, user_id = int(post_id), int(user_id)

    if action == "approve":
        if deduct_slot_by_admin(user_id):
            set_post_status(post_id, "approved")
            await context.bot.send_message(user_id, "✅ Your post has been approved for raiding! 🚀")
            await query.edit_message_text("✅ Post approved and 1 slot deducted.")
        else:
            set_post_status(post_id, "rejected")
            await query.edit_message_text("❌ Rejected: user has no available slots.")
    else:  # reject
        set_post_status(post_id, "rejected")
        await context.bot.send_message(user_id, "❌ Your post has been rejected.")
        await query.edit_message_text("❌ Post rejected.")


async def handle_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    post_id = int(query.data.split("|")[1])
    # optional: log to DB that user completed post_id here…

    await query.edit_message_reply_markup(None)      # remove Done button
    await query.message.reply_text("✅ Thanks! Your raid participation was recorded.")

# ────────────────────────── HANDLER ─────────────────────────


async def handle_callback_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data.startswith("confirm_twitter|"):
        handle = data.split("|")[1]
        from db import set_twitter_handle

        success = set_twitter_handle(user.id, handle)

        if success:
            await query.edit_message_text(
                f"✅ Twitter handle @`{handle}` has been confirmed and saved.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                f"❌ The handle @`{handle}` is already in use by another user.\n"
                "Please send a different Twitter handle.",
                parse_mode="Markdown"
            )
            context.user_data["awaiting_twitter"] = True

    elif data.startswith("done|"):
        post_id = int(data.split("|")[1])
        tweet_link = get_post_link_by_id(post_id)
        tweet_id = extract_tweet_id(tweet_link)

        user_data = get_user(user.id)
        if not user_data:
            await query.message.reply_text("❌ User not found.")
            return

        access_token = user_data.get("twitter_access_token")
        if not access_token:
            await query.message.reply_text("❌ You must log in with Twitter before participating.")
            return

        if has_completed_post(user.id, post_id):
            await query.message.reply_text("✅ You've already completed this task.")
            return

        if has_liked_post_user_token(access_token, tweet_id):
            mark_post_completed(user.id, post_id)
            add_task_slot(user.id, 0.1)
            await query.message.reply_text("✅ Task verified! You've earned 0.1 slots.")
        else:
            await query.message.reply_text("❌ We couldn’t verify your like. Please try again after liking the tweet.")


async def handle_message_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    user = update.effective_user

    if txt.startswith("done|"):
        _, post_id, tweet_url = txt.split("|")
        tweet_id = tweet_url.split("/")[-1]  # Extract tweet ID

        twitter = get_twitter_handle(user.id)
        if not twitter:
            await query.answer("No Twitter handle found.")
            return

        if has_liked_post(twitter, tweet_id):
            await query.answer("✅ Verified! You liked the post.")
            # You can add: increment slot, log, etc.
        else:
            await query.answer("❌ Not verified. Please like the tweet first.")
        return

    if context.user_data.get("awaiting_twitter"):
        handle = txt.strip().lstrip("@")
        context.user_data["pending_handle"] = handle
        context.user_data["awaiting_twitter"] = False

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Confirm", callback_data=f"confirm_twitter|{handle}")
        ]])
        await update.message.reply_text(
            f"⚠️ You entered `@{handle}` as your Twitter handle.\n\n"
            "Please confirm. *You won’t be able to change this later.*\n"
            "All tasks are verified using this twitter handle, click 🔥 Ongoing Raids to set another handle",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # 🔥 Ongoing Raids
    elif txt == "🔥 Ongoing Raids":
        twitter = get_twitter_handle(user.id)
        user_data = get_user(user.id)
        access_token = user_data.get(
            "twitter_access_token") if user_data else None
        if not twitter or not access_token:
            connect_url = f"{os.getenv('AUTH_SERVER_BASE_URL')}/login?tgid={user.id}"
            await update.message.reply_text(
                "🐦 Before you can join a raid, connect your Twitter account.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔗 Connect Twitter", url=f"{AUTH_SERVER_URL}/login?tgid={telegram_id}")

                ]])
            )
            return

        posts = get_recent_approved_posts()
        if not posts:
            await update.message.reply_text("🚫 No active raids in the last 24 hours.")
        else:
            for post_id, post_link, name in posts:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "✅ Done", callback_data=f"done|{post_id}")]
                ])
                await update.message.reply_text(
                    f"🔥 *New Raid by {name}*\n🔗 {post_link}",
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )

    # 🎯 Slots
    elif txt == "🎯 Slots":
        slots = get_user_slots(user.id)
        await update.message.reply_text(
            f"🎯 *Slot Info*\n\nHi {user.first_name}, you have *{slots}* engagement slot(s).\n\n"
            "📌 Earn more slots by participating in raids or referring others!",
            parse_mode="Markdown"
        )

    # 📤 Post
    elif txt == "📤 Post":
        await update.message.reply_text(
            "📤 *Submit your post link for review:*\n\n"
            "_Paste the full link below. You will be notified when it is approved._",
            parse_mode="Markdown",
            reply_markup=cancel_kbd()
        )
        context.user_data["awaiting_post"] = True

    # 📨 Invite Friends
    elif txt == "📨 Invite Friends":
        ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
        user_data = get_user(user.id)
        if not user_data:
            await update.message.reply_text("❗ You need to start the bot with /start first.")
            return
        ref1 = user_data["ref_count_l1"] if user_data else 0
        await update.message.reply_text(
            "📨 *Referral Program*\n\n"
            "🎯 Invite others and earn *0.5 engagement slot* per referral!\n\n"
            f"🔗 Your referral link:\n`{ref_link}`\n\n"
            f"📊 *Total Referrals:* {ref1}",
            parse_mode="Markdown"
        )

    # 🎧 Support
    elif txt == "🎧 Support":
        await update.message.reply_text(
            "🎧 *Need help with the Bot?*\n\n"
            "Tap the button below to chat with us:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Contact Us", url=SUPPORT_URL)]]
            )
        )

    # 📱 Contacts
    elif txt == "📱 Contacts":
        await update.message.reply_text(
            "📩 *Contact Us:*\n\n"
            "📧 web3kaiju@gmail.com\n"
            "🔗 X: https://x.com/web3kaiju\n"
            "📱 Telegram: https://t.me/web3kaijun\n"
            "📞 WhatsApp: https://wa.me/+2347043031993",
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    # 🛠️ Review Posts
    elif txt == "🛠️ Review Posts":
        if user.id in ADMINS:
            await review_posts(update, context)
        else:
            await update.message.reply_text("⛔ You’re not authorized.")

    # 🚫 Cancel
    elif txt == "🚫 Cancel":
        context.user_data.pop("awaiting_post", None)
        await update.message.reply_text("Back to main menu.", reply_markup=main_kbd(user.id))

    # Awaited Post Link
    elif context.user_data.get("awaiting_post"):
        post_link = txt
        if not post_link.startswith("http"):
            await update.message.reply_text("❌ Invalid link. Please send a full URL.")
            return
        save_post(user.id, post_link)
        context.user_data["awaiting_post"] = False
        await update.message.reply_text(
            "✅ Your post has been submitted for review.\nYou’ll be notified once it’s approved. 🤝",
            reply_markup=main_kbd(user.id)
        )
        # Notify admins
        name = user.full_name
        for admin_id in ADMINS:
            await context.bot.send_message(admin_id, f"📬 New post submitted by *{name}*.", parse_mode="Markdown")

    # 👤 Profile
    elif txt == "👤 Profile":
        user_data = get_user(user.id)
        if not user_data:
            await update.message.reply_text("User not found.")
            return
        ref1 = user_data["ref_count_l1"]

        stats = get_user_stats(user.id)
        access_token = user_data.get("twitter_access_token")
        print("DEBUG TOKEN:", access_token)
        approved, rejected, task_slots, ref_slots = stats
        twitter = get_twitter_handle(user.id) or "Not set"

        await update.message.reply_text(
            f"👤 *Your Profile*\n\n"
            f"🐦 Twitter: @{twitter or 'Not set'}\n\n"
            f"✅ Approved Posts: {approved}\n"
            f"❌ Rejected Posts: {rejected}\n\n"
            f"💰 Slot Earnings:\n"
            f"🪙 From Raids: {task_slots}\n"
            f"👥 From Referrals: {ref_slots}",
            parse_mode="Markdown"
        )

    # Fallback
    else:
        await update.message.reply_text("❓ I didn't understand that. Choose an option:", reply_markup=main_kbd(user.id))


# ─────────────────────────── MAIN ────────────────────────────
def main():
    app = ApplicationBuilder().token(API_KEY).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(
        handle_callback_buttons, pattern=r"^confirm_twitter\|"))
    app.add_handler(CommandHandler("review", review_posts))
    app.add_handler(CallbackQueryHandler(
        admin_callback, pattern=r"^(approve|reject)\|"))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message_buttons))
    app.add_handler(CallbackQueryHandler(
        handle_done_callback, pattern=r"^done\|"))
    app.add_handler(CallbackQueryHandler(handle_callback_buttons))

    run_background_jobs()
    print("🤖 Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
