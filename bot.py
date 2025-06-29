import sqlite3
import os
import re
import pytz
import logging
from datetime import datetime, timedelta
from threading import Thread
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Bot
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from db import (
    get_twitter_handle, get_recent_approved_posts, get_user_stats,
    add_user, get_user, get_user_slots, save_post, get_pending_posts,
    set_post_status, deduct_slot_by_admin, expire_old_posts, set_twitter_handle,
    get_post_link_by_id, has_completed_post, mark_post_completed, add_task_slot
)
from twitter_api import TwitterAPI

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
AUTH_SERVER_URL = os.getenv("AUTH_SERVER_URL")
API_KEY = os.getenv("TELEGRAM_TOKEN")
CHANNEL_URL = "https://t.me/Damitechinfo"
SUPPORT_URL = "https://t.me/web3kaijun"
ADMINS = [6229232611]  # Telegram IDs of admins
TWITTER_VERIFICATION_INTERVAL = 3600  # Check Twitter connection every hour

# ──────────────────────── UTILITIES ─────────────────────────


def run_background_jobs():
    """Runs hourly job that expires approved posts >24 h old."""
    scheduler = BackgroundScheduler(timezone=pytz.utc)
    scheduler.add_job(
        expire_old_posts,
        "interval",
        hours=1,
        next_run_time=datetime.now() + timedelta(minutes=1)
    )
    scheduler.start()
    logger.info("🕒 Background job started to expire old posts every hour.")


def check_expired_tokens():
    """Notify users with expired tokens"""
    import sqlite3  # Make sure this is imported at the top

    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT telegram_id, twitter_handle
            FROM users
            WHERE token_expires_at < datetime('now')
        """)
        expired_users = cursor.fetchall()

        bot = Bot(token=API_KEY)
        for user_id, handle in expired_users:
            try:
                bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Your Twitter connection (@{handle}) has expired.\n"
                    "Please reconnect to continue raiding:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "Reconnect",
                        url=f"{AUTH_SERVER_URL}/login?tgid={user_id}"
                    )]])
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {str(e)}")
    finally:
        conn.close()


def extract_tweet_id(link: str) -> str | None:
    """Extract tweet ID from URL"""
    match = re.search(r"twitter\.com\/[^\/]+\/status\/(\d+)", link)
    return match.group(1) if match else None


def main_kbd(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Main keyboard layout"""
    keyboard = [
        ["🔥 Ongoing Raids"],
        ["🎯 Slots", "📤 Post", "📨 Invite Friends"],
        ["🎧 Support", "📱 Contacts", "👤 Profile"],
    ]
    if user_id in ADMINS:
        keyboard.append(["🛠️ Review Posts"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_kbd() -> ReplyKeyboardMarkup:
    """Cancel action keyboard"""
    return ReplyKeyboardMarkup([["🚫 Cancel"]], resize_keyboard=True)


def check_twitter_connection(user_id: int) -> bool:
    """Check if user has valid Twitter connection"""
    user_data = get_user(user_id)
    if not user_data or not user_data.get('twitter_access_token'):
        return False

    # Check if token is expired
    expires_at = user_data.get('token_expires_at')
    if expires_at and datetime.now() > datetime.fromisoformat(expires_at):
        return False

    return True


async def notify_twitter_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send Twitter connection prompt"""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🔗 Connect Twitter",
            url=f"{AUTH_SERVER_URL}/login?tgid={update.effective_user.id}"
        )
    ]])
    await update.message.reply_text(
        "🔐 You need to connect your Twitter account to participate in raids.",
        reply_markup=keyboard
    )

# ────────────────────────── COMMANDS ────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    args = context.args
    ref_by = int(args[0]) if args and args[0].isdigit() else None

    added = add_user(user.id, user.full_name, ref_by)

    welcome = (
        f"*Welcome {user.first_name}!*\n\n"
        "🎉 You've been registered with *2 engagement slots*.\n"
        "🔗 Share your referral link to earn more slots.\n\n"
        f"`https://t.me/{context.bot.username}?start={user.id}`"
    ) if added else (
        f"*Welcome back, {user.first_name}!* 👋\n\n"
        "Here's your referral link again:\n"
        f"`https://t.me/{context.bot.username}?start={user.id}`"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown")
    await update.message.reply_text("🔘 Choose an option:", reply_markup=main_kbd(user.id))


async def connect_twitter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /connect command for Twitter auth"""
    user = update.effective_user
    auth_url = f"{AUTH_SERVER_URL}/login?tgid={user.id}"

    await update.message.reply_text(
        "🔗 Connect your Twitter account to participate in raids:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Connect Twitter", url=auth_url)
        ]])
    )


