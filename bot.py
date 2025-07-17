import os
import re
import pytz
import logging
from datetime import datetime, timedelta, timezone
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton
)
from telegram.constants import ChatType
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from functools import partial
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from db import (
    get_recent_approved_posts, get_user_stats,
    add_user, get_user, get_user_slots, save_post, get_pending_posts,
    set_post_status, deduct_slot_by_admin, expire_old_posts, set_twitter_handle,
    get_post_link_by_id, has_completed_post, mark_post_completed, add_task_slot,
    expire_old_posts, ban_unresponsive_post_owners, is_user_banned, create_verification,
    mark_post_completed, get_post_owner_id, create_verification, mark_post_completed,
    close_verification, auto_approve_stale_posts, is_in_cooldown, get_user_active_posts,
    get_verifications_for_post, update_last_post_time,

)
from apscheduler.triggers.cron import CronTrigger
# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
API_KEY = os.getenv("TELEGRAM_TOKEN")
CHANNEL_URL = "https://t.me/Damitechinfo"
REQUIRED_GROUP = "@telemtsa"
SUPPORT_URL = "https://t.me/web3kaijun"
ADMINS = [6229232611]  # Telegram IDs of admins
GROUP_ID = -1002828603829

# ──────────────────────── UTILITIES ─────────────────────────


def run_background_jobs():
    """Runs hourly jobs for expiring posts and banning unresponsive users."""
    scheduler = BackgroundScheduler(timezone=pytz.utc)

    scheduler.add_job(
        func=expire_old_posts,
        trigger="interval",
        hours=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1)


    )

    scheduler.add_job(
        func=ban_unresponsive_post_owners,
        trigger="interval",
        hours=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2)


    )

    scheduler.add_job(
        partial(auto_approve_stale_posts),
        "interval",
        minutes=10,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3)
    )

    # DAILY REMINDER AT 10 AM
    scheduler.add_job(
        lambda: application.bot.send_message(
            chat_id=GROUP_ID,
            text="📢 Daily Reminder: Don’t forget to complete your raids and submit your posts!"
        ),
        trigger=CronTrigger(hour=10, minute=0, timezone='Africa/Lagos')
    )

    scheduler.start()
    logger.info("🕒 Background jobs started.")


def extract_tweet_id(url: str) -> str | None:
    """
    Extract tweet ID from a Twitter or X.com link.
    Supports both twitter.com and x.com formats.
    """
    match = re.search(r"(twitter\.com|x\.com)/\w+/status/(\d+)", url)
    if match:
        return match.group(2)
    return None

# Main menu keyboard


def is_valid_tweet_link(url: str) -> bool:
    """Check if a URL is a valid Twitter/X status link"""
    return bool(re.search(r"(twitter\.com|x\.com)/\w+/status/\d+", url))


