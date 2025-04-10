"""
Simple Telegram Quiz Bot implementation
"""
import os
import json
import random
import asyncio
import logging
import re
import requests
from urllib.parse import urlparse
from telegram import Update, Poll, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, PollHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters, PollAnswerHandler
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define conversation states
QUESTION, OPTIONS, ANSWER, NEGATIVE_MARKING, CATEGORY, CUSTOM_ID = range(6)
EDIT_SELECT, EDIT_QUESTION, EDIT_OPTIONS, EDIT_ANSWER = range(6, 10)
CLONE_URL, CLONE_MANUAL, CLONE_OPTIONS, CLONE_ANSWER, CLONE_ID = range(10, 15)
ADD_QUESTION_FULL = 15
ADD_QUESTION_CUSTOM_ID = 16

# Get bot token from environment
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Create data directory if it doesn't exist
os.makedirs('data', exist_ok=True)

# File paths
QUESTIONS_FILE = 'data/questions.json'
USERS_FILE = 'data/users.json'

def load_questions():
    """Load questions from the JSON file"""
    try:
        if os.path.exists(QUESTIONS_FILE):
            with open(QUESTIONS_FILE, 'r', encoding='utf-8') as file:
                questions = json.load(file)
            logger.info(f"Loaded {len(questions)} questions")
            return questions
        else:
            # Create sample questions if file doesn't exist
            questions = [
                {
                    "id": 1,
                    "question": "What is the capital of France?",
                    "options": ["Berlin", "Madrid", "Paris", "Rome"],
                    "answer": 2,  # Paris (0-based index)
                    "category": "Geography",
                    "negative_marking": 0  # Default no negative marking
                },
                {
                    "id": 2,
                    "question": "Which planet is known as the Red Planet?",
                    "options": ["Venus", "Mars", "Jupiter", "Saturn"],
                    "answer": 1,  # Mars (0-based index)
                    "category": "Science",
                    "negative_marking": 0  # Default no negative marking
                }
            ]
            save_questions(questions)
            return questions
    except Exception as e:
        logger.error(f"Error loading questions: {e}")
        return []

def save_questions(questions):
    """Save questions to the JSON file"""
    try:
        with open(QUESTIONS_FILE, 'w', encoding='utf-8') as file:
            json.dump(questions, file, ensure_ascii=False, indent=4)
        logger.info(f"Saved {len(questions)} questions")
        return True
    except Exception as e:
        logger.error(f"Error saving questions: {e}")
        return False

def get_next_question_id():
    """Get the next available question ID"""
    questions = load_questions()
    if not questions:
        return 1
    return max(q.get("id", 0) for q in questions) + 1

def get_question_by_id(question_id):
    """Get a question by its ID"""
    questions = load_questions()
    for question in questions:
        if question.get("id") == question_id:
            return question
    return None

def delete_question_by_id(question_id):
    """Delete a question by its ID"""
    questions = load_questions()
    updated_questions = [q for q in questions if q.get("id") != question_id]
    if len(updated_questions) < len(questions):
        save_questions(updated_questions)
        return True
    return False

def parse_telegram_quiz_url(url):
    """Parse a Telegram quiz URL to extract question and options"""
    try:
        # Basic URL validation
        if not url or "t.me" not in url:
            logger.error(f"Not a valid Telegram URL: {url}")
            return None
        
        # Try different methods to extract quiz content
        logger.info(f"Attempting to extract quiz from URL: {url}")
        
        # Method 1: Try to use Telegram API (Pyrogram) if credentials are available
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if api_id and api_hash and bot_token:
            try:
                from pyrogram import Client
                import asyncio
                
                # Extract channel username and message ID from URL
                channel_pattern = r't\.me/([^/]+)/(\d+)'
                channel_match = re.search(channel_pattern, url)
                
                if channel_match:
                    channel_name = channel_match.group(1)
                    message_id = int(channel_match.group(2))
                    
                    # Function to get message using Pyrogram
                    async def get_quiz_message():
                        logger.info(f"Trying to fetch message from {channel_name}, ID: {message_id}")
                        async with Client(
                            "quiz_bot_client",
                            api_id=api_id,
                            api_hash=api_hash,
                            bot_token=bot_token,
                            in_memory=True
                        ) as app:
                            try:
                                message = await app.get_messages(channel_name, message_id)
                                if message:
                                    # If it's a poll message
                                    if message.poll:
                                        return {
                                            "question": message.poll.question,
                                            "options": [opt.text for opt in message.poll.options],
                                            "answer": 0  # Default, user will select correct answer
                                        }
                                    # If it's a text message that might contain quiz info
                                    elif message.text:
                                        # Try to parse text as quiz (question + options format)
                                        lines = message.text.strip().split('\n')
                                        if len(lines) >= 3:  # At least 1 question and 2 options
                                            question = lines[0]
                                            options = []
                                            
                                            # Extract options (look for numbered/lettered options)
                                            for line in lines[1:]:
                                                line = line.strip()
                                                # Remove common option prefixes
                                                line = re.sub(r'^[a-z][\.\)]\s*', '', line)
                                                line = re.sub(r'^\d+[\.\)]\s*', '', line)
                                                if line:
                                                    options.append(line)
                                            
                                            if len(options) >= 2:
                                                return {
                                                    "question": question,
                                                    "options": options,
                                                    "answer": 0
                                                }
                            except Exception as e:
                                logger.error(f"Error getting message with Pyrogram: {e}")
                                return None
                        return None
                    
                    # Run the async function
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(get_quiz_message())
                    loop.close()
                    
                    if result:
                        logger.info(f"Successfully extracted quiz via Pyrogram: {result['question']}")
                        return result
            except Exception as e:
                logger.error(f"Pyrogram method failed: {e}")
        
        # Method 2: Enhanced web scraping with multiple patterns
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        # Try to get both the regular URL and the embedded version
        try:
            response = requests.get(url, headers=headers)
            content = response.text
            
            # First, look for standard poll format
            poll_q_match = re.search(r'<div class="tgme_widget_message_poll_question">([^<]+)</div>', content)
            poll_options = re.findall(r'<div class="tgme_widget_message_poll_option_text">([^<]+)</div>', content)
            
            if poll_q_match and poll_options and len(poll_options) >= 2:
                question = poll_q_match.group(1).strip()
                return {
                    "question": question,
                    "options": poll_options,
                    "answer": 0
                }
            
            # If not a direct poll, try embedded view
            if "rajsthangk" in url or "gk" in url.lower() or "quiz" in url.lower():
                # Try to extract channel and message_id
                channel_pattern = r't\.me/([^/]+)/(\d+)'
                channel_match = re.search(channel_pattern, url)
                
                if channel_match:
                    channel_name = channel_match.group(1)
                    message_id = channel_match.group(2)
                    
                    # Try embedded view
                    embed_url = f"https://t.me/{channel_name}/{message_id}?embed=1"
                    try:
                        embed_response = requests.get(embed_url, headers=headers)
                        embed_content = embed_response.text
                        
                        # Try to find quiz in embedded view
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(embed_content, 'html.parser')
                        
                        # Look for message text that might contain quiz
                        message_text = soup.select_one('.tgme_widget_message_text')
                        if message_text:
                            text = message_text.get_text().strip()
                            lines = [line.strip() for line in text.split('\n') if line.strip()]
                            
                            if lines and len(lines) >= 3:  # At least question + 2 options
                                question = lines[0]
                                
                                # Check if this looks like a quiz (has options with A), B), 1., 2., etc.)
                                option_pattern = re.compile(r'^[A-Za-z0-9][\.\)]')
                                options = []
                                for line in lines[1:]:
                                    # Remove option markers
                                    clean_line = re.sub(r'^[A-Za-z0-9][\.\)]\s*', '', line)
                                    if clean_line:
                                        options.append(clean_line)
                                
                                if len(options) >= 2:
                                    logger.info(f"Extracted quiz from message text with {len(options)} options")
                                    return {
                                        "question": question,
                                        "options": options,
                                        "answer": 0
                                    }
                        
                        # For RAJ GK QUIZ HOUSE format, look for quiz title
                        page_title = soup.select_one('meta[property="og:title"]')
                        if page_title and "quiz" in page_title.get('content', '').lower():
                            title = page_title.get('content', '').strip()
                            
                            # Try to extract options from the page
                            lines = []
                            for p in soup.select('.tgme_widget_message_text p'):
                                lines.append(p.get_text().strip())
                            
                            # If we have potential options
                            if lines and len(lines) >= 2:
                                return {
                                    "question": title,
                                    "options": lines,
                                    "answer": 0
                                }
                    except Exception as e:
                        logger.error(f"Error scraping embedded content: {e}")
            
            # Try another fallback method for general text parsing
            try:
                # Look for a clear question and option structure in the page content
                lines = [line.strip() for line in content.split('\n') if line.strip()]
                text_content = ' '.join(lines)
                
                # Try regex patterns for common quiz formats
                quiz_patterns = [
                    r'question:\s*([^\?]+\??)\s*options:(.+)',
                    r'quiz:\s*([^\?]+\??)\s*a\)(.*?)b\)(.*?)c\)(.*?)(d\).*?)?$',
                    r'([^\?]+\??)\s*a\.\s*(.*?)\s*b\.\s*(.*?)\s*c\.\s*(.*?)(\s*d\.\s*.*?)?$'
                ]
                
                for pattern in quiz_patterns:
                    match = re.search(pattern, text_content, re.IGNORECASE | re.DOTALL)
                    if match:
                        question = match.group(1).strip()
                        options = []
                        for g in range(2, min(len(match.groups()) + 2, 6)):
                            if match.group(g) and match.group(g).strip():
                                options.append(match.group(g).strip())
                        if len(options) >= 2:
                            return {
                                "question": question,
                                "options": options,
                                "answer": 0
                            }
            except Exception as e:
                logger.error(f"Error parsing text content: {e}")
                
        except Exception as e:
            logger.error(f"Error fetching URL content: {e}")
        
        return None
    except Exception as e:
        logger.error(f"Error in parse_telegram_quiz_url: {e}")
        return None

