import random
import os
import sqlite3
from dotenv import load_dotenv
from flask import Flask, send_file
import threading

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Load environment variables
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

ESCROW_GROUP_ID = -1003775971340
ESCROW_UPI = os.getenv("ESCROW_UPI")

# Database setup
conn = sqlite3.connect("escrow.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS deals(
deal_id TEXT PRIMARY KEY,
buyer TEXT,
seller TEXT,
item TEXT,
amount TEXT,
status TEXT,
message_id INTEGER
)
""")

conn.commit()

# Conversation states
SELLER, ITEM, AMOUNT = range(3)

users = {}

import uuid

def generate_deal_id():
    return str(uuid.uuid4())[:8]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.message.from_user
    username = user.username

    if username:
        users[username.lower()] = user.id

    keyboard = [
        [
            InlineKeyboardButton("🛒 Buyer", callback_data="role_buyer"),
            InlineKeyboardButton("📦 Seller", callback_data="role_seller")
        ]
    ]

    await update.message.reply_text(
        "Welcome to Escrow Bot\n\nSelect your role:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    role = query.data.split("_")[1]

    if role == "buyer":
        await query.edit_message_text(
            "You selected BUYER\n\nCreate deal using:\n/create"
        )

    else:
        await query.edit_message_text(
            "You selected SELLER\n\nWait for buyer to create deal."
        )


async def create(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Enter Seller Username (@seller)")
    return SELLER


async def seller(update: Update, context: ContextTypes.DEFAULT_TYPE):
    seller_username = update.message.text.replace("@","")
    context.user_data["seller"] = seller_username

    await update.message.reply_text("What are you buying?")
    return ITEM


async def item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["item"] = update.message.text

    await update.message.reply_text("Enter Deal Amount:")
    return AMOUNT


async def amount(update: Update, context: ContextTypes.DEFAULT_TYPE):

    deal_id = generate_deal_id()

    buyer = update.message.from_user.username
    if not buyer:
        await update.message.reply_text(
            "Please set a Telegram username in your profile before creating a deal."
        )
        return ConversationHandler.END

    seller = context.user_data["seller"]
    item = context.user_data["item"]
    amount = update.message.text

    cursor.execute(
        """
        INSERT INTO deals (deal_id,buyer,seller,item,amount,status)
        VALUES (?,?,?,?,?,?)
        """,
        (deal_id,buyer,seller,item,amount,"pending")
    )

    conn.commit()

    summary = f"""
Deal Created

Deal ID: {deal_id}
Buyer: @{buyer}
Seller: @{seller}
Item: {item}
Amount: {amount}

Waiting for seller approval
"""

    await update.message.reply_text(summary)
    await context.bot.send_message(
        chat_id=ESCROW_GROUP_ID,
        text=f"""
    New Escrow Deal Created

    Deal ID: {deal_id}

    Buyer: @{buyer}
    Seller: @{seller}

    Item: {item}
    Amount: ₹{amount}

    Status: Waiting for seller approval
    """
    )

    keyboard = [
        [
            InlineKeyboardButton("Accept", callback_data=f"accept_{deal_id}"),
            InlineKeyboardButton("Reject", callback_data=f"reject_{deal_id}")
        ],
        [
            InlineKeyboardButton("Cancel Deal", callback_data=f"cancel_{deal_id}")
        ]
    ]

    seller_id = users.get(seller.lower())

    if seller_id:
        await context.bot.send_message(
            chat_id=seller_id,
            text=f"""
New Escrow Deal

Deal ID: {deal_id}
Buyer: @{buyer}
Item: {item}
Amount: {amount}
""",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    # Send group invite to buyer and seller
    invite_link = "https://t.me/safe_escrow_deals"

    buyer_id = users.get(buyer)

    if buyer_id:
        await context.bot.send_message(
            chat_id=buyer_id,
            text=f"Join escrow monitoring group:\n{invite_link}"
        )

    if seller_id:
        await context.bot.send_message(
            chat_id=seller_id,
            text=f"Join escrow monitoring group:\n{invite_link}"
        )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"New Deal Created\nDeal ID: {deal_id}"
    )
    tracker = await context.bot.send_message(
        chat_id=ESCROW_GROUP_ID,
        text=f"""
    Deal #{deal_id}

    Buyer: @{buyer}
    Seller: @{seller}
    Item: {item}
    Amount: ₹{amount}

    Status:
    ✔ Deal Created
    ❌ Seller Accepted
    ❌ Payment Sent
    ❌ Item Delivered
    ❌ Completed
    """
    )

    cursor.execute(
        "UPDATE deals SET message_id=? WHERE deal_id=?",
        (tracker.message_id, deal_id)
    )
    conn.commit()

    return ConversationHandler.END


async def seller_response(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[0]
    deal_id = parts[-1]

    if action == "cancel":

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("cancelled", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Deal Cancelled")

        cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
        deal = cursor.fetchone()

        buyer_username = deal[1]
        buyer_id = users.get(buyer_username)

        if buyer_id:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=f"Seller cancelled deal {deal_id}"
            )

        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"Deal {deal_id} cancelled."
        )

        await update_tracker(context, deal_id)

        return

    cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    deal = cursor.fetchone()

    if not deal:
        return

    # 🔒 SECURITY CHECK (ADD HERE)
    if query.from_user.username != deal[2]:
        await query.answer("Only the seller can perform this action.", show_alert=True)
        return

    buyer_username = deal[1]
    buyer_id = users.get(buyer_username)



    buyer_username = deal[1]
    buyer_id = users.get(buyer_username)

    if action == "accept":

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("accepted", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Deal Accepted")

        # Notify buyer
        if buyer_id:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=f"""