def main_kbd(user_id: int | None = None) -> ReplyKeyboardMarkup:
    """Main keyboard layout"""
    keyboard = [
        ["🔥 Ongoing Raids"],
        ["🎯 Slots", "📤 Post", "📨 Invite Friends"],
        ["🎧 Support", "📱 Contacts", "👤 Profile"],
        ["📊 My Ongoing Raids"]

    ]
    if user_id in ADMINS:
        keyboard.append(["🛠️ Review Posts", "📊 Stats"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def cancel_kbd() -> ReplyKeyboardMarkup:
    """Cancel action keyboard"""
    return ReplyKeyboardMarkup([["🚫 Cancel"]], resize_keyboard=True)


async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        text="🔔 *Daily Reminder*\n\nDon't forget to complete your raids, submit your posts, and earn engagement slots today! 💰",
        parse_mode="Markdown"
    )

# ────────────────────────── COMMANDS ────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref_by = int(args[0]) if args and args[0].isdigit() else None

    # Enforce group join
    try:
        member = await context.bot.get_chat_member(REQUIRED_GROUP, user.id)
        if member.status not in ("member", "administrator", "creator"):
            raise Exception("Not a member")
    except:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Join Beta Group",
                                  url="https://t.me/telemtsa")],
            [InlineKeyboardButton("✅ Done", callback_data="check_join")]
        ])
        await update.message.reply_text(
            "🚀 *Welcome to the Beta Test of this bot*\n\n"
            "To start using this bot, please join our *beta testing group* first.",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # Register the user
    added = add_user(user.id, user.full_name, ref_by)

    # Welcome message
    welcome = (
        f"👋 *Welcome {user.first_name} to the Web3 Raid Bot (Beta)!*\n\n"
        "Here’s what you can do:\n"
        "• 📤 Submit your Twitter/X posts for engagement (costs 1 slot)\n"
        "• ✅ Join other users' raids to earn 0.1 slots per raid\n"
        "• 📨 Invite friends to earn 0.2 slots each\n"
        "• 👤 View your profile: slot stats, referrals, and Twitter handle\n"
        "• 🧠 Manual verification system ensures fairness\n\n"
        "Beta testers get *2 free slots* and early access to all features!\n\n"
        f"🔗 Your referral link:\n`https://t.me/{context.bot.username}?start={user.id}`"
    ) if added else (
        f"*Welcome back, {user.first_name}!* 👋\n\n"
        "Here's your referral link again 🔗\n\n"
        f"`https://t.me/{context.bot.username}?start={user.id}`"
    )
    print(update.effective_chat.id)

    await update.message.reply_text(welcome, parse_mode="Markdown")
    if update.message.chat.type == ChatType.PRIVATE:
        await update.message.reply_text("🔘 Choose an option:", reply_markup=main_kbd(user.id))


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
            # Go back to main menu
            await context.bot.send_message(
                chat_id=user.id,
                text="🔘 You're now connected! Choose an option:",
                reply_markup=main_kbd(user.id)
            )
            context.user_data.pop("awaiting_twitter", None)  # Clean up state
        else:
            await query.edit_message_text(
                f"❌ The handle @`{handle}` is already in use by another user.\n"
                "Please send a different Twitter handle.",
                parse_mode="Markdown"
            )
            context.user_data["awaiting_twitter"] = True

    elif data.startswith("vconfirm|"):
        _, post_id_str, doer_id_str = data.split("|")
        post_id = int(post_id_str)
        doer_id = int(doer_id_str)

        # Grant reward and close verification
        add_task_slot(doer_id, 0.1)
        close_verification(post_id, doer_id)
        await context.bot.send_message(
            chat_id=doer_id,
            text="✅ Your raid was confirmed! You've earned 0.1 slots."
        )
        await query.edit_message_text("🟢 You confirmed the raid as successful.")

    elif data.startswith("responses|"):
        await handle_view_responses(update, context)

    elif data.startswith("vreject|"):
        _, post_id_str, doer_id_str = data.split("|")
        post_id = int(post_id_str)
        doer_id = int(doer_id_str)

        close_verification(post_id, doer_id)
        await context.bot.send_message(
            chat_id=doer_id,
            text="❌ Your raid was rejected by the post owner. No slots awarded."
        )
        await query.edit_message_text("🔴 You rejected the raid.")

    elif data == "check_join":
        try:
            member = await context.bot.get_chat_member(REQUIRED_GROUP, user.id)
            if member.status in ("member", "administrator", "creator"):
                await query.edit_message_text("✅ You're in! Please click /start again to continue.")
            else:
                await query.edit_message_text("🚫 You haven't joined the group yet click /start to retry.")
        except:
            await query.edit_message_text("❌ Couldn't verify. Try again later.")


async def handle_my_ongoing_raids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    approved_posts = get_user_active_posts(
        user.id)  # You’ll create this in db.py

    if not approved_posts:
        await update.message.reply_text("📭 You don’t have any active raids at the moment.")
        return

    for post in approved_posts:
        post_id, post_link, approved_at = post
        expires_at = datetime.fromisoformat(approved_at) + timedelta(hours=24)
        time_left = expires_at - datetime.utcnow()
        hours, minutes = divmod(int(time_left.total_seconds() // 60), 60)

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👥 View Responses",
                                 callback_data=f"responses|{post_id}")
        ]])

        await update.message.reply_text(
            f"🧵 *Your Raid*\n🔗 {post_link}\n⏳ Time left: {hours}h {minutes}m",
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )


