"""
Django settings for deaddrop project.

Generated by 'django-admin startproject' using Django 4.2.7.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
MEDIA_ROOT = os.path.join(BASE_DIR, 'media') # Here
MEDIA_URL = '/media/'


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "django-insecure-&h=!n9a_qro&o^zb-^d@_9(avb*cte^dw796a0*0=#b2pp2$!e"

# The server's public and private key as PEM-encoded Ed25519 keys, in base64.
# When not set, message signing is not performed (though this is up to the
# agent's protocols).
SERVER_PUBLIC_KEY = os.environ.get("SERVER_PUBLIC_KEY", "")
SERVER_PRIVATE_KEY = os.environ.get("SERVER_PRIVATE_KEY", "")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Allow the container hosts
ALLOWED_HOSTS = [
    'backend',
    'localhost',
    '127.0.0.1'
]


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "backend.apps.BackendConfig",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    "django_celery_results"
]

REST_FRAMEWORK = {
    'DEFAULT_FILTER_BACKENDS': [
        'backend.filters.AllDjangoFilterBackend'
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # 'rest_framework.authentication.TokenAuthentication',
        # 'rest_framework.authentication.SessionAuthentication'
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        # 'rest_framework.permissions.IsAuthenticated',
    ]
}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",

]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    'http://127.0.0.1:5173', # Svelte (same machine)
    'http://frontend:5173', # Svelte (in Docker)
]

ROOT_URLCONF = "deaddrop.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "deaddrop.wsgi.application"


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
# https://testdriven.io/blog/dockerizing-django-with-postgres-gunicorn-and-nginx/
#
# This defaults to the sqlite database by default, but effectively allows
# the Postgres database to be declared through environment variables.
DATABASES = {
    "default": {
        "ENGINE": os.environ.get("SQL_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.environ.get("SQL_DATABASE", BASE_DIR / "db.sqlite3"),
        "USER": os.environ.get("SQL_USER", "user"),
        "PASSWORD": os.environ.get("SQL_PASSWORD", "password"),
        "HOST": os.environ.get("SQL_HOST", "localhost"),
        "PORT": os.environ.get("SQL_PORT", "5432"),
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "US/Pacific"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = "static/"

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery stuff
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_BACKEND", "redis://redis:6379/0") # this should be django db

# CELERY_TASK_SERIALIZER = 'pickle'
# CELERY_ACCEPT_CONTENT = ['json', 'pickle']
# Note that the above is, naturally, quite risky. Avoid as long as possible.

CELERY_RESULT_BACKEND = 'django-db'
CELERY_CACHE_BACKEND = 'django-cache'

# https://github.com/celery/django-celery-results/issues/130#issuecomment-583319233
# This does track if the task is started and correctly creates a TaskResult,
# but it's missing a lot of information. The method used in tasks.py is preferred
# instead.
# CELERY_TASK_TRACK_STARTED = True

# https://github.com/celery/django-celery-results/issues/326
# Fixes the task name and arguments getting overwritten with None after the task
# finishes.
CELERY_RESULT_EXTENDED = True

# Default directories for the package manager
AGENT_PACKAGE_DIR = "packages/agents"
PROTOCOL_PACKAGE_DIR = "packages/protocols"

