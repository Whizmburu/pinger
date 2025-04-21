# config.py

import os

# Bot token
TELEGRAM_BOT_TOKEN     = os.getenv('TELEGRAM_BOT_TOKEN')

# Admin
ADMIN_ID               = int(os.getenv('ADMIN_ID', '7612857358'))
ADMIN_USERNAME         = os.getenv('ADMIN_USERNAME', 'YourTelegramUsername')

# Update channel
UPDATE_CHANNEL         = os.getenv('UPDATE_CHANNEL', '@whiz_t')

# Storage
DB_FILE                = os.getenv('DB_FILE', 'users.json')
DOWNLOAD_DIR           = os.getenv('DOWNLOAD_DIR', 'downloads')

# Limits & TTLs
TELEGRAM_MAX_FILE_SIZE = int(os.getenv('TELEGRAM_MAX_FILE_SIZE', 50 * 1024 * 1024))
HOURLY_LIMIT           = int(os.getenv('HOURLY_LIMIT', 5))
FILE_TTL               = int(os.getenv('FILE_TTL', 3600))  # seconds
