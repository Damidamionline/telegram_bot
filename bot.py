import os
import re
import logging
from datetime import datetime, timedelta
import pytz

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters, PicklePersistence
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

from db import (
    add_user, get_user, get_user_slots, get_user_stats,
    save_post, is_user_banned, is_valid_tweet_link,
    is_in_cooldown, update_last_post_time, get_pending_posts,
    set_post_status, deduct_slot_by_admin,
    get_recent_approved_posts, has_completed_post,
    get_post_link_by_id, get_post_owner_id,
    mark_post_completed, create_verification,
    get_verifications_for_post, close_verification,
    expire_old_posts, ban_unresponsive_post_owners,
    auto_approve_stale_posts, set_twitter_handle,
    get_user_active_posts
)

load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

API_KEY = os.getenv("TELEGRAM_TOKEN")
REQUIRED_GROUP = "@telemtsa"
SUPPORT_URL = "https://t.me/web3kaijun"
ADMINS = [6229232611]
GROUP_ID = -1002828603829  # for daily reminders

# ─── Keyboards ──────────────────────────────────────────


def main_kbd(user_id=None):
    kb = [
        ["🔥 Ongoing Raids"],
        ["🎯 Slots", "📤 Post", "📨 Invite Friends"],
        ["🎧 Support", "📱 Contacts", "👤 Profile"],
        ["📊 My Ongoing Raids"]
    ]
    if user_id in ADMINS:
        kb.append(["🛠️ Review Posts", "📊 Stats"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def cancel_kbd():
    return ReplyKeyboardMarkup([["🚫 Cancel"]], resize_keyboard=True)

# ─── Background Jobs ───────────────────────────────────


def run_background_jobs(app):
    sched = BackgroundScheduler(timezone=pytz.utc)
    sched.add_job(expire_old_posts, 'interval', hours=1,
                  next_run_time=datetime.utcnow() + timedelta(minutes=1))
    sched.add_job(ban_unresponsive_post_owners, 'interval', hours=1,
                  next_run_time=datetime.utcnow() + timedelta(minutes=2))
    sched.add_job(auto_approve_stale_posts, 'interval', minutes=10,
                  next_run_time=datetime.utcnow() + timedelta(minutes=3))
    # daily reminder
    sched.add_job(
        lambda: app.bot.send_message(
            chat_id=GROUP_ID,
            text="📢 Daily Reminder: Don’t forget to complete your raids and submit your posts!"
        ),
        CronTrigger(hour=10, minute=0, timezone='Africa/Lagos')
    )
    sched.start()
    logger.info("🕒 Background jobs started.")

# ─── /start ─────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref_by = int(args[0]) if args and args[0].isdigit() else None

    # enforce group join
    try:
        mem = await context.bot.get_chat_member(REQUIRED_GROUP, user.id)
        if mem.status not in ("member", "administrator", "creator"):
            raise
    except:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Join Beta Group",
                                  url="https://t.me/telemtsa")],
            [InlineKeyboardButton("✅ Done", callback_data="check_join")]
        ])
        return await update.message.reply_text(
            "🚀 Please join our beta group to continue.", reply_markup=kb
        )

    added = add_user(user.id, user.full_name, ref_by)
    msg = (
        f"👋 Welcome {user.first_name}! Beta testers get *2 free slots*.\n"
        f"🔗 Referral: `https://t.me/{context.bot.username}?start={user.id}`"
    ) if added else f"👋 Welcome back! Your link: `https://t.me/{context.bot.username}?start={user.id}`"

    await update.message.reply_text(msg, parse_mode="Markdown")
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.message.reply_text("🔘 Choose an option:", reply_markup=main_kbd(user.id))

# ─── /post command ───────────────────────────────────────


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_post"] = True
    await update.message.reply_text(
        "📤 Please paste your Twitter/X post link for review:",
        reply_markup=cancel_kbd()
    )

# ─── Message & Button Router ────────────────────────────


