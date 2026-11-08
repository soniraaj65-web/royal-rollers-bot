import os
import re
import asyncio
import sqlite3
import logging
from datetime import datetime
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "9011260716:AAGYT2mI36SQvqK9aRi2wIdmzXrtBz-NjmE"
ADMINS = ["raj1235567"]
COMMISSION_PERCENT = 10
PORT = int(os.environ.get("PORT", 10000))

PINNED_SHEET_MSG_ID = None

logging.basicConfig(level=logging.INFO)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Royal Rollers Live")

def run_server():
    server = HTTPServer(("0.0.0.0", PORT), SimpleHandler)
    server.serve_forever()

def get_db():
    conn = sqlite3.connect("royal_rollers.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = get_db()
c = db.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    balance REAL DEFAULT 0.0,
    side_balance REAL DEFAULT 0.0,
    in_match INTEGER DEFAULT 0
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_no INTEGER,
    host_id INTEGER,
    host_name TEXT,
    opp_id INTEGER,
    opp_name TEXT,
    amount REAL,
    condition TEXT,
    status TEXT,
    table_msg_id INTEGER,
    estimate_msg_id INTEGER,
    chat_id INTEGER
)
""")
c.execute("""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    val INTEGER
)
""")
c.execute("INSERT OR IGNORE INTO meta (key, val) VALUES ('table_counter', 0)")
db.commit()

def get_next_counter(key_name):
    c.execute("SELECT val FROM meta WHERE key = ?", (key_name,))
    row = c.fetchone()
    current = row["val"] if row else 0
    nxt = current + 1
    c.execute("INSERT OR REPLACE INTO meta (key, val) VALUES (?, ?)", (key_name, nxt))
    db.commit()
    return nxt

def get_or_create_user(user):
    uid = user.id
    uname = (user.username or "").lower().replace("@", "")
    fname = user.first_name or "Player"

    c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id, username, name, balance, side_balance, in_match) VALUES (?, ?, ?, 0.0, 0.0, 0)",
                  (uid, uname, fname))
        db.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        row = c.fetchone()
    else:
        c.execute("UPDATE users SET username = ?, name = ? WHERE user_id = ?", (uname, fname, uid))
        db.commit()
    return row

def get_or_create_by_username(uname_raw):
    clean = uname_raw.lower().replace("@", "").strip()
    c.execute("SELECT * FROM users WHERE LOWER(username) = ?", (clean,))
    row = c.fetchone()
    if row:
        return row
    dummy_uid = abs(hash(clean)) % (10**9)
    c.execute("INSERT INTO users (user_id, username, name, balance, side_balance, in_match) VALUES (?, ?, ?, 0.0, 0.0, 0)",
              (dummy_uid, clean, clean))
    db.commit()
    c.execute("SELECT * FROM users WHERE user_id = ?", (dummy_uid,))
    return c.fetchone()

def update_bal(user_id, new_bal):
    c.execute("UPDATE users SET balance = ? WHERE user_id = ?", (float(new_bal), user_id))
    db.commit()

def parse_amount_and_condition(text):
    if not text:
        return None, "full"
    
    match = re.search(r"(\d+(?:\.\d+)?\s*k|\d+(?:\.\d+)?)(.*)", text, re.IGNORECASE)
    if not match:
        return None, "full"
    
    amt_raw = match.group(1).strip().lower()
    rem = match.group(2).strip()
    
    if "k" in amt_raw:
        amt = float(amt_raw.replace("k", "")) * 1000.0
    else:
        amt = float(amt_raw)
        
    cond = rem if rem else "full"
    cond = re.sub(r"^([✅\-\:\s]+)", "", cond).strip()
    if not cond:
        cond = "full"
    return amt, cond

def format_mention(user_row):
    uname = user_row["username"]
    if uname:
        return f"@{uname.replace('@', '')}"
    safe_name = (user_row["name"] or "Player").replace("<", "&lt;").replace(">", "&gt;")
    return f'<a href="tg://user?id={user_row["user_id"]}">{safe_name}</a>'

async def safe_delete(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id):
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

async def delayed_delete(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, delay=60):
    await asyncio.sleep(delay)
    await safe_delete(context, chat_id, message_id)

def generate_sheet():
    c.execute("SELECT name, username, balance FROM users WHERE balance != 0 ORDER BY balance DESC")
    rows = c.fetchall()
    c.execute("SELECT COUNT(*) as live FROM games WHERE status = 'PLAYING'")
    live_count = c.fetchone()["live"]
    now_time = datetime.now().strftime("%I:%M %p")

    text = "👑 ♛ 𝐑𝐎𝐘𝐀𝐋 𝐑𝐎𝐋𝐋𝐄𝐑𝐒 ♛ • 𝐋𝐈𝐕𝐄 𝐋𝐄𝐃𝐆𝐄𝐑 👑\n"
    text += "──────────────────────────\n"
    text += "📋 Commission & Player Ledger:\n"
    text += "──────────────────────────\n"
    if not rows:
        text += "Sabhi accounts filhal clear hain (₹0.0).\n"
    else:
        for idx, r in enumerate(rows, start=1):
            disp = f"@{r['username']}" if r['username'] else r['name']
            dot = "🟢" if r["balance"] >= 0 else "🔴"
            text += f"{idx:02d}. {dot} {disp}: ₹{r['balance']:.1f}\n"

    text += "──────────────────────────\n"
    text += f"⚔️ Active Tables : {live_count}\n"
    text += f"⏱️ Updated At    : {now_time}\n"
    text += "──────────────────────────\n"
    text += "🔄 Automated Real-Time Settlement Engine"
    return text

async def sync_sheet(chat_id, context: ContextTypes.DEFAULT_TYPE):
    global PINNED_SHEET_MSG_ID
    if PINNED_SHEET_MSG_ID:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=PINNED_SHEET_MSG_ID,
                text=generate_sheet()
            )
        except Exception:
            pass

async def create_table_match(context: ContextTypes.DEFAULT_TYPE, chat_id, u1_row, u2_row, amt, cond_text, clean_ids):
    h_id = u1_row["user_id"]
    o_id = u2_row["user_id"]
    h_bal = float(u1_row["balance"])
    o_bal = float(u2_row["balance"])

    h_disp = format_mention(u1_row)
    o_disp = format_mention(u2_row)

    if h_bal < amt or o_bal < amt:
        h_dot = "🟢" if h_bal >= amt else "🔴"
        o_dot = "🟢" if o_bal >= amt else "🔴"

        fail_card = (
            "🔴 Failed because one of the users would have a balance below the minimum threshold (0).\n\n"
            f"{h_dot} {h_disp} estimate:\n"
            f"{h_bal:.1f} - {amt:.1f} ➔ {(h_bal - amt):.1f}\n\n"
            f"{o_dot} {o_disp} estimate:\n"
            f"{o_bal:.1f} - {amt:.1f} ➔ {(o_bal - amt):.1f}"
        )
        err = await context.bot.send_message(chat_id=chat_id, text=fail_card, parse_mode=ParseMode.HTML)
        asyncio.create_task(delayed_delete(context, chat_id, err.message_id, 30))
        return

    new_h = h_bal - amt
    new_o = o_bal - amt
    update_bal(h_id, new_h)
    update_bal(o_id, new_o)

    t_num = get_next_counter("table_counter")

    loader = await context.bot.send_message(chat_id=chat_id, text="🎲 Rolling dice . . .")
    await asyncio.sleep(0.4)
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=loader.message_id, text="⏳ Generating Match Slip . . .")
    except Exception:
        pass
    await asyncio.sleep(0.3)

    c.execute("INSERT INTO games (table_no, host_id, host_name, opp_id, opp_name, amount, condition, status, table_msg_id, estimate_msg_id, chat_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'PLAYING', NULL, NULL, ?)",
              (t_num, h_id, h_disp, o_id, o_disp, amt, cond_text, chat_id))
    gid = c.lastrowid
    c.execute("UPDATE users SET in_match = 1 WHERE user_id IN (?, ?)", (h_id, o_id))
    db.commit()

    card1_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Cancel This Table", callback_data=f"cancel:{gid}")],
        [
            InlineKeyboardButton("🏆 #1 Won...", callback_data=f"win1:{gid}"),
            InlineKeyboardButton("🏆 #2 Won...", callback_data=f"win2:{gid}")
        ]
    ])
    amt_str = f"{int(amt)}" if amt.is_integer() else f"{amt:.1f}"
    card1_text = (
        f"🎲 Table No. {t_num}\n\n"
        f"(1). {h_disp}\n\n"
        f"(2). {o_disp}\n\n"
        f"{amt_str} ✅ {cond_text}"
    )

    card2_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Check Estimate", callback_data=f"est:{gid}")]])
    card2_text = (
        f"Action #{t_num} successful! ✅\n\n"
        f"🟢 {h_disp} estimate:\n"
        f"{h_bal:.1f} - {amt:.1f} ➔ {new_h:.1f}\n\n"
        f"🟢 {o_disp} estimate:\n"
        f"{o_bal:.1f} - {amt:.1f} ➔ {new_o:.1f}"
    )

    await safe_delete(context, chat_id, loader.message_id)

    sent1 = await context.bot.send_message(chat_id=chat_id, text=card1_text, reply_markup=card1_kb, parse_mode=ParseMode.HTML)
    sent2 = await context.bot.send_message(chat_id=chat_id, text=card2_text, reply_markup=card2_kb, parse_mode=ParseMode.HTML)

    c.execute("UPDATE games SET table_msg_id = ?, estimate_msg_id = ? WHERE id = ?", (sent1.message_id, sent2.message_id, gid))
    db.commit()

    for mid in clean_ids:
        asyncio.create_task(delayed_delete(context, chat_id, mid, 30))
    await sync_sheet(chat_id, context)

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    user_clean = (user.username or user.first_name or "").lower().replace("@", "")

    if query.data.startswith("details:"):
        uid = int(query.data.split(":")[1])
        c.execute("SELECT * FROM users WHERE user_id = ?", (uid,))
        r = c.fetchone()
        if r:
            disp = f"@{r['username']}" if r['username'] else r['name']
            await query.answer(f"👤 {disp}\n💵 Balance: ₹{r['balance']:.1f}\n⌛ In-Match: {'True' if r['in_match'] else 'False'}", show_alert=True)
        else:
            await query.answer("Record nahi mila!", show_alert=True)
        return

    data = query.data.split(":")
    action, gid = data[0], int(data[1])

    c.execute("SELECT * FROM games WHERE id = ?", (gid,))
    g = c.fetchone()
    if not g:
        await query.answer("Match record nahi mila!", show_alert=True)
        return

    table_no = g["table_no"]
    h_name, o_name = g["host_name"], g["opp_name"]
    amt = float(g["amount"])
    t_msg_id = g["table_msg_id"]
    est_msg_id = g["estimate_msg_id"]

    if action == "est":
        c.execute("SELECT balance FROM users WHERE user_id = ?", (g["host_id"],))
        hb = c.fetchone()["balance"]
        c.execute("SELECT balance FROM users WHERE user_id = ?", (g["opp_id"],))
        ob = c.fetchone()["balance"]
        await query.answer(f"📊 Action #{table_no} Balance:\n\n{h_name}: ₹{hb:.1f}\n{o_name}: ₹{ob:.1f}", show_alert=True)
        return

    try:
        cm = await context.bot.get_chat_member(query.message.chat_id, user.id)
        is_admin = (user_clean in ADMINS) or (cm.status in ["administrator", "creator"])
    except Exception:
        is_admin = user_clean in ADMINS

    if not is_admin:
        await query.answer("❌ Only Admins can settle or cancel!", show_alert=True)
        return

    if g["status"] != "PLAYING":
        await query.answer("⚠️ Match already settled/closed!", show_alert=True)
        return

    if action == "cancel":
        c.execute("SELECT balance FROM users WHERE user_id = ?", (g["host_id"],))
        hb = c.fetchone()["balance"] + amt
        c.execute("SELECT balance FROM users WHERE user_id = ?", (g["opp_id"],))
        ob = c.fetchone()["balance"] + amt
        update_bal(g["host_id"], hb)
        update_bal(g["opp_id"], ob)

        c.execute("UPDATE games SET status = 'CANCELED' WHERE id = ?", (gid,))
        c.execute("UPDATE users SET in_match = 0 WHERE user_id IN (?, ?)", (g["host_id"], g["opp_id"]))
        db.commit()

        await query.edit_message_reply_markup(reply_markup=None)
        if est_msg_id:
            try:
                card2_cancel = (
                    f"Action #{table_no} Canceled & Refunded! 🚫\n\n"
                    f"🟢 {h_name} refund:\n➔ {hb:.1f}\n\n"
                    f"🟢 {o_name} refund:\n➔ {ob:.1f}"
                )
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=est_msg_id, text=card2_cancel, parse_mode=ParseMode.HTML)
            except Exception:
                pass
        await sync_sheet(query.message.chat_id, context)
        await query.answer("Match Canceled!")

        if t_msg_id:
            asyncio.create_task(delayed_delete(context, query.message.chat_id, t_msg_id, 60))
        if est_msg_id:
            asyncio.create_task(delayed_delete(context, query.message.chat_id, est_msg_id, 60))
        return

    if action in ["win1", "win2"]:
        wid = g["host_id"] if action == "win1" else g["opp_id"]
        wname = h_name if action == "win1" else o_name
        tot = amt * 2.0
        win_amt = tot - (tot * (COMMISSION_PERCENT / 100.0))

        c.execute("SELECT balance FROM users WHERE user_id = ?", (wid,))
        wb = c.fetchone()["balance"] + win_amt
        update_bal(wid, wb)

        c.execute("UPDATE games SET status = 'FINISHED' WHERE id = ?", (gid,))
        c.execute("UPDATE users SET in_match = 0 WHERE user_id IN (?, ?)", (g["host_id"], g["opp_id"]))
        db.commit()

        await query.edit_message_reply_markup(reply_markup=None)
        if est_msg_id:
            try:
                card2_settled = (
                    f"Action #{table_no} Settled! 🏆\n\n"
                    f"👑 Winner: {wname}\n"
                    f"Credited: +₹{win_amt:.1f} ➔ ₹{wb:.1f}"
                )
                await context.bot.edit_message_text(chat_id=query.message.chat_id, message_id=est_msg_id, text=card2_settled, parse_mode=ParseMode.HTML)
            except Exception:
                pass

        w_msg = await query.message.reply_text(f"🏆 TABLE #{table_no} WINNER!\n👑 {wname} won ₹{win_amt:.1f} (10% Club Commission Deducted).", parse_mode=ParseMode.HTML)
        await sync_sheet(query.message.chat_id, context)

        asyncio.create_task(delayed_delete(context, query.message.chat_id, w_msg.message_id, 60))
        if t_msg_id:
            asyncio.create_task(delayed_delete(context, query.message.chat_id, t_msg_id, 60))
        if est_msg_id:
            asyncio.create_task(delayed_delete(context, query.message.chat_id, est_msg_id, 60))

        await query.answer("Winner Declared!")
        return

async def photo_cleaner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.photo:
        sender = update.effective_user
        if sender.is_bot or "rose" in (sender.username or "").lower():
            asyncio.create_task(delayed_delete(context, update.effective_chat.id, update.message.message_id, 60))

async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PINNED_SHEET_MSG_ID
    if not update.message or not update.message.text:
        return

    raw = update.message.text.strip()
    text = raw.lower()
    sender = update.effective_user
    chat_id = update.effective_chat.id

    u_self = get_or_create_user(sender)

    sender_clean = (sender.username or sender.first_name or "").lower().replace("@", "")
    try:
        cm = await context.bot.get_chat_member(chat_id, sender.id)
        is_admin = (sender_clean in ADMINS) or (cm.status in ["administrator", "creator"])
    except Exception:
        is_admin = sender_clean in ADMINS

    clean_cmd = text.lstrip("/").strip()

    if clean_cmd in ["bal", "balance", "mybal"]:
        disp = format_mention(u_self)
        status_txt = "Yes" if u_self["in_match"] else "No"
        bal_text = (
            "💳 <b>Account Overview</b> 💳\n"
            "──────────────────────────\n"
            f"🤠 Player  : {disp}\n"
            f"💵 Balance : ₹{float(u_self['balance']):.1f}\n"
            f"⚔️ In Match: {status_txt}\n"
            "──────────────────────────\n"
            "<i>Auto-deleting in 20 seconds...</i>"
        )
        b_msg = await update.message.reply_text(bal_text, parse_mode=ParseMode.HTML)
        asyncio.create_task(delayed_delete(context, chat_id, update.message.message_id, 20))
        asyncio.create_task(delayed_delete(context, chat_id, b_msg.message_id, 20))
        return

    calc_match = re.match(r"^(\d+(?:\.\d+)?)\s*([\+\-\*\/])\s*(\d+(?:\.\d+)?)$", text)
    if calc_match:
        n1, op, n2 = float(calc_match.group(1)), calc_match.group(2), float(calc_match.group(3))
        res = n1 + n2 if op == '+' else n1 - n2 if op == '-' else n1 * n2 if op == '*' else (n1 / n2 if n2 != 0 else 0)
        res_str = f"{int(res)}" if res.is_integer() else f"{res:.2f}"
        msg = await update.message.reply_text(f"{raw} = {res_str}")
        asyncio.create_task(delayed_delete(context, chat_id, msg.message_id, 45))
        return

    if clean_cmd in ["pinsheet", "sheet", "ledger"] and is_admin:
        msg = await update.message.reply_text(generate_sheet())
        try:
            await context.bot.pin_chat_message(chat_id=chat_id, message_id=msg.message_id, disable_notification=True)
            PINNED_SHEET_MSG_ID = msg.message_id
            asyncio.create_task(safe_delete(context, chat_id, update.message.message_id))
        except Exception:
            pass
        return

    add_match = re.match(r"^(?:add|addbal|\+|credit)\s*(\d+(?:\.\d+)?\s*k|\d+)", text)
    if update.message.reply_to_message and add_match and is_admin:
        target = update.message.reply_to_message.from_user
        amt_str = add_match.group(1)
        amt = float(amt_str.replace("k", "")) * 1000.0 if "k" in amt_str else float(amt_str)
        if target and amt:
            u_row = get_or_create_user(target)
            old_bal = float(u_row["balance"])
            new_bal = old_bal + amt
            update_bal(target.id, new_bal)

            t_disp = format_mention(u_row)
            card = f"Balance Added ✅\n\n💵 New Balance: ₹{new_bal:.1f}\n🤠 User: {t_disp}\n\nchanges: {old_bal:.1f} + {amt:.1f}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Full Details", callback_data=f"details:{target.id}")]])
            sent = await update.message.reply_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
            await sync_sheet(chat_id, context)
            asyncio.create_task(delayed_delete(context, chat_id, sent.message_id, 60))
            return

    cut_match = re.match(r"^(?:cut|cutbal|-|debit|w|wd|withdraw|withdrawal|payout)\s*(\d+(?:\.\d+)?\s*k|\d+)", text)
    if update.message.reply_to_message and cut_match and is_admin:
        target = update.message.reply_to_message.from_user
        amt_str = cut_match.group(1)
        amt = float(amt_str.replace("k", "")) * 1000.0 if "k" in amt_str else float(amt_str)
        if target and amt:
            u_row = get_or_create_user(target)
            old_bal = float(u_row["balance"])
            new_bal = old_bal - amt
            update_bal(target.id, new_bal)

            t_disp = format_mention(u_row)
            card = f"Withdrawal Processed 💸\n\n💵 New Balance: ₹{new_bal:.1f}\n🤠 User: {t_disp}\n\nchanges: {old_bal:.1f} - {amt:.1f}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 Full Details", callback_data=f"details:{target.id}")]])
            sent = await update.message.reply_text(card, reply_markup=kb, parse_mode=ParseMode.HTML)
            await sync_sheet(chat_id, context)
            asyncio.create_task(delayed_delete(context, chat_id, sent.message_id, 60))
            return

    mentions = re.findall(r"@([a-zA-Z0-9_]+)", raw)
    cleaned_line = re.sub(r"@[a-zA-Z0-9_]+", "", raw).strip()
    amt, cond = parse_amount_and_condition(cleaned_line)

    if is_admin and len(mentions) >= 2 and amt and amt >= 10.0:
        u1 = get_or_create_by_username(mentions[0])
        u2 = get_or_create_by_username(mentions[1])
        if u1["user_id"] != u2["user_id"]:
            await create_table_match(context, chat_id, u1, u2, amt, cond, [update.message.message_id])
            return

    if is_admin and update.message.reply_to_message:
        replied = update.message.reply_to_message
        r_amt, r_cond = parse_amount_and_condition(replied.text or "")
        final_amt = amt if amt else r_amt
        final_cond = cond if cond != "full" else r_cond

        if final_amt and final_amt >= 10.0 and replied.reply_to_message:
            u1 = get_or_create_user(replied.reply_to_message.from_user)
            u2 = get_or_create_user(replied.from_user)
            if u1["user_id"] != u2["user_id"]:
                clean = [update.message.message_id, replied.message_id, replied.reply_to_message.message_id]
                await create_table_match(context, chat_id, u1, u2, final_amt, final_cond, clean)
                return

def main():
    Thread(target=run_server, daemon=True).start()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, photo_cleaner))
    app.add_handler(MessageHandler(filters.TEXT, router))
    logging.info("Royal Rollers Engine Live!")
    app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