async def handle_raid_participation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle raid completion and ask post owner for confirmation (no API check)"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    post_id = int(query.data.split("|")[1])

    user_data = get_user(user.id)
    if not user_data:
        await query.edit_message_text("❌ You need to /start first.")
        return

    if not user_data.get("twitter_handle"):
        await query.edit_message_text("❌ You need to send your Twitter handle first.")
        return

    if has_completed_post(user.id, post_id):
        await query.edit_message_text("✅ You've already submitted this raid.")
        return

    tweet_link = get_post_link_by_id(post_id)

    if not tweet_link or not ("twitter.com" in tweet_link or "x.com" in tweet_link):
        await query.edit_message_text("❌ Invalid tweet link. It must be from Twitter or X.")
        return

    tweet_id = extract_tweet_id(tweet_link)
    if not tweet_id:
        await query.edit_message_text("❌ Unable to extract tweet ID. Make sure it's a full link.")
        return

    post_owner = get_post_owner_id(post_id)
    if not post_owner:
        await query.edit_message_text("⚠️ Could not find the post owner.")
        return

    if post_owner == user.id:
        await query.edit_message_text("❌ You cannot participate in your own raid.")
        return

    # Mark the post as completed (pending confirmation)
    mark_post_completed(user.id, post_id)

    # Create a verification entry for manual confirmation
    create_verification(post_id, user.id, post_owner)
    twitter_handle = user_data.get("twitter_handle", "N/A")
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    naija_time = datetime.now(pytz.timezone(
        "Africa/Lagos")).strftime("%Y-%m-%d %I:%M %p")
    # Notify the post owner for approval

    verifications = get_verifications_for_post(post_id)
    status = None
    for v in verifications:
        if v[0] == user.id:  # v[0] = doer_id
            status = v[3]    # v[3] = status (confirmed/rejected/pending)
            break

    # Decide buttons
    buttons = []
    if status == "pending":
        buttons = [[
            InlineKeyboardButton(
                "✅ Confirm", callback_data=f"vconfirm|{post_id}|{user.id}"),
            InlineKeyboardButton(
                "❌ Reject", callback_data=f"vreject|{post_id}|{user.id}")
        ]]

    await context.bot.send_message(
        chat_id=post_owner,
        text=(
            f"📣 {user.username or user.full_name} says they've completed your raid:\n"
            f"🔗 {tweet_link}\n"
            f"🐦 Twitter: @{twitter_handle}\n\n"
            f"🕒 Submitted: {timestamp}\n\n"
            f"🕒 Submitted: {naija_time} (Nigerian Time)\n\n"
            f"{'Do you confirm this?' if buttons else '✅ Already reviewed.'}"
        ),
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )

    await query.edit_message_text("✅ Raid submitted. Waiting for the post owner to confirm.")


async def handle_view_responses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    post_id = int(query.data.split("|")[1])
    verifications = get_verifications_for_post(post_id)  # define this in db.py

    if not verifications:
        await query.edit_message_text("📭 No responses for this raid yet.")
        return

    for v in verifications:
        doer_id, raider_username, raider_handle, status = v
        name = f"{raider_username}\n\n" if raider_username else f"User {doer_id}"
        handle = f"X: (@{raider_handle})" if raider_handle else ""
        label = f"{name} {handle} — Status: {status or 'Pending'}"

        # Only show buttons if still pending
        if status == "pending":
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ Confirm", callback_data=f"vconfirm|{post_id}|{doer_id}"),
                InlineKeyboardButton(
                    "❌ Reject", callback_data=f"vreject|{post_id}|{doer_id}")
            ]])
        else:
            keyboard = None  # No buttons for confirmed/rejected

        await query.message.reply_text(label, reply_markup=keyboard)


# ────────────────────────── MESSAGE HANDLERS ─────────────────