async def check_twitter_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check_twitter command"""
    user = update.effective_user
    user_data = get_user(user.id)

    if not user_data or not user_data.get('twitter_access_token'):
        await update.message.reply_text(
            "❌ You haven't connected your Twitter account yet.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Connect Now", url=f"{AUTH_SERVER_URL}/login?tgid={user.id}")
            ]])
        )
        return

    try:
        user_info = TwitterAPI.verify_user_identity(
            user_data['twitter_access_token'])
        if user_info:
            await update.message.reply_text(
                f"✅ Connected to Twitter as @{user_data['twitter_handle']}\n"
                f"🆔 Twitter ID: {user_data.get('twitter_id', 'N/A')}"
            )
        else:
            await update.message.reply_text("⚠️ Your Twitter connection expired. Please reconnect.")
    except Exception as e:
        logger.error(f"Twitter verification error: {str(e)}")
        await update.message.reply_text("⚠️ Error verifying Twitter connection.")

# ──────────────────────── ADMIN COMMANDS ─────────────────────


async def review_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin post review handler"""
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("⛔ You're not authorized.")
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
                "❌ Reject", callback_data=f"reject|{post_id}|{tg_id}")
        ]])
        await update.message.reply_text(f"👤 {name}\n🔗 {link}", reply_markup=kb)


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin approval/rejection"""
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
    else:
        set_post_status(post_id, "rejected")
        await context.bot.send_message(user_id, "❌ Your post has been rejected.")
        await query.edit_message_text("❌ Post rejected.")

# ──────────────────────── CALLBACK HANDLERS ─────────────────


async def connect_twitter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /connect command"""
    user = update.effective_user
    auth_url = f"{AUTH_SERVER_URL}/login?tgid={user.id}"

    await update.message.reply_text(
        "Click below to connect your Twitter account:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔗 Connect Twitter", url=auth_url)
        ]])
    )