# User tracking functions
def load_users():
    """Load user data from file"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as file:
                users = json.load(file)
            return users
        else:
            return {}
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(users):
    """Save user data to file"""
    try:
        with open(USERS_FILE, 'w', encoding='utf-8') as file:
            json.dump(users, file, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logger.error(f"Error saving users: {e}")
        return False

def get_user_data(user_id):
    """Get data for a specific user"""
    users = load_users()
    return users.get(str(user_id), {"quizzes_taken": 0, "correct_answers": 0})

def update_user_data(user_id, data):
    """Update data for a specific user"""
    users = load_users()
    users[str(user_id)] = data
    save_users(users)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start command handler"""
    user = update.effective_user
    
    # Check if an ID was provided to directly start a quiz with that ID
    if context.args and context.args[0].isdigit():
        question_id = int(context.args[0])
        # Start a quiz with that specific ID
        question = get_question_by_id(question_id)
        if question:
            # Initialize quiz data
            context.user_data['quiz'] = {
                'questions': [question],
                'current_index': 0,
                'correct_count': 0,
                'wrong_count': 0,
                'participants': {},
                'start_time': asyncio.get_event_loop().time(),
                'negative_marking': question.get('negative_marking', 0),
                'single_question_mode': True  # Flag to indicate single question mode
            }
            
            # Start the quiz
            await update.message.reply_text(f"Starting quiz with question ID #{question_id}...")
            
            # Send the timer message
            timer_msg = await update.message.reply_text("⏱ Quiz timer: 00:00")
            context.user_data['quiz']['timer_message_id'] = timer_msg.message_id
            context.user_data['quiz']['timer_chat_id'] = timer_msg.chat_id
            
            # Start the timer
            asyncio.create_task(update_timer(context))
            
            # Send the question
            await send_question(update, context)
            return
        else:
            await update.message.reply_text(f"❌ Question with ID #{question_id} not found.")
            
    # If no ID provided or ID not found, show welcome message
    welcome_message = (
        f"👋 Hello {user.first_name}! Welcome to the Quiz Bot.\n\n"
        f"I can help you create and take quizzes. Here are some commands:\n\n"
        f"• /start - Show this welcome message\n"
        f"• /start 123 - Start quiz with question ID #123\n"
        f"• /help - Show detailed help\n"
        f"• /add - Add a new quiz question (step by step)\n"
        f"• /addq - Add a new quiz question (all at once)\n"
        f"• /quiz - Start a quiz\n"
        f"• /category - Start a quiz from a specific category\n"
        f"• /delete - Delete a question\n"
        f"• /stats - Show your stats\n"
        f"• /poll2q - Convert a poll to a question\n"
        f"• /clone - Clone a quiz from a link\n\n"
        f"Let's start quizzing! 🎯"
    )
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Help command handler"""
    help_text = (
        "📚 *Quiz Bot Help*\n\n"
        "*Basic Commands:*\n"
        "• /start - Show welcome message\n"
        "• /start 123 - Start quiz with ID #123\n"
        "• /help - Show this help message\n"
        "• /quiz - Start a quiz with random questions\n"
        "• /quiz 5 - Start a quiz with 5 random questions\n"
        "• /quiz id=123 - Start with specific question ID\n"
        "• /stats - Show your quiz statistics\n\n"
        
        "*Question Management:*\n"
        "• /add - Add a new question (step by step)\n"
        "• /addq - Add a new question (all at once)\n"
        "• /delete - Delete a question\n"
        "• /edit - Edit an existing question\n\n"
        
        "*Advanced Features:*\n"
        "• /category - Start a quiz from specific category\n"
        "• /clone - Clone a quiz from a link or message\n"
        "• /poll2q - Convert a Telegram poll to a question\n"
        "  (Reply to a poll with this command)\n\n"
        
        "*Quiz Options:*\n"
        "• Negative marking: Penalties for wrong answers\n"
        "• Categories: Organize questions by topic\n"
        "• Custom IDs: Assign specific IDs to questions\n\n"
        
        "*Poll2Q Options:*\n"
        "Reply to a poll with `/poll2q`\n\n"
        "With custom ID:\n"
        "• `/poll2q id=123` - Use specific ID #123\n"
        "• `/poll2q start=50` - Start from ID #50\n"
        "• `/poll2q batch` - Process multiple polls\n\n"
        
        "Send /quiz to start a quiz now!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new question (step by step)"""
    await update.message.reply_text(
        "Let's add a new quiz question! Please send me the question text."
    )
    return QUESTION

async def add_question_full(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of adding a new question (all at once)"""
    instructions = (
        "📝 *Add a new question (all at once)*\n\n"
        "Please send me your question in this format:\n\n"
        "*Question*\n"
        "Option A\n"
        "Option B\n"
        "Option C\n"
        "Option D\n"
        "Correct: A\n"
        "Category: General\n"
        "Negative: 0\n"
        "ID: 123\n\n"
        "The last four lines (Correct, Category, Negative, ID) are optional. "
        "If omitted, the first option will be correct, category will be 'General', "
        "negative marking will be 0, and you'll be asked for a custom ID."
    )
    await update.message.reply_text(instructions, parse_mode="Markdown")
    return ADD_QUESTION_FULL

async def parse_full_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parse a question that was sent all at once"""
    text = update.message.text
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    if len(lines) < 3:  # Need at least question + 2 options
        await update.message.reply_text(
            "❌ Not enough lines. I need at least a question and 2 options."
        )
        return ADD_QUESTION_FULL
    
    # First line is the question
    question_text = lines[0]
    
    # Next lines are options until we hit a special line
    options = []
    correct_option = 0  # Default to first option
    category = "General"  # Default category
    negative_marking = 0  # Default no negative marking
    custom_id = None  # Default is None for auto-generated ID
    
    for i, line in enumerate(lines[1:], 1):
        if line.lower().startswith("correct:"):
            # Extract correct answer (A, B, C, D or 1, 2, 3, 4)
            correct_str = line.split(":", 1)[1].strip()
            if correct_str.isdigit():
                correct_option = int(correct_str) - 1  # Convert from 1-based to 0-based
            elif correct_str.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                correct_option = ord(correct_str.upper()) - ord('A')  # A->0, B->1, etc.
            continue
            
        if line.lower().startswith("category:"):
            category = line.split(":", 1)[1].strip()
            continue
            
        if line.lower().startswith("negative:"):
            try:
                negative_marking = float(line.split(":", 1)[1].strip())
            except ValueError:
                negative_marking = 0
            continue
            
        if line.lower().startswith("id:"):
            try:
                custom_id = int(line.split(":", 1)[1].strip())
            except ValueError:
                custom_id = None
            continue
            
        # If we get here, it's an option
        options.append(line)
    
    # Validate
    if len(options) < 2:
        await update.message.reply_text(
            "❌ Not enough options. I need at least 2 options."
        )
        return ADD_QUESTION_FULL
        
    if correct_option < 0 or correct_option >= len(options):
        await update.message.reply_text(
            f"❌ Invalid correct answer. It should be between 1 and {len(options)}."
        )
        return ADD_QUESTION_FULL
    
    # Store the question data in context
    context.user_data["addq_data"] = {
        "question": question_text,
        "options": options,
        "answer": correct_option,
        "category": category,
        "negative_marking": negative_marking,
        "custom_id": custom_id
    }
    
    # If custom ID was provided, save the question directly
    if custom_id is not None:
        # Create question
        question = {
            "id": custom_id,
            "question": question_text,
            "options": options,
            "answer": correct_option,
            "category": category,
            "negative_marking": negative_marking
        }
        
        # Load existing questions
        questions = load_questions()
        
        # Check if ID already exists
        existing_question = next((q for q in questions if q.get("id") == custom_id), None)
        if existing_question:
            # Ask for confirmation to replace
            keyboard = [
                [InlineKeyboardButton("Yes, replace it", callback_data=f"addq_replace_{custom_id}")],
                [InlineKeyboardButton("No, use different ID", callback_data="addq_new_id")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❓ A question with ID #{custom_id} already exists. Do you want to replace it?",
                reply_markup=reply_markup
            )
            return ConversationHandler.END
        else:
            # Add and save
            questions.append(question)
            save_questions(questions)
            
            # Format the correct answer display
            correct_letter = chr(ord('A') + correct_option)
            correct_text = options[correct_option]
            
            await update.message.reply_text(
                f"✅ Question saved successfully with ID #{custom_id}.\n\n"
                f"*Question:* {question_text}\n\n"
                f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(options)]) + "\n\n"
                f"*Correct answer:* {correct_letter}. {correct_text}\n"
                f"*Category:* {category}\n"
                f"*Negative marking:* {negative_marking}\n\n"
                f"You can use /addq to add another question or /quiz to start a quiz.",
                parse_mode="Markdown"
            )
            
            # Clear the user data
            context.user_data.clear()
            return ConversationHandler.END
    else:
        # Ask for custom ID
        await update.message.reply_text(
            "Would you like to assign a custom ID to this question? Reply with a number, or 'auto' to auto-generate."
        )
        return ADD_QUESTION_CUSTOM_ID

