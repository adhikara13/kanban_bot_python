import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, ConversationHandler, Filters
import sqlite3
import os
from queue import Queue
from telegram.ext import Dispatcher, JobQueue
from tabulate import tabulate
import datetime
from dotenv import load_dotenv

load_dotenv("token.env")  # Load environment variables from .env file

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

bot = telegram.Bot(token=TOKEN)

updater = Updater(token=TOKEN)
dispatcher = updater.dispatcher

DATABASE_NAME = "kanban_board.db"

conn = sqlite3.connect(DATABASE_NAME)
cursor = conn.cursor()

cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        status TEXT NOT NULL,
        assignee TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by INTEGER NOT NULL
    )
''')

def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="I love Vika!")

def new_task(update, context):
    # Clear any previous user data
    context.user_data.clear()
    def prompt_name(update, context):
        context.user_data['name'] = update.message.text
        context.bot.send_message(chat_id=update.effective_chat.id, text="Enter task description:")
        return "description"

    def prompt_description(update, context):
        context.user_data['description'] = update.message.text
        context.bot.send_message(chat_id=update.effective_chat.id, text="Enter task status:")
        return "status"

    def prompt_status(update, context):
        context.user_data['status'] = update.message.text
        context.bot.send_message(chat_id=update.effective_chat.id, text="Enter task assignee:")
        return "assignee"

    def prompt_assignee(update, context):
        context.user_data['assignee'] = update.message.text
        create_task(update, context)

    def create_task(update, context):
        user_id = update.message.from_user.id
        task_name = context.user_data['name']
        task_description = context.user_data['description']
        task_status = context.user_data['status']
        task_assignee = context.user_data['assignee']

        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()

        cursor.execute(f"INSERT INTO tasks (name, description, status, assignee, created_by) VALUES (?, ?, ?, ?, ?)", (task_name, task_description, task_status, task_assignee, user_id))
        conn.commit()

        cursor.close()
        conn.close()

        context.bot.send_message(chat_id=update.effective_chat.id, text=f"New task created: {task_name}")

    # Clear any previous user data
    context.user_data.clear()

    # Prompt the user for the task name
    update.message.reply_text("Enter task name:")

    # Set up conversation handler to handle user input
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.text, prompt_name)],
        states={
            "description": [MessageHandler(Filters.text, prompt_description)],
            "status": [MessageHandler(Filters.text, prompt_status)],
            "assignee": [MessageHandler(Filters.text, prompt_assignee)],
        },
        fallbacks=[],
    )

    # Add conversation handler to the dispatcher
    context.dispatcher.add_handler(conv_handler)

    return "name"





def update_task(update, context):
    task_id = context.args[0]
    task_status = context.args[1]
    
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute(f"UPDATE tasks SET status = ? WHERE id = ?", (task_status, task_id))
    conn.commit()
    
    context.bot.send_message(chat_id=update.effective_chat.id, text=f"Task {task_id} updated to status: {task_status}")


def delete_task(update, context):
    # Ask the user which task they want to delete
    context.bot.send_message(chat_id=update.effective_chat.id, text="Which task do you want to delete? Enter task name:")

    # Set up conversation handler to handle user input
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.text, confirm_delete)],
        states={
            "confirm": [MessageHandler(Filters.text, delete)],
        },
        fallbacks=[],
        per_user=True,
        per_message=False,
    )

    # Add conversation handler to the dispatcher
    context.dispatcher.add_handler(conv_handler)


def confirm_delete(update, context):
    task_name = update.message.text

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Select the task with the given name
    cursor.execute(f"SELECT * FROM tasks WHERE name = ?", (task_name,))
    task = cursor.fetchone()

    if not task:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"No task found with name '{task_name}'")
        return ConversationHandler.END

    # Store the task ID in user data
    context.user_data['task_id'] = task[0]

    # Confirm deletion with the user
    context.bot.send_message(chat_id=update.effective_chat.id, text=f"Are you sure you want to delete the following task?\n\nName: {task[1]}\nDescription: {task[2]}\nStatus: {task[3]}\nAssignee: {task[4]}")

    # Wait for user confirmation
    return "confirm"


def delete(update, context):
    # Delete the task with the stored task ID
    task_id = context.user_data['task_id']

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute(f"DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()

    context.bot.send_message(chat_id=update.effective_chat.id, text="Task deleted")

    # End the conversation
    return ConversationHandler.END


from telegram.ext import CallbackContext

def view_board(update, context):
    # Retrieve the user ID of the user who sent the message
    user_id = update.message.from_user.id

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Select tasks only for the user who created them
    cursor.execute(f"SELECT * FROM tasks WHERE created_by = ? ORDER BY created_at DESC", (user_id,))
    tasks = cursor.fetchall()

    # Check if there are any tasks
    if not tasks:
        context.bot.send_message(chat_id=update.effective_chat.id, text="The board is empty")
        return

    tasks_by_status = {}

    for task in tasks:
        status = task[3]
        if status not in tasks_by_status:
            tasks_by_status[status] = []
        tasks_by_status[status].append([task[0], task[1], task[2], task[4]])

    board_text = ""

    for status, tasks in tasks_by_status.items():
        board_text += f"\nStatus:\n*{status}*\n\n"
        for task in tasks:
            board_text += f"**Name:** {task[1]}\n**Description:** {task[2]}\n**Assignee:** {task[3]}\n\n"
    
    context.bot.send_message(chat_id=update.effective_chat.id, text=board_text, parse_mode=telegram.ParseMode.MARKDOWN_V2)


def schedule_daily_view(context: CallbackContext):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    # Select all users from the tasks table
    cursor.execute("SELECT DISTINCT created_by FROM tasks")
    users = cursor.fetchall()

    for user in users:
        user_id = user[0]

        # Select tasks only for the user who created them
        cursor.execute(f"SELECT * FROM tasks WHERE created_by = ? ORDER BY created_at DESC", (user_id,))
        tasks = cursor.fetchall()

        # Check if there are any tasks
        if not tasks:
            continue

        tasks_by_status = {}

        for task in tasks:
            status = task[3]
            if status not in tasks_by_status:
                tasks_by_status[status] = []
            tasks_by_status[status].append([task[0], task[1], task[2], task[4]])

        board_text = ""

        for status, tasks in tasks_by_status.items():
            board_text += f"\nStatus:\n*{status}*\n\n"
            for task in tasks:
                board_text += f"**ID:** {task[0]}\n**Name:** {task[1]}\n**Description:** {task[2]}\n**Assignee:** {task[3]}\n\n"

        context.bot.send_message(chat_id=user_id, text=board_text, parse_mode=telegram.ParseMode.MARKDOWN_V2)


# Schedule the daily view to be sent every day at 6am
updater.job_queue.run_daily(schedule_daily_view, time=datetime.time(hour=6))
# Debugging run every 1 second
# updater.job_queue.run_repeating(schedule_daily_view, interval=1, first=0)



# def view_board(update, context):
#     # Retrieve the user ID of the user who sent the message
#     user_id = update.message.from_user.id

#     conn = sqlite3.connect(DATABASE_NAME)
#     cursor = conn.cursor()

#     # Select tasks only for the user who created them
#     cursor.execute(f"SELECT * FROM tasks WHERE created_by = ? ORDER BY created_at DESC", (user_id,))
#     tasks = cursor.fetchall()

#     # Check if there are any tasks
#     if not tasks:
#         context.bot.send_message(chat_id=update.effective_chat.id, text="The board is empty")
#         return

#     tasks_by_status = {}

#     for task in tasks:
#         status = task[3]
#         if status not in tasks_by_status:
#             tasks_by_status[status] = []
#         tasks_by_status[status].append([task[0], task[1], task[2], task[4]])

#     board_text = ""

#     for status, tasks in tasks_by_status.items():
#         board_text += f"\nStatus:\n*{status}*\n\n"
#         for task in tasks:
#             board_text += f"**ID:** {task[0]}\n**Name:** {task[1]}\n**Description:** {task[2]}\n**Assignee:** {task[3]}\n\n"

#     context.bot.send_message(chat_id=update.effective_chat.id, text=board_text, parse_mode=telegram.ParseMode.MARKDOWN_V2)

#     cursor.close()
#     conn.close()








from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup

def menu(update, context):
    # Define the keyboard layout
    keyboard = [
        [KeyboardButton('/start'), KeyboardButton('/view_board')],
        [KeyboardButton('/new_task'), KeyboardButton('/delete_task')]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard)

    # Define the menu button
    menu_button = InlineKeyboardButton(text='Menu', callback_data='menu')

    # Create the inline keyboard layout with the menu button
    inline_keyboard = [[menu_button]]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)

    # Send the menu to the user with the inline keyboard
    # context.bot.send_message(chat_id=update.effective_chat.id, text='Please select an action:', reply_markup=reply_markup, reply_markup=inline_markup)
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True, inline_keyboard=[[menu_button]])
    context.bot.send_message(chat_id=update.effective_chat.id, text='Please select an action:', reply_markup=reply_markup)



# Define the handlers for the bot
start_handler = CommandHandler('start', start)
new_task_handler = CommandHandler('new_task', new_task)
update_task_handler = CommandHandler('update_task', update_task)
delete_task_handler = CommandHandler('delete_task', delete_task)
view_board_handler = CommandHandler('view_board', view_board)
menu_handler = CommandHandler('menu', menu)

# Add the handlers to the dispatcher
dispatcher.add_handler(start_handler)
dispatcher.add_handler(new_task_handler)
dispatcher.add_handler(update_task_handler)
dispatcher.add_handler(delete_task_handler)
dispatcher.add_handler(view_board_handler)
dispatcher.add_handler(menu_handler)

# Start the bot
updater.start_polling()
updater.idle()

