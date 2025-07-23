# Schedule Pipeline Telegram Bot

A Telegram bot for parsing, storing, and providing university class schedules. The bot allows users to request their group schedule and provides an admin interface for broadcasting messages. It supports schedule extraction from PDF files, database storage, and user-friendly Telegram interactions.

## Features
- **Telegram Bot**: Users can request their group schedule by sending their group number.
- **PDF Schedule Parsing**: Extracts schedule data from university PDF files.
- **Database Storage**: Stores lessons, streams, student groups, and users in a relational database (SQLite by default).
- **Admin Broadcast**: Sends startup and broadcast messages to admin users.
- **Schedule Downloader**: Downloads and parses schedules from university websites.
- **Async & Modern Python**: Built with `aiogram`, `SQLAlchemy`, and async best practices.

## Project Structure
```
main.py                      # Entry point for the bot
config.py                    # Configuration and environment variables
requirements.txt             # Python dependencies
alembic.ini                  # Alembic migration config
infrastructure/              # Database models, migrations, and setup
parsers/                     # PDF and data parsers, schedule downloader
common/                      # Shared utilities (e.g., academic calendar)
tgbot/                       # Telegram bot handlers, middlewares, services
```

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/gurumbay/schedule-pipeline
cd schedule-pipeline
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the project root with the following variables:
```
BOT_TOKEN=<your-telegram-bot-token>
ADMINS=<list-of-admin-ids>
USE_REDIS=False
DB_HOST=localhost
POSTGRES_PASSWORD=yourpassword
POSTGRES_USER=youruser
POSTGRES_DB=yourdb
DB_PORT=5432
REDIS_PASSWORD=yourredispassword
REDIS_PORT=6379
REDIS_HOST=localhost
```
*Note: By default, the project uses SQLite for local development. For production, configure PostgreSQL and Redis as needed.*

### 4. Run Database Migrations
```bash
alembic upgrade head
```

### 5. Run the Bot
```bash
python main.py
```

## Usage
- **Start the bot**: Send `/start` in Telegram to the bot.
- **Get schedule**: Send your group number (e.g., `153 А`) to receive the current week's schedule.
- **Admin broadcast**: Admins receive a startup notification when the bot launches.

## Schedule Parsing & Downloading
- **PDF Parsing**: Place schedule PDF files in a directory and use the provided parsers to extract and load data into the database.
- **Automated Download**: Use `parsers/schedules_downloader.py` to fetch schedules from the university website.

## Project Dependencies
- `aiogram` - Telegram bot framework
- `alembic` - Database migrations
- `aiosqlite` - Async SQLite driver
- `aiohttp` - Async HTTP client
- `beautifulsoup4` - HTML parsing
- `environs` - Environment variable management
- `pandas` - Data processing
- `pdfplumber` - PDF table extraction
- `redis` - Redis support (optional)
- `SQLAlchemy` - ORM

## Development & Contribution
- Follow PEP8 and best async practices.
- Use Alembic for database migrations.
- PRs and issues are welcome!

## License
MIT License 