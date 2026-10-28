"""Chat tests run with a key generated for this test run; no real key is
ever in the repository."""

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings

from couples import services as couples

TEST_KEY = Fernet.generate_key().decode()
with_chat_key = override_settings(CHAT_ENCRYPTION_KEYS=[TEST_KEY])
PASSWORD = "a-long-passphrase-1"


def make_couple(*emails):
    users = [get_user_model().objects.create_user(email=e, password=PASSWORD, display_name=e.split("@")[0].title())
             for e in emails]
    couple = couples.create_couple(users[0])
    for user in users[1:]:
        couples.redeem_invitation(user, couples.create_invitation(users[0]))
    return couple, users
