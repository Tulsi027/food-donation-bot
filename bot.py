import os
import datetime
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ✅ Google Sheets Setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
google_creds_json = os.getenv("GOOGLE_CREDS")  # 🔹 Get JSON string from environment variable
google_creds_dict = json.loads(google_creds_json)  # 🔹 Convert string → dict
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open("FoodDonation")
ngo_sheet = sheet.worksheet("NGO")
donation_sheet = sheet.worksheet("Donations")

# ✅ Telegram Token (set on Render as an Environment Variable)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# ✅ Conversation States
CHOOSING_ROLE, NGO_NAME, NGO_LOCATION, NGO_CONTACT, FOOD_DETAILS, FOOD_LOCATION, FOOD_TIME, DONOR_CONTACT = range(8)

# ✅ Helper: parse pickup time
def parse_pickup_time(time_text):
    now = datetime.datetime.now()
    today = now.strftime("%Y-%m-%d")

    try:
        return datetime.datetime.strptime(time_text, "%Y-%m-%d %H:%M")
    except:
        pass
    try:
        return datetime.datetime.strptime(f"{today} {time_text}", "%Y-%m-%d %I:%M %p")
    except:
        pass
    try:
        return datetime.datetime.strptime(f"{today} {time_text}", "%Y-%m-%d %I %p")
    except:
        return None

# ✅ Helper: get available donations
def get_available_donations():
    records = donation_sheet.get_all_records()
    available = []
    now = datetime.datetime.now()
    for idx, r in enumerate(records, start=2):
        status = r.get("Status", "")
        try:
            pickup_time = datetime.datetime.strptime(r["Pickup Time"], "%Y-%m-%d %H:%M")
        except:
            continue
        if status == "Available" and pickup_time > now:
            available.append((idx, r))
    return available

# ✅ Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["NGO", "Donor"]]
    await update.message.reply_text(
        "👋 Welcome to *Food Donation Bot!*\nAre you registering as an NGO or donating food?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSING_ROLE

# ✅ Choose Role
async def choose_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text
    if role == "NGO":
        await update.message.reply_text("✅ Great! Please send your NGO name.")
        return NGO_NAME
    else:
        await update.message.reply_text("🍛 Awesome! Please describe the food (Veg/Non-Veg & Quantity).")
        return FOOD_DETAILS

# ✅ NGO Registration
async def ngo_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ngo_name"] = update.message.text
    await update.message.reply_text("📍 Please send NGO location.")
    return NGO_LOCATION

async def ngo_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["ngo_location"] = update.message.text
    await update.message.reply_text("📞 Please send NGO contact number.")
    return NGO_CONTACT

async def ngo_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ngo_name = context.user_data["ngo_name"]
    ngo_location = context.user_data["ngo_location"]
    ngo_contact = update.message.text
    chat_id = update.message.chat_id
    date_registered = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    ngo_sheet.append_row([ngo_name, ngo_location, ngo_contact, chat_id, date_registered])
    await update.message.reply_text("✅ NGO registered successfully! Thank you.")

    # 🔥 Show all current donations to the NGO immediately
    donations = get_available_donations()
    if donations:
        msg = "🍛 *Here are current available donations:*\n\n"
        for idx, r in donations:
            msg += (f"#{idx-1}\n🍲 {r['Food']}\n📍 {r['Location']}\n⏰ Pickup: {r['Pickup Time']}\n"
                    f"📞 Contact: {r['Donor Contact']}\n👉 Send `/accept {idx-1}` to claim\n\n")
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ No current donations available right now.")

    return ConversationHandler.END

# ✅ Donor Flow
async def food_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["food_details"] = update.message.text
    await update.message.reply_text("📍 Please send the food pickup location.")
    return FOOD_LOCATION

async def food_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["food_location"] = update.message.text
    await update.message.reply_text("⏰ Please provide pickup time (e.g. `10:30 PM` or `2025-08-03 19:00`).")
    return FOOD_TIME

async def food_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_text = update.message.text
    pickup_dt = parse_pickup_time(time_text)
    if not pickup_dt:
        await update.message.reply_text("⚠️ Invalid time format. Try `10:30 PM` or `2025-08-03 19:00`.")
        return FOOD_TIME
    context.user_data["food_time"] = pickup_dt.strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text("📞 Please share your contact number.")
    return DONOR_CONTACT

async def donor_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    food = context.user_data["food_details"]
    location = context.user_data["food_location"]
    time = context.user_data["food_time"]
    donor_contact = update.message.text

    donation_sheet.append_row([food, location, donor_contact, time, "Available"])

    await update.message.reply_text("🙏 Thank you! Your food donation has been listed.")

    ngos = ngo_sheet.get_all_records()
    donation_row = len(donation_sheet.get_all_values())
    donation_id = donation_row - 1

    for ngo in ngos:
        chat_id = ngo.get("Chat ID")
        if chat_id:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(f"🍛 *New Food Donation Alert!*\n"
                          f"#{donation_id}\n"
                          f"🍲 {food}\n📍 {location}\n⏰ Pickup: {time}\n📞 Contact: {donor_contact}\n\n"
                          f"👉 Send `/accept {donation_id}` to claim this donation."),
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"❌ Could not notify NGO: {e}")

    return ConversationHandler.END