async def add_question_handle_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom ID input for addq command"""
    text = update.message.text.strip().lower()
    
    if text == "auto":
        # Use auto-generated ID
        custom_id = get_next_question_id()
    else:
        try:
            custom_id = int(text)
            if custom_id <= 0:
                await update.message.reply_text(
                    "❌ ID must be a positive number. Please try again, or reply 'auto'."
                )
                return ADD_QUESTION_CUSTOM_ID
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid ID format. Please enter a number, or reply 'auto'."
            )
            return ADD_QUESTION_CUSTOM_ID
    
    # Get question data from context
    data = context.user_data.get("addq_data", {})
    if not data:
        await update.message.reply_text(
            "❌ Question data not found. Please start over with /addq."
        )
        return ConversationHandler.END
    
    # Create question with the custom ID
    question = {
        "id": custom_id,
        "question": data["question"],
        "options": data["options"],
        "answer": data["answer"],
        "category": data["category"],
        "negative_marking": data["negative_marking"]
    }
    
    # Load existing questions
    questions = load_questions()
    
    # Check if ID already exists
    existing_question = next((q for q in questions if q.get("id") == custom_id), None)
    if existing_question:
        # Replace the existing question
        for i, q in enumerate(questions):
            if q.get("id") == custom_id:
                questions[i] = question
                break
    else:
        # Add as new question
        questions.append(question)
    
    # Save questions
    save_questions(questions)
    
    # Format the correct answer display
    correct_option = data["answer"]
    correct_letter = chr(ord('A') + correct_option)
    correct_text = data["options"][correct_option]
    
    await update.message.reply_text(
        f"✅ Question saved successfully with ID #{custom_id}.\n\n"
        f"*Question:* {data['question']}\n\n"
        f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(data['options'])]) + "\n\n"
        f"*Correct answer:* {correct_letter}. {correct_text}\n"
        f"*Category:* {data['category']}\n"
        f"*Negative marking:* {data['negative_marking']}\n\n"
        f"You can use /addq to add another question or /quiz to start a quiz.",
        parse_mode="Markdown"
    )
    
    # Clear the user data
    context.user_data.clear()
    return ConversationHandler.END

async def addq_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callbacks for addq command"""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split('_')
    action = data[1]
    
    if action == "replace":
        custom_id = int(data[2])
        
        # Get question data
        data = context.user_data.get("addq_data", {})
        if not data:
            await query.edit_message_text(
                "❌ Question data not found. Please start over with /addq."
            )
            return
        
        # Create and save the question
        question = {
            "id": custom_id,
            "question": data["question"],
            "options": data["options"],
            "answer": data["answer"],
            "category": data["category"],
            "negative_marking": data["negative_marking"]
        }
        
        # Load, replace, and save
        questions = load_questions()
        for i, q in enumerate(questions):
            if q.get("id") == custom_id:
                questions[i] = question
                break
        save_questions(questions)
        
        # Format the correct answer display
        correct_option = data["answer"]
        correct_letter = chr(ord('A') + correct_option)
        correct_text = data["options"][correct_option]
        
        await query.edit_message_text(
            f"✅ Question replaced successfully with ID #{custom_id}.\n\n"
            f"*Question:* {data['question']}\n\n"
            f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(data['options'])]) + "\n\n"
            f"*Correct answer:* {correct_letter}. {correct_text}\n"
            f"*Category:* {data['category']}\n"
            f"*Negative marking:* {data['negative_marking']}\n\n"
            f"You can use /addq to add another question or /quiz to start a quiz.",
            parse_mode="Markdown"
        )
        
        # Clear the user data
        context.user_data.clear()
    
    elif action == "new_id":
        # Ask for a different ID
        await query.edit_message_text(
            "Please enter a different ID number for this question, or 'auto' to auto-generate."
        )
        
        # Set state to await custom ID
        context.user_data["awaiting_different_id"] = True

async def receive_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the question text and ask for options"""
    question_text = update.message.text
    context.user_data["question"] = question_text
    context.user_data["options"] = []
    
    await update.message.reply_text(
        f"Question: {question_text}\n\n"
        f"Please send me all options separated by new lines:\n"
        f"Option 1\n"
        f"Option 2\n"
        f"Option 3\n"
        f"Option 4"
    )
    return OPTIONS

async def receive_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive all options at once"""
    text = update.message.text
    options = [line.strip() for line in text.split('\n') if line.strip()]
    
    if len(options) < 2:
        await update.message.reply_text(
            "❌ Not enough options. I need at least 2 options. Please try again."
        )
        return OPTIONS
    
    context.user_data["options"] = options
    
    # Display the options as an alphabetical list
    options_text = "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(options)])
    
    # Ask for the correct answer
    await update.message.reply_text(
        f"Options received:\n\n{options_text}\n\n"
        f"Which option is correct? Enter the letter (A, B, C, etc.) or number (1, 2, 3, etc.)."
    )
    return ANSWER

async def receive_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the correct answer"""
    answer_text = update.message.text.strip().upper()
    options = context.user_data.get("options", [])
    
    # Convert letter (A, B, C) or number (1, 2, 3) to index
    if answer_text.isalpha() and len(answer_text) == 1:
        answer = ord(answer_text) - ord('A')  # A->0, B->1, etc.
    elif answer_text.isdigit():
        answer = int(answer_text) - 1  # Convert from 1-based to 0-based
    else:
        await update.message.reply_text(
            f"❌ Invalid format. Please enter a letter (A, B, C) or number (1, 2, 3)."
        )
        return ANSWER
    
    if answer < 0 or answer >= len(options):
        await update.message.reply_text(
            f"❌ Invalid answer. Please enter a valid option between A and {chr(ord('A') + len(options) - 1)} "
            f"or between 1 and {len(options)}."
        )
        return ANSWER
    
    # Store the answer
    context.user_data["answer"] = answer
    
    # Ask about negative marking
    keyboard = [
        [InlineKeyboardButton("No negative marking", callback_data="negative_0")],
        [InlineKeyboardButton("-0.25 points per wrong answer", callback_data="negative_0.25")],
        [InlineKeyboardButton("-0.5 points per wrong answer", callback_data="negative_0.5")],
        [InlineKeyboardButton("-1 point per wrong answer", callback_data="negative_1")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Do you want to enable negative marking for this question?",
        reply_markup=reply_markup
    )
    return NEGATIVE_MARKING

async def receive_negative_marking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the negative marking setting"""
    query = update.callback_query
    await query.answer()
    
    # Extract negative marking value from callback data
    negative_marking = float(query.data.split('_')[1])
    context.user_data["negative_marking"] = negative_marking
    
    # Ask for custom ID
    keyboard = [
        [InlineKeyboardButton("Auto-generated ID", callback_data="id_auto")],
        [InlineKeyboardButton("Custom ID", callback_data="id_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"Negative marking set to: {negative_marking}\n\n"
        f"Would you like to use an auto-generated ID or set a custom ID?",
        reply_markup=reply_markup
    )
    return CUSTOM_ID

async def receive_id_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle ID choice (auto or custom)"""
    query = update.callback_query
    await query.answer()
    
    id_choice = query.data.split('_')[1]
    
    if id_choice == "auto":
        # Use auto-generated ID and move to category selection
        # Load all categories
        questions = load_questions()
        categories = sorted(set(q.get("category", "General") for q in questions))
        if not categories:
            categories = ["General"]
        
        # Create keyboard with available categories
        keyboard = []
        for i, category in enumerate(categories):
            button = InlineKeyboardButton(category, callback_data=f"addcat_{category}")
            if i % 2 == 0:  # Two categories per row
                keyboard.append([button])
            else:
                keyboard[-1].append(button)
        
        # Add "New Category" button
        keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="addcat_new")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Update message to ask for category
        await query.edit_message_text(
            f"Using auto-generated ID.\n\n"
            f"Choose a category for this question:",
            reply_markup=reply_markup
        )
        return CATEGORY
    else:
        # Ask for custom ID
        await query.edit_message_text(
            "Please enter a custom ID number for this question:"
        )
        context.user_data["awaiting_custom_id"] = True
        return CUSTOM_ID

async def receive_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive custom ID input"""
    if not context.user_data.get("awaiting_custom_id", False):
        return ConversationHandler.END
    
    try:
        custom_id = int(update.message.text.strip())
        if custom_id <= 0:
            await update.message.reply_text(
                "❌ ID must be a positive number. Please try again."
            )
            return CUSTOM_ID
        
        # Store the custom ID
        context.user_data["custom_id"] = custom_id
        
        # Now ask for category
        # Load all categories
        questions = load_questions()
        categories = sorted(set(q.get("category", "General") for q in questions))
        if not categories:
            categories = ["General"]
        
        # Create keyboard with available categories
        keyboard = []
        for i, category in enumerate(categories):
            button = InlineKeyboardButton(category, callback_data=f"addcat_{category}")
            if i % 2 == 0:  # Two categories per row
                keyboard.append([button])
            else:
                keyboard[-1].append(button)
        
        # Add "New Category" button
        keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="addcat_new")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Using custom ID: {custom_id}\n\n"
            f"Choose a category for this question:",
            reply_markup=reply_markup
        )
        return CATEGORY
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid ID format. Please enter a number."
        )
        return CUSTOM_ID