Seller accepted the deal.

Deal ID: {deal_id}

Send payment to escrow wallet:

UPI: {ESCROW_UPI}
Amount: ₹{deal[4]}

After payment send screenshot here.
"""
            )

        # Notify group
        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"""
Deal Accepted

Deal ID: {deal_id}
Buyer: @{buyer_username}
Seller: @{deal[2]}

Buyer must now send payment.
"""
        )

    else:

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("rejected", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Deal Rejected")

        if buyer_id:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=f"Seller rejected deal {deal_id}"
            )

    await update_tracker(context, deal_id)


async def admin_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    action, deal_id = query.data.split("_")[1:]

    cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    deal = cursor.fetchone()

    if not deal:
        return

    buyer_id = users.get(deal[1])
    seller_id = users.get(deal[2])
    item = deal[3]

    if action == "paid":

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("paid", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Payment Verified")

        # notify seller
        if seller_id:
            await context.bot.send_message(
                chat_id=seller_id,
                text=f"""
Admin verified payment for deal {deal_id}

Please deliver the {item} to the buyer.
"""
            )

        # notify buyer
        if buyer_id:
            await context.bot.send_message(
                chat_id=buyer_id,
                text=f"""
✅ Payment Verified by Admin

Deal ID: {deal_id}

Seller will now deliver the {item}.
You will be asked to confirm after delivery.
"""
            )

        # notify group
        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"""
Payment Verified by Admin

Deal ID: {deal_id}

Seller should now deliver the {item}.
"""
        )

        # start delayed confirmation timer (3 minutes)
        context.application.create_task(
            delayed_buyer_confirmation(context, buyer_id, deal_id)
        )

    else:

        await query.edit_message_text("Payment Rejected")

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("payment rejected", deal_id)
        )
        conn.commit()

    await update_tracker(context, deal_id)


async def delayed_buyer_confirmation(context, buyer_id, deal_id):

    import asyncio
    await asyncio.sleep(180)   # 3 minutes

    keyboard = [
        [
            InlineKeyboardButton("✅ Yes I received", callback_data=f"buyer_yes_{deal_id}"),
            InlineKeyboardButton("❌ No I did not receive", callback_data=f"buyer_no_{deal_id}")
        ]
    ]

    await context.bot.send_message(
        chat_id=buyer_id,
        text="Did you receive the item from the seller?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def seller_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    action = parts[1]
    deal_id = parts[2]

    if action == "delivered":

        await query.edit_message_text("Seller confirmed item delivered.")

        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"Seller confirmed delivery for deal {deal_id}."
        )

    else:

        await query.edit_message_text("Seller said item not delivered yet.")


async def buyer_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    action, deal_id = query.data.split("_")[1:]

    cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    deal = cursor.fetchone()

    if not deal:
        return

    # 🔒 Security check – only buyer can press the button
    if query.from_user.username != deal[1]:
        await query.answer("Only buyer can confirm.", show_alert=True)
        return

    buyer_id = users.get(deal[1])

    if action == "yes":

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("completed", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Buyer confirmed item received.")

        # Notify group
        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"""
Deal Completed

Deal ID: {deal_id}

Buyer confirmed item received.
"""
        )

    else:

        cursor.execute(
            "UPDATE deals SET status=? WHERE deal_id=?",
            ("buyer dispute", deal_id)
        )
        conn.commit()

        await query.edit_message_text("Buyer reported item NOT received.")

        # Notify group
        await context.bot.send_message(
            chat_id=ESCROW_GROUP_ID,
            text=f"""
⚠️ Dispute Opened

Deal ID: {deal_id}

