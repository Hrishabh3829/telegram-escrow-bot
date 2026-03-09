# Telegram Escrow Bot

A simple Telegram bot that manages escrow deals between a buyer and a seller.

The bot records deals, verifies payment, and lets the buyer confirm whether the item was received.

## Links

* **Telegram Bot:** https://t.me/Blaze567bot
* **Escrow Monitoring Group:** https://t.me/safe_escrow_deals

---

## Features

* Create escrow deals
* Seller approval (accept / reject / cancel)
* Buyer sends payment screenshot
* Admin verifies payment
* Buyer confirms item received
* Dispute option if item not received
* Deal tracking in group
* SQLite database for storing deals

---

## Workflow

1. Buyer creates a deal using `/create`
2. Seller accepts or rejects the deal
3. Buyer sends payment proof
4. Admin verifies payment
5. Seller delivers item
6. Buyer confirms item received or reports issue

---

## Commands

| Command       | Description             |
| ------------- | ----------------------- |
| `/start`      | Start the bot           |
| `/create`     | Create a new deal       |
| `/adminpanel` | Admin view of all deals |

---

## Setup

### 1. Clone the repository

```
git clone https://github.com/yourusername/telegram-escrow-bot.git
cd telegram-escrow-bot
```

### 2. Install dependencies

```
pip install python-telegram-bot python-dotenv
```

### 3. Create `.env`

```
BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_id
ESCROW_UPI=your_upi_id
```

### 4. Run the bot

```
python main.py
```

---

## Database

SQLite database `escrow.db` is created automatically.

Deals table fields:

* deal_id
* buyer
* seller
* item
* amount
* status
* message_id

---

## Tech Stack

* Python
* python-telegram-bot
* SQLite

---

## License

@hrishabh3829
