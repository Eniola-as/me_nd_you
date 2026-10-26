from django.core.management.base import BaseCommand

from game.models import CoupleSession


class Command(BaseCommand):
    help = "Delete couple sessions (and their custom questions) inactive for 30+ days."

    def handle(self, *args, **options):
        count, _ = CoupleSession.inactive().delete()
        self.stdout.write(f"Deleted {count} objects from inactive sessions.")