Buyer reported item NOT received.
Admin review required.
"""
        )

    # Update tracker message
    await update_tracker(context, deal_id)


async def update_tracker(context, deal_id):

    cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    deal = cursor.fetchone()

    if not deal:
        return

    buyer = deal[1]
    seller = deal[2]
    item = deal[3]
    amount = deal[4]
    status = deal[5]
    message_id = deal[6]

    stages = {
        "pending": [
            "✔ Deal Created",
            "❌ Seller Accepted",
            "❌ Payment Sent",
            "❌ Item Delivered",
            "❌ Completed"
        ],

        "accepted": [
            "✔ Deal Created",
            "✔ Seller Accepted",
            "❌ Payment Sent",
            "❌ Item Delivered",
            "❌ Completed"
        ],

        "paid": [
            "✔ Deal Created",
            "✔ Seller Accepted",
            "✔ Payment Sent",
            "❌ Item Delivered",
            "❌ Completed"
        ],

        "delivered": [
            "✔ Deal Created",
            "✔ Seller Accepted",
            "✔ Payment Sent",
            "✔ Item Delivered",
            "❌ Completed"
        ],

        "buyer confirmed": [
            "✔ Deal Created",
            "✔ Seller Accepted",
            "✔ Payment Sent",
            "✔ Item Delivered",
            "✔ Completed"
        ],

        "completed": [
            "✔ Deal Created",
            "✔ Seller Accepted",
            "✔ Payment Sent",
            "✔ Item Delivered",
            "✔ Completed"
        ],

        "rejected": [
            "✔ Deal Created",
            "❌ Seller Rejected",
            "❌ Payment Sent",
            "❌ Item Delivered",
            "❌ Completed"
        ],

        "cancelled": [
            "✔ Deal Created",
            "❌ Deal Cancelled",
            "❌ Payment Sent",
            "❌ Item Delivered",
            "❌ Completed"
        ]
    }

    stage_text = "\n".join(stages.get(status, []))

    await context.bot.edit_message_text(
        chat_id=ESCROW_GROUP_ID,
        message_id=message_id,
        text=f"""
Deal #{deal_id}

Buyer: @{buyer}
Seller: @{seller}
Item: {item}
Amount: ₹{amount}

Status:
{stage_text}
"""
    )

async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):

    caption = update.message.caption

    if not caption:
        await update.message.reply_text("Please include Deal ID in caption.")
        return

    deal_id = caption.strip()

    await context.bot.send_message(
        chat_id=ESCROW_GROUP_ID,
        text="Payment screenshot received. Waiting for admin verification."
    )

    await update.message.reply_text(
        "Payment proof received. Admin(@Hrishabh2200032748) will verify."
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Payment Received", callback_data=f"admin_paid_{deal_id}"),
            InlineKeyboardButton("❌ Payment Not Received", callback_data=f"admin_reject_{deal_id}")
        ]
    ]

    await context.bot.forward_message(
        chat_id=ADMIN_ID,
        from_chat_id=update.message.chat_id,
        message_id=update.message.message_id
    )

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"Deal ID: {deal_id}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.from_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Usage: /paid DEAL_ID")
        return

    deal_id = context.args[0]

    cursor.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
    deal = cursor.fetchone()

    if not deal:
        await update.message.reply_text("Deal not found")
        return

    cursor.execute(
        "UPDATE deals SET status=? WHERE deal_id=?",
        ("paid", deal_id)
    )

    conn.commit()

    seller_id = users.get(deal[2])

    if seller_id:
        await context.bot.send_message(
            chat_id=seller_id,
            text=f"""
Payment received for deal {deal_id}

Please deliver the item.

After delivery use:
/delivered {deal_id}
"""
        )

    await update.message.reply_text("Payment marked as received.")

    # update tracker message
    await update_tracker(context, deal_id)

async def groupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Group ID: {chat_id}")

# async def delivered(update: Update, context: ContextTypes.DEFAULT_TYPE):
#
#     if not context.args:
#         await update.message.reply_text("Usage: /delivered DEAL_ID")
#         return
#
#     deal_id = context.args[0]
#
#     cursor.execute("SELECT * FROM deals WHERE deal_id=?",(deal_id,))
#     deal = cursor.fetchone()
#
#     if not deal:
#         return
#
#     buyer_id = users.get(deal[1])
#
#     cursor.execute(
#         "UPDATE deals SET status=? WHERE deal_id=?",
#         ("delivered",deal_id)
#     )
#     conn.commit()
#     await context.bot.send_message(
#         chat_id=ESCROW_GROUP_ID,
#         text=f"""
#     Seller marked item delivered
#
#     Deal ID: {deal_id}
#
#     Waiting for buyer confirmation.
#     Buyer should run:
#     /confirm {deal_id}
#     """
#     )
#
#     if buyer_id:
#         await context.bot.send_message(
#             chat_id=buyer_id,
#             text=f"""
# Seller marked item delivered
#
# Deal ID: {deal_id}
#
# Use /confirm {deal_id}
# """
#         )
#     await update_tracker(context, deal_id)


