from django.core.management.base import BaseCommand

from accounts.deletion import purge_due


class Command(BaseCommand):
    help = ("Permanently delete accounts deleted over 7 days ago and couple spaces closed over "
            "30 days ago. Runs on every deploy; the app also runs it at most hourly.")

    def handle(self, *args, **options):
        result = purge_due()
        self.stdout.write(f"Purged {result['accounts']} account(s) and {result['couple_spaces']} "
                          "closed couple space(s).")
