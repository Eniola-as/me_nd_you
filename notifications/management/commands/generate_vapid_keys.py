"""Print a new VAPID key pair for push notifications. Set them as the
VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY environment variables (on Render: the
service's Environment tab). Run it once: a new pair unsubscribes every
device. Nothing is stored or sent anywhere."""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Command(BaseCommand):
    help = "Print a new VAPID key pair for push notifications."

    def handle(self, *args, **options):
        key = ec.generate_private_key(ec.SECP256R1())  # The curve Web Push uses.
        private = key.private_numbers().private_value.to_bytes(32, "big")
        public = key.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f"VAPID_PUBLIC_KEY={b64url(public)}")
        self.stdout.write(f"VAPID_PRIVATE_KEY={b64url(private)}")
        self.stdout.write("Keep the private key secret. Changing the pair later unsubscribes every device.")
