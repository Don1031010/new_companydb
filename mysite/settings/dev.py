import os

from .base import *

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Read secret key from environment; fall back to insecure default for convenience.
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-)xf_=)=3rr_$o+q85*y3jm2j4d@&acap!nt7f0@jom#z5db)k^",
)

# SECURITY WARNING: define the correct hosts in production!
ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


try:
    from .local import *
except ImportError:
    pass