async def handle_message_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    txt = update.message.text.strip()
    user = update.effective_user

    if context.user_data.get("awaiting_twitter"):
        if txt == "🚫 Cancel":
            context.user_data["awaiting_twitter"] = False
            await update.message.reply_text(
                "🚫 Twitter handle setup cancelled.",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text(
                "🔙 Back to main menu.",
                reply_markup=main_kbd(user.id)
            )
            return

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
        context.user_data["awaiting_post"] = True
        await update.message.reply_text(
            "📤 *Submit your Twitter/X post link for review:*\n\n"
            "🔗 Please paste a *valid Twitter (twitter.com) or X (x.com) post link* below.\n"
            "Example: https://x.com/Web3Kaiju/status/1901622919777652813",
            parse_mode="Markdown",
            reply_markup=cancel_kbd()
        )

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

    elif context.user_data.get("awaiting_post"):
        await handle_post_submission(update, context)

    elif txt == "👤 Profile":
        await handle_profile(update, context)

    elif txt == "📊 Stats":
        await handle_stats_backup(update, context)

    else:
        # Catch-all for unrecognized inputs
        context.user_data["awaiting_post"] = False  # Optional safety
        await update.message.reply_text(
            "❓ I didn't understand that. Choose an option:",
            reply_markup=main_kbd(user.id)
        )


# ──────────────────────── HANDLER HELPERS ────────────────────


async def handle_ongoing_raids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle ongoing raids display"""
    user = update.effective_user
    chat = update.effective_chat
    user_data = get_user(user.id)

    if not user_data:
        await update.message.reply_text(
            f"👋 @{user.username or user.first_name}, please start the bot in private:\n"
            f"https://t.me/{context.bot.username}?start={user.id}"
        )
        return

    # If user hasn't set Twitter handle
    if not user_data.get("twitter_handle"):
        if chat.type != "private":
            # Send message in group telling user to go to DM
            await update.message.reply_text(
                f"❗️@{user.username or user.first_name}, to join raids, please message the bot privately first:\n"
                f"👉 [Click here to set your Twitter handle](https://t.me/{context.bot.username}?start={user.id})\n\n"
                f"Then tap *🔥 Ongoing Raids* to continue.",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            return
        else:
            # Ask for handle in private chat
            context.user_data["awaiting_twitter"] = True
            await update.message.reply_text(
                "📮 Please send your Twitter handle (e.g., `@username`).",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardMarkup(
                    [["🚫 Cancel"]], resize_keyboard=True
                )
            )
            return

    # Continue with showing raids
    group_id = chat.id if chat.type in ("group", "supergroup") else None
    posts = get_recent_approved_posts(group_id=group_id, with_time=True)

    if not posts:
        await update.message.reply_text("🚫 No active raids in the last 24 hours.")
    else:
        for post_id, post_link, name, approved_at_str in posts:
            approved_at = datetime.fromisoformat(approved_at_str)
            expires_at = approved_at + timedelta(hours=24)
            now = datetime.utcnow()
            time_left = expires_at - now

            hours_left = int(time_left.total_seconds() // 3600)
            minutes_left = int((time_left.total_seconds() % 3600) // 60)
            time_left_str = f"{hours_left}h {minutes_left}m left"

            if has_completed_post(user.id, post_id):
                status = "✅ You’ve already joined this raid."
                keyboard = None
            else:
                status = "❌ You haven’t joined this raid yet."
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "✅ Done", callback_data=f"done|{post_id}")]
                ])

            await update.message.reply_text(
                f"🔥 *New Raid by {name}*\n"
                f"🔗 {post_link}\n\n"
                f"{status}\n🕒 *Time Left:* {time_left_str}",
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
    user = update.effective_user
    user_data = get_user(user.id)

    # 🔒 Check if user is banned from posting
    if is_user_banned(user.id):
        await update.message.reply_text(
            "⛔ You are temporarily banned from posting due to unverified raids.\n"
            "📆 You can post again after 48 hours.",
            parse_mode="Markdown"
        )
        return

    # 📨 User is submitting a tweet link
    text = update.message.text.strip()

    # 🔗 Validate tweet link
    if not is_valid_tweet_link(text):
        await update.message.reply_text(
            "❌ Invalid tweet link. Only links from *twitter.com* or *x.com* are allowed.\n"
            "Please send a valid Twitter/X post link:",
            parse_mode="Markdown"
        )
        return

    # ⏳ Check 12-hour cooldown
    cooldown_hours = 12
    in_cooldown, remaining = is_in_cooldown(user.id, cooldown_hours)
    if in_cooldown:
        await update.message.reply_text(
            f"⏳ You can only submit one post every {cooldown_hours} hours.\n"
            f"🕒 Please wait {remaining} more before submitting again."
        )
        return

    # 💾 Save the post
    chat = update.effective_chat
    group_id = chat.id if chat.type in ("group", "supergroup") else None
    save_post(user.id, text, group_id=group_id)
    update_last_post_time(user.id)
    context.user_data["awaiting_post"] = False

    # ✅ Notify user
    await update.message.reply_text(
        "✅ Your post has been submitted for review. You'll be notified when it's approved.",
        reply_markup=main_kbd(user.id),
    )

    # 📢 Notify admins
    name = user.full_name
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📬 New post submitted by *{name}*:\n{text}",
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"[ADMIN NOTIFY ERROR] Admin ID: {admin_id} - {e}")


async def post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_post"] = True
    await update.message.reply_text("📨 Please send the Twitter/X post link you'd like to submit.")

    # First-time call to /post or menu button
    await update.message.reply_text(
        "📤 *Submit your Twitter/X post link for review:*\n\n"
        "🔗 Please paste a *valid Twitter (twitter.com) or X (x.com) post link* below.\n"
        "Example: https://x.com/Web3Kaiju/status/1901622919777652813",
        parse_mode="Markdown",
        reply_markup=cancel_kbd()
    )
    context.user_data["awaiting_post"] = True


async def handle_stats_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send raw DB file to admin."""
    user = update.effective_user
    if user.id not in ADMINS:
        return

    db_path = "bot_data.db"  # or your actual DB file path

    if not os.path.exists(db_path):
        await update.message.reply_text("❌ Database file not found.")
        return

    await update.message.reply_document(
        document=open(db_path, "rb"),
        filename="bot_data_backup.db",
        caption="📦 Here is the current bot_data.db backup.\nYou can restore it after redeploying.",
    )


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
        "🎯 Invite others and earn *0.2 engagement slot* per referral!\n\n"
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


async def has_joined_required_group(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(REQUIRED_GROUP, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if not data.startswith("v|"):
        return

    _, post_id_str = data.split("|")
    post_id = int(post_id_str)
    telegram_id = query.from_user.id

    # Check if user already completed this post
    if has_completed_post(telegram_id, post_id):
        await query.edit_message_text("❗️You've already completed this raid.")
        return

    # Get post info
    post = get_post(post_id)
    if not post:
        await query.edit_message_text("❗️This post no longer exists.")
        return

    tweet_url = post[2]
    tweet_id = tweet_url.split("/")[-1]

    # Get user token from DB
    user = get_user(telegram_id)
    access_token = user.get("twitter_access_token")
    if not access_token:
        await query.edit_message_text("❗️Your Twitter account is not connected.")
        return


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel action"""
    context.user_data.pop("awaiting_post", None)
    await update.message.reply_text("Back to main menu.", reply_markup=main_kbd(update.effective_user.id))

# ─────────────────────────── MAIN ────────────────────────────


def main():
    """Start the bot"""
    app = ApplicationBuilder().token(API_KEY).build()

    run_background_jobs()

    # ─────────────── CALLBACK HANDLERS ───────────────
    app.add_handler(CallbackQueryHandler(
        handle_callback_buttons, pattern=r"^(confirm_twitter|responses|vconfirm|vreject)\|"))
    app.add_handler(CallbackQueryHandler(
        handle_raid_participation, pattern=r"^done\|"))
    app.add_handler(CallbackQueryHandler(
        admin_callback, pattern=r"^(approve|reject)\|"))
    app.add_handler(CallbackQueryHandler(
        handle_callback_buttons))  # catch-all fallback

    # ─────────────── COMMAND HANDLERS (group + private) ───────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("review", review_posts))
    app.add_handler(CommandHandler("slots", handle_slots))
    app.add_handler(CommandHandler("profile", handle_profile))
    app.add_handler(CommandHandler("post", handle_post_submission))
    app.add_handler(CommandHandler("referrals", handle_referrals))
    app.add_handler(CommandHandler("support", handle_support))
    app.add_handler(CommandHandler("contacts", handle_contacts))
    app.add_handler(CommandHandler("ongoing_raids", handle_ongoing_raids))
    app.add_handler(CommandHandler(
        "my_raids", handle_my_ongoing_raids))  # optional

    # ─────────────── TEXT BUTTON HANDLERS (private chats only) ───────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message_buttons
    ))

    logger.info("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