async def receive_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the category selection"""
    query = update.callback_query
    await query.answer()
    
    category = query.data.split('_')[1]
    
    if category == "new":
        # Ask user to enter a new category
        await query.edit_message_text(
            "Please reply with the name of the new category you want to create."
        )
        # Set a flag to expect a new category input
        context.user_data['awaiting_new_category'] = True
        return CATEGORY
    
    # Store the category
    context.user_data["category"] = category
    
    # Get the question ID (custom or auto-generated)
    question_id = context.user_data.get("custom_id")
    if question_id is None:
        question_id = get_next_question_id()
    
    # Create the question object
    question = {
        "id": question_id,
        "question": context.user_data["question"],
        "options": context.user_data["options"],
        "answer": context.user_data["answer"],
        "category": category,
        "negative_marking": context.user_data.get("negative_marking", 0)
    }
    
    # Load existing questions
    questions = load_questions()
    
    # Check if this ID already exists
    existing_question = next((q for q in questions if q.get("id") == question_id), None)
    if existing_question:
        # Replace the existing question
        for i, q in enumerate(questions):
            if q.get("id") == question_id:
                questions[i] = question
                break
    else:
        # Add as new question
        questions.append(question)
    
    # Save questions
    save_questions(questions)
    
    # Format the correct answer display
    correct_index = context.user_data["answer"]
    correct_letter = chr(ord('A') + correct_index)
    correct_text = context.user_data["options"][correct_index]
    
    # Update message with success
    await query.edit_message_text(
        f"✅ Question saved successfully with ID #{question_id}.\n\n"
        f"*Question:* {question['question']}\n\n"
        f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(question['options'])]) + "\n\n"
        f"*Correct answer:* {correct_letter}. {correct_text}\n"
        f"*Category:* {category}\n"
        f"*Negative marking:* {question['negative_marking']}\n\n"
        f"You can use /add to add another question or /quiz to start a quiz.",
        parse_mode="Markdown"
    )
    
    # Clear the user data
    context.user_data.clear()
    return ConversationHandler.END

async def receive_new_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive a new category name"""
    # Check if we're expecting a new category
    if not context.user_data.get('awaiting_new_category', False):
        return ConversationHandler.END
    
    # Get the category name
    new_category = update.message.text.strip()
    
    # Validate the category name
    if not new_category or len(new_category) > 50:
        await update.message.reply_text(
            "❌ Category name must be between 1 and 50 characters. Please try again."
        )
        return CATEGORY
    
    # Store the category
    context.user_data["category"] = new_category
    
    # Get the question ID (custom or auto-generated)
    question_id = context.user_data.get("custom_id")
    if question_id is None:
        question_id = get_next_question_id()
    
    # Create the question object
    question = {
        "id": question_id,
        "question": context.user_data["question"],
        "options": context.user_data["options"],
        "answer": context.user_data["answer"],
        "category": new_category,
        "negative_marking": context.user_data.get("negative_marking", 0)
    }
    
    # Load existing questions
    questions = load_questions()
    
    # Check if this ID already exists
    existing_question = next((q for q in questions if q.get("id") == question_id), None)
    if existing_question:
        # Replace the existing question
        for i, q in enumerate(questions):
            if q.get("id") == question_id:
                questions[i] = question
                break
    else:
        # Add as new question
        questions.append(question)
    
    # Save questions
    save_questions(questions)
    
    # Format the correct answer display
    correct_index = context.user_data["answer"]
    correct_letter = chr(ord('A') + correct_index)
    correct_text = context.user_data["options"][correct_index]
    
    await update.message.reply_text(
        f"✅ Question saved successfully with ID #{question_id} in new category '{new_category}'.\n\n"
        f"*Question:* {question['question']}\n\n"
        f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(question['options'])]) + "\n\n"
        f"*Correct answer:* {correct_letter}. {correct_text}\n"
        f"*Category:* {new_category}\n"
        f"*Negative marking:* {question['negative_marking']}\n\n"
        f"You can use /add to add another question or /quiz to start a quiz.",
        parse_mode="Markdown"
    )
    
    # Clear the user data
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the conversation"""
    await update.message.reply_text(
        "Operation cancelled. No changes were made.",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data.clear()
    return ConversationHandler.END

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz"""
    user_id = update.effective_user.id
    # Clear any existing quiz data
    if 'quiz' in context.user_data:
        del context.user_data['quiz']
    
    # Get number of questions or specific question ID from args
    question_id = None
    num_questions = 5  # Default number of questions
    
    if context.args:
        for arg in context.args:
            if arg.isdigit():
                num_questions = int(arg)
            elif arg.startswith("id="):
                try:
                    question_id = int(arg.split("=")[1])
                except ValueError:
                    await update.message.reply_text("Invalid question ID format. Try again.")
                    return
    
    # Initialize quiz data
    context.user_data['quiz'] = {
        'questions': [],
        'current_index': 0,
        'correct_count': 0,
        'wrong_count': 0,
        'participants': {},
        'start_time': asyncio.get_event_loop().time(),
        'negative_marking': 0  # Default, will be updated per question
    }
    
    # If specific question ID provided, get that question
    if question_id:
        question = get_question_by_id(question_id)
        if question:
            context.user_data['quiz']['questions'] = [question]
            context.user_data['quiz']['negative_marking'] = question.get('negative_marking', 0)
        else:
            await update.message.reply_text(f"Question with ID {question_id} not found.")
            del context.user_data['quiz']
            return
    else:
        # Otherwise, get random questions
        all_questions = load_questions()
        if not all_questions:
            await update.message.reply_text("No questions available. Add some questions first with /add.")
            del context.user_data['quiz']
            return
        
        # Randomly select questions
        available = min(num_questions, len(all_questions))
        context.user_data['quiz']['questions'] = random.sample(all_questions, available)
    
    # Send the timer message
    timer_msg = await update.message.reply_text("⏱ Quiz timer: 00:00")
    context.user_data['quiz']['timer_message_id'] = timer_msg.message_id
    context.user_data['quiz']['timer_chat_id'] = timer_msg.chat_id
    
    # Start the timer
    asyncio.create_task(update_timer(context))
    
    # Start the quiz
    await send_question(update, context)