# ✅ /findfood
async def find_food(update: Update, context: ContextTypes.DEFAULT_TYPE):
    donations = get_available_donations()
    if not donations:
        await update.message.reply_text("❌ No food donations available right now.")
        return
    msg = "🍛 *Available Food Donations:*\n\n"
    for idx, r in donations:
        msg += (f"#{idx-1}\n🍲 {r['Food']}\n📍 {r['Location']}\n⏰ Pickup: {r['Pickup Time']}\n"
                f"📞 Contact: {r['Donor Contact']}\n👉 Send `/accept {idx-1}` to claim\n\n")
    await update.message.reply_text(msg, parse_mode="Markdown")

# ✅ /accept
async def accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ngos = ngo_sheet.get_all_records()

    if len(context.args) == 0:
        await update.message.reply_text("⚠️ Please provide a donation number. Example: `/accept 3`", parse_mode="Markdown")
        return

    try:
        donation_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("⚠️ Invalid number. Example: `/accept 3`", parse_mode="Markdown")
        return

    row = donation_id + 1
    values = donation_sheet.row_values(row)

    if not values:
        await update.message.reply_text("❌ Donation not found.")
        return

    status = values[4]
    ngo_name = "Unknown NGO"
    for ngo in ngos:
        if ngo.get("Chat ID") == update.message.chat_id:
            ngo_name = ngo.get("NGO Name") or ngo.get("NGO") or "Unnamed NGO"

    if status != "Available":
        await update.message.reply_text(f"⚠️ This donation is already claimed ({status}).")
        return

    donation_sheet.update_cell(row, 5, f"Claimed by {ngo_name}")
    await update.message.reply_text(f"✅ You claimed donation #{donation_id} successfully!")

    for ngo in ngos:
        chat_id = ngo.get("Chat ID")
        if chat_id and chat_id != update.message.chat_id:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Donation #{donation_id} has been claimed by *{ngo_name}*.",
                    parse_mode="Markdown"
                )
            except:
                continue

# ✅ Build Bot
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler("start", start)],
    states={
        CHOOSING_ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_role)],
        NGO_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ngo_name)],
        NGO_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ngo_location)],
        NGO_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ngo_contact)],
        FOOD_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_details)],
        FOOD_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_location)],
        FOOD_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, food_time)],
        DONOR_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, donor_contact)],
    },
    fallbacks=[]
)

app.add_handler(conv_handler)
app.add_handler(CommandHandler("findfood", find_food))
app.add_handler(CommandHandler("accept", accept))

print("✅ Bot is running... send /start in Telegram")
app.run_polling()