async def handle_message_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    user = update.effective_user

    # 1) If we're waiting for a post link, handle it first
    if context.user_data.get("awaiting_post"):
        await handle_post_submission(update, context)
        return

    # 2) Other menu buttons
    if txt == "🔥 Ongoing Raids":
        await handle_ongoing_raids(update, context)
    elif txt == "🎯 Slots":
        await handle_slots(update, context)
    elif txt == "📤 Post":
        await post_command(update, context)
    elif txt == "📨 Invite Friends":
        await handle_referrals(update, context)
    elif txt == "🎧 Support":
        await handle_support(update, context)
    elif txt == "📱 Contacts":
        await handle_contacts(update, context)
    elif txt == "🛠️ Review Posts":
        await review_posts(update, context)
    elif txt == "🚫 Cancel":
        context.user_data.pop("awaiting_post", None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_kbd(user.id))
    elif txt == "👤 Profile":
        await handle_profile(update, context)
    elif txt == "📊 Stats":
        await handle_stats_backup(update, context)
    else:
        await update.message.reply_text(
            "❓ I didn’t understand that. Choose an option:",
            reply_markup=main_kbd(user.id)
        )

# ─── handle_post_submission ─────────────────────────────


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin Approve / Reject buttons."""
    query = update.callback_query
    await query.answer()  # Acknowledge callback

    data = query.data  # e.g. "approve_123" or "reject_123"
    action, post_id_str = data.split("_", 1)
    post_id = int(post_id_str)

    if action == "approve":
        set_post_status(post_id, approved=True)
        await query.edit_message_text(f"✅ Post #{post_id} approved.")
    else:
        set_post_status(post_id, approved=False)
        await query.edit_message_text(f"❌ Post #{post_id} rejected.")

    # (Optionally notify the post owner here)


async def handle_post_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    # cancel flow
    if text == "🚫 Cancel":
        context.user_data.pop("awaiting_post", None)
        return await update.message.reply_text("❌ Submission cancelled.", reply_markup=main_kbd(user.id))

    # banned?
    if is_user_banned(user.id):
        return await update.message.reply_text(
            "⛔ You are banned from posting for 48h.", parse_mode="Markdown"
        )

    # validate link
    if not is_valid_tweet_link(text):
        return await update.message.reply_text(
            "❌ Invalid link. Only twitter.com or x.com/status/… allowed."
        )

    # cooldown
    cooldown, remaining = is_in_cooldown(user.id, 12)
    if cooldown:
        return await update.message.reply_text(
            f"⏳ Wait {remaining} before posting again."
        )

    # save
    chat = update.effective_chat
    gid = chat.id if chat.type in ("group", "supergroup") else None
    save_post(user.id, text, group_id=gid)
    update_last_post_time(user.id)
    context.user_data.pop("awaiting_post", None)

    await update.message.reply_text(
        "✅ Your post is submitted for review!", reply_markup=main_kbd(user.id)
    )
    for aid in ADMINS:
        await context.bot.send_message(
            aid, f"📬 New post from *{user.full_name}*:\n{text}",
            parse_mode="Markdown"
        )

# ─── (Other handlers: ongoing_raids, slots, referrals, support, contacts,
#      review_posts, admin_callbacks, raid_participation, view_responses, profile, stats, etc.)
#      — keep these as you had them, just ensure they’re all registered below.

# ─── Main Setup ──────────────────────────────────────────


def main():
    persistence = PicklePersistence(filepath="bot_data.pkl")
    app = ApplicationBuilder().token(API_KEY).persistence(persistence).build()

    # background jobs
    run_background_jobs(app)

    # callbacks
    app.add_handler(CallbackQueryHandler(
        admin_callback,      pattern=r"^(approve|reject)\|"))
    app.add_handler(CallbackQueryHandler(
        handle_raid_participation, pattern=r"^done\|"))
    app.add_handler(CallbackQueryHandler(handle_callback_buttons))

    # commands
    app.add_handler(CommandHandler("start",           start))
    app.add_handler(CommandHandler("post",            post_command))
    app.add_handler(CommandHandler("slots",           handle_slots))
    app.add_handler(CommandHandler("profile",         handle_profile))
    app.add_handler(CommandHandler("referrals",       handle_referrals))
    app.add_handler(CommandHandler("support",         handle_support))
    app.add_handler(CommandHandler("contacts",        handle_contacts))
    app.add_handler(CommandHandler("review",          review_posts))
    app.add_handler(CommandHandler("ongoing_raids",   handle_ongoing_raids))
    app.add_handler(CommandHandler("my_raids",        handle_my_ongoing_raids))
    app.add_handler(CommandHandler("stats",           handle_stats_backup))

    # text buttons (private only)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message_buttons
    ))

    logger.info("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