async def update_timer(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Update the quiz timer"""
    try:
        # Get quiz data
        quiz_data = context.user_data.get('quiz', {})
        if not quiz_data:
            return
        
        timer_message_id = quiz_data.get('timer_message_id')
        timer_chat_id = quiz_data.get('timer_chat_id')
        start_time = quiz_data.get('start_time')
        
        if not timer_message_id or not timer_chat_id or not start_time:
            return
        
        for _ in range(600):  # 10 minutes max
            # Check if quiz still exists
            if 'quiz' not in context.user_data:
                return
            
            # Calculate elapsed time
            elapsed = asyncio.get_event_loop().time() - start_time
            minutes, seconds = divmod(int(elapsed), 60)
            
            # Update the timer message
            timer_text = f"⏱ Quiz timer: {minutes:02d}:{seconds:02d}"
            try:
                await context.bot.edit_message_text(
                    text=timer_text,
                    chat_id=timer_chat_id,
                    message_id=timer_message_id
                )
            except Exception as e:
                logger.error(f"Error updating timer: {e}")
                return
            
            # Wait for next second
            await asyncio.sleep(1)
    except Exception as e:
        logger.error(f"Timer error: {e}")

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a quiz question"""
    quiz_data = context.user_data.get('quiz', {})
    questions = quiz_data.get('questions', [])
    current_index = quiz_data.get('current_index', 0)
    
    if not questions or current_index >= len(questions):
        await update.message.reply_text("No questions available or quiz complete.")
        return
    
    question = questions[current_index]
    question_text = question['question']
    options = question['options']
    correct_option = question['answer']
    
    # Get negative marking for this question
    negative_marking = question.get('negative_marking', 0)
    quiz_data['negative_marking'] = negative_marking
    
    # Format question text with question number
    formatted_question = f"{current_index+1}/{len(questions)} {question_text}"
    
    # Show negative marking if enabled
    if negative_marking > 0:
        formatted_question += f" (Wrong answer: -{negative_marking} points)"
    
    # Send the poll
    message = await context.bot.send_poll(
        chat_id=update.effective_chat.id,
        question=formatted_question,
        options=options,
        type='quiz',
        correct_option_id=correct_option,
        is_anonymous=False,
        explanation=None,
    )
    
    # Store the poll ID for tracking answers
    context.user_data['quiz']['current_poll_id'] = message.poll.id
    context.user_data['quiz']['current_poll_message_id'] = message.message_id
    
    # Increment the current index
    context.user_data['quiz']['current_index'] += 1
    
    # If we're at the end of questions, schedule the end_quiz function
    if current_index == len(questions) - 1:
        # Wait for people to answer the last question
        await asyncio.sleep(5)
        await end_quiz(update, context)

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle answers to quiz polls"""
    poll_answer = update.poll_answer
    poll_id = poll_answer.poll_id
    selected_option = poll_answer.option_ids[0] if poll_answer.option_ids else None
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    
    # Get quiz data
    quiz_data = context.user_data.get('quiz', {})
    current_poll_id = quiz_data.get('current_poll_id')
    
    # Check if this is the current poll
    if poll_id == current_poll_id:
        # Get current question
        current_index = quiz_data.get('current_index', 0) - 1  # -1 because we already incremented
        questions = quiz_data.get('questions', [])
        
        if 0 <= current_index < len(questions):
            question = questions[current_index]
            correct_option = question.get('answer')
            negative_marking = quiz_data.get('negative_marking', 0)
            
            # Check if the answer is correct
            is_correct = selected_option == correct_option
            
            # Update participant data
            participants = quiz_data.get('participants', {})
            user_id_str = str(user_id)
            if user_id_str not in participants:
                participants[user_id_str] = {
                    'correct': 0, 
                    'wrong': 0,
                    'points': 0,
                    'answered': 0, 
                    'name': user_name
                }
            
            participants[user_id_str]['answered'] += 1
            
            if is_correct:
                participants[user_id_str]['correct'] += 1
                participants[user_id_str]['points'] += 1
                quiz_data['correct_count'] = quiz_data.get('correct_count', 0) + 1
            else:
                participants[user_id_str]['wrong'] += 1
                quiz_data['wrong_count'] = quiz_data.get('wrong_count', 0) + 1
                # Apply negative marking if enabled
                if negative_marking > 0:
                    participants[user_id_str]['points'] -= negative_marking
            
            # Update quiz data
            quiz_data['participants'] = participants
            context.user_data['quiz'] = quiz_data
            
            # Update user stats in database
            user_data = get_user_data(user_id)
            user_data['quizzes_taken'] = user_data.get('quizzes_taken', 0) + 1
            user_data['correct_answers'] = user_data.get('correct_answers', 0) + (1 if is_correct else 0)
            update_user_data(user_id, user_data)
            
            # If in single-question mode, check if we need to send another question
            if quiz_data.get('single_question_mode') and 'quiz' in context.user_data:
                # Get all questions
                all_questions = load_questions()
                
                # Filter out questions we've already seen
                seen_ids = [q.get('id') for q in quiz_data.get('questions', [])]
                remaining_questions = [q for q in all_questions if q.get('id') not in seen_ids]
                
                # If there are questions remaining, add a continuation button
                if remaining_questions:
                    # Choose a random next question
                    next_question = random.choice(remaining_questions)
                    
                    # Add button to continue to next question
                    keyboard = [
                        [InlineKeyboardButton("➡️ Next Question", callback_data=f"next_{next_question['id']}")]
                    ]
                    
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    # Send the "Next Question" button after a short delay
                    await asyncio.sleep(3)
                    
                    if 'quiz' in context.user_data:  # Check if quiz still exists
                        try:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text="Continue to the next question?",
                                reply_markup=reply_markup
                            )
                        except Exception as e:
                            logger.error(f"Error sending next question button: {e}")

async def continue_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'Next Question' button click"""
    query = update.callback_query
    await query.answer()
    
    # Extract the question ID from the callback data
    question_id = int(query.data.split('_')[1])
    
    # Get the question
    question = get_question_by_id(question_id)
    if not question:
        await query.edit_message_text("Error: Question not found.")
        return
    
    # Update the quiz with the new question
    if 'quiz' not in context.user_data:
        # If we don't have an active quiz, start a new one
        context.user_data['quiz'] = {
            'questions': [question],
            'current_index': 0,
            'correct_count': 0,
            'wrong_count': 0,
            'participants': {},
            'start_time': asyncio.get_event_loop().time(),
            'negative_marking': question.get('negative_marking', 0),
            'single_question_mode': True  # Flag to indicate single question mode
        }
    else:
        # Add the question to the existing quiz
        context.user_data['quiz']['questions'].append(question)
    
    # Delete the "Next Question" button
    await query.delete_message()
    
    # Send the new question
    await send_question(query, context)

async def end_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """End the quiz and show results"""
    quiz_data = context.user_data.get('quiz', {})
    if not quiz_data:
        await update.message.reply_text("No quiz in progress.")
        return
    
    questions = quiz_data.get('questions', [])
    participants = quiz_data.get('participants', {})
    
    # Calculate time taken
    start_time = quiz_data.get('start_time')
    time_taken = None
    if start_time:
        end_time = asyncio.get_event_loop().time()
        time_taken = end_time - start_time
    
    # Format results
    if not participants:
        await update.message.reply_text(
            "Quiz completed, but no one participated.\n\n"
            "Start a new quiz with /quiz or /category."
        )
        # Clean up quiz data
        context.user_data.pop('quiz', None)
        return
    
    # Sort participants by points (considering negative marking)
    sorted_participants = sorted(
        participants.items(),
        key=lambda x: (x[1]['points'], x[1]['correct'], -x[1]['answered']),
        reverse=True
    )
    
    # Generate results text with medals
    results_text = "🏁 *Quiz Results* 🏁\n\n"
    
    # Add time taken if available
    if time_taken:
        minutes, seconds = divmod(int(time_taken), 60)
        results_text += f"⏱ *Time:* {minutes}m {seconds}s\n\n"
    
    results_text += f"📊 *Questions:* {len(questions)}\n\n"
    results_text += "🏆 *Leaderboard:* 🏆\n"
    
    # Add each participant with rank and medal
    for i, (user_id, data) in enumerate(sorted_participants):
        # Award medals for top performers
        if i == 0 and len(sorted_participants) >= 1:
            medal = "🥇"
        elif i == 1 and len(sorted_participants) >= 2:
            medal = "🥈"
        elif i == 2 and len(sorted_participants) >= 3:
            medal = "🥉"
        else:
            medal = "🎯"
        
        name = data.get('name', f"User {user_id}")
        correct = data.get('correct', 0)
        wrong = data.get('wrong', 0)
        points = data.get('points', 0)
        answered = data.get('answered', 0)
        
        # Calculate score percentage
        score_pct = (correct / len(questions)) * 100 if len(questions) > 0 else 0
        
        # Add user's result line with points
        if points == correct:  # No negative marking applied
            results_text += f"{medal} *{i+1}.* {name}: {correct}/{len(questions)} ({score_pct:.1f}%)\n"
        else:
            results_text += f"{medal} *{i+1}.* {name}: {correct}/{len(questions)} ({score_pct:.1f}%) [Points: {points}]\n"
    
    # Add a footer
    results_text += "\nThanks for participating! Start another quiz with /quiz or /category."
    
    # Send results
    await update.message.reply_text(results_text, parse_mode="Markdown")
    
    # Clear quiz data
    context.user_data.pop('quiz', None)

async def delete_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a question"""
    questions = load_questions()
    if not questions:
        await update.message.reply_text("No questions available to delete.")
        return
    
    # Create inline keyboard with all questions
    keyboard = []
    for question in questions:
        q_id = question.get('id')
        q_text = question.get('question', '')
        # Truncate long questions
        if len(q_text) > 30:
            q_text = q_text[:27] + "..."
        button = InlineKeyboardButton(f"ID #{q_id}: {q_text}", callback_data=f"delete_{q_id}")
        keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a question to delete:", reply_markup=reply_markup)

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle delete confirmation callback"""
    query = update.callback_query
    await query.answer()
    
    # Extract question ID from callback data
    question_id = int(query.data.split('_')[1])
    
    # Delete the question
    success = delete_question_by_id(question_id)
    
    if success:
        await query.edit_message_text(f"Question #{question_id} deleted successfully.")
    else:
        await query.edit_message_text(f"Could not delete question #{question_id}. It may not exist.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user statistics"""
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    
    quizzes_taken = user_data.get('quizzes_taken', 0)
    correct_answers = user_data.get('correct_answers', 0)
    
    # Calculate accuracy percentage
    accuracy = (correct_answers / quizzes_taken * 100) if quizzes_taken > 0 else 0
    
    stats_text = (
        "📊 *Your Quiz Statistics* 📊\n\n"
        f"👤 *User:* {update.effective_user.first_name}\n"
        f"🎯 *Quizzes Taken:* {quizzes_taken}\n"
        f"✅ *Correct Answers:* {correct_answers}\n"
        f"📈 *Accuracy:* {accuracy:.1f}%\n\n"
        f"Keep it up! Take more quizzes with /quiz"
    )
    
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a quiz from a specific category"""
    questions = load_questions()
    
    if not questions:
        await update.message.reply_text("No questions available. Add some questions first with /add.")
        return
    
    # Get all unique categories
    categories = set(q.get('category', 'General') for q in questions)
    
    # Create inline keyboard with categories
    keyboard = []
    for cat in sorted(categories):
        count = sum(1 for q in questions if q.get('category') == cat)
        button = InlineKeyboardButton(f"{cat} ({count})", callback_data=f"cat_{cat}")
        keyboard.append([button])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a category for your quiz:", reply_markup=reply_markup)

async def send_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send the next question in the quiz"""
    quiz_data = context.user_data.get('quiz', {})
    current_index = quiz_data.get('current_index', 0)
    questions = quiz_data.get('questions', [])
    
    if current_index < len(questions):
        # Send the next question
        await send_question(update, context)
    else:
        # End the quiz if we've gone through all questions
        await end_quiz(update, context)

async def category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection callback"""
    query = update.callback_query
    await query.answer()
    
    # Extract category from callback data
    category = query.data.split('_')[1]
    
    # Get questions from the selected category
    questions = load_questions()
    category_questions = [q for q in questions if q.get('category') == category]
    
    if not category_questions:
        await query.edit_message_text(f"No questions found in category: {category}")
        return
    
    # Randomly select up to 5 questions from the category
    num_questions = min(5, len(category_questions))
    selected_questions = random.sample(category_questions, num_questions)
    
    # Set up the quiz
    context.user_data['quiz'] = {
        'questions': selected_questions,
        'current_index': 0,
        'correct_count': 0,
        'wrong_count': 0,
        'participants': {},
        'start_time': asyncio.get_event_loop().time(),
        'negative_marking': 0  # Will be updated per question
    }
    
    # Update the message to indicate quiz has started
    await query.edit_message_text(f"Starting quiz with {num_questions} questions from {category}...")
    
    # Send the timer message
    timer_msg = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="⏱ Quiz timer: 00:00"
    )
    context.user_data['quiz']['timer_message_id'] = timer_msg.message_id
    context.user_data['quiz']['timer_chat_id'] = timer_msg.chat_id
    
    # Start the timer
    asyncio.create_task(update_timer(context))
    
    # Start the quiz
    await send_question(query, context)

async def clone_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the process of cloning a quiz"""
    keyboard = [
        [InlineKeyboardButton("From URL", callback_data="clone_url")],
        [InlineKeyboardButton("Enter manually", callback_data="clone_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "How would you like to clone a quiz?\n\n"
        "• From URL: Paste a link to a Telegram quiz\n"
        "• Enter manually: Type question and options",
        reply_markup=reply_markup
    )
    context.user_data['clone_state'] = 'waiting_for_method'
    return ConversationHandler.END  # We'll handle transitions via callbacks

async def clone_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle clone method selection"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "clone_url":
        await query.edit_message_text(
            "Please send me a URL to the Telegram quiz you want to clone. "
            "This can be a shared link to a poll or quiz message."
        )
        context.user_data['clone_state'] = 'waiting_for_url'
        return CLONE_URL
    elif query.data == "clone_manual":
        await query.edit_message_text(
            "Please send me the question for your quiz."
        )
        context.user_data['clone_state'] = 'waiting_for_question'
        return CLONE_MANUAL
    
    return ConversationHandler.END

async def clone_from_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle URL input for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_url':
        return ConversationHandler.END
    
    url = update.message.text.strip()
    
    # Show processing message
    processing_message = await update.message.reply_text("🔄 Processing quiz from URL...")
    
    # Try to extract quiz from URL
    quiz_data = parse_telegram_quiz_url(url)
    
    if not quiz_data:
        await processing_message.edit_text(
            "❌ Could not extract quiz data from this URL. Please make sure it's a valid Telegram quiz link. "
            "You can try again or use /cancel to stop."
        )
        return CLONE_URL
    
    # Store quiz data
    context.user_data['clone_question'] = quiz_data['question']
    context.user_data['clone_options'] = quiz_data['options']
    
    # Display extracted quiz
    options_text = "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(quiz_data['options'])])
    
    await processing_message.edit_text(
        f"✅ Quiz extracted successfully!\n\n"
        f"*Question:* {quiz_data['question']}\n\n"
        f"*Options:*\n{options_text}\n\n"
        f"Which option is correct? Enter the letter (A, B, C, etc.) or number (1, 2, 3, etc.).",
        parse_mode="Markdown"
    )
    
    context.user_data['clone_state'] = 'waiting_for_answer'
    return CLONE_ANSWER

async def clone_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle manual question input for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_question':
        return ConversationHandler.END
    
    question_text = update.message.text.strip()
    context.user_data['clone_question'] = question_text
    
    await update.message.reply_text(
        f"Question: {question_text}\n\n"
        f"Please send me all options separated by new lines:\n"
        f"Option 1\n"
        f"Option 2\n"
        f"Option 3\n"
        f"Option 4"
    )
    
    context.user_data['clone_state'] = 'waiting_for_options'
    return CLONE_OPTIONS

async def clone_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle options input for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_options':
        return ConversationHandler.END
    
    options_text = update.message.text.strip()
    options = [line.strip() for line in options_text.split('\n') if line.strip()]
    
    if len(options) < 2:
        await update.message.reply_text(
            "❌ Not enough options. I need at least 2 options. Please try again."
        )
        return CLONE_OPTIONS
    
    context.user_data['clone_options'] = options
    
    # Display options as an alphabetical list
    formatted_options = "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(options)])
    
    await update.message.reply_text(
        f"Options received:\n\n{formatted_options}\n\n"
        f"Which option is correct? Enter the letter (A, B, C, etc.) or number (1, 2, 3, etc.)."
    )
    
    context.user_data['clone_state'] = 'waiting_for_answer'
    return CLONE_ANSWER

async def clone_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle correct answer selection for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_answer':
        return ConversationHandler.END
    
    answer_text = update.message.text.strip().upper()
    options = context.user_data.get('clone_options', [])
    
    # Convert letter (A, B, C) or number (1, 2, 3) to index
    if answer_text.isalpha() and len(answer_text) == 1:
        answer = ord(answer_text) - ord('A')  # A->0, B->1, etc.
    elif answer_text.isdigit():
        answer = int(answer_text) - 1  # Convert from 1-based to 0-based
    else:
        await update.message.reply_text(
            f"❌ Invalid format. Please enter a letter (A, B, C) or number (1, 2, 3)."
        )
        return CLONE_ANSWER
    
    if answer < 0 or answer >= len(options):
        await update.message.reply_text(
            f"❌ Invalid answer. Please enter a valid option between A and {chr(ord('A') + len(options) - 1)} "
            f"or between 1 and {len(options)}."
        )
        return CLONE_ANSWER
    
    # Store answer
    context.user_data['clone_answer'] = answer
    
    # Ask about ID
    keyboard = [
        [InlineKeyboardButton("Auto-generated ID", callback_data="cloneid_auto")],
        [InlineKeyboardButton("Custom ID", callback_data="cloneid_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Would you like to use an auto-generated ID or set a custom ID?",
        reply_markup=reply_markup
    )
    
    context.user_data['clone_state'] = 'waiting_for_id_choice'
    return CLONE_ID

async def clone_id_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ID choice for cloning"""
    query = update.callback_query
    await query.answer()
    
    if context.user_data.get('clone_state') != 'waiting_for_id_choice':
        await query.edit_message_text("Error: Clone process is not in the right state. Please start over with /clone.")
        return
    
    id_choice = query.data.split('_')[1]
    
    if id_choice == "auto":
        # Use auto ID
        context.user_data['clone_id'] = None
        
        # Now ask for category
        # Get all unique categories
        questions = load_questions()
        categories = sorted(set(q.get('category', 'General') for q in questions))
        if not categories:
            categories = ['General']
        
        # Create keyboard with categories
        keyboard = []
        for i, category in enumerate(categories):
            button = InlineKeyboardButton(category, callback_data=f"clonecat_{category}")
            if i % 2 == 0:  # Two categories per row
                keyboard.append([button])
            else:
                keyboard[-1].append(button)
        
        # Add "New Category" button
        keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="clonecat_new")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Please select a category for this question:",
            reply_markup=reply_markup
        )
        
        context.user_data['clone_state'] = 'waiting_for_category'
    else:
        # Ask for custom ID
        await query.edit_message_text(
            "Please reply with the custom ID number you want to use for this question."
        )
        context.user_data['clone_state'] = 'waiting_for_custom_id'

async def clone_custom_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID input for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_custom_id':
        return
    
    try:
        custom_id = int(update.message.text.strip())
        if custom_id <= 0:
            await update.message.reply_text(
                "❌ ID must be a positive number. Please try again."
            )
            return
        
        # Store custom ID
        context.user_data['clone_id'] = custom_id
        
        # Now ask for category
        # Get all unique categories
        questions = load_questions()
        categories = sorted(set(q.get('category', 'General') for q in questions))
        if not categories:
            categories = ['General']
        
        # Create keyboard with categories
        keyboard = []
        for i, category in enumerate(categories):
            button = InlineKeyboardButton(category, callback_data=f"clonecat_{category}")
            if i % 2 == 0:  # Two categories per row
                keyboard.append([button])
            else:
                keyboard[-1].append(button)
        
        # Add "New Category" button
        keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="clonecat_new")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Using custom ID: {custom_id}\n\n"
            f"Please select a category for this question:",
            reply_markup=reply_markup
        )
        
        context.user_data['clone_state'] = 'waiting_for_category'
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid ID format. Please enter a number."
        )

async def clone_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection callback for cloning"""
    query = update.callback_query
    await query.answer()
    
    if context.user_data.get('clone_state') != 'waiting_for_category':
        await query.edit_message_text("Error: Clone process is not in the right state. Please start over with /clone.")
        return
    
    # Extract category from callback data
    category = query.data.split('_')[1]
    
    if category == "new":
        # Ask user to enter a new category
        await query.edit_message_text(
            "Please reply with the name of the new category you want to create."
        )
        context.user_data['clone_state'] = 'waiting_for_new_category'
        return
    
    # Save the cloned question with the selected category
    await save_cloned_question(query, context, category)

async def clone_new_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle new category input for cloning"""
    if context.user_data.get('clone_state') != 'waiting_for_new_category':
        return
    
    new_category = update.message.text.strip()
    
    # Validate the category name
    if not new_category or len(new_category) > 50:
        await update.message.reply_text(
            "❌ Category name must be between 1 and 50 characters. Please try again."
        )
        return
    
    # Save the cloned question with the new category
    await save_cloned_question(update, context, new_category)

async def save_cloned_question(update, context, category):
    """Save the cloned question with the given category"""
    # Get clone data
    question_text = context.user_data.get('clone_question')
    options = context.user_data.get('clone_options', [])
    answer = context.user_data.get('clone_answer', 0)
    custom_id = context.user_data.get('clone_id')
    
    if not question_text or not options:
        message_text = "Error: Missing question data. Please start over with /clone."
        if isinstance(update, Update):
            await update.message.reply_text(message_text)
        else:  # CallbackQuery
            await update.edit_message_text(message_text)
        return
    
    # Create new question
    question_id = custom_id if custom_id is not None else get_next_question_id()
    new_question = {
        "id": question_id,
        "question": question_text,
        "options": options,
        "answer": answer,
        "category": category,
        "negative_marking": 0  # Default no negative marking
    }
    
    # Load existing questions
    questions = load_questions()
    
    # Check if ID already exists
    if custom_id is not None:
        existing_question = next((q for q in questions if q.get("id") == custom_id), None)
        if existing_question:
            # Replace the existing question
            for i, q in enumerate(questions):
                if q.get("id") == custom_id:
                    questions[i] = new_question
                    break
        else:
            # Add as new question
            questions.append(new_question)
    else:
        # Add as new question with auto ID
        questions.append(new_question)
    
    # Save questions
    save_questions(questions)
    
    # Format success message
    correct_letter = chr(ord('A') + answer)
    success_message = (
        f"✅ Question cloned successfully with ID #{question_id}!\n\n"
        f"*Question:* {question_text}\n\n"
        f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(options)]) + "\n\n"
        f"*Correct answer:* {correct_letter}. {options[answer]}\n"
        f"*Category:* {category}\n\n"
        f"You can use /clone to clone another question or /quiz to start a quiz."
    )
    
    # Send success message
    if isinstance(update, Update):
        await update.message.reply_text(success_message, parse_mode="Markdown")
    else:  # CallbackQuery
        await update.edit_message_text(success_message, parse_mode="Markdown")
    
    # Clear clone data
    context.user_data.pop('clone_question', None)
    context.user_data.pop('clone_options', None)
    context.user_data.pop('clone_answer', None)
    context.user_data.pop('clone_id', None)
    context.user_data.pop('clone_state', None)

# Function to handle the /poll2q command
async def poll_to_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Convert a Telegram poll to a quiz question with enhanced styling"""
    # Check if the command was a reply to a poll message
    message = update.message
    custom_id = None
    batch_mode = False
    
    # Check for command arguments
    if context.args:
        for arg in context.args:
            if arg.lower() == "batch":
                batch_mode = True
                context.user_data['batch_mode'] = True
            elif arg.startswith("id="):
                custom_id = int(arg.split('=')[1])
                context.user_data['custom_id_preset'] = custom_id
            elif arg.startswith("start="):
                start_id = int(arg.split('=')[1])
                context.user_data['next_id_start'] = start_id
    
    if not message.reply_to_message:
        await message.reply_text(
            "⚠️ Please reply to a poll message with this command.\n\n"
            "For example:\n"
            "1. Find a poll/quiz in any Telegram chat\n"
            "2. Reply to it with the command /poll2q\n\n"
            "*Advanced Options:*\n"
            "• `/poll2q id=123` - Use specific ID #123\n"
            "• `/poll2q start=50` - Start from ID #50\n"
            "• `/poll2q batch` - Process multiple polls\n\n"
            "This will convert the poll to a saved quiz question.",
            parse_mode="Markdown"
        )
        return
    
    # Check if the replied message is a poll
    poll = message.reply_to_message.poll
    if not poll:
        await message.reply_text("The message you replied to is not a poll. Please reply to a poll message.")
        return
    
    # Extract poll data
    question_text = poll.question
    options = [option.text for option in poll.options]
    
    # Store in user data for later processing
    context.user_data['poll_data'] = {
        'question': question_text,
        'options': options,
        'custom_id': custom_id  # Store custom ID if provided
    }
    
    # Create keyboard for selecting correct answer
    keyboard = []
    for i, option in enumerate(options):
        # Truncate long options
        display_option = option if len(option) < 30 else option[:27] + "..."
        keyboard.append([InlineKeyboardButton(
            f"{chr(ord('A') + i)}. {display_option}", 
            callback_data=f"poll_answer_{i}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        "📝 *Converting Poll to Question*\n\n"
        f"*Question:* {question_text}\n\n"
        "*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(options)]) + "\n\n"
        "👇 Please select the *correct answer* from the options below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_poll_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the selection of correct answer for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract answer index from callback data
    answer_index = int(query.data.split('_')[-1])
    
    # Get the stored poll data
    poll_data = context.user_data.get('poll_data', {})
    if not poll_data:
        await query.edit_message_text("Error: Poll data not found. Please try again.")
        return
    
    # Add the answer to the poll data
    poll_data['answer'] = answer_index
    context.user_data['poll_data'] = poll_data
    
    # Check if we have a custom ID preset
    if 'custom_id_preset' in context.user_data:
        custom_id = context.user_data['custom_id_preset']
        # Use this ID directly
        await save_poll_as_question(update, context, poll_data['question'], poll_data['options'], answer_index)
        return
    
    # Get all unique categories from existing questions
    questions = load_questions()
    categories = sorted(set(q.get('category', 'General') for q in questions))
    if not categories:
        categories = ['General']
    
    # Create category selection buttons
    keyboard = []
    for i, category in enumerate(categories):
        button = InlineKeyboardButton(category, callback_data=f"pollcat_{category}")
        if i % 2 == 0:  # Two categories per row
            keyboard.append([button])
        else:
            keyboard[-1].append(button)
    
    # Add "New Category" button
    keyboard.append([InlineKeyboardButton("➕ New Category", callback_data="pollcat_new")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "✅ Correct answer selected!\n\n"
        f"*Question:* {poll_data['question']}\n"
        f"*Correct Answer:* {poll_data['options'][answer_index]}\n\n"
        "📂 Please select a category for this question:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def save_poll_as_question(update, context, question_text, options, correct_answer):
    """Save poll data as a quiz question"""
    # Set default category
    category = context.user_data.get('poll_category', 'General')
    
    # Ask about ID method (unless we already have a preset ID)
    if 'custom_id_preset' in context.user_data:
        custom_id = context.user_data['custom_id_preset']
        del context.user_data['custom_id_preset']
        await save_final_poll_question(update, context, custom_id)
    else:
        # Ask about ID method
        keyboard = [
            [InlineKeyboardButton("🔢 Auto ID", callback_data="pollid_auto")],
            [InlineKeyboardButton("🔍 Select Existing ID", callback_data="pollid_select")],
            [InlineKeyboardButton("✏️ Custom ID", callback_data="pollid_custom")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if isinstance(update, Update):
            await update.message.reply_text(
                "🆔 Choose an ID method for this question:",
                reply_markup=reply_markup
            )
        else:  # It's a CallbackQuery
            await update.edit_message_text(
                "🆔 Choose an ID method for this question:",
                reply_markup=reply_markup
            )

async def handle_poll_category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle category selection for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    # Extract category from callback data
    category = query.data.split('_')[1]
    
    if category == "new":
        # Ask user to enter a new category
        await query.edit_message_text(
            "Please reply with the name of the new category you want to create."
        )
        # Set a flag to expect a new category input
        context.user_data['awaiting_new_category'] = True
    else:
        # Store the selected category
        context.user_data['poll_category'] = category
        
        # Move to ID selection
        await save_poll_as_question(query, context, 
                                   context.user_data['poll_data']['question'],
                                   context.user_data['poll_data']['options'],
                                   context.user_data['poll_data']['answer'])

async def handle_poll_id_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ID method selection for poll conversion"""
    query = update.callback_query
    await query.answer()
    
    method = query.data.split('_')[1]
    
    if method == "auto":
        # Use auto-generated ID
        await save_final_poll_question(query, context)
    elif method == "select":
        # Show existing IDs to choose from
        questions = load_questions()
        if not questions:
            await query.edit_message_text("No existing questions found. Using auto-generated ID instead.")
            await save_final_poll_question(query, context)
            return
        
        # Get all IDs
        ids = sorted([q.get('id', 0) for q in questions])
        
        # Create buttons for IDs, in rows of 5
        buttons = []
        current_row = []
        for i, qid in enumerate(ids[-20:]):  # Show last 20 IDs
            current_row.append(InlineKeyboardButton(str(qid), callback_data=f"pollid_use_{qid}"))
            if (i + 1) % 5 == 0 or i == len(ids) - 1:  # New row every 5 buttons or at the end
                buttons.append(current_row)
                current_row = []
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        await query.edit_message_text(
            "Select an ID to use for this question (most recent IDs shown):",
            reply_markup=reply_markup
        )
    elif method == "custom":
        # Let user enter custom ID
        await query.edit_message_text(
            "Please reply with the custom ID number you want to use for this question."
        )
        
        # Set flag to expect custom ID input
        context.user_data['awaiting_custom_id'] = True

async def handle_poll_custom_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID button selection callbacks"""
    query = update.callback_query
    await query.answer()
    
    custom_type = query.data.split('_')[1]
    
    if custom_type == "use":
        # User wants to use an existing ID
        selection = query.data.split('_')[2]
        try:
            custom_id = int(selection)
            # Check if this ID exists
            question = get_question_by_id(custom_id)
            if question:
                await query.edit_message_text(f"You're replacing an existing question with ID #{custom_id}.")
            
            await save_final_poll_question(query, context, custom_id)
        except ValueError:
            await query.edit_message_text("Invalid ID format. Using auto-generated ID instead.")
            await save_final_poll_question(query, context)
    else:
        # Unknown selection
        await query.edit_message_text("Unknown selection. Using auto-generated ID instead.")
        await save_final_poll_question(query, context)

async def handle_poll_use_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle selection of an existing ID to use"""
    query = update.callback_query
    await query.answer()
    
    # Get the ID from callback data
    id_str = query.data.split('_')[-1]
    selected_id = int(id_str)
    
    # Use this ID for the new question
    await save_final_poll_question(query, context, selected_id)

async def handle_custom_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle custom ID input for poll conversion"""
    # Check if we're awaiting a custom ID
    if context.user_data.get('awaiting_custom_id', False):
        try:
            custom_id = int(update.message.text.strip())
            if custom_id <= 0:
                await update.message.reply_text("ID must be a positive number. Using auto-generated ID instead.")
                await save_final_poll_question(update, context)
            else:
                await save_final_poll_question(update, context, custom_id)
        except ValueError:
            await update.message.reply_text("Invalid ID format. Please enter a number.")
        return
        
    # Check if we're awaiting a new category for a poll
    if context.user_data.get('awaiting_new_category', False):
        new_category = update.message.text.strip()
        if not new_category:
            await update.message.reply_text("Category name cannot be empty. Please try again.")
            return
            
        # Store the new category
        context.user_data['poll_category'] = new_category
        context.user_data['awaiting_new_category'] = False
        
        # Continue with ID selection
        await save_poll_as_question(update, context, 
                                  context.user_data['poll_data']['question'],
                                  context.user_data['poll_data']['options'],
                                  context.user_data['poll_data']['answer'])
        return
        
    # Handle clone custom ID input
    if context.user_data.get('clone_state') == 'waiting_for_custom_id':
        await clone_custom_id(update, context)
        return
        
    # Handle clone new category input
    if context.user_data.get('clone_state') == 'waiting_for_new_category':
        await clone_new_category(update, context)
        return

    # Handle different ID for addq
    if context.user_data.get('awaiting_different_id', False):
        text = update.message.text.strip().lower()
        if text == "auto":
            custom_id = get_next_question_id()
        else:
            try:
                custom_id = int(text)
                if custom_id <= 0:
                    await update.message.reply_text("ID must be a positive number. Using auto-generated ID instead.")
                    custom_id = get_next_question_id()
            except ValueError:
                await update.message.reply_text("Invalid ID format. Using auto-generated ID instead.")
                custom_id = get_next_question_id()
        
        # Get the question data
        data = context.user_data.get("addq_data", {})
        if not data:
            await update.message.reply_text("Error: Question data not found. Please start over with /addq.")
            return
        
        # Create and save the question
        question = {
            "id": custom_id,
            "question": data["question"],
            "options": data["options"],
            "answer": data["answer"],
            "category": data["category"],
            "negative_marking": data["negative_marking"]
        }
        
        # Load existing questions
        questions = load_questions()
        
        # Check if ID already exists
        existing_question = next((q for q in questions if q.get("id") == custom_id), None)
        if existing_question:
            # Replace the existing question
            for i, q in enumerate(questions):
                if q.get("id") == custom_id:
                    questions[i] = question
                    break
        else:
            # Add as new question
            questions.append(question)
        
        # Save questions
        save_questions(questions)
        
        # Format the correct answer display
        correct_option = data["answer"]
        correct_letter = chr(ord('A') + correct_option)
        correct_text = data["options"][correct_option]
        
        await update.message.reply_text(
            f"✅ Question saved successfully with ID #{custom_id}.\n\n"
            f"*Question:* {data['question']}\n\n"
            f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(data['options'])]) + "\n\n"
            f"*Correct answer:* {correct_letter}. {correct_text}\n"
            f"*Category:* {data['category']}\n"
            f"*Negative marking:* {data['negative_marking']}\n\n"
            f"You can use /addq to add another question or /quiz to start a quiz.",
            parse_mode="Markdown"
        )
        
        # Clear the user data
        context.user_data.clear()
        return

async def save_final_poll_question(update, context, custom_id=None):
    """Save the final question with all data"""
    # Get the poll data
    poll_data = context.user_data.get('poll_data', {})
    if not poll_data:
        message_text = "Error: Poll data not found. Please try again."
        if isinstance(update, Update):
            await update.message.reply_text(message_text)
        else:  # CallbackQuery
            await update.edit_message_text(message_text)
        return
    
    # Create new question object
    new_question = {
        "question": poll_data['question'],
        "options": poll_data['options'],
        "answer": poll_data['answer'],
        "category": context.user_data.get('poll_category', 'General'),
        "negative_marking": 0  # Default no negative marking
    }
    
    # Set ID (custom or auto-generated)
    if custom_id is not None:
        new_question["id"] = custom_id
    else:
        # Get next available ID
        next_id_start = context.user_data.get('next_id_start', None)
        if next_id_start:
            new_question["id"] = next_id_start
            context.user_data['next_id_start'] = next_id_start + 1
        else:
            new_question["id"] = get_next_question_id()
    
    # Load existing questions
    questions = load_questions()
    
    # Check if this ID already exists
    existing_question = next((q for q in questions if q.get('id') == new_question['id']), None)
    if existing_question:
        # Replace existing question
        for i, q in enumerate(questions):
            if q.get('id') == new_question['id']:
                questions[i] = new_question
                break
    else:
        # Add new question
        questions.append(new_question)
    
    # Save questions
    save_questions(questions)
    
    # Clean up context data
    if 'awaiting_custom_id' in context.user_data:
        del context.user_data['awaiting_custom_id']
    if 'poll_data' in context.user_data:
        del context.user_data['poll_data']
    if 'poll_category' in context.user_data:
        del context.user_data['poll_category']
    
    # Prepare success message
    correct_letter = chr(ord('A') + new_question['answer'])
    success_message = (
        f"✅ Question saved successfully with ID #{new_question['id']}!\n\n"
        f"*Question:* {new_question['question']}\n\n"
        f"*Options:*\n" + "\n".join([f"{chr(ord('A') + i)}. {opt}" for i, opt in enumerate(new_question['options'])]) + "\n\n"
        f"*Correct Answer:* {correct_letter}. {new_question['options'][new_question['answer']]}\n"
        f"*Category:* {new_question['category']}\n\n"
    )
    
    # Check if batch mode is active
    batch_mode = context.user_data.get('batch_mode', False)
    if batch_mode:
        success_message += "Batch mode is active. Reply to another poll with /poll2q to continue adding questions."
    else:
        success_message += "Use /quiz to start a quiz with your saved questions!"
    
    # Send success message
    if isinstance(update, Update):
        await update.message.reply_text(success_message, parse_mode="Markdown")
    else:  # CallbackQuery
        await update.edit_message_text(success_message, parse_mode="Markdown")

async def test_results_display():
    """Test function to verify quiz results display properly"""
    # Create mock objects
    class MockMessage:
        async def reply_text(self, text, **kwargs):
            print(f"MOCK REPLY: {text}")
            return None
    
    class MockUpdate:
        message = MockMessage()
    
    class MockContext:
        user_data = {
            'quiz': {
                'questions': [
                    {'id': 1, 'question': 'Test Q1', 'options': ['A', 'B', 'C'], 'answer': 0},
                    {'id': 2, 'question': 'Test Q2', 'options': ['D', 'E', 'F'], 'answer': 1},
                ],
                'participants': {
                    '1234': {'name': 'Alice', 'correct': 2, 'wrong': 0, 'points': 2, 'answered': 2},
                    '5678': {'name': 'Bob', 'correct': 1, 'wrong': 1, 'points': 0.5, 'answered': 2},
                    '9012': {'name': 'Charlie', 'correct': 0, 'wrong': 1, 'points': -0.5, 'answered': 1},
                },
                'start_time': 0,  # Dummy value
                'negative_marking': 0.5,
            }
        }
    
    mock_update = MockUpdate()
    mock_context = MockContext()
    
    # Call end_quiz with our mock objects
    await end_quiz(mock_update, mock_context)

def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add conversation handler for adding questions (step by step)
    add_question_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_question)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_question)],
            OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_options)],
            ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_answer)],
            NEGATIVE_MARKING: [CallbackQueryHandler(receive_negative_marking, pattern=r"^negative_")],
            CUSTOM_ID: [
                CallbackQueryHandler(receive_id_choice, pattern=r"^id_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_id)
            ],
            CATEGORY: [
                CallbackQueryHandler(receive_category, pattern=r"^addcat_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_category)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_question_handler)
    
    # Add conversation handler for adding questions (all at once)
    add_question_full_handler = ConversationHandler(
        entry_points=[CommandHandler("addq", add_question_full)],
        states={
            ADD_QUESTION_FULL: [MessageHandler(filters.TEXT & ~filters.COMMAND, parse_full_question)],
            ADD_QUESTION_CUSTOM_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_question_handle_custom_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_question_full_handler)
    
    # Add conversation handler for cloning
    clone_handler = ConversationHandler(
        entry_points=[CommandHandler("clone", clone_start)],
        states={
            CLONE_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_from_url)],
            CLONE_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_manual)],
            CLONE_OPTIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_options)],
            CLONE_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, clone_answer)],
            CLONE_ID: [
                CallbackQueryHandler(clone_id_callback, pattern=r"^cloneid_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, clone_custom_id)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(clone_handler)
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("quiz", quiz))
    application.add_handler(CommandHandler("delete", delete_question))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("category", category))
    application.add_handler(CommandHandler("poll2q", poll_to_question))
    
    # Add callback handlers
    application.add_handler(CallbackQueryHandler(delete_callback, pattern=r"^delete_"))
    application.add_handler(CallbackQueryHandler(category_callback, pattern=r"^cat_"))
    application.add_handler(CallbackQueryHandler(clone_method_callback, pattern=r"^clone_"))
    application.add_handler(CallbackQueryHandler(clone_category_callback, pattern=r"^clonecat_"))
    application.add_handler(CallbackQueryHandler(continue_quiz, pattern=r"^next_"))
    application.add_handler(CallbackQueryHandler(addq_callback, pattern=r"^addq_"))
    
    # Add poll handlers
    application.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # Add poll2q related callback handlers
    application.add_handler(CallbackQueryHandler(handle_poll_answer_callback, pattern=r"^poll_answer_"))
    application.add_handler(CallbackQueryHandler(handle_poll_category_selection, pattern=r"^pollcat_"))
    application.add_handler(CallbackQueryHandler(handle_poll_id_selection, pattern=r"^pollid_"))
    application.add_handler(CallbackQueryHandler(handle_poll_custom_selection, pattern=r"^pollcustom_"))
    application.add_handler(CallbackQueryHandler(handle_poll_use_id, pattern=r"^pollid_use_"))
    
    # Add handler for custom ID input and new category input
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.UpdateType.MESSAGE,
        handle_custom_id_input
    ))
    
    # Start the Bot
    application.run_polling()

if __name__ == "__main__":
    main()