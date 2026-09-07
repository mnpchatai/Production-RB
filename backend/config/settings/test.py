from .dev import *  # noqa: F403

# เทสต์ต้องรันบน PostgreSQL จริงเท่านั้น (ดู CLAUDE.md หัวข้อ "เทสต์")
# เพราะ select_for_update และ numeric ทำงานไม่เหมือน SQLite
DATABASES["default"]["NAME"] = os.environ.get("POSTGRES_DB", "mes")  # noqa: F405
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
