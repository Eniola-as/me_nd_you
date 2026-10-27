"""game.0007 removes secret-word couples. Couple-space questions survive;
secret-word couples, their questions and their play history are deleted."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("game", "0006_custom_question_space"), ("couples", "0004_remove_legacy_link")]
AFTER = [("game", "0007_remove_secret_word_couples")]


class RemoveSecretWordCouplesMigrationTests(TransactionTestCase):
    serialized_rollback = True  # Restore the question bank for later tests.

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        self.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_space_questions_survive_and_secret_word_data_goes(self):
        apps = self.migrate(BEFORE)
        Couple = apps.get_model("couples", "Couple")
        CoupleSession = apps.get_model("game", "CoupleSession")
        CustomQuestion = apps.get_model("game", "CustomQuestion")
        PlayedQuestion = apps.get_model("game", "PlayedQuestion")
        space = Couple.objects.create()
        kept = CustomQuestion.objects.create(space=space, text="Ours?", mode="questions")
        session = CoupleSession.objects.create(partner1_name="A", partner2_name="B", secret_word="old-word",
                                               session_key="k")
        CustomQuestion.objects.create(couple=session, text="Old?", mode="questions")
        PlayedQuestion.objects.create(couple=session, text="Old?", mode="questions")

        apps = self.migrate(AFTER)
        CustomQuestion = apps.get_model("game", "CustomQuestion")
        self.assertEqual(list(CustomQuestion.objects.values_list("pk", "text")), [(kept.pk, "Ours?")])
        self.assertEqual(CustomQuestion.objects.get().space_id, space.pk)
        tables = connection.introspection.table_names()
        self.assertNotIn("game_couplesession", tables)
        self.assertNotIn("game_playedquestion", tables)
        self.assertFalse(CustomQuestion._meta.get_field("space").null)

    def test_a_fresh_database_loses_nothing(self):
        apps = self.migrate(BEFORE)
        bank = apps.get_model("game", "Question").objects.count()
        apps = self.migrate(AFTER)
        self.assertEqual(apps.get_model("game", "Question").objects.count(), bank)
        self.assertGreater(bank, 1900)