async def check_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check_connection command"""
    user = update.effective_user
    if check_twitter_connection(user.id):
        user_data = get_user(user.id)
        await update.message.reply_text(
            f"✅ Connected to Twitter as @{user_data['twitter_handle']}"
        )
    else:
        await notify_twitter_required(update, context)


async def handle_callback_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all callback button presses"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    if data.startswith("confirm_twitter|"):
        handle = data.split("|")[1]
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


async def handle_raid_participation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Verify raid participation"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    post_id = int(query.data.split("|")[1])
    if not check_twitter_connection(user.id):
        await notify_twitter_required(update, context)
        return
    user_data = get_user(user.id)
    if not user_data or not user_data.get('twitter_access_token'):
        await query.edit_message_text(
            "❌ You must connect your Twitter account first.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Connect Twitter", url=f"{AUTH_SERVER_URL}/login?tgid={user.id}")
            ]])
        )
        return

    tweet_link = get_post_link_by_id(post_id)
    tweet_id = extract_tweet_id(tweet_link)

    if not tweet_id:
        await query.edit_message_text("❌ Invalid tweet link.")
        return

    try:
        if TwitterAPI.has_liked_tweet(user_data['twitter_access_token'], tweet_id):
            mark_post_completed(user.id, post_id)
            add_task_slot(user.id, 0.1)
            await query.edit_message_text("✅ Verified! You've earned 0.1 slots.")
        else:
            await query.edit_message_text(
                "❌ Like not detected. Please like the tweet and try again.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔁 Check Again", callback_data=f"done|{post_id}")
                ]])
            )
    except Exception as e:
        logger.error(f"Error verifying tweet like: {str(e)}")
        await query.edit_message_text("⚠️ Error verifying like. Please try again later.")

# ────────────────────────── MESSAGE HANDLERS ─────────────────


async def handle_message_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    txt = update.message.text.strip()
    user = update.effective_user

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
            "Please confirm. *You won't be able to change this later.*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    elif txt == "🔥 Ongoing Raids":
        await handle_ongoing_raids(update, context)
    elif txt == "🎯 Slots":
        await handle_slots(update, context)
    elif txt == "📤 Post":
        await handle_post_submission(update, context)
    elif txt == "📨 Invite Friends":
        await handle_referrals(update, context)
    elif txt == "🎧 Support":
        await handle_support(update, context)
    elif txt == "📱 Contacts":
        await handle_contacts(update, context)
    elif txt == "🛠️ Review Posts":
        await review_posts(update, context)
    elif txt == "🚫 Cancel":
        await handle_cancel(update, context)
    elif txt == "👤 Profile":
        await handle_profile(update, context)
    elif context.user_data.get("awaiting_post"):
        await handle_post_link(update, context)
    else:
        await update.message.reply_text("❓ I didn't understand that. Choose an option:", reply_markup=main_kbd(user.id))

# ──────────────────────── HANDLER HELPERS ────────────────────


async def handle_ongoing_raids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ongoing raids display"""
    user = update.effective_user
    user_data = get_user(user.id)

    if not user_data or not user_data.get('twitter_access_token'):
        await update.message.reply_text(
            "🐦 Before you can join raids, connect your Twitter account.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "Connect Twitter", url=f"{AUTH_SERVER_URL}/login?tgid={user.id}")
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


async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle profile display"""
    user = update.effective_user
    user_data = get_user(user.id)
    if not user_data:
        await update.message.reply_text("User not found.")
        return

    stats = get_user_stats(user.id)
    approved, rejected, task_slots, ref_slots = stats
    twitter = user_data.get('twitter_handle', 'Not set')

    await update.message.reply_text(
        f"👤 *Your Profile*\n\n"
        f"🐦 Twitter: @{twitter}\n\n"
        f"✅ Approved Posts: {approved}\n"
        f"❌ Rejected Posts: {rejected}\n\n"
        f"💰 Slot Earnings:\n"
        f"🪙 From Raids: {task_slots}\n"
        f"👥 From Referrals: {ref_slots}",
        parse_mode="Markdown"
    )


async def handle_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle slots display"""
    user = update.effective_user
    slots = get_user_slots(user.id)
    await update.message.reply_text(
        f"🎯 *Slot Info*\n\nHi {user.first_name}, you have *{slots}* engagement slot(s).\n\n"
        "📌 Earn more slots by participating in raids or referring others!",
        parse_mode="Markdown"
    )


async def handle_post_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle post submission"""
    await update.message.reply_text(
        "📤 *Submit your post link for review:*\n\n"
        "_Paste the full link below. You will be notified when it is approved._",
        parse_mode="Markdown",
        reply_markup=cancel_kbd()
    )
    context.user_data["awaiting_post"] = True


async def handle_post_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle submitted post link"""
    post_link = update.message.text.strip()
    user = update.effective_user

    if not post_link.startswith("http"):
        await update.message.reply_text("❌ Invalid link. Please send a full URL.")
        return

    save_post(user.id, post_link)
    context.user_data["awaiting_post"] = False
    await update.message.reply_text(
        "✅ Your post has been submitted for review.\nYou'll be notified once it's approved. 🤝",
        reply_markup=main_kbd(user.id)
    )

    # Notify admins
    name = user.full_name
    for admin_id in ADMINS:
        await context.bot.send_message(admin_id, f"📬 New post submitted by *{name}*.", parse_mode="Markdown")


async def handle_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle referral program"""
    user = update.effective_user
    user_data = get_user(user.id)
    if not user_data:
        await update.message.reply_text("❗ You need to start the bot with /start first.")
        return

    ref_link = f"https://t.me/{context.bot.username}?start={user.id}"
    ref1 = user_data["ref_count_l1"] if user_data else 0

    await update.message.reply_text(
        "📨 *Referral Program*\n\n"
        "🎯 Invite others and earn *0.5 engagement slot* per referral!\n\n"
        f"🔗 Your referral link:\n`{ref_link}`\n\n"
        f"📊 *Total Referrals:* {ref1}",
        parse_mode="Markdown"
    )


async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle support request"""
    await update.message.reply_text(
        "🎧 *Need help with the Bot?*\n\n"
        "Tap the button below to chat with us:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Contact Us", url=SUPPORT_URL)]]
        )
    )


async def handle_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle contact information"""
    await update.message.reply_text(
        "📩 *Contact Us:*\n\n"
        "📧 web3kaiju@gmail.com\n"
        "🔗 X: https://x.com/web3kaiju\n"
        "📱 Telegram: https://t.me/web3kaijun\n"
        "📞 WhatsApp: https://wa.me/+2347043031993",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel action"""
    context.user_data.pop("awaiting_post", None)
    await update.message.reply_text("Back to main menu.", reply_markup=main_kbd(update.effective_user.id))

# ─────────────────────────── MAIN ────────────────────────────


def main():
    """Start the bot"""
    app = ApplicationBuilder().token(API_KEY).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check_twitter", check_twitter_connection))
    app.add_handler(CommandHandler("review", review_posts))
    app.add_handler(CommandHandler("connect", connect_twitter))
    app.add_handler(CommandHandler("check_connection", check_connection))
    # Callback handlers
    app.add_handler(CallbackQueryHandler(
        handle_callback_buttons, pattern=r"^confirm_twitter\|"))
    app.add_handler(CallbackQueryHandler(
        admin_callback, pattern=r"^(approve|reject)\|"))
    app.add_handler(CallbackQueryHandler(
        handle_raid_participation, pattern=r"^done\|"))

    # Message handler
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_message_buttons))

    # Background jobs
    run_background_jobs()

    logger.info("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