# async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
#
#     if not context.args:
#         await update.message.reply_text("Usage: /confirm DEAL_ID")
#         return
#
#     deal_id = context.args[0]
#
#     cursor.execute(
#         "UPDATE deals SET status=? WHERE deal_id=?",
#         ("buyer confirmed", deal_id)
#     )
#
#     conn.commit()
#
#     await context.bot.send_message(
#         chat_id=ADMIN_ID,
#         text=f"""
# Buyer confirmed delivery
#
# Deal ID: {deal_id}
#
# Admin can release payment:
# /release {deal_id}
# """
#     )
#
#     await update_tracker(context, deal_id)


# async def release(update: Update, context: ContextTypes.DEFAULT_TYPE):
#
#     if update.message.from_user.id != ADMIN_ID:
#         return
#
#     if not context.args:
#         await update.message.reply_text("Usage: /release DEAL_ID")
#         return
#
#     deal_id = context.args[0]
#
#     cursor.execute("SELECT * FROM deals WHERE deal_id=?",(deal_id,))
#     deal = cursor.fetchone()
#
#     if not deal:
#         return
#
#     seller_id = users.get(deal[2])
#
#     cursor.execute(
#         "UPDATE deals SET status=? WHERE deal_id=?",
#         ("completed",deal_id)
#     )
#     conn.commit()
#     await context.bot.send_message(
#         chat_id=ESCROW_GROUP_ID,
#         text=f"""
#     Deal Completed
#
#     Deal ID: {deal_id}
#
#     Admin released payment to seller.
#     Escrow closed successfully.
#     """
#     )
#
#
#     if seller_id:
#         await context.bot.send_message(
#             chat_id=seller_id,
#             text=f"Payment released for deal {deal_id}"
#         )
#
#     await update_tracker(context, deal_id)

async def mydeals(update: Update, context: ContextTypes.DEFAULT_TYPE):

    username = update.message.from_user.username

    cursor.execute(
        "SELECT * FROM deals WHERE buyer=? OR seller=?",
        (username,username)
    )

    deals = cursor.fetchall()

    if not deals:
        await update.message.reply_text("No deals found")
        return

    text = ""

    for deal in deals:
        text += f"{deal[0]} | {deal[3]} | {deal[4]} | {deal[5]}\n"

    await update.message.reply_text(text)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not context.args:
        await update.message.reply_text("Usage: /status DEAL_ID")
        return

    deal_id = context.args[0]

    cursor.execute("SELECT * FROM deals WHERE deal_id=?",(deal_id,))
    deal = cursor.fetchone()

    if not deal:
        await update.message.reply_text("Deal not found")
        return

    await update.message.reply_text(
        f"""
Deal ID: {deal[0]}
Buyer: @{deal[1]}
Seller: @{deal[2]}
Item: {deal[3]}
Amount: {deal[4]}
Status: {deal[5]}
"""
    )


async def adminpanel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT * FROM deals")
    deals = cursor.fetchall()

    if not deals:
        await update.message.reply_text("No deals found")
        return

    text = ""

    for deal in deals:
        text += f"{deal[0]} | @{deal[1]} → @{deal[2]} | {deal[4]} | {deal[5]}\n"

    await update.message.reply_text(text)


app = ApplicationBuilder().token(TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("create",create)],
    states={
        SELLER: [MessageHandler(filters.TEXT & (~filters.COMMAND), seller)],
        ITEM: [MessageHandler(filters.TEXT & (~filters.COMMAND), item)],
        AMOUNT: [MessageHandler(filters.TEXT & (~filters.COMMAND), amount)]
    },
    fallbacks=[]
)

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(role_handler, pattern="role_"))

app.add_handler(conv_handler)

app.add_handler(CommandHandler("groupid", groupid))

# CALLBACK BUTTON HANDLERS
app.add_handler(CallbackQueryHandler(seller_response, pattern="^(accept|reject|cancel)_"))
app.add_handler(CallbackQueryHandler(admin_payment, pattern="admin_"))
app.add_handler(CallbackQueryHandler(seller_delivery, pattern="seller_"))
app.add_handler(CallbackQueryHandler(buyer_confirmation, pattern="buyer_"))

# MESSAGE HANDLERS
app.add_handler(MessageHandler(filters.PHOTO, payment))

# COMMAND HANDLERS
app.add_handler(CommandHandler("paid", paid))
app.add_handler(CommandHandler("mydeals", mydeals))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("adminpanel", adminpanel))

# app.add_handler(CommandHandler("delivered", delivered))
# app.add_handler(CommandHandler("confirm", confirm))
# app.add_handler(CommandHandler("release", release))

web = Flask(__name__)

@web.route("/")
def home():
    return send_file("index.html")

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web.run(host="0.0.0.0", port=port)

print("Escrow Bot Running...")

threading.Thread(target=run_web).start()

app.run_polling()